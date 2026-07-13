"""add sports nutrition metadata and evidence sources

Revision ID: meal_0002
Revises: meal_0001
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "meal_0002"
down_revision: Union[str, None] = "meal_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_default = sa.text("'[]'")
    for name in (
        "allergens", "dietary_patterns", "protein_families",
        "micronutrient_focus", "training_contexts", "recovery_roles",
        "evidence_source_ids",
    ):
        op.add_column(
            "meal_options",
            sa.Column(name, sa.JSON(), nullable=False, server_default=json_default),
        )
    op.add_column("meal_options", sa.Column(
        "whole_grain", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("meal_options", sa.Column(
        "digestibility", sa.String(), nullable=False, server_default="moderate"))
    op.add_column("meal_options", sa.Column(
        "nutrition_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("meal_options", sa.Column(
        "review_status", sa.String(), nullable=False,
        server_default="principle_based_unverified_portion"))
    op.add_column("meal_options", sa.Column(
        "catalog_revision", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "nutrition_evidence_sources",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("nutrition_evidence_sources")
    for name in (
        "catalog_revision", "review_status", "nutrition_verified",
        "digestibility", "whole_grain", "evidence_source_ids",
        "recovery_roles", "training_contexts", "micronutrient_focus",
        "protein_families", "dietary_patterns", "allergens",
    ):
        with op.batch_alter_table("meal_options") as batch:
            batch.drop_column(name)
