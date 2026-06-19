# GymRat MCP

카톡 안에 사는 AI 퍼스널 트레이너. PlayMCP / Kakao Tools에 등록하는 MCP 서버.

## 구조

```
gymrat-mcp/
├── server.py            # FastMCP 진입점, 툴 10개 등록 (얇게 유지)
├── tools/
│   ├── profile.py       # get_profile, update_profile        [구현됨]
│   ├── logging_tools.py # log_weight/inbody/workout/meal      [저장 구현, 파싱 TODO]
│   ├── analysis.py      # analyze_trend                       [구조, TODO]
│   ├── routine.py       # generate_routine                    [구조, TODO]
│   └── coaching.py      # generate_meal_plan, get_recommendation [구조, TODO]
├── db/
│   ├── models.py        # SQLAlchemy 테이블
│   ├── session.py       # 커넥션 / init_db
│   └── seed_exercises.py# 운동 라이브러리 적재
├── data/exercises.json  # 운동 라이브러리 (확장)
├── Dockerfile
└── docker-compose.yml
```

## 로컬 실행

```bash
# 1) 의존성
pip install -r requirements.txt

# 2) (옵션) DB 없이 빠른 테스트 — DATABASE_URL 미설정 시 SQLite 사용
python -m db.seed_exercises     # 운동 라이브러리 적재
python server.py                # http://0.0.0.0:8000

# 또는 Postgres 포함 통째로
docker compose up --build
```

## MCP 동작 확인 (배포 전 스모크 테스트)

```bash
# MCP Inspector로 툴 목록·호출 확인
npx @modelcontextprotocol/inspector
# 서버 URL: http://localhost:8000/mcp  (Streamable HTTP)
```

## 진행 체크리스트

- [x] 프로젝트 스캐폴딩
- [x] DB 스키마 (users, *_logs, exercise_library)
- [x] 프로필 툴 구현
- [x] 기록 툴 저장 로직
- [ ] **이미지 입력 가능 여부 확인** (인바디·식단 좌우)
- [ ] **톡캘린더 쓰기 권한 확인** (식사·운동 알림 좌우)
- [ ] log_workout 자연어 파서 (_parse_workout)
- [ ] analyze_trend 통계 로직
- [ ] generate_routine 점진적 과부하 룰
- [ ] generate_meal_plan 질적 가이드 룰
- [ ] 운동 라이브러리 30~50개로 확장
- [ ] 카카오 클라우드 배포 + PlayMCP 등록 왕복
- [ ] 페르소나 톤 가이드 4종

## 가드레일 (절대 원칙)

- 정확 칼로리/그램 수치 ❌ → 질적 코칭만
- 하드한 제한식·식이강박 조장 ❌
- 자세는 텍스트 큐까지만 (정밀 판정 ❌)
- 페르소나는 말투만 — 가드레일은 항상 적용
