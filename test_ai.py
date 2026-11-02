"""AI 실패 처리 시험: 가짜 모델로 시간 초과, 빈 응답, 검사 실패, 성공을 차례로 만듦.

실행: python tests/test_ai.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ai_assign  # noqa: E402

s = lambda no, main, subs=(): {"student_no": no, "name": no, "main": main, "subs": set(subs)}
teams = {1: [s("a", "기획자")], 2: [s("b", "웹 프로그래머")]}
un = [s("c", "웹 프로그래머"), s("d", "기획자")]
good = '```json\n{"assignments": [{"student_no": "c", "team": 1}, {"student_no": "d", "team": "팀2"}]}\n```'
bad = '{"assignments": [{"student_no": "c", "team": 2}, {"student_no": "d", "team": 1}]}'

ai_assign.TIMEOUT_S = 2


def fake_call(key, model, prompt):
    if model == "slow":
        time.sleep(4); return good
    if model == "empty":
        raise ValueError("빈 응답")
    if model == "bad":
        return bad
    return good


ai_assign._call = fake_call
logs = []
plan, src = ai_assign.assign_with_ai("k", ["slow", "bad", "ok"], teams, un, lambda m: None,
                                     lambda *a: logs.append(a))
for l in logs:
    print(l)
assert [l[2] for l in logs] == ["시간 초과", "검사 실패", "성공"], logs
assert logs[0][4] <= 2.5, "120초(여기선 2초) 전체 제한이 지켜지지 않음"
assert src.startswith("3차")
logs.clear()
plan, src = ai_assign.assign_with_ai("k", ["empty", "bad", "slow"], teams, un, lambda m: None,
                                     lambda *a: logs.append(a))
assert plan is None and [l[2] for l in logs] == ["빈 응답", "검사 실패", "시간 초과"], logs
print("AI 실패 처리 시험 통과")
