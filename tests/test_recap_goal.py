"""P5: 주간 리캡 + 목표 마일스톤 투영 테스트."""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db, SessionLocal
from db.models import ExerciseSet
from tools.analysis import get_weekly_recap, get_goal_projection


def _seed(session, uid, exercise, day, weight, reps, sets=1, is_warmup=False):
    for i in range(sets):
        session.add(ExerciseSet(user_id=uid, date=day, exercise=exercise,
                                set_no=i + 1, weight=weight, reps=reps,
                                is_warmup=is_warmup))


class WeeklyRecapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_empty_week(self):
        r = get_weekly_recap("recap-empty")
        self.assertEqual(r["sessions"], 0)
        self.assertEqual(r["flag"], "no_sessions")
        self.assertTrue(r["nudges"])

    def test_counts_sessions_and_tonnage(self):
        uid = "recap-basic"
        today = date.today()
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", today - timedelta(days=1), 60, 5, sets=3)
            _seed(session, uid, "스쿼트", today - timedelta(days=3), 100, 5, sets=2)
            session.commit()
        finally:
            session.close()
        r = get_weekly_recap(uid)
        self.assertEqual(r["sessions"], 2)                      # 서로 다른 두 날
        self.assertEqual(r["tonnage"], 60 * 5 * 3 + 100 * 5 * 2)  # 900 + 1000
        self.assertIn("가슴", r["part_volume"])
        self.assertIn("하체", r["part_volume"])

    def test_tonnage_delta_vs_prev_week(self):
        uid = "recap-delta"
        today = date.today()
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", today - timedelta(days=2), 60, 5, sets=2)   # 이번주 600
            _seed(session, uid, "벤치프레스", today - timedelta(days=9), 60, 5, sets=1)   # 지난주 300
            session.commit()
        finally:
            session.close()
        r = get_weekly_recap(uid)
        self.assertEqual(r["tonnage"], 600)
        self.assertEqual(r["tonnage_delta"], 300)              # 600 - 300

    def test_new_pr_flagged(self):
        uid = "recap-pr"
        today = date.today()
        session = SessionLocal()
        try:
            _seed(session, uid, "데드리프트", today - timedelta(days=20), 100, 5, sets=1)  # 과거 최고
            _seed(session, uid, "데드리프트", today - timedelta(days=2), 120, 5, sets=1)   # 이번주 경신
            session.commit()
        finally:
            session.close()
        r = get_weekly_recap(uid)
        self.assertTrue(any(p["type"] == "weight" for p in r["new_prs"]))


class GoalProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_no_records(self):
        r = get_goal_projection("goal-none", "벤치프레스", 100)
        self.assertEqual(r["flag"], "insufficient_data")
        self.assertIsNone(r["projected_date"])

    def test_already_achieved(self):
        uid = "goal-done"
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", date.today() - timedelta(days=2),
                  110, 1, sets=1)
            session.commit()
        finally:
            session.close()
        r = get_goal_projection(uid, "벤치프레스", 100)
        self.assertEqual(r["flag"], "achieved")
        self.assertTrue(r["on_track"])

    def test_rising_projects_future_date(self):
        uid = "goal-rising"
        today = date.today()
        session = SessionLocal()
        try:
            # 40일에 걸쳐 e1RM 상승(80 → 90, reps=1이라 e1RM=weight).
            _seed(session, uid, "스쿼트", today - timedelta(days=40), 80, 1, sets=1)
            _seed(session, uid, "스쿼트", today - timedelta(days=1), 90, 1, sets=1)
            session.commit()
        finally:
            session.close()
        r = get_goal_projection(uid, "스쿼트", 100)
        self.assertGreater(r["rate_per_week"], 0)
        self.assertIsNotNone(r["projected_date"])
        self.assertGreater(r["projected_date"], today.isoformat())

    def test_stalled_no_projection(self):
        uid = "goal-stall"
        today = date.today()
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", today - timedelta(days=30), 80, 1, sets=1)
            _seed(session, uid, "벤치프레스", today - timedelta(days=1), 80, 1, sets=1)
            session.commit()
        finally:
            session.close()
        r = get_goal_projection(uid, "벤치프레스", 100)
        self.assertEqual(r["flag"], "stalled")
        self.assertFalse(r["on_track"])

    def test_by_date_on_track(self):
        uid = "goal-deadline"
        today = date.today()
        session = SessionLocal()
        try:
            _seed(session, uid, "데드리프트", today - timedelta(days=30), 100, 1, sets=1)
            _seed(session, uid, "데드리프트", today - timedelta(days=1), 120, 1, sets=1)
            session.commit()
        finally:
            session.close()
        # 주당 ~4.6kg 상승 → 목표 130까지 약 2~3주. 먼 마감이면 on_track True.
        r = get_goal_projection(uid, "데드리프트", 130,
                                by_date=(today + timedelta(days=120)).isoformat())
        self.assertTrue(r["on_track"])


if __name__ == "__main__":
    unittest.main()
