"""rename meal log photo_analysis to meal_text

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13

사용자 식단 원문을 저장하는 실제 계약에 맞춰 컬럼명을 변경한다.
기존 레코드는 컬럼 rename으로 그대로 보존한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("meal_logs") as batch:
        batch.alter_column(
            "photo_analysis",
            new_column_name="meal_text",
            existing_type=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("meal_logs") as batch:
        batch.alter_column(
            "meal_text",
            new_column_name="photo_analysis",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
