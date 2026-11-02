"""부록 연습용 시나리오 3개를 메모리 저장소로 실행해 기대 결과와 비교함.

실행: python tests/test_scenarios.py  (저장소 폴더에서)
"""
import itertools
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rules  # noqa: E402
import service  # noqa: E402

HERE = os.path.dirname(__file__)


class MemRepo:
    """service 가 쓰는 저장소의 메모리 버전(DB 대신)."""

    def __init__(self):
        self.students, self.teams, self.mem = {}, [], {}   # members: student_id -> (team, slot)
        self.apps, self.votes_, self.settings = [], {}, {}

    def load(self, rows, n):
        self.__init__()
        for i, r in enumerate(rows, start=1):
            self.students[i] = {"id": i, "student_no": r["student_no"], "name": r["name"],
                                "main": r["main"], "subs": set(r["subs"]), "is_admin": False}
        self.teams = list(range(1, n + 1))

    def setting_get(self, k): return self.settings.get(k)
    def setting_set(self, k, v): self.settings[k] = v
    def student_by_no(self, no): return next((s for s in self.students.values() if s["student_no"] == no), None)
    def team_exists(self, t): return t in self.teams
    def lock_team(self, t): pass
    def lock_all_teams(self): pass
    def team_ids(self): return list(self.teams)

    def members(self, t):
        return [self.students[sid] for sid, (tt, _) in sorted(self.members_items(), key=lambda x: x[1][1]) if tt == t]

    def members_items(self): return list(self.mem.items())
    def team_of(self, sid): return self.mem[sid][0] if sid in self.mem else None
    def pending_of(self, sid): return next((a for a in self.apps if a["student_id"] == sid and a["status"] == "대기"), None)
    def last_app_of(self, sid):
        xs = [a for a in self.apps if a["student_id"] == sid]
        return xs[-1] if xs else None
    def app_get(self, i): return self.apps[i]

    def app_insert(self, t, sid, st, reason):
        if st == "대기" and self.pending_of(sid):
            raise service.Conflict()
        self.apps.append({"id": len(self.apps), "team_id": t, "student_id": sid, "status": st, "reason": reason})
        return len(self.apps) - 1

    def app_set_status(self, i, st, reason): self.apps[i].update(status=st, reason=reason)
    def pending_apps(self): return [a for a in self.apps if a["status"] == "대기"]

    def member_add(self, t, sid):
        used = {s for tt, s in self.mem.values() if tt == t}
        free = [s for s in range(1, 5) if s not in used]
        if sid in self.mem or not free:
            raise service.Conflict()
        self.mem[sid] = (t, free[0])

    def member_remove(self, sid): self.mem.pop(sid, None)
    def votes(self, aid): return dict(self.votes_.get(aid, {}))
    def vote_add(self, aid, vid, v): self.votes_.setdefault(aid, {})[vid] = v
    def unassigned(self): return [s for s in self.students.values() if s["id"] not in self.mem]


def roster(name):
    with open(os.path.join(HERE, "..", "sample_data", name), encoding="utf-8-sig") as f:
        return service.parse_roster(f.read())


def no(prefix, k): return f"{prefix}{k:02d}"


FAIL = []


def expect(step, got, want):
    ok = got.split(":")[0] == want
    print(f"  {'OK ' if ok else 'XX '} {step}: {got}  (기대 {want})")
    if not ok:
        FAIL.append((step, got, want))


def finish(repo, label):
    print(" ", service.close(repo))
    teams, un = service.snapshot(repo)
    print("  남은 학생:", [s["name"] for s in un])
    plan = rules.solve(teams, un)
    assert plan is not None, "배정 없음"
    assert not rules.validate_plan(teams, un, plan)
    print(" ", service.confirm(repo, plan))
    teams, un = service.snapshot(repo)
    assert not un
    assert not rules.validate_plan(teams, [], [])
    for t, ms in teams.items():
        print(f"   팀{t}:", ", ".join(m["name"] for m in ms))
    print(f"  {label} 확정 뒤 규칙 검사 통과")


def easy():
    print("[쉬움]")
    r = MemRepo(); r.load(roster("쉬움.csv"), 3); p = "20261"
    a = service.apply
    expect("1", a(r, no(p, 1), 1), "승인"); expect("1", a(r, no(p, 2), 2), "승인"); expect("1", a(r, no(p, 3), 3), "승인")
    expect("2", a(r, no(p, 4), 1), "대기"); expect("2", service.vote(r, no(p, 1), no(p, 4), True), "승인")
    expect("3", a(r, no(p, 5), 2), "대기"); expect("3", service.vote(r, no(p, 2), no(p, 5), True), "승인")
    expect("4", a(r, no(p, 7), 1), "대기"); expect("4", service.vote(r, no(p, 1), no(p, 7), True), "대기")
    expect("4", service.vote(r, no(p, 4), no(p, 7), False), "거절")
    expect("5", a(r, no(p, 6), 3), "대기"); expect("5", service.vote(r, no(p, 3), no(p, 6), True), "승인")
    finish(r, "쉬움")


