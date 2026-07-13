from threading import Lock

from sqlalchemy import select

from meal_db.models import MealOptionRecord, NutritionEvidenceSource
from meal_db.session import MealSessionLocal


class MealCatalogUnavailable(RuntimeError):
    pass


_ready = False
_ready_lock = Lock()


def _ensure_catalog_ready() -> None:
    """직접 도구 호출·테스트에서도 별도 DB를 최초 한 번 준비한다."""
    global _ready
    if _ready:
        return
    with _ready_lock:
        if _ready:
            return
        from meal_db.session import init_meal_db

        init_meal_db()
        _ready = True


def seed_builtin_catalog() -> dict:
    """내장 카탈로그에서 없는 ID만 한 트랜잭션으로 추가한다."""
    from meal_db.catalog import MEAL_CATALOG, validate_catalog
    from meal_db.evidence import EVIDENCE_SOURCES

    validate_catalog()
    session = MealSessionLocal()
    inserted = 0
    enriched = 0
    evidence_inserted = 0
    try:
        existing = {
            row.id: row
            for row in session.scalars(select(MealOptionRecord)).all()
        }
        for option in MEAL_CATALOG:
            record = existing.get(option["option_id"])
            metadata = {
                "allergens": option["allergens"],
                "dietary_patterns": option["dietary_patterns"],
                "protein_families": option["protein_families"],
                "whole_grain": option["whole_grain"],
                "micronutrient_focus": option["micronutrient_focus"],
                "training_contexts": option["training_contexts"],
                "digestibility": option["digestibility"],
                "recovery_roles": option["recovery_roles"],
                "evidence_source_ids": option["evidence_source_ids"],
                "nutrition_verified": option["nutrition_verified"],
                "review_status": option["review_status"],
                "catalog_revision": 2,
            }
            if record:
                if (record.catalog_revision or 0) < 2:
                    for key, value in metadata.items():
                        setattr(record, key, value)
                    enriched += 1
                continue
            session.add(MealOptionRecord(
                id=option["option_id"],
                meal_type=option["meal_type"],
                name=option["name"],
                components=option["components"],
                ingredients=option["ingredients"],
                balance_axes=option["balance_axes"],
                goals=option["goals"],
                is_active=option.get("active", True),
                selection_weight=option.get("selection_weight", 100),
                **metadata,
            ))
            inserted += 1
        existing_evidence_ids = set(session.scalars(
            select(NutritionEvidenceSource.id)).all())
        for source in EVIDENCE_SOURCES:
            if source["id"] in existing_evidence_ids:
                continue
            session.add(NutritionEvidenceSource(**source))
            evidence_inserted += 1
        session.commit()
        return {
            "catalog_size": len(MEAL_CATALOG),
            "inserted": inserted,
            "enriched": enriched,
            "evidence_inserted": evidence_inserted,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_active_meal_options() -> list[dict]:
    """활성 식단 후보를 식단 DB에서만 읽는다."""
    try:
        _ensure_catalog_ready()
    except Exception as exc:
        raise MealCatalogUnavailable(
            "독립 식단 DB를 준비하지 못했습니다") from exc
    session = MealSessionLocal()
    try:
        rows = session.scalars(
            select(MealOptionRecord)
            .where(MealOptionRecord.is_active.is_(True))
            .order_by(MealOptionRecord.id)
        ).all()
        if not rows:
            raise MealCatalogUnavailable("활성 식단 후보가 없습니다")
        return [
            {
                "option_id": row.id,
                "meal_type": row.meal_type,
                "name": row.name,
                "components": dict(row.components),
                "ingredients": list(row.ingredients),
                "balance_axes": list(row.balance_axes),
                "goals": list(row.goals),
                "selection_weight": row.selection_weight,
                "allergens": list(row.allergens),
                "dietary_patterns": list(row.dietary_patterns),
                "protein_families": list(row.protein_families),
                "whole_grain": row.whole_grain,
                "micronutrient_focus": list(row.micronutrient_focus),
                "training_contexts": list(row.training_contexts),
                "digestibility": row.digestibility,
                "recovery_roles": list(row.recovery_roles),
                "evidence_source_ids": list(row.evidence_source_ids),
                "nutrition_verified": row.nutrition_verified,
                "review_status": row.review_status,
            }
            for row in rows
        ]
    except MealCatalogUnavailable:
        raise
    except Exception as exc:
        raise MealCatalogUnavailable(
            "독립 식단 DB에서 후보를 불러오지 못했습니다") from exc
    finally:
        session.close()
