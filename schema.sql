-- 팀 편성 앱의 테이블(모두 tf_ 로 시작). 앱이 시작할 때 이 파일을 그대로 실행함(이미 있으면 건너뜀).

create table if not exists tf_students (
    id            serial primary key,
    student_no    text not null unique,                 -- 학번(유일)
    name          text not null,
    main_role     text check (main_role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                                            '테스터', '보고서 작성자', '발표자')),  -- 관리자는 null
    password_hash text not null,                        -- bcrypt 해시(비밀번호 원문은 저장하지 않음)
    is_admin      boolean not null default false
);

create table if not exists tf_student_sub_roles (
    student_id integer not null references tf_students(id) on delete cascade,
    role       text not null check (role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                                             '테스터', '보고서 작성자', '발표자')),
    primary key (student_id, role)
);

create table if not exists tf_teams (
    id   integer primary key,                           -- 팀 번호(팀1 → 1)
    name text not null unique
);

create table if not exists tf_members (
    team_id    integer not null references tf_teams(id) on delete cascade,
    slot_no    integer not null check (slot_no between 1 and 4),   -- 다섯 번째 자리를 막음
    student_id integer not null unique references tf_students(id) on delete cascade,  -- 한 학생은 한 팀
    joined_at  timestamptz not null default now(),
    primary key (team_id, slot_no)                      -- 같은 자리에는 먼저 도착한 학생만 기록됨
);

create table if not exists tf_applications (
    id         serial primary key,
    team_id    integer not null references tf_teams(id) on delete cascade,
    student_id integer not null references tf_students(id) on delete cascade,
    status     text not null check (status in ('대기', '승인', '거절')),
    reason     text,
    created_at timestamptz not null default now(),
    decided_at timestamptz
);

-- 한 학생은 결과를 기다리는 지원을 하나만 가질 수 있음
create unique index if not exists tf_applications_one_pending
    on tf_applications (student_id) where status = '대기';

create table if not exists tf_votes (
    application_id integer not null references tf_applications(id) on delete cascade,
    voter_id       integer not null references tf_students(id) on delete cascade,
    vote           text not null check (vote in ('찬성', '거부')),
    created_at     timestamptz not null default now(),
    primary key (application_id, voter_id)              -- 한 번 투표하면 바꿀 수 없음
);

create table if not exists tf_settings (
    key   text primary key,                             -- closed, proposal, confirmed
    value text
);

create table if not exists tf_ai_logs (
    id         serial primary key,
    created_at timestamptz not null default now(),
    attempt    integer not null,                        -- 1차, 2차, 3차
    model      text not null,
    outcome    text not null,                           -- 성공, 시간 초과, 오류, 빈 응답, 검사 실패
    detail     text,
    elapsed_s  real
);