def medium():
    print("[중간]")
    r = MemRepo(); r.load(roster("중간.csv"), 4); p = "20262"
    a, v = service.apply, service.vote
    expect("1", a(r, no(p, 1), 1), "승인")
    expect("2", a(r, no(p, 5), 1), "대기"); expect("2", v(r, no(p, 1), no(p, 5), True), "승인")
    expect("3", a(r, no(p, 2), 1), "막힘")
    expect("4", a(r, no(p, 6), 2), "승인")
    expect("5", a(r, no(p, 9), 2), "대기"); expect("5", v(r, no(p, 6), no(p, 9), True), "승인")
    expect("6", a(r, no(p, 10), 2), "대기"); expect("6", v(r, no(p, 6), no(p, 10), True), "대기")
    expect("6", v(r, no(p, 9), no(p, 10), False), "거절")
    expect("7", a(r, no(p, 3), 3), "승인"); expect("7", a(r, no(p, 11), 4), "승인")
    expect("8", a(r, no(p, 12), 4), "대기"); expect("8", a(r, no(p, 12), 3), "막힘")
    print(" ", service.close(r))
    expect("9", v(r, no(p, 11), no(p, 12), True), "거절")
    expect("10", a(r, no(p, 2), 3), "막힘")
    r.settings["closed"] = "1"
    teams, un = service.snapshot(r)
    names = sorted(s["name"] for s in un)
    assert "학생3(PL;RW)" in names and "학생11(RW)" in names, names
    plan = rules.solve(teams, un); assert plan
    print(" ", service.confirm(r, plan))
    teams, un = service.snapshot(r); assert not un
    for t, ms in teams.items():
        print(f"   팀{t}:", ", ".join(m["name"] for m in ms))


def hard():
    print("[어려움]")
    r = MemRepo(); r.load(roster("어려움.csv"), 4); p = "20263"
    a, v = service.apply, service.vote
    expect("1", a(r, no(p, 1), 1), "승인")
    expect("2", a(r, no(p, 4), 1), "대기"); expect("2", v(r, no(p, 1), no(p, 4), True), "승인")
    expect("3", a(r, no(p, 7), 1), "대기"); expect("3", v(r, no(p, 1), no(p, 7), True), "대기")
    expect("3", v(r, no(p, 4), no(p, 7), True), "승인")
    expect("4", a(r, no(p, 2), 2), "승인")
    expect("5", a(r, no(p, 8), 2), "대기"); expect("5", v(r, no(p, 2), no(p, 8), True), "승인")
    expect("6", a(r, no(p, 5), 2), "대기"); expect("6", a(r, no(p, 6), 2), "대기")
    expect("7", v(r, no(p, 2), no(p, 5), True), "대기"); expect("7", v(r, no(p, 8), no(p, 5), True), "승인")
    expect("8", v(r, no(p, 2), no(p, 6), True), "대기"); expect("8", v(r, no(p, 8), no(p, 6), True), "대기")
    expect("8", v(r, no(p, 5), no(p, 6), True), "거절")
    expect("9", a(r, no(p, 11), 3), "승인")
    expect("10", a(r, no(p, 15), 3), "대기"); expect("10", v(r, no(p, 11), no(p, 15), True), "승인")
    expect("11", a(r, no(p, 14), 3), "막힘")
    expect("12", a(r, no(p, 10), 4), "승인")
    expect("13", a(r, no(p, 13), 1), "대기"); expect("13", v(r, no(p, 1), no(p, 13), True), "대기")
    finish(r, "어려움")
    un_names = [s["name"] for s in service.snapshot(r)[1]]
    assert not un_names


def solver_stress():
    """완전 탐색이 16명 모두 남아도 빨리 끝나는지, 찾은 답이 늘 검사를 통과하는지."""
    import time
    random.seed(1)
    worst = 0.0
    for trial in range(300):
        n = random.randint(8, 16)
        rows = [{"student_no": str(i), "name": f"s{i}", "main": random.choice(rules.ROLES),
                 "subs": set(random.sample(rules.ROLES, random.randint(0, 2)))} for i in range(n)]
        teams = {t: [] for t in range(1, random.randint(3, 4) + 1)}
        t0 = time.time()
        plan = rules.solve(teams, rows)
        worst = max(worst, time.time() - t0)
        if plan is not None:
            assert not rules.validate_plan(teams, rows, plan), plan
        elif n <= 9:   # 작을 때는 무식한 전수 조사로 정말 답이 없는지 확인
            for combo in itertools.product(list(teams), repeat=n):
                pl = [(rows[i]["student_no"], combo[i]) for i in range(n)]
                assert rules.validate_plan(teams, rows, pl), "solve 가 놓친 답이 있음"
    print(f"[완전 탐색] 300회 통과, 가장 오래 걸린 경우 {worst:.3f}초")


def infeasible():
    s = lambda no, main, subs=(): {"student_no": no, "name": no, "main": main, "subs": set(subs)}
    teams = {1: [s("a", "테스터"), s("b", "발표자"), s("c", "보고서 작성자"), s("d", "프론트엔드 디자이너")],
             2: [s("e", "기획자"), s("f", "웹 프로그래머")]}
    un = [s("g", "기획자"), s("h", "웹 프로그래머")]
    assert rules.solve(teams, un) is None
    print("[배정 없음 안내]", rules.diagnose(teams, un))


if __name__ == "__main__":
    easy(); medium(); hard(); solver_stress(); infeasible()
    print("실패:", FAIL if FAIL else "없음")
    sys.exit(1 if FAIL else 0)
