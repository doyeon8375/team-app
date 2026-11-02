"""지원, 투표, 마감, 배정 확정, 명단 올리기.

함수마다 repo(한 트랜잭션 안에서 쓰는 저장소)를 받음. 실제 앱은 db.PgRepo,
시험은 tests 의 MemRepo 를 씀. 반환값은 result 안내 글자("승인/대기/거절/막힘: ...").
"""
from __future__ import annotations

import rules


class Conflict(Exception):
    """DB 유일성 제약에 걸림(동시에 같은 자리를 차지하려 함 등)."""


def _block(msg: str) -> str:
    return f"막힘: {msg}"


def is_closed(repo) -> bool:
    return repo.setting_get("closed") == "1"


# ---------------------------------------------------------------- 지원

def apply(repo, student_no: str, team_id: int) -> str:
    me = repo.student_by_no(student_no)
    if me is None or me["is_admin"]:
        return _block("학생 계정이 아님")
    if not repo.team_exists(team_id):
        return _block("없는 팀")
    repo.lock_team(team_id)
    if is_closed(repo):
        return _block("모집이 마감됨")
    if repo.team_of(me["id"]) is not None:
        return _block("이미 팀이 있음")
    if repo.pending_of(me["id"]) is not None:
        return _block("결과를 기다리는 지원이 있음")
    members = repo.members(team_id)
    reason = rules.join_block_reason(members, me)
    if reason:
        return _block(reason)
    if not members:
        repo.app_insert(team_id, me["id"], "승인", "빈 팀이라 바로 승인")
        repo.member_add(team_id, me["id"])
        return f"승인: 팀{team_id}에 들어감"
    repo.app_insert(team_id, me["id"], "대기", None)
    return f"대기: 팀{team_id} 팀원 {len(members)}명의 투표를 기다림"


# ---------------------------------------------------------------- 투표

def vote(repo, voter_no: str, applicant_no: str, yes: bool) -> str:
    voter = repo.student_by_no(voter_no)
    applicant = repo.student_by_no(applicant_no)
    if voter is None or applicant is None:
        return _block("학생을 찾을 수 없음")
    app = repo.pending_of(applicant["id"])
    if app is None:
        last = repo.last_app_of(applicant["id"])
        if last is None:
            return _block("투표할 지원이 없음")
        return f"{last['status']}: 이미 결과가 나온 지원" + (f"({last['reason']})" if last["reason"] else "")
    team_id = app["team_id"]
    repo.lock_team(team_id)
    app = repo.app_get(app["id"])           # 잠근 뒤 다시 읽음
    if app["status"] != "대기":
        return f"{app['status']}: 이미 결과가 나온 지원"
    if is_closed(repo):
        return _block("모집이 마감됨")
    members = repo.members(team_id)
    if voter["id"] not in {m["id"] for m in members}:
        return _block("이 팀의 팀원이 아님")
    votes = repo.votes(app["id"])
    if voter["id"] in votes:
        return _block(f"이미 투표함(내 투표: {votes[voter['id']]})")
    repo.vote_add(app["id"], voter["id"], "찬성" if yes else "거부")
    if not yes:
        repo.app_set_status(app["id"], "거절", f"{voter['name']}이(가) 거부함")
        return f"거절: {voter['name']}이(가) 거부함"
    votes[voter["id"]] = "찬성"
    return _try_approve(repo, app, applicant, members, votes)


def _try_approve(repo, app, applicant, members, votes) -> str:
    waiting = [m for m in members if votes.get(m["id"]) != "찬성"]
    if waiting:
        names = ", ".join(m["name"] for m in waiting)
        return f"대기: 아직 투표하지 않은 팀원이 있음({names})"
    # 승인 직전 검사(투표가 끝난 순서대로 처리됨)
    reason = rules.join_block_reason(members, applicant)
    if reason:
        repo.app_set_status(app["id"], "거절", f"승인 직전 검사: {reason}")
        return f"거절: 승인 직전 검사에서 걸림 - {reason}"
    try:
        repo.member_add(app["team_id"], applicant["id"])
    except Conflict:
        repo.app_set_status(app["id"], "거절", "다른 학생이 먼저 자리를 차지함")
        return "거절: 다른 학생이 먼저 자리를 차지함"
    repo.app_set_status(app["id"], "승인", "팀원 모두 찬성")
    return f"승인: {applicant['name']}이(가) 팀{app['team_id']}에 들어감"


