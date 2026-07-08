import os
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from db.models import Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gymrat_dev.db")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config():
    """cwd 에 관계없이 동작하도록 절대경로로 Alembic 설정을 구성."""
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def init_db():
    """스키마를 Alembic head 로 맞춘다(앱 시작 시 호출).

    - 신규 DB: 마이그레이션을 처음부터 적용해 전체 스키마 생성.
    - Alembic 도입 이전부터 존재하던 DB(alembic_version 없음): baseline(0001)로
      stamp 해 기존 스키마를 채택한 뒤, 이후 마이그레이션만 적용한다.
      => 배포 DB 는 재배포만으로 누락 컬럼(0002)이 자동 반영된다.
    """
    from alembic import command

    insp = inspect(engine)
    legacy = insp.has_table("users") and not insp.has_table("alembic_version")

    cfg = _alembic_config()
    if legacy:
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


def get_session():
    """컨텍스트 매니저로 세션 반환"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
