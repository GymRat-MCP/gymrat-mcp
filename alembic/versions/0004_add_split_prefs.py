"""add users.training_days / split_style / custom_split

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12

분할(split) 개인화(프리셋 스타일 + 커스텀 분할)에서 users 모델에 추가된 세 컬럼을
실제 DB에 반영한다. 전부 nullable → 기존 유저는 무영향(미설정 = 기존 PPL/상하체 자동).
0002 패턴을 따라 존재 여부 확인 후 추가해 수동 ALTER 로 먼저 추가된 DB 에서도 안전.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = {
    "training_days": sa.Integer(),
    "split_style": sa.String(),
    "custom_split": sa.JSON(),
}


def _existing_user_columns() -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns("users")}


def upgrade() -> None:
    existing = _existing_user_columns()
    for name, type_ in _NEW_COLUMNS.items():
        if name not in existing:
            op.add_column("users", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    existing = _existing_user_columns()
    with op.batch_alter_table("users") as batch:
        for name in _NEW_COLUMNS:
            if name in existing:
                batch.drop_column(name)
