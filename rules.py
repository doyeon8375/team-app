"""팀 편성 규칙 (DB, 화면과 무관한 순수 함수).

학생은 dict 로 다룸: {"id", "student_no", "name", "main", "subs"(set)}
"""
from __future__ import annotations

ROLES = ["기획자", "웹 프로그래머", "프론트엔드 디자이너", "테스터", "보고서 작성자", "발표자"]
PL = "기획자"
WP = "웹 프로그래머"
REQUIRED = (PL, WP)
MIN_SIZE = 2
MAX_SIZE = 4


def can_play(student: dict, role: str) -> bool:
    return student["main"] == role or role in student["subs"]


def roles_text(student: dict) -> str:
    subs = [r for r in ROLES if r in student["subs"]]
    return student["main"] + (" / 보조: " + ", ".join(subs) if subs else "")


def required_filled(members: list[dict]) -> int:
    """기획자와 웹 프로그래머를 서로 다른 학생이 맡을 때, 채울 수 있는 필수 역할 수(0~2)."""
    pl = {m["student_no"] for m in members if can_play(m, PL)}
    wp = {m["student_no"] for m in members if can_play(m, WP)}
    if pl and wp and len(pl | wp) >= 2:
        return 2
    if pl or wp:
        return 1
    return 0


def missing_required(members: list[dict]) -> int:
    return len(REQUIRED) - required_filled(members)


def missing_role_names(members: list[dict]) -> list[str]:
    """아직 못 채운 필수 역할 이름(안내용)."""
    pl = [m for m in members if can_play(m, PL)]
    wp = [m for m in members if can_play(m, WP)]
    if required_filled(members) == 2:
        return []
    if not pl and not wp:
        return [PL, WP]
    if not pl:
        return [PL]
    if not wp:
        return [WP]
    # 한 사람이 둘 다 할 수 있지만 혼자뿐
    return ["기획자 또는 웹 프로그래머(서로 다른 학생)"]


def join_block_reason(members: list[dict], applicant: dict) -> str | None:
    """applicant 가 이 팀에 들어갈 수 없는 이유. 들어갈 수 있으면 None.

    정원, 주 역할 중복, 필수 포함 역할 자리를 검사함(지원할 때와 승인 직전에 같이 씀).
    """
    if len(members) >= MAX_SIZE:
        return "팀이 꽉 참"
    if any(m["main"] == applicant["main"] for m in members):
        return "같은 주 역할의 팀원이 있음"
    after = members + [applicant]
    left = MAX_SIZE - len(after)
    if left < missing_required(after):
        return "필수 포함 역할(기획자, 웹 프로그래머)을 맡을 학생의 자리가 모자람"
    return None


# ---------------------------------------------------------------- 배정안 검사

def validate_plan(teams: dict[int, list[dict]], unassigned: list[dict],
                  plan: list[tuple[str, int]]) -> list[str]:
    """2.5절 4항의 다섯 가지 검사. 문제 목록을 돌려줌(비어 있으면 통과)."""
    errors: list[str] = []
    by_no = {s["student_no"]: s for s in unassigned}
    seen: dict[str, int] = {}
    for no, team_id in plan:
        no = str(no)
        if no not in by_no:
            errors.append(f"팀이 없는 학생이 아닌 학번이 들어 있음: {no}")
            continue
        if team_id not in teams:
            errors.append(f"없는 팀 번호: {team_id} (학번 {no})")
            continue
        if no in seen:
            errors.append(f"{by_no[no]['name']}이(가) 두 번 이상 배정됨")
            continue
        seen[no] = team_id
    # 1. 빠짐없이
    for s in unassigned:
        if s["student_no"] not in seen:
            errors.append(f"{s['name']}이(가) 배정되지 않음")
    # 결과 팀 구성
    result = {tid: list(ms) for tid, ms in teams.items()}
    for no, tid in seen.items():
        result[tid].append(by_no[no])
    for tid in sorted(result):
        ms = result[tid]
        # 3. 인원
        if not (MIN_SIZE <= len(ms) <= MAX_SIZE):
            errors.append(f"팀{tid}의 인원이 {len(ms)}명임(2~4명이어야 함)")
        # 4. 주 역할 중복
        mains = [m["main"] for m in ms]
        dups = sorted({r for r in mains if mains.count(r) > 1})
        for r in dups:
            errors.append(f"팀{tid}에 주 역할 {r}이(가) 중복됨")
        # 5. 필수 포함 역할
        if ms and missing_required(ms) > 0:
            errors.append(f"팀{tid}에 {', '.join(missing_role_names(ms))}을(를) 맡을 학생이 없음")
    return errors


