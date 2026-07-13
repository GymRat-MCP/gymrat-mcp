"""create isolated meal catalog

Revision ID: meal_0001
Revises:
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "meal_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meal_options",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("meal_type", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("ingredients", sa.JSON(), nullable=False),
        sa.Column("balance_axes", sa.JSON(), nullable=False),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("selection_weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_meal_options_type_active", "meal_options",
        ["meal_type", "is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_meal_options_type_active", table_name="meal_options")
    op.drop_table("meal_options")
