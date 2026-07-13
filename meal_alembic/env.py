from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from meal_db.models import MealBase
from meal_db.session import MEAL_DATABASE_URL


config = context.config
config.set_main_option("sqlalchemy.url", MEAL_DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MealBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=MEAL_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
