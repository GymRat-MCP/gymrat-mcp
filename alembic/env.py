"""Alembic 실행 환경.

DB URL과 모델 메타데이터를 앱(db.session / db.models)에서 그대로 가져와
스키마 정의의 단일 소스를 유지한다. autogenerate는 이 metadata를 기준으로
현재 DB와의 차이를 감지한다.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# cwd 와 무관하게 앱 패키지를 import 할 수 있도록 레포 루트를 sys.path 에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import DATABASE_URL, engine
from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """URL만으로 SQL 스크립트를 생성(오프라인 모드)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER 제약 대응(batch mode)
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """앱과 동일한 엔진으로 실제 DB에 마이그레이션 적용."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER 제약 대응(batch mode)
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
