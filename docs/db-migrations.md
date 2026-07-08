# DB 마이그레이션 가이드 (Alembic)

> DB 스키마(테이블·컬럼)를 바꿀 때 **반드시** 따라야 하는 절차입니다.
> 모델(`db/models.py`)만 고치고 마이그레이션을 안 만들면 프로덕션에는 반영되지
> 않습니다. (실제로 이 사고가 한 번 났습니다 — 아래 "왜 필요한가" 참고)

---

## 0. 30초 요약

```bash
# 1) db/models.py 에서 모델 수정
# 2) 마이그레이션 생성 (순번은 직전 +1)
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate --rev-id 0003 -m "add users.height_cm"
# 3) alembic/versions/0003_*.py 를 눈으로 검토·수정
# 4) 로컬 적용 + 테스트 → 커밋 → PR to dev
.venv/bin/alembic upgrade head
.venv/bin/pytest -q
```

`dev`에 머지하면 자동배포가 재빌드+재시작하며 프로덕션에 자동 반영됩니다.
**수동 SQL(ALTER) 실행 금지** — 마이그레이션 파일이 유일한 경로입니다.

---

## 왜 필요한가

예전 `init_db()`는 `Base.metadata.create_all()`만 호출했습니다. 이건
**"없는 테이블만 새로 만들 뿐, 기존 테이블에 새 컬럼을 추가하지 않습니다."**
그래서 모델에 `available_equipment` 컬럼을 추가해도 이미 존재하던 배포
Postgres의 `users` 테이블엔 반영되지 않았고, 조회할 때 이런 오류가 터졌습니다.

```
column users.available_equipment does not exist
```

Alembic은 스키마 변경을 **버전이 매겨진 파일**로 기록하고, 배포 때
`alembic upgrade head`로 순서대로 적용해 이 문제를 없앱니다.

---

## 구조

```
alembic.ini                 # 설정 (DB URL 은 여기 없음 — 아래 env.py 가 앱에서 가져옴)
alembic/
  env.py                    # db.session 의 DATABASE_URL·Base 를 단일 소스로 재사용
  versions/
    0001_baseline.py        # Alembic 도입 시점의 전체 스키마
    0002_...py              # 이후 변경 하나당 파일 하나
db/session.py               # init_db() 가 앱 시작 시 upgrade head 실행
```

- **DB 접속 정보는 `alembic.ini`에 없습니다.** `env.py`가 앱과 똑같이
  `db.session.DATABASE_URL`을 읽으므로, 로컬은 `gymrat_dev.db`(sqlite),
  배포는 Postgres에 자동으로 붙습니다. 따로 설정할 것 없습니다.
- 순번(rev-id)은 `0001`, `0002`, `0003` … 4자리로 이어갑니다.

---

## 앱 시작 시 동작 (`init_db()`)

| DB 상태 | 동작 |
|---|---|
| 완전히 빈 DB (신규 배포) | 처음부터 `upgrade head` → 전체 스키마 생성 |
| 기존 DB (`alembic_version` 없음) | `0001` stamp 후 `upgrade head` → 누락분만 반영 |
| 이미 최신 | `upgrade head` 가 아무것도 안 함 (idempotent) |

기존 데이터는 항상 보존됩니다(Postgres는 `pgdata` 볼륨 유지).

---

## 표준 절차 (자세히)

### 1. 모델 수정
`db/models.py`에서 컬럼/테이블을 추가·변경합니다.

```python
class User(Base):
    __tablename__ = "users"
    ...
    height_cm = Column(Float, nullable=True)   # 새 컬럼
```

