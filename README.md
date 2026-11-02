# 팀 프로젝트 팀 편성 앱

> ✏️ 표시가 있는 곳은 직접 채워야 함. 제출 전에 이 줄과 ✏️ 안내를 지울 것.

## 1. 배포 주소
✏️ https://______.streamlit.app

## 2. PRD와 구현 계획
- `docs/PRD.md`
- `docs/구현 계획.md`

## 3. 고른 해결 방법
| 기능 | 고른 해결 | 내용 |
|---|---|---|
| 다른 사람의 변경 보기 | 어려운 해결 | `st.fragment(run_every=3)` 로 팀 목록, 투표, 팀이 없는 학생을 3초마다 다시 그림 |
| 필수 포함 역할을 지킬 수 없는 팀 | 어려운 해결 | 지원할 때, 들어간 뒤 남는 자리 수가 못 채운 필수 역할 수보다 적으면 막음(`rules.join_block_reason`) |
| 같은 팀에 대기 중인 지원이 여럿 | 어려운 해결 | 마지막 찬성이 들어와 승인하려는 때 정원, 주 역할 중복, 필수 역할 자리를 다시 검사(`service._try_approve`) |
| 마지막 자리에 두 명이 동시에 들어감 | 어려운 해결 | `tf_members` 의 `primary key (team_id, slot_no)` 와 `student_id unique`(`schema.sql`), 팀 행 `for update` 잠금 |
| AI 응답이 늦을 때 | 어려운 해결 | 요청을 따로 실행하고 1초마다 경과를 재서 모델마다 전체 120초가 되면 끊고 다음 모델로 넘어감(`ai_assign.py`) |
| 3차 모델까지 실패 | 어려운 해결 | 검사 다섯 가지를 모두 통과하는 배정을 백트래킹으로 모든 경우를 따져 찾음(`rules.solve`). 배정이 없으면 이유를 보여 주고 AI를 부르지 않음 |
| AI 대기 중 화면 | 어려운 해결 | `assign_status` 에 "N차 모델(이름)의 응답을 기다리는 중… 경과 초 / 120초" |
| DB 일시정지 막기 | 어려운 해결 | GitHub Actions 예약 작업(`.github/workflows/keep-db-awake.yml`)이 매일 DB에 질의 |

## 4. 쓴 모델
✏️ Streamlit Secrets 의 `MODEL_1~3` 에 실제로 넣은 이름으로 고칠 것
- 1차 `nvidia/nemotron-3-super-120b-a12b:free`
- 2차 `______:free`
- 3차 `______:free`

## 5. 오픈라우터 AI 모델 호출 실패 사례
✏️ 관리자 화면의 "AI 호출 기록"에 실제로 남은 실패(시간 초과, 오류, 빈 응답, 검사 실패)를 캡처해 `img/` 에 넣고 적을 것.
예시 형식: "N차 모델(이름)이 ___ 해서 다음 모델로 넘어감(화면 `img/ai-fail.png`)"

## 6. 클로드가 잘못된 추론이나 답변을 한 사례
✏️ 직접 겪은 사례와, 알아챈 방법(화면 또는 커밋 해시)을 적을 것.

## 7. 내 앱의 문제점이나 개선할 점
✏️ 연습용 시나리오를 해 보다 발견한 것을 단계와 화면으로 적을 것("문제 없음"은 인정되지 않음).

---

## 실행 방법(로컬)
```bash
pip install -r requirements.txt
cp .env.example .env      # 값을 채움
streamlit run streamlit_app.py
```
규칙 시험: `python tests/test_scenarios.py`, `python tests/test_ai.py` (DB 없이 실행됨)

## 파일
| 파일 | 내용 |
|---|---|
| `streamlit_app.py` | 화면 |
| `rules.py` | 규칙 검사, 완전 탐색 배정 |
| `service.py` | 지원, 투표, 마감, 확정 |
| `db.py` | Supabase 연결과 질의 |
| `ai_assign.py` | 오픈라우터 1~3차 모델 호출 |
| `schema.sql` | `tf_` 테이블 |
| `sample_data/` | 연습용 시나리오 명단(가상 학생) |
