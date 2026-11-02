# 팀 프로젝트 팀 편성 앱

## 1. 배포 주소
https://team-app-yeon.streamlit.app

## 2. PRD와 구현 계획
- `PRD.md`
- `구현 계획.md`

## 3. 고른 해결 방법
| 기능 | 고른 해결 | 내용 |
|---|---|---|
| 다른 사람의 변경 보기 | 어려운 해결 | `st.fragment(run_every=3)` 로 팀 목록, 투표, 팀이 없는 학생을 3초마다 다시 그림 |
| 필수 포함 역할을 지킬 수 없는 팀 | 어려운 해결 | 지원할 때, 들어간 뒤 남는 자리 수가 못 채운 필수 역할 수보다 적으면 막음(`rules.py` 의 `join_block_reason`) |
| 같은 팀에 대기 중인 지원이 여럿 | 어려운 해결 | 마지막 찬성이 들어와 승인하려는 때 정원, 주 역할 중복, 필수 역할 자리를 다시 검사(`service.py` 의 `_try_approve`) |
| 마지막 자리에 두 명이 동시에 들어감 | 어려운 해결 | `tf_members` 의 `primary key (team_id, slot_no)` 와 `student_id unique`(`schema.sql`), 팀 행 `for update` 잠금 |
| AI 응답이 늦을 때 | 어려운 해결 | 요청을 따로 실행하고 1초마다 경과를 재서, 모델마다 전체 120초가 되면 끊고 다음 모델로 넘어감(`ai_assign.py`) |
| 3차 모델까지 실패 | 어려운 해결 | 검사 다섯 가지를 모두 통과하는 배정을 백트래킹으로 모든 경우를 따져 찾음(`rules.py` 의 `solve`). 배정이 없으면 이유를 보여 주고 AI를 부르지 않음 |
| AI 대기 중 화면 | 어려운 해결 | `assign_status` 에 "N차 모델(이름)의 응답을 기다리는 중… 경과 초 / 120초" 를 보여 줌 |
| DB 일시정지 막기 | 어려운 해결 | GitHub Actions 예약 작업(`.github/workflows/keep-db-awake.yml`)이 매일 00:17 UTC에 DB에 질의함(화면 `actions-success.png`) |

## 4. 쓴 모델
- 1차 `nvidia/nemotron-3.5-super-vl:free`
- 2차 `cohere/north-mini-code:free`
- 3차 `liquid/lfm-2.5-2.6b:free`

## 5. 오픈라우터 AI 모델 호출 실패 사례
부록 1(쉬움) 연습 시나리오 6단계에서 AI 배정을 눌렀을 때, 처음 설정했던 1차 `nvidia/nemotron-3-super-120b-a12b:free`, 2차 `openai/gpt-oss-120b:free`, 3차 `z-ai/glm-4.5-air:free` 가 모두 HTTP 404(무료로 더 이상 제공하지 않음)로 실패함. 앱이 1차 → 2차 → 3차로 넘어간 뒤, 3차까지 실패하자 모든 경우를 따져 찾은 배정안을 만들었고 이를 확정함(화면 `ai-fail.png`, 관리자 화면의 "AI 호출 기록").

## 6. 클로드가 잘못된 추론이나 답변을 한 사례
클로드가 앱을 만들 때 1~3차 기본 모델 이름을, 지금도 무료로 쓸 수 있는지 확인하지 않고 넣었음. 배포한 뒤 부록 1(쉬움) 6단계에서 "AI 호출 기록"에 세 모델 모두 HTTP 404 "This model is unavailable for free" 가 뜬 것을 보고 알아챔(화면 `ai-fail.png`). 오픈라우터 모델 목록에서 지금 무료인 텍스트 모델 3개를 직접 골라 Streamlit Secrets 의 `MODEL_1~3` 으로 바꿨고, 다시 시험했을 때 1차 모델이 성공함(화면 `ai-success.png`).

## 7. 내 앱의 문제점이나 개선할 점
중간.csv 명단(학생 12명, 팀 4개)으로 처음 상태를 만들고 바로 마감한 뒤 AI 배정을 눌렀을 때, 1차 모델의 응답에 75.2초가 걸려 관리자가 그동안 기다려야 했음(화면 `ai-success.png`). 세 모델이 모두 느리면 최대 6분(120초 × 3)까지 걸릴 수 있음. 개선 방법: 모델의 제한 시간을 줄이거나, 앱이 미리 찾아 둔 배정안을 먼저 보여 주고 AI 답은 뒤에 비교하게 바꾸기.

---

## 실행 방법(로컬)
pip install -r requirements.txt 한 뒤 .env 를 만들고 streamlit run streamlit_app.py

규칙 시험: python test_scenarios.py, python test_ai.py