# ---------------------------------------------------------------- 완전 탐색 배정

def solve(teams: dict[int, list[dict]], unassigned: list[dict]) -> list[tuple[str, int]] | None:
    """규칙을 모두 지키는 배정을 모든 경우를 따져 찾음. 없으면 None."""
    team_ids = sorted(teams)
    state = {tid: list(teams[tid]) for tid in team_ids}

    def placeable(tid: int, s: dict) -> bool:
        return join_block_reason(state[tid], s) is None

    def globally_ok(remaining: int) -> bool:
        need = sum(max(0, MIN_SIZE - len(state[t])) for t in team_ids if True)
        cap = sum(MAX_SIZE - len(state[t]) for t in team_ids)
        if need > remaining or cap < remaining:
            return False
        for t in team_ids:
            if MAX_SIZE - len(state[t]) < missing_required(state[t]):
                return False
        return True

    def candidates(s: dict) -> list[int]:
        out, empty_tried = [], False
        for t in team_ids:
            if not state[t]:
                if empty_tried:   # 빈 팀끼리는 서로 같으므로 하나만 시도
                    continue
                empty_tried = True
            if placeable(t, s):
                out.append(t)
        return out

    plan: list[tuple[str, int]] = []

    def finished_ok() -> bool:
        for t in team_ids:
            ms = state[t]
            if not (MIN_SIZE <= len(ms) <= MAX_SIZE):
                return False
            if missing_required(ms) > 0:
                return False
        return True

    def rec(rest: list[dict]) -> bool:
        if not rest:
            return finished_ok()
        if not globally_ok(len(rest)):
            return False
        # 갈 곳이 가장 적은 학생부터
        best, best_c = None, None
        for s in rest:
            c = candidates(s)
            if best_c is None or len(c) < len(best_c):
                best, best_c = s, c
                if not c:
                    return False
        rest2 = [s for s in rest if s is not best]
        # 인원이 적은 팀부터 시도
        for t in sorted(best_c, key=lambda t: len(state[t])):
            state[t].append(best)
            plan.append((best["student_no"], t))
            if rec(rest2):
                return True
            plan.pop()
            state[t].pop()
        return False

    if rec(list(unassigned)):
        return list(plan)
    return None


def diagnose(teams: dict[int, list[dict]], unassigned: list[dict]) -> str:
    """규칙을 지키는 배정이 없을 때 그 이유."""
    reasons = []
    n_teams = len(teams)
    total = sum(len(m) for m in teams.values()) + len(unassigned)
    if total < MIN_SIZE * n_teams:
        reasons.append(f"학생이 {total}명이라 팀 {n_teams}개를 2명 이상씩 채울 수 없음")
    for tid in sorted(teams):
        ms = teams[tid]
        if MAX_SIZE - len(ms) < missing_required(ms):
            reasons.append(f"팀{tid}에 {', '.join(missing_role_names(ms))}을(를) 맡을 학생이 없음"
                           f"(남은 자리 {MAX_SIZE - len(ms)}개)")
            continue
        fits = [s for s in unassigned if all(m["main"] != s["main"] for m in ms)]
        for role in REQUIRED:
            if not any(can_play(m, role) for m in ms) and not any(can_play(s, role) for s in fits):
                reasons.append(f"팀{tid}에 {role}을(를) 맡을 학생이 없음")
    if not reasons:
        reasons.append("모든 경우를 따져 보았으나 인원, 주 역할 중복, 필수 포함 역할을 함께 지키는 배정이 없음")
    return "; ".join(reasons)