# ---------------------------------------------------------------- 마감

def close(repo) -> str:
    repo.lock_all_teams()
    if is_closed(repo):
        return _block("이미 마감됨")
    repo.setting_set("closed", "1")
    rejected = 0
    for app in repo.pending_apps():
        repo.app_set_status(app["id"], "거절", "모집 마감")
        rejected += 1
    removed = []
    for tid in repo.team_ids():
        ms = repo.members(tid)
        if len(ms) == 1:
            repo.member_remove(ms[0]["id"])
            removed.append(ms[0]["name"])
    repo.setting_set("proposal", "")
    msg = f"승인: 모집을 마감함(대기 지원 {rejected}건 거절"
    if removed:
        msg += ", 1명뿐인 팀에서 뺀 학생: " + ", ".join(removed)
    return msg + ")"


# ---------------------------------------------------------------- 배정

def snapshot(repo) -> tuple[dict[int, list[dict]], list[dict]]:
    teams = {tid: repo.members(tid) for tid in repo.team_ids()}
    return teams, repo.unassigned()


def confirm(repo, plan: list[tuple[str, int]]) -> str:
    repo.lock_all_teams()
    if not is_closed(repo):
        return _block("모집을 마감하지 않음")
    teams, unassigned = snapshot(repo)
    errors = rules.validate_plan(teams, unassigned, plan)
    if errors:
        return _block("배정안이 지금 상태와 맞지 않음 - " + "; ".join(errors))
    by_no = {s["student_no"]: s for s in unassigned}
    for no, tid in plan:
        repo.member_add(tid, by_no[no]["id"])   # 겹치면 Conflict → 트랜잭션 전체 취소
    repo.setting_set("proposal", "")
    repo.setting_set("confirmed", "1")
    return f"승인: 배정안을 확정함({len(plan)}명 배정)"


# ---------------------------------------------------------------- 명단

def parse_roster(text: str) -> list[dict]:
    """CSV 글자(BOM 제거 뒤)를 학생 목록으로. 틀리면 ValueError."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    need = ["student_no", "name", "main_role", "sub_roles"]
    if reader.fieldnames is None or [f.strip() for f in reader.fieldnames][:4] != need:
        raise ValueError(f"CSV 첫 줄은 {','.join(need)} 이어야 함")
    rows, seen = [], set()
    for i, r in enumerate(reader, start=2):
        no = (r.get("student_no") or "").strip()
        name = (r.get("name") or "").strip()
        main = (r.get("main_role") or "").strip()
        subs_raw = (r.get("sub_roles") or "").strip()
        if not no and not name:
            continue
        if not no or not name:
            raise ValueError(f"{i}번째 줄: 학번이나 이름이 비어 있음")
        if no.lower() == "admin":
            raise ValueError(f"{i}번째 줄: admin 은 학번으로 쓸 수 없음")
        if no in seen:
            raise ValueError(f"{i}번째 줄: 학번 {no}이(가) 중복됨")
        if main not in rules.ROLES:
            raise ValueError(f"{i}번째 줄: 주 역할 '{main}'이(가) 6개 역할에 없음")
        subs = [s.strip() for s in subs_raw.split(";") if s.strip()]
        for s in subs:
            if s not in rules.ROLES:
                raise ValueError(f"{i}번째 줄: 보조 역할 '{s}'이(가) 6개 역할에 없음")
        if len(subs) > 2:
            raise ValueError(f"{i}번째 줄: 보조 역할은 2개까지임")
        seen.add(no)
        rows.append({"student_no": no, "name": name, "main": main,
                     "subs": [s for s in subs if s != main]})
    if not rows:
        raise ValueError("학생이 한 명도 없음")
    return rows
