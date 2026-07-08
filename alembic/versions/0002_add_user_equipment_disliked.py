"""add users.available_equipment / disliked_exercises

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08

보유 장비 필터 + 선호 종목 제외(커밋 2d4c717)에서 users 모델에 추가된 두 컬럼을
실제 DB에 반영한다. baseline 도입 이전에 이미 컬럼을 가진 DB(로컬 dev 등)나
수동 ALTER 로 먼저 추가된 배포 DB 에서도 안전하도록 존재 여부를 확인 후 추가한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = {
    "available_equipment": sa.Text(),
    "disliked_exercises": sa.Text(),
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
    # SQLite 는 DROP COLUMN 에 batch(재작성) 필요 → 두 DB 공통으로 batch 사용
    with op.batch_alter_table("users") as batch:
        for name in _NEW_COLUMNS:
            if name in existing:
                batch.drop_column(name)
