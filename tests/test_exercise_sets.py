"""P0: ExerciseSet 듀얼라이트 + 백필 테스트."""
import os
import tempfile
import unittest
from datetime import date

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db, SessionLocal
from db.models import ExerciseSet, WorkoutLog
from tools.logging_tools import log_workout, _expand_to_sets


class ExpandToSetsTest(unittest.TestCase):
    def test_expands_sets_to_rows(self):
        parsed = [{"exercise": "벤치프레스", "weight": 70.0, "sets": 3, "reps": 5}]
        rows = _expand_to_sets(parsed, "u", "2026-07-01", log_id=1)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.set_no for r in rows], [1, 2, 3])
        self.assertTrue(all(r.weight == 70.0 and r.reps == 5 for r in rows))
        self.assertTrue(all(r.exercise == "벤치프레스" for r in rows))

    def test_skips_empty_exercise(self):
        rows = _expand_to_sets([{"exercise": "", "sets": 3}], "u", "2026-07-01", 1)
        self.assertEqual(rows, [])

    def test_missing_sets_defaults_to_one(self):
        rows = _expand_to_sets([{"exercise": "데드리프트", "weight": 100, "reps": 5}],
                               "u", "2026-07-01", 1)
        self.assertEqual(len(rows), 1)

    def test_bodyweight_keeps_null_weight(self):
        rows = _expand_to_sets([{"exercise": "풀업", "weight": None, "sets": 2, "reps": 10}],
                               "u", "2026-07-01", 1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.weight is None for r in rows))


class DualWriteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_log_workout_writes_exercise_sets(self):
        uid = "dualwrite-1"
        log_workout(uid, "벤치 60 5x5",
                    exercises=[{"exercise": "벤치", "weight": 60, "sets": 5, "reps": 5}])
        session = SessionLocal()
        try:
            sets = session.query(ExerciseSet).filter_by(user_id=uid).all()
            self.assertEqual(len(sets), 5)                      # 5세트 → 5행
            self.assertTrue(all(s.exercise == "벤치프레스" for s in sets))  # 정규화됨
            self.assertTrue(all(s.weight == 60 for s in sets))
            # log_id 가 WorkoutLog 와 연결
            log = session.query(WorkoutLog).filter_by(user_id=uid).one()
            self.assertTrue(all(s.log_id == log.id for s in sets))
        finally:
            session.close()

    def test_multiple_exercises_expand(self):
        uid = "dualwrite-2"
        log_workout(uid, "스쿼트 100 3x5, 데드 120 1x5",
                    exercises=[{"exercise": "스쿼트", "weight": 100, "sets": 3, "reps": 5},
                               {"exercise": "데드", "weight": 120, "sets": 1, "reps": 5}])
        session = SessionLocal()
        try:
            sets = session.query(ExerciseSet).filter_by(user_id=uid).all()
            self.assertEqual(len(sets), 4)   # 3 + 1
        finally:
            session.close()


class BackfillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_backfill_creates_and_is_idempotent(self):
        from db.backfill_exercise_sets import backfill
        uid = "backfill-1"
        session = SessionLocal()
        try:
            # 듀얼라이트 우회: WorkoutLog 만 직접 심어 '과거 데이터' 상황 재현
            log = WorkoutLog(user_id=uid, date=date(2026, 6, 1), raw_text="벤치 50 4x8",
                             parsed=[{"exercise": "벤치프레스", "weight": 50, "sets": 4, "reps": 8}])
            session.add(log)
            session.commit()
            log_id = log.id
        finally:
            session.close()

        r1 = backfill()
        session = SessionLocal()
        try:
            sets = session.query(ExerciseSet).filter_by(log_id=log_id).all()
            self.assertEqual(len(sets), 4)
        finally:
            session.close()

        # 두 번째 실행은 새로 만들지 않음(idempotent)
        r2 = backfill()
        session = SessionLocal()
        try:
            sets = session.query(ExerciseSet).filter_by(log_id=log_id).all()
            self.assertEqual(len(sets), 4)   # 여전히 4(중복 생성 없음)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
