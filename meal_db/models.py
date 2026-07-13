from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import declarative_base


MealBase = declarative_base()


class MealOptionRecord(MealBase):
    """추천 가능한 정성적 식단 후보. 사용자 데이터와 FK를 맺지 않는다."""

    __tablename__ = "meal_options"

    id = Column(String, primary_key=True)
    meal_type = Column(String, nullable=False)
    name = Column(Text, nullable=False, unique=True)
    components = Column(JSON, nullable=False)
    ingredients = Column(JSON, nullable=False)
    balance_axes = Column(JSON, nullable=False)
    goals = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    selection_weight = Column(Integer, nullable=False, default=100)
    allergens = Column(JSON, nullable=False, default=list)
    dietary_patterns = Column(JSON, nullable=False, default=list)
    protein_families = Column(JSON, nullable=False, default=list)
    whole_grain = Column(Boolean, nullable=False, default=False)
    micronutrient_focus = Column(JSON, nullable=False, default=list)
    training_contexts = Column(JSON, nullable=False, default=list)
    digestibility = Column(String, nullable=False, default="moderate")
    recovery_roles = Column(JSON, nullable=False, default=list)
    evidence_source_ids = Column(JSON, nullable=False, default=list)
    nutrition_verified = Column(Boolean, nullable=False, default=False)
    review_status = Column(
        String, nullable=False, default="principle_based_unverified_portion")
    catalog_revision = Column(Integer, nullable=False, default=2)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_meal_options_type_active", "meal_type", "is_active"),
    )


class NutritionEvidenceSource(MealBase):
    __tablename__ = "nutrition_evidence_sources"

    id = Column(String, primary_key=True)
    organization = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    evidence_type = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    publication_year = Column(Integer, nullable=True)
