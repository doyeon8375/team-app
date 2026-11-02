"""오픈라우터 AI 배정: 1차 → 2차 → 3차 모델, 모델마다 전체 120초 제한.

AI 의 답은 rules.validate_plan 으로 검사하고, 통과하지 못하면 다음 모델로 넘어감.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time

import requests

import rules

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_S = 120

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _student_json(s: dict) -> dict:
    return {"student_no": s["student_no"], "name": s["name"], "main_role": s["main"],
            "sub_roles": [r for r in rules.ROLES if r in s["subs"]]}


def build_prompt(teams: dict[int, list[dict]], unassigned: list[dict]) -> str:
    data = {
        "teams": [{"team": tid, "members": [_student_json(m) for m in ms]} for tid, ms in sorted(teams.items())],
        "unassigned_students": [_student_json(s) for s in unassigned],
    }
    return (
        "너는 대학 수업의 팀 프로젝트 팀을 편성하는 도우미야. 아래 JSON 은 지금의 팀 구성과 팀이 없는 학생이야.\n"
        "팀이 없는 학생만 기존 팀에 넣어. 이미 팀에 있는 학생은 옮기지 마. 새 팀을 만들지 마.\n"
        "규칙:\n"
        "1. 팀이 없는 학생은 빠짐없이, 각각 정확히 한 팀에 배정한다.\n"
        "2. 배정한 뒤 모든 팀은 2~4명이다.\n"
        "3. 한 팀 안에 main_role 이 같은 학생이 2명 이상이면 안 된다.\n"
        "4. 모든 팀에는 '기획자'를 맡을 학생과 '웹 프로그래머'를 맡을 학생이 서로 다른 사람으로 1명씩 있어야 한다. "
        "main_role 이나 sub_roles 에 그 역할이 있으면 맡을 수 있다. 한 학생이 둘을 동시에 맡을 수는 없다.\n\n"
        f"데이터:\n{json.dumps(data, ensure_ascii=False)}\n\n"
        "답은 설명 없이 아래 형식의 JSON 하나만 써.\n"
        '{"assignments": [{"student_no": "학번", "team": 팀번호}]}'
    )


def parse_plan(text: str) -> list[tuple[str, int]]:
    """AI 의 답에서 배정안을 꺼냄. 형식이 틀리면 ValueError."""
    if not text or not text.strip():
        raise ValueError("빈 응답")
    t = re.sub(r"```(?:json)?", "", text)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("응답에 JSON 이 없음")
    obj = json.loads(t[start:end + 1])
    items = obj.get("assignments") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise ValueError("assignments 목록이 없음")
    plan = []
    for it in items:
        no = str(it["student_no"]).strip()
        team = it["team"]
        if isinstance(team, str):
            team = int(re.sub(r"\D", "", team))
        plan.append((no, int(team)))
    return plan


def _call(api_key: str, model: str, prompt: str) -> str:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "X-Title": "Team Formation App"},
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 8000,
              "temperature": 0.2,
              "reasoning": {"effort": "low"}},
        timeout=(10, TIMEOUT_S + 10),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"오류 응답: {str(body['error'])[:200]}")
    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if not content or not content.strip():
        raise ValueError("빈 응답")
    return content


def assign_with_ai(api_key: str, models: list[str], teams, unassigned, on_status, on_log):
    """모델을 차례로 부름. 검사를 통과한 배정안과 모델 이름을 돌려줌. 모두 실패하면 (None, None).

    on_status(글자): 화면 안내를 바꿈. on_log(차수, 모델, 결과, 자세히, 걸린 초): 기록.
    """
    prompt = build_prompt(teams, unassigned)
    for i, model in enumerate(models, start=1):
        t0 = time.monotonic()
        fut = _executor.submit(_call, api_key, model, prompt)
        outcome, detail, plan = "", "", None
        while True:
            left = TIMEOUT_S - (time.monotonic() - t0)
            if left <= 0:
                fut.cancel()   # 이미 시작한 요청은 버림(결과를 기다리지 않음)
                outcome, detail = "시간 초과", f"{TIMEOUT_S}초 안에 응답하지 않음"
                break
            on_status(f"{i}차 모델({model})의 응답을 기다리는 중… {int(time.monotonic() - t0)}초 / {TIMEOUT_S}초")
            try:
                text = fut.result(timeout=min(1.0, left))
            except concurrent.futures.TimeoutError:
                continue
            except ValueError as e:
                outcome, detail = "빈 응답" if "빈 응답" in str(e) else "오류", str(e)
                break
            except Exception as e:  # HTTP 오류, 429, 연결 오류 등
                outcome, detail = "오류", str(e)
                break
            try:
                plan = parse_plan(text)
            except Exception as e:
                outcome, detail = "형식 오류", f"{e}: {text[:300]}"
                plan = None
                break
            errors = rules.validate_plan(teams, unassigned, plan)
            if errors:
                outcome, detail = "검사 실패", "; ".join(errors)
                plan = None
            else:
                outcome, detail = "성공", f"{len(plan)}명 배정"
            break
        elapsed = round(time.monotonic() - t0, 1)
        on_log(i, model, outcome, detail, elapsed)
        if plan is not None:
            return plan, f"{i}차 모델({model})"
        on_status(f"{i}차 모델 실패({outcome}: {detail[:120]}). 다음으로 넘어감")
    return None, None
