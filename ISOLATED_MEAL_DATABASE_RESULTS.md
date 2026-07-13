# 독립 식단 DB 구현 및 검증 결과

## 결과

- 기존 PostgreSQL과 별개인 `meal-db` 서비스와 `meal_pgdata` 볼륨을 추가했다.
- 기존 `db/models.py`, `db/session.py`, `alembic/` migration은 수정하지 않았다.
- 식단 DB는 독립 SQLAlchemy Base, 세션, migration 이력과 seed를 사용한다.
- 추천 런타임은 식단 DB에서 활성 후보를 조회하며 정적 fallback을 사용하지 않는다.
- 카탈로그를 기존 27개에서 총 72개로 확장하고 스포츠영양 metadata와 근거 출처를 추가했다.

## 기존 DB 무충돌 증거

작업 전후 기존 DB 공개 테이블은 동일했다.

```text
alembic_version, exercise_library, exercise_sets, inbody_logs, meal_logs,
programs, users, weight_logs, workout_logs
```

기존 핵심 행 수도 동일했다.

```text
users=57
meal_logs=44
weight_logs=19
```

식단 DB 공개 테이블은 다음 세 개뿐이다.

```text
alembic_version
meal_options
nutrition_evidence_sources
```

볼륨도 `gymrat-mcp_pgdata`, `gymrat-mcp_meal_pgdata`로 분리됐다.

## 검증 결과

- 로컬 전체 회귀: `192 passed, 33 subtests passed`
- 독립 SQLite 격리 테스트: main DB에 `meal_options` 없음, meal DB에 `users` 없음
- idempotent seed: 최신 적재 후 72개, 두 번째 삽입 0개
- Docker 식단 DB: 아침·점심·저녁·간식 각각 18개, 총 72개
- 실제 Docker MCP 반복 호출: 8회 모두 서로 다른 조합
- 선호·비선호·알레르기 및 위험 식단 가드레일 통과
- `meal-db` 단독 재시작 후 서버 재시작 없이 MCP 호출 자동 복구 확인
