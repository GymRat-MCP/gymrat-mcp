"""운동 라이브러리 정적 데이터 적재 — 최초 1회 실행.

    python -m db.seed_exercises
"""
import json
from pathlib import Path
from db.session import SessionLocal, init_db
from db.models import ExerciseLibrary

DATA_PATH = Path(__file__).parent.parent / "data" / "exercises.json"


def seed():
    init_db()
    items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    session = SessionLocal()
    try:
        added = 0
        for it in items:
            exists = (session.query(ExerciseLibrary)
                      .filter(ExerciseLibrary.name == it["name"]).first())
            if exists:
                continue
            session.add(ExerciseLibrary(
                name=it["name"], target=it["target"],
                equipment=it.get("equipment"), form_cues=it.get("form_cues", []),
            ))
            added += 1
        session.commit()
        print(f"seeded {added} exercises (total in file: {len(items)})")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
