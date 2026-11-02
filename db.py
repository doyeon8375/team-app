"""Supabase(PostgreSQL) 연결과 저장소.

연결은 앱 전체에서 한 번 만든 연결 풀을 다시 씀(질의마다 새로 연결하지 않음).
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager

import bcrypt
import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

import service

_HERE = os.path.dirname(os.path.abspath(__file__))


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


class Database:
    def __init__(self, url: str):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            1, 8, url, connect_timeout=10,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
        self._lock = threading.Lock()

    @contextmanager
    def tx(self):
        """한 트랜잭션. 끝나면 커밋, 오류면 롤백. 끊긴 연결은 버리고 한 번 다시 시도함."""
        conn = self._pool.getconn()
        try:
            if conn.closed:
                raise psycopg2.InterfaceError("closed")
            conn.cursor().execute("select 1")
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            self._pool.putconn(conn, close=True)
            conn = self._pool.getconn()
        broken = False
        try:
            conn.rollback()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield PgRepo(cur)
            conn.commit()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            broken = True
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                broken = True
            raise
        finally:
            self._pool.putconn(conn, close=broken)

    def init_schema(self, admin_password: str):
        with open(os.path.join(_HERE, "schema.sql"), encoding="utf-8") as f:
            sql = f.read()
        with self.tx() as repo:
            repo.cur.execute("select pg_advisory_xact_lock(424242)")
            repo.cur.execute(sql)
            repo.cur.execute("select id, password_hash from tf_students where student_no = 'admin'")
            row = repo.cur.fetchone()
            if row is None:
                repo.cur.execute(
                    "insert into tf_students (student_no, name, main_role, password_hash, is_admin) "
                    "values ('admin', '관리자', null, %s, true)", (hash_password(admin_password),))
            elif not check_password(admin_password, row["password_hash"]):
                repo.cur.execute("update tf_students set password_hash = %s, is_admin = true where id = %s",
                                 (hash_password(admin_password), row["id"]))


class PgRepo:
    """service.py 가 쓰는 저장소. 한 트랜잭션의 커서를 감쌈."""

    def __init__(self, cur):
        self.cur = cur

    def _one(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchone()

    def _all(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchall()

    # 설정
    def setting_get(self, key):
        r = self._one("select value from tf_settings where key = %s", (key,))
        return r["value"] if r else None

    def setting_set(self, key, value):
        self.cur.execute("insert into tf_settings (key, value) values (%s, %s) "
                         "on conflict (key) do update set value = excluded.value", (key, value))

    # 학생
    def _students(self, where="", args=()):
        rows = self._all(
            "select s.id, s.student_no, s.name, s.main_role, s.is_admin, s.password_hash, "
            "coalesce(array_agg(r.role) filter (where r.role is not null), '{}') as subs "
            "from tf_students s left join tf_student_sub_roles r on r.student_id = s.id "
            f"{where} group by s.id order by s.student_no", args)
        return [{"id": r["id"], "student_no": r["student_no"], "name": r["name"], "main": r["main_role"],
                 "subs": set(r["subs"]), "is_admin": r["is_admin"], "password_hash": r["password_hash"]}
                for r in rows]

    def student_by_no(self, no):
        xs = self._students("where s.student_no = %s", (no,))
        return xs[0] if xs else None

    def all_students(self):
        return [s for s in self._students() if not s["is_admin"]]

    # 팀
    def team_exists(self, team_id):
        return self._one("select 1 from tf_teams where id = %s", (team_id,)) is not None

    def lock_team(self, team_id):
        self.cur.execute("select id from tf_teams where id = %s for update", (team_id,))

    def lock_all_teams(self):
        self.cur.execute("select id from tf_teams order by id for update")

    def team_ids(self):
        return [r["id"] for r in self._all("select id from tf_teams order by id")]

    def members(self, team_id):
        ids = [r["student_id"] for r in
               self._all("select student_id from tf_members where team_id = %s order by slot_no", (team_id,))]
        if not ids:
            return []
        by_id = {s["id"]: s for s in self._students("where s.id = any(%s)", (ids,))}
        return [by_id[i] for i in ids]

    def all_members(self):
        return self._all("select team_id, student_id, slot_no from tf_members order by team_id, slot_no")

    def team_of(self, student_id):
        r = self._one("select team_id from tf_members where student_id = %s", (student_id,))
        return r["team_id"] if r else None

    def member_add(self, team_id, student_id):
        self.cur.execute("savepoint add_member")
        try:
            self.cur.execute(
                "insert into tf_members (team_id, slot_no, student_id) "
                "select %s, min(n), %s from generate_series(1, 4) n "
                "where n not in (select slot_no from tf_members where team_id = %s) having min(n) is not null",
                (team_id, student_id, team_id))
            if self.cur.rowcount != 1:
                raise service.Conflict()
        except psycopg2.errors.UniqueViolation:
            self.cur.execute("rollback to savepoint add_member")
            raise service.Conflict()
        self.cur.execute("release savepoint add_member")

    def member_remove(self, student_id):
        self.cur.execute("delete from tf_members where student_id = %s", (student_id,))

    def unassigned(self):
        return self._students("where not s.is_admin and s.id not in (select student_id from tf_members)")

    # 지원
    def pending_of(self, student_id):
        return self._one("select * from tf_applications where student_id = %s and status = '대기'", (student_id,))

    def last_app_of(self, student_id):
        return self._one("select * from tf_applications where student_id = %s order by id desc limit 1",
                         (student_id,))

    def app_get(self, app_id):
        return self._one("select * from tf_applications where id = %s", (app_id,))

    def app_insert(self, team_id, student_id, status, reason):
        self.cur.execute("savepoint add_app")
        try:
            r = self._one("insert into tf_applications (team_id, student_id, status, reason, decided_at) "
                          "values (%s, %s, %s, %s, case when %s <> '대기' then now() end) returning id",
                          (team_id, student_id, status, reason, status))
        except psycopg2.errors.UniqueViolation:
            self.cur.execute("rollback to savepoint add_app")
            raise service.Conflict()
        self.cur.execute("release savepoint add_app")
        return r["id"]

    def app_set_status(self, app_id, status, reason):
        self.cur.execute("update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
                         (status, reason, app_id))

    def pending_apps(self):
        return self._all("select * from tf_applications where status = '대기' order by id")

    # 투표
    def votes(self, app_id):
        return {r["voter_id"]: r["vote"] for r in
                self._all("select voter_id, vote from tf_votes where application_id = %s", (app_id,))}

    def all_votes_for_pending(self):
        return self._all("select v.application_id, v.voter_id, v.vote from tf_votes v "
                         "join tf_applications a on a.id = v.application_id where a.status = '대기'")

    def vote_add(self, app_id, voter_id, vote):
        try:
            self.cur.execute("insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)",
                             (app_id, voter_id, vote))
        except psycopg2.errors.UniqueViolation:
            raise service.Conflict()

    # 명단 올리기
    def reset(self, rows, team_count):
        self.cur.execute("select pg_advisory_xact_lock(424243)")
        self.cur.execute("delete from tf_votes")
        self.cur.execute("delete from tf_applications")
        self.cur.execute("delete from tf_members")
        self.cur.execute("delete from tf_teams")
        self.cur.execute("delete from tf_student_sub_roles where student_id in "
                         "(select id from tf_students where not is_admin)")
        self.cur.execute("delete from tf_students where not is_admin")
        self.cur.execute("delete from tf_settings")
        self.cur.execute("delete from tf_ai_logs")
        for t in range(1, team_count + 1):
            self.cur.execute("insert into tf_teams (id, name) values (%s, %s)", (t, f"팀{t}"))
        pw = "1234".encode()
        for r in rows:
            h = bcrypt.hashpw(pw, bcrypt.gensalt(rounds=10)).decode()
            sid = self._one("insert into tf_students (student_no, name, main_role, password_hash) "
                            "values (%s, %s, %s, %s) returning id", (r["student_no"], r["name"], r["main"], h))["id"]
            for role in r["subs"]:
                self.cur.execute("insert into tf_student_sub_roles (student_id, role) values (%s, %s)", (sid, role))
        self.setting_set("closed", "0")

    # AI 기록
    def ai_log(self, attempt, model, outcome, detail, elapsed):
        self.cur.execute("insert into tf_ai_logs (attempt, model, outcome, detail, elapsed_s) "
                         "values (%s, %s, %s, %s, %s)", (attempt, model, outcome, (detail or "")[:2000], elapsed))

    def ai_logs(self, limit=15):
        return self._all("select * from tf_ai_logs order by id desc limit %s", (limit,))