### 2. 마이그레이션 자동생성
autogenerate는 **"현재 로컬 DB"와 "모델"의 차이**를 잡습니다. 그래서 먼저
로컬 DB를 head로 맞춘 뒤 생성해야 엉뚱한 diff가 안 섞입니다.

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate --rev-id 0003 -m "add users.height_cm"
```

- `--rev-id 0003` : **직전 순번 +1**. 안 주면 랜덤 해시가 되어 순서 추적이 어려워집니다.
- 결과: `alembic/versions/0003_add_users_height_cm.py`
- 바뀔 게 없으면 `No changes detected in schema` — 정상(모델 == head).

### 3. 생성 파일 검토 (가장 중요)
autogenerate는 만능이 아닙니다. **반드시 `upgrade()`/`downgrade()`를 눈으로 확인**하세요.

- **컬럼 rename** → autogenerate는 `drop_column` + `add_column`으로 잡습니다
  (데이터 날아감!). 직접 `op.alter_column(..., new_column_name=...)`으로 고치세요.
- **NOT NULL 컬럼 추가** → 기존 행 때문에 실패합니다. `server_default`를 주거나
  3단계(널 허용 추가 → 값 채움 → NOT NULL)로 나누세요.
- **데이터 이관**이 필요하면 `op.execute("UPDATE ...")`를 직접 추가.

### 4. 로컬 적용 + 테스트
```bash
.venv/bin/alembic upgrade head    # 로컬 sqlite 에 실제 적용
.venv/bin/pytest -q
```

### 5. 커밋 → PR to `dev` → 머지
머지되면 `deploy.yml`이 Lightsail에서 `docker compose up -d --build`로
재빌드+재시작 → `init_db()`가 `upgrade head`를 실행 → 프로덕션 반영 완료.

---

## 예시 모음

### 예시 A — 컬럼 추가 (가장 흔함)
모델에 `Column("height_cm", Float, nullable=True)` 추가 후 생성하면:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column("height_cm", sa.Float(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table("users") as batch:   # SQLite 는 DROP 에 batch 필요
        batch.drop_column("height_cm")
```

> **Tip.** 기존 배포/로컬 DB에 이미 컬럼이 있을 수 있는 전환기 상황이라면
> `0002`처럼 존재 여부를 확인하고 추가하는 가드를 넣으면 안전합니다.
> (평상시 새 컬럼은 그럴 필요 없음)
>
> ```python
> existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
> if "height_cm" not in existing:
>     op.add_column("users", sa.Column("height_cm", sa.Float(), nullable=True))
> ```

### 예시 B — 새 테이블 추가
모델에 새 클래스를 추가한 뒤 autogenerate하면 `op.create_table(...)` /
`op.drop_table(...)`가 통째로 생성됩니다. 그대로 검토만 하면 됩니다.

### 예시 C — NOT NULL 컬럼을 기존 테이블에 추가
바로 `nullable=False`로 추가하면 기존 행 때문에 실패합니다. 기본값을 주세요.

```python
def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("units", sa.String(), nullable=False, server_default="kg"),
    )
    # 애플리케이션이 항상 값을 넣는다면, 이후 서버 기본값 제거도 가능:
    # op.alter_column("users", "units", server_default=None)
```

### 예시 D — 컬럼 이름 변경 (autogenerate 신뢰 금지)
autogenerate는 drop+add로 잘못 잡습니다. 직접 이렇게 고치세요.

```python
def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("injuries", new_column_name="injury_note")

def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("injury_note", new_column_name="injuries")
```

---

## 자주 쓰는 명령

```bash
.venv/bin/alembic current      # 지금 DB 가 어느 리비전인지
.venv/bin/alembic history      # 마이그레이션 이력(base → head)
.venv/bin/alembic upgrade head # 최신까지 적용
.venv/bin/alembic downgrade -1 # 한 단계 되돌리기
.venv/bin/alembic check        # 모델과 DB 가 일치하는지(=드리프트 없는지)
```

> `.venv/bin/alembic` 대신 `.venv/bin/python -m alembic` 도 동일합니다.
> (이 프로젝트 venv 는 uv 로 관리됩니다)

---

## 하지 말 것 / 흔한 실수

- ❌ **모델만 고치고 마이그레이션 안 만들기** — 프로덕션에 반영 안 됨(이번 사고 원인).
- ❌ **프로덕션에서 손으로 `ALTER TABLE`** — 마이그레이션 이력과 어긋납니다.
  긴급 복구가 정말 필요하면 임시로 쓰되, 반드시 대응하는 마이그레이션 파일도 만드세요.
- ❌ `create_all()` 부활 — 스키마의 단일 소스는 마이그레이션 파일입니다.
- ⚠️ **rev-id 순번 건너뛰기/중복** — 4자리 순번을 직전 +1로 이어가세요.
- ⚠️ 여러 브랜치에서 동시에 마이그레이션을 만들면 head가 갈라집니다.
  그때는 `alembic merge -m "merge heads" <rev1> <rev2>`로 합칩니다(1인 작업이면 신경 안 써도 됨).
