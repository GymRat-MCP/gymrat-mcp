"""P1: estimate_1rm / 종목별 e1RM 히스토리 테스트."""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db, SessionLocal
from db.models import ExerciseSet
from tools.analysis import estimate_1rm, _exercise_series, get_exercise_history


class Estimate1RMTest(unittest.TestCase):
    def test_reps_one_returns_weight(self):
        self.assertEqual(estimate_1rm(100, 1), 100.0)

    def test_epley_formula(self):
        # 100kg x 5 -> 100*(1+5/30) = 116.666...
        self.assertAlmostEqual(estimate_1rm(100, 5), 100 * (1 + 5 / 30))

    def test_bodyweight_is_none(self):
        self.assertIsNone(estimate_1rm(None, 8))

    def test_invalid_reps(self):
        self.assertIsNone(estimate_1rm(80, 0))
        self.assertIsNone(estimate_1rm(80, None))


def _seed(session, uid, exercise, day, weight, reps, sets=1, is_warmup=False):
    for i in range(sets):
        session.add(ExerciseSet(user_id=uid, date=day, exercise=exercise,
                                set_no=i + 1, weight=weight, reps=reps,
                                is_warmup=is_warmup))


class ExerciseSeriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_daily_aggregation(self):
        uid = "series-1"
        session = SessionLocal()
        try:
            d = date(2026, 6, 1)
            _seed(session, uid, "벤치프레스", d, 60, 5, sets=3)
            _seed(session, uid, "벤치프레스", d, 70, 3, sets=1)   # 같은 날 더 무거운 세트
            session.commit()
        finally:
            session.close()

        pts = _exercise_series(uid, "벤치프레스", date(2026, 1, 1))
        self.assertEqual(len(pts), 1)
        p = pts[0]
        self.assertEqual(p["top_weight"], 70.0)                 # 최고 중량
        # best e1rm = max(60*(1+5/30), 70*(1+3/30)) = max(70, 77) = 77
        self.assertAlmostEqual(p["best_e1rm"], round(70 * (1 + 3 / 30), 1))
        self.assertEqual(p["volume"], 60 * 5 * 3 + 70 * 3)      # 900 + 210

    def test_warmup_excluded(self):
        uid = "series-warmup"
        session = SessionLocal()
        try:
            d = date(2026, 6, 2)
            _seed(session, uid, "스쿼트", d, 40, 10, sets=1, is_warmup=True)
            _seed(session, uid, "스쿼트", d, 100, 5, sets=1)
            session.commit()
        finally:
            session.close()

        pts = _exercise_series(uid, "스쿼트", date(2026, 1, 1))
        self.assertEqual(pts[0]["top_weight"], 100.0)   # 워밍업 40kg 제외

    def test_normalizes_exercise_name(self):
        uid = "series-norm"
        session = SessionLocal()
        try:
            # 저장은 정규화명, 조회는 별칭
            _seed(session, uid, "벤치프레스", date(2026, 6, 3), 80, 5, sets=1)
            session.commit()
        finally:
            session.close()
        pts = _exercise_series(uid, "벤치", date(2026, 1, 1))   # 별칭으로 조회
        self.assertEqual(len(pts), 1)


class ExerciseHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_rising_trend_up(self):
        uid = "hist-up"
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", date(2026, 6, 1), 60, 5, sets=1)
            _seed(session, uid, "벤치프레스", date(2026, 6, 10), 72.5, 5, sets=1)
            session.commit()
        finally:
            session.close()

        r = get_exercise_history(uid, "벤치", period_days=3650)
        self.assertEqual(r["exercise"], "벤치프레스")
        self.assertEqual(r["e1rm_trend"]["direction"], "up")
        self.assertGreater(r["e1rm_trend"]["pct_change"], 0)
        self.assertIsNone(r["flag"])
        self.assertEqual(len(r["points"]), 2)

    def test_insufficient_data(self):
        uid = "hist-thin"
        session = SessionLocal()
        try:
            _seed(session, uid, "데드리프트", date(2026, 6, 1), 100, 5, sets=1)
            session.commit()
        finally:
            session.close()

        r = get_exercise_history(uid, "데드리프트", period_days=3650)
        self.assertEqual(r["flag"], "insufficient_data")
        self.assertIsNone(r["e1rm_trend"]["pct_change"])

    def test_no_records(self):
        r = get_exercise_history("nobody", "벤치", period_days=90)
        self.assertEqual(r["points"], [])
        self.assertEqual(r["flag"], "insufficient_data")

    def test_period_window_filters_old(self):
        uid = "hist-window"
        session = SessionLocal()
        try:
            old = date.today() - timedelta(days=200)
            recent = date.today() - timedelta(days=5)
            _seed(session, uid, "오버헤드프레스", old, 40, 5, sets=1)
            _seed(session, uid, "오버헤드프레스", recent, 50, 5, sets=1)
            session.commit()
        finally:
            session.close()

        r = get_exercise_history(uid, "오버헤드프레스", period_days=90)
        self.assertEqual(len(r["points"]), 1)   # 200일 전은 창 밖


if __name__ == "__main__":
    unittest.main()
