# 독립 식단 데이터베이스

## 구조

식단 카탈로그는 사용자·운동 기록 PostgreSQL과 물리적으로 분리한다.

| 구분 | 기존 데이터 DB | 식단 카탈로그 DB |
|---|---|---|
| Compose 서비스 | `db` | `meal-db` |
| 데이터베이스 | `gymrat` | `meal_catalog` |
| 연결 환경변수 | `DATABASE_URL` | `MEAL_DATABASE_URL` |
| Docker 볼륨 | `pgdata` | `meal_pgdata` |
| SQLAlchemy Base | `db.models.Base` | `meal_db.models.MealBase` |
| migration | `alembic/` | `meal_alembic/` |

두 저장소 사이에는 외래키와 교차 transaction이 없다. 식단 코드에서
`DATABASE_URL`, `db.models.Base`, 기존 Alembic metadata를 사용하지 않는다.

## 시작 과정

1. Docker가 `db`와 `meal-db`를 각각 시작한다.
2. 두 서비스의 healthcheck가 통과한 후 MCP 서버가 시작된다.
3. 기존 `init_db()`는 기존 DB migration만 적용한다.
4. `init_meal_db()`는 식단 DB의 독립 migration을 적용한다.
5. `option_id`가 없는 내장 후보만 추가한다. 재시작해도 기존 행은 덮어쓰거나 중복 삽입하지 않는다.
6. `generate_meal_plan`은 `meal-db`의 활성 후보만 조회해 선택기에 전달한다.

## 현재 카탈로그

- 총 72개
- 아침 18개
- 점심 18개
- 저녁 18개
- 간식 18개

각 후보는 메뉴명, 끼니 유형, 구성 요소, 식재료, 균형 축, 적용 목표,
활성화 상태와 선택 가중치를 저장한다. 사용자 선호·비선호·알레르기 필터는
조회된 후보의 식재료 태그를 대상으로 적용한다.

스포츠영양 metadata로 알레르겐, 식단 유형, 단백질 family, 통곡물 여부,
미량영양소 초점, 운동 전후 맥락, 소화 부담, 회복 역할, 근거 source ID,
영양 검증 상태를 저장한다. `nutrition_evidence_sources`는 ACSM·ISSN·USDA·AIS
자료의 제목, 기관, URL과 적용 요지를 보관한다.

표준 중량과 조리 상태가 없는 현재 메뉴는 모두
`principle_based_unverified_portion`이며 `nutrition_verified=false`다.

## 장애 격리

- 식단 DB 오류 시 기존 DB로 fallback하지 않는다.
- 식단 추천만 `MealCatalogUnavailable`로 실패하며 기존 기록 DB에는 쓰지 않는다.
- SQLAlchemy `pool_pre_ping`으로 식단 DB 컨테이너 재시작 후 죽은 연결을 교체한다.
- 식단 DB는 호스트 포트를 공개하지 않아 기존 PostgreSQL의 `5432`와 충돌하지 않는다.

## 검증 항목

- 기존 DB에 `meal_options`가 없는지 확인
- 식단 DB에 `users`, `meal_logs`, `weight_logs`가 없는지 확인
- seed 두 번째 실행의 삽입 수가 0인지 확인
- 식단 DB 재시작 후 서버 재시작 없이 MCP 추천이 복구되는지 확인
- 기존 DB의 테이블 목록과 핵심 행 수가 작업 전후 동일한지 확인
