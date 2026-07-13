import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# 기존 DATABASE_URL을 절대 참조하지 않는다. 로컬 기본값도 별도 파일이다.
MEAL_DATABASE_URL = os.getenv(
    "MEAL_DATABASE_URL", "sqlite:///./gymrat_meals_dev.db")

# 별도 DB 컨테이너가 재시작돼도 죽은 풀 연결을 다음 요청 전에 교체한다.
meal_engine = create_engine(MEAL_DATABASE_URL, echo=False, pool_pre_ping=True)
MealSessionLocal = sessionmaker(
    bind=meal_engine, autocommit=False, autoflush=False)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _meal_alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "meal_alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "meal_alembic"))
    return cfg


def init_meal_db() -> None:
    """식단 DB 전용 migration과 seed를 적용한다."""
    command.upgrade(_meal_alembic_config(), "head")
    from meal_db.repository import seed_builtin_catalog

    seed_builtin_catalog()
