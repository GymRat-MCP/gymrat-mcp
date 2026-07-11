"""P4: 상대날짜 백필 + 운동 기록 수정/삭제 테스트."""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db, SessionLocal
from db.models import WorkoutLog, ExerciseSet
from tools.workout_parser import parse_relative_date
from tools.logging_tools import log_workout, edit_workout, delete_workout


class RelativeDateTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 7, 10)   # 금요일

    def test_basic(self):
        self.assertEqual(parse_relative_date("오늘", self.today), self.today)
        self.assertEqual(parse_relative_date("어제", self.today),
                         self.today - timedelta(days=1))
        self.assertEqual(parse_relative_date("그제", self.today),
                         self.today - timedelta(days=2))

    def test_n_units_ago(self):
        self.assertEqual(parse_relative_date("3주 전 벤치 70", self.today),
                         self.today - timedelta(weeks=3))
        self.assertEqual(parse_relative_date("5일전", self.today),
                         self.today - timedelta(days=5))
        self.assertEqual(parse_relative_date("2개월 전", self.today),
                         self.today - timedelta(days=60))

    def test_last_week(self):
        self.assertEqual(parse_relative_date("지난주", self.today),
                         self.today - timedelta(weeks=1))
        self.assertEqual(parse_relative_date("지지난주", self.today),
                         self.today - timedelta(weeks=2))

    def test_weekday_most_recent_past(self):
        # 2026-07-10은 금요일. "월요일" → 가장 최근 지난 월요일(4일 전).
        self.assertEqual(parse_relative_date("월요일에 스쿼트", self.today),
                         self.today - timedelta(days=4))
        # 같은 요일(금요일) → 지난주 그 요일(7일 전).
        self.assertEqual(parse_relative_date("금요일", self.today),
                         self.today - timedelta(days=7))

    def test_unrecognized_returns_none(self):
        self.assertIsNone(parse_relative_date("벤치 70 5x5", self.today))
        self.assertIsNone(parse_relative_date("", self.today))


class BackfillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_call_level_relative_date(self):
        uid = "bf-call"
        r = log_workout(uid, "벤치 70 5x5", date="3주 전",
                        confirm_with_history=False)
        self.assertTrue(r["saved"])
        session = SessionLocal()
        try:
            rows = (session.query(ExerciseSet)
                    .filter(ExerciseSet.user_id == uid).all())
            self.assertTrue(rows)
            expected = date.today() - timedelta(weeks=3)
            self.assertTrue(all(s.date == expected for s in rows))
        finally:
            session.close()

    def test_per_item_date_override(self):
        uid = "bf-item"
        r = log_workout(
            uid, "온보딩",
            exercises=[
                {"exercise": "벤치프레스", "weight": 60, "sets": 1, "reps": 5,
                 "date": "어제"},
                {"exercise": "스쿼트", "weight": 100, "sets": 1, "reps": 5,
                 "date": "2주 전"},
            ],
            confirm_with_history=False)
        self.assertTrue(r["saved"])
        session = SessionLocal()
        try:
            bench = (session.query(ExerciseSet)
                     .filter(ExerciseSet.user_id == uid,
                             ExerciseSet.exercise == "벤치프레스").first())
            squat = (session.query(ExerciseSet)
                     .filter(ExerciseSet.user_id == uid,
                             ExerciseSet.exercise == "스쿼트").first())
            self.assertEqual(bench.date, date.today() - timedelta(days=1))
            self.assertEqual(squat.date, date.today() - timedelta(weeks=2))
        finally:
            session.close()


class EditDeleteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _last_log_id(self, uid):
        session = SessionLocal()
        try:
            log = (session.query(WorkoutLog)
                   .filter(WorkoutLog.user_id == uid)
                   .order_by(WorkoutLog.id.desc()).first())
            return log.id
        finally:
            session.close()

    def test_edit_replaces_sets(self):
        uid = "ed-edit"
        log_workout(uid, "벤치 70 5x5", confirm_with_history=False)
        log_id = self._last_log_id(uid)
        # 무게 오타 교정: 70 → 75.
        r = edit_workout(uid, log_id, exercises=[
            {"exercise": "벤치프레스", "weight": 75, "sets": 5, "reps": 5}])
        self.assertTrue(r["updated"])
        session = SessionLocal()
        try:
            rows = (session.query(ExerciseSet)
                    .filter(ExerciseSet.log_id == log_id).all())
            self.assertEqual(len(rows), 5)                 # 5세트 재전개
            self.assertTrue(all(s.weight == 75 for s in rows))
        finally:
            session.close()

    def test_edit_date_moves_sets(self):
        uid = "ed-date"
        log_workout(uid, "스쿼트 100 5x5", confirm_with_history=False)
        log_id = self._last_log_id(uid)
        r = edit_workout(uid, log_id, date="1주 전")
        self.assertTrue(r["updated"])
        expected = date.today() - timedelta(weeks=1)
        session = SessionLocal()
        try:
            log = session.get(WorkoutLog, log_id)
            rows = (session.query(ExerciseSet)
                    .filter(ExerciseSet.log_id == log_id).all())
            self.assertEqual(log.date, expected)
            self.assertTrue(all(s.date == expected for s in rows))
        finally:
            session.close()

    def test_edit_rejects_other_user(self):
        uid = "ed-owner"
        log_workout(uid, "데드 140 5x5", confirm_with_history=False)
        log_id = self._last_log_id(uid)
        r = edit_workout("someone-else", log_id, date="어제")
        self.assertFalse(r["updated"])

    def test_delete_removes_log_and_sets(self):
        uid = "ed-del"
        log_workout(uid, "벤치 60 3x10", confirm_with_history=False)
        log_id = self._last_log_id(uid)
        r = delete_workout(uid, log_id)
        self.assertTrue(r["deleted"])
        self.assertEqual(r["removed_sets"], 3)
        session = SessionLocal()
        try:
            self.assertIsNone(session.get(WorkoutLog, log_id))
            self.assertEqual(
                session.query(ExerciseSet)
                .filter(ExerciseSet.log_id == log_id).count(), 0)
        finally:
            session.close()

    def test_delete_rejects_other_user(self):
        uid = "ed-del-owner"
        log_workout(uid, "스쿼트 80 5x5", confirm_with_history=False)
        log_id = self._last_log_id(uid)
        r = delete_workout("intruder", log_id)
        self.assertFalse(r["deleted"])


if __name__ == "__main__":
    unittest.main()
