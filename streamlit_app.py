"""팀 프로젝트 팀 편성 앱 (Streamlit + Supabase + OpenRouter).

화면 요소의 key 는 과제 공고 2.7절 표를 그대로 따름.
"""
from __future__ import annotations

import json
import os
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import ai_assign
import db as dbmod
import rules
import service

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
KST = ZoneInfo("Asia/Seoul")
REFRESH_S = 3   # 다른 사람의 변경을 다시 그리는 간격(5초 이하)

DEFAULT_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "z-ai/glm-4.5-air:free",
]

st.set_page_config(page_title="팀 편성", page_icon="🧩", layout="wide")


# ---------------------------------------------------------------- 설정과 DB

def secret(name: str, default: str | None = None) -> str | None:
    """Streamlit Secrets → .env(환경 변수) 순으로 찾음. 값은 화면에 출력하지 않음."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


def models() -> list[str]:
    return [secret(f"MODEL_{i}") or DEFAULT_MODELS[i - 1] for i in (1, 2, 3)]


@st.cache_resource(show_spinner="DB에 연결하는 중…")
def get_db() -> dbmod.Database:
    url, admin_pw = secret("DATABASE_URL"), secret("ADMIN_PASSWORD")
    database = dbmod.Database(url)
    database.init_schema(admin_pw)
    return database


missing = [n for n in ("DATABASE_URL", "ADMIN_PASSWORD", "OPENROUTER_API_KEY") if not secret(n)]
if missing:
    st.error("설정 값이 없음: " + ", ".join(missing) + " (.env 나 Streamlit Secrets 에 넣어 주세요)")
    st.stop()

try:
    DB = get_db()
except Exception as e:
    st.error(f"DB에 연결하지 못함({type(e).__name__}). DATABASE_URL 과 Supabase 프로젝트 상태를 확인해 주세요.")
    st.stop()


def run(fn, *args) -> str:
    """service 함수를 한 트랜잭션으로 실행하고 결과 안내를 돌려줌."""
    try:
        with DB.tx() as repo:
            return fn(repo, *args)
    except service.Conflict:
        return "막힘: 다른 처리와 동시에 일어나서 기록하지 못함. 다시 눌러 주세요"
    except Exception as e:
        return f"막힘: 처리 중 오류가 남({type(e).__name__})"


def kst(ts) -> str:
    return ts.astimezone(KST).strftime("%m-%d %H:%M:%S") if ts else ""


# ---------------------------------------------------------------- 로그인

ss = st.session_state
ss.setdefault("user_no", None)
ss.setdefault("last_result", "")


def current_user():
    if not ss.user_no:
        return None
    with DB.tx() as repo:
        u = repo.student_by_no(ss.user_no)
    if u is None:            # 명단이 바뀌어 계정이 사라짐
        ss.user_no = None
    return u


def show_result():
    with st.container(key="result"):
        if ss.last_result:
            kind = ss.last_result.split(":")[0]
            {"승인": st.success, "대기": st.info, "거절": st.warning, "막힘": st.error}.get(kind, st.write)(ss.last_result)


def login_page():
    st.title("🧩 팀 프로젝트 팀 편성")
    with st.form("login_form"):
        no = st.text_input("학번", key="login_student_no")
        pw = st.text_input("비밀번호", type="password", key="login_password")
        submitted = st.form_submit_button("로그인", key="login_submit")
    if submitted:
        with DB.tx() as repo:
            u = repo.student_by_no(no.strip())
        if u and dbmod.check_password(pw, u["password_hash"]):
            ss.user_no = u["student_no"]
            ss.last_result = f"승인: {u['name']}(으)로 로그인함"
            st.rerun()
        ss.last_result = "막힘: 학번이나 비밀번호가 틀림"
    show_result()


def header(user):
    c1, c2 = st.columns([5, 1])
    with c1:
        with st.container(key="whoami"):
            if user["is_admin"]:
                st.markdown(f"**{user['name']}** (admin) 로그인함")
            else:
                st.markdown(f"**{user['name']}** ({user['student_no']}) 로그인함 · {rules.roles_text(user)}")
    with c2:
        if st.button("로그아웃", key="logout"):
            ss.user_no, ss.last_result = None, ""
            st.rerun()


# ---------------------------------------------------------------- 공통: 상태 읽기

def load_state():
    """화면 한 번에 필요한 것을 한 연결, 한 트랜잭션으로 읽음."""
    with DB.tx() as repo:
        students = {s["id"]: s for s in repo.all_students()}
        team_ids = repo.team_ids()
        members = {t: [] for t in team_ids}
        for r in repo.all_members():
            if r["student_id"] in students:
                members[r["team_id"]].append(students[r["student_id"]])
        pending = repo.pending_apps()
        votes = {}
        for v in repo.all_votes_for_pending():
            votes.setdefault(v["application_id"], {})[v["voter_id"]] = v["vote"]
        closed = repo.setting_get("closed") == "1"
        proposal = repo.setting_get("proposal") or ""
        confirmed = repo.setting_get("confirmed") == "1"
    return dict(students=students, team_ids=team_ids, members=members, pending=pending,
                votes=votes, closed=closed, proposal=proposal, confirmed=confirmed)


def member_line(m) -> str:
    return f"- **{m['name']}** · {rules.roles_text(m)}"


# ---------------------------------------------------------------- 학생 화면

@st.fragment(run_every=REFRESH_S)
def student_view(user_no: str):
    show_result_slot = st.empty()
    S = load_state()
    me = next((s for s in S["students"].values() if s["student_no"] == user_no), None)
    if me is None:
        st.warning("명단에서 계정을 찾을 수 없음. 다시 로그인해 주세요.")
        return
    my_team = next((t for t, ms in S["members"].items() if any(m["id"] == me["id"] for m in ms)), None)
    my_pending = next((a for a in S["pending"] if a["student_id"] == me["id"]), None)
    can_apply = my_team is None and my_pending is None and not S["closed"]

    if S["closed"]:
        st.info("모집이 마감되었음" + (" · 배정이 확정되었음" if S["confirmed"] else ""))
    if my_team is None:
        st.caption("아직 팀이 없음" + (f" · 팀{my_pending['team_id']}에 지원하고 결과를 기다리는 중"
                                       if my_pending else ""))

    clicked = None
    cols = st.columns(min(4, max(1, len(S["team_ids"]))))
    for i, t in enumerate(S["team_ids"]):
        ms = S["members"][t]
        with cols[i % len(cols)]:
            with st.container(key=f"team_{t}", border=True):
                mine = " · ⭐ 내 팀" if t == my_team else ""
                st.markdown(f"#### 팀{t} ({len(ms)}/4){mine}")
                st.markdown("\n".join(member_line(m) for m in ms) if ms else "_빈 팀_")
            if st.button(f"팀{t}에 지원", key=f"apply_{t}", disabled=not can_apply):
                clicked = ("apply", t)

    # 내 팀에 들어온 지원
    if my_team is not None:
        apps = [a for a in S["pending"] if a["team_id"] == my_team]
        st.subheader("내 팀에 들어온 지원")
        if not apps:
            st.caption("대기 중인 지원이 없음")
        team_members = S["members"][my_team]
        for a in apps:
            ap = S["students"][a["student_id"]]
            vs = S["votes"].get(a["id"], {})
            with st.container(border=True):
                st.markdown(f"**{ap['name']}** · {rules.roles_text(ap)}")
                st.caption("투표: " + ", ".join(f"{m['name']} {vs.get(m['id'], '아직')}" for m in team_members))
                if me["id"] in vs:
                    st.markdown(f"내 투표: **{vs[me['id']]}**")
                else:
                    c1, c2 = st.columns(2)
                    if c1.button("찬성", key=f"vote_yes_{ap['student_no']}"):
                        clicked = ("vote", ap["student_no"], True)
                    if c2.button("거부", key=f"vote_no_{ap['student_no']}"):
                        clicked = ("vote", ap["student_no"], False)

    if clicked:
        if clicked[0] == "apply":
            ss.last_result = run(service.apply, user_no, clicked[1])
        else:
            ss.last_result = run(service.vote, user_no, clicked[1], clicked[2])
        st.rerun(scope="fragment")

    with show_result_slot.container():
        show_result()


# ---------------------------------------------------------------- 관리자 화면

@st.fragment(run_every=REFRESH_S)
def admin_board():
    S = load_state()
    st.subheader("팀 현황")
    cols = st.columns(min(4, max(1, len(S["team_ids"]))))
    for i, t in enumerate(S["team_ids"]):
        ms = S["members"][t]
        with cols[i % len(cols)]:
            with st.container(key=f"team_{t}", border=True):
                st.markdown(f"#### 팀{t} ({len(ms)}/4)")
                st.markdown("\n".join(member_line(m) for m in ms) if ms else "_빈 팀_")
                apps = [a for a in S["pending"] if a["team_id"] == t]
                if apps:
                    st.caption("대기 지원: " + ", ".join(S["students"][a["student_id"]]["name"] for a in apps))
    assigned = {m["id"] for ms in S["members"].values() for m in ms}
    st.subheader("팀이 없는 학생")
    with st.container(key="unassigned", border=True):
        rest = [s for s in S["students"].values() if s["id"] not in assigned]
        st.markdown("\n".join(member_line(s) for s in rest) if rest else "_없음_")
    st.caption(f"모집: {'마감' if S['closed'] else '진행 중'} · 화면은 {REFRESH_S}초마다 다시 그림")


def plan_table(plan, source):
    with DB.tx() as repo:
        by_no = {s["student_no"]: s for s in repo.all_students()}
    rows = [{"이름": by_no[n]["name"] if n in by_no else n,
             "주 역할": by_no[n]["main"] if n in by_no else "",
             "보조 역할": ", ".join(r for r in rules.ROLES if n in by_no and r in by_no[n]["subs"]),
             "배정된 팀": f"팀{t}"} for n, t in plan]
    st.markdown(f"**배정안** (만든 곳: {source})")
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def do_assign(status_box) -> str:
    with DB.tx() as repo:
        if not service.is_closed(repo):
            return "막힘: 먼저 모집을 마감해야 함"
        teams, unassigned = service.snapshot(repo)

    def say(msg):
        ss.assign_msg = msg
        status_box.info(msg)

    # 규칙을 지키는 배정이 있는지 먼저 모든 경우를 따져 확인함
    say("규칙을 지키는 배정이 있는지 확인하는 중…")
    fallback = rules.solve(teams, unassigned)
    if fallback is None:
        reason = rules.diagnose(teams, unassigned)
        ss.assign_msg = f"규칙을 지키는 배정이 없음: {reason}"
        status_box.error(ss.assign_msg)
        return "막힘: 규칙을 지키는 배정이 없음"
    if not unassigned:
        plan, source = [], "팀이 없는 학생이 없음"
    else:
        def log(attempt, model, outcome, detail, elapsed):
            with DB.tx() as r:
                r.ai_log(attempt, model, outcome, detail, elapsed)
        plan, source = ai_assign.assign_with_ai(secret("OPENROUTER_API_KEY"), models(),
                                                teams, unassigned, say, log)
        if plan is None:
            plan, source = fallback, "앱이 직접 찾음(3차 모델까지 실패)"
            with DB.tx() as r:
                r.ai_log(4, "앱 자체 배정", "성공", "모든 경우를 따져 찾은 배정안", 0)
    with DB.tx() as repo:
        repo.setting_set("proposal", json.dumps({"plan": plan, "source": source}, ensure_ascii=False))
    ss.assign_msg = f"배정안을 만듦: {source}. 아래 배정안을 확인하고 확정해 주세요."
    status_box.success(ss.assign_msg)
    return f"승인: 배정안을 만듦({source})"


def do_start(file, team_count) -> str:
    if file is None:
        return "막힘: 명단 CSV 파일을 올려 주세요"
    try:
        text = file.getvalue().decode("utf-8-sig")
        rows = service.parse_roster(text)
    except UnicodeDecodeError:
        return "막힘: CSV를 UTF-8로 읽을 수 없음"
    except ValueError as e:
        return f"막힘: CSV 오류 - {e}"
    n = int(team_count)
    if not 1 <= n <= 10:
        return "막힘: 팀 수는 1~10이어야 함"
    try:
        with DB.tx() as repo:
            repo.reset(rows, n)
    except Exception as e:
        return f"막힘: 처음 상태를 만들지 못함({type(e).__name__})"
    ss.assign_msg = ""
    return f"승인: 명단으로 처음 상태를 만듦(학생 {len(rows)}명, 팀 {n}개)"


def admin_view(user):
    show_result_slot = st.empty()
    action = None

    with st.expander("1. 명단 올리기", expanded=True):
        file = st.file_uploader("명단 CSV (UTF-8, BOM 있어도 됨)", type=["csv"], key="admin_roster_file")
        count = st.number_input("팀 수", min_value=1, max_value=10, value=3, step=1, key="admin_team_count")
        if st.button("명단으로 처음 상태 만들기", key="admin_start", type="primary"):
            action = "start"

    st.markdown("##### 2. 모집 마감")
    if st.button("모집 마감", key="admin_close"):
        action = "close"

    st.markdown("##### 3. 남은 학생 배정")
    c1, c2 = st.columns(2)
    if c1.button("AI 배정", key="admin_assign"):
        action = "assign"
    if c2.button("배정안 확정", key="admin_confirm"):
        action = "confirm"
    with st.container(key="assign_status"):
        status_box = st.empty()
        if ss.get("assign_msg"):
            msg = ss.assign_msg
            (status_box.error if msg.startswith("규칙을 지키는 배정이 없음") else status_box.info)(msg)

    if action == "start":
        ss.last_result = do_start(file, count)
    elif action == "close":
        ss.last_result = run(service.close)
        ss.assign_msg = ""
    elif action == "assign":
        ss.last_result = do_assign(status_box)
    elif action == "confirm":
        with DB.tx() as repo:
            raw = repo.setting_get("proposal") or ""
        if not raw:
            ss.last_result = "막힘: 확정할 배정안이 없음(먼저 AI 배정을 눌러 주세요)"
        else:
            plan = [(str(n), int(t)) for n, t in json.loads(raw)["plan"]]
            ss.last_result = run(service.confirm, plan)
            if ss.last_result.startswith("승인"):
                ss.assign_msg = "배정안을 확정했음"
    if action:
        st.rerun()

    with show_result_slot.container():
        show_result()

    with DB.tx() as repo:
        raw = repo.setting_get("proposal") or ""
    if raw:
        p = json.loads(raw)
        plan_table([(str(n), int(t)) for n, t in p["plan"]], p["source"])

    admin_board()

    with st.expander("AI 호출 기록"):
        st.caption("모델: " + " → ".join(f"{i}차 {m}" for i, m in enumerate(models(), start=1)))
        with DB.tx() as repo:
            logs = repo.ai_logs()
        if logs:
            st.dataframe(pd.DataFrame([{"시각(한국)": kst(r["created_at"]),
                                        "차수": "앱" if r["attempt"] == 4 else f"{r['attempt']}차",
                                        "모델": r["model"], "결과": r["outcome"], "걸린 초": r["elapsed_s"],
                                        "자세히": r["detail"]} for r in logs]),
                         hide_index=True)
        else:
            st.caption("기록 없음")


# ---------------------------------------------------------------- 시작

user = current_user()
if user is None:
    login_page()
else:
    header(user)
    if user["is_admin"]:
        admin_view(user)
    else:
        student_view(user["student_no"])
