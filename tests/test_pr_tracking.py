"""P2: PR(개인 신기록) 감지 & 축하 문구 테스트."""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db, SessionLocal
from db.models import ExerciseSet
from tools.analysis import _detect_prs, pr_headline
from tools.logging_tools import log_workout


def _seed(session, uid, exercise, day, weight, reps, sets=1, is_warmup=False):
    for i in range(sets):
        session.add(ExerciseSet(user_id=uid, date=day, exercise=exercise,
                                set_no=i + 1, weight=weight, reps=reps,
                                is_warmup=is_warmup))


def _types(prs, exercise=None):
    return {p["type"] for p in prs
            if exercise is None or p["exercise"] == exercise}


class DetectPRsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _detect(self, uid, parsed):
        session = SessionLocal()
        try:
            return _detect_prs(session, uid, parsed)
        finally:
            session.close()

    def test_first_record_is_not_pr(self):
        # 비교 대상이 없으면 PR 아님.
        prs = self._detect("pr-first", [{"exercise": "벤치프레스",
                                         "weight": 100, "sets": 1, "reps": 5}])
        self.assertEqual(prs, [])

    def test_weight_pr_detected(self):
        uid = "pr-weight"
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", date(2026, 6, 1), 80, 5, sets=3)
            session.commit()
        finally:
            session.close()
        prs = self._detect(uid, [{"exercise": "벤치프레스",
                                  "weight": 85, "sets": 1, "reps": 5}])
        types = _types(prs)
        self.assertIn("weight", types)
        weight_pr = next(p for p in prs if p["type"] == "weight")
        self.assertEqual(weight_pr["value"], 85.0)
        self.assertEqual(weight_pr["prev"], 80.0)
        # 더 무거운 중량 → e1RM 도 함께 경신.
        self.assertIn("e1rm", types)

    def test_rep_pr_at_same_weight(self):
        uid = "pr-reps"
        session = SessionLocal()
        try:
            _seed(session, uid, "스쿼트", date(2026, 6, 1), 100, 5, sets=1)
            session.commit()
        finally:
            session.close()
        # 같은 무게에서 반복수 경신(5 → 8).
        prs = self._detect(uid, [{"exercise": "스쿼트",
                                  "weight": 100, "sets": 1, "reps": 8}])
        rep_pr = next(p for p in prs if p["type"] == "reps")
        self.assertEqual(rep_pr["value"], 8)
        self.assertEqual(rep_pr["prev"], 5)
        self.assertEqual(rep_pr["weight"], 100.0)

    def test_no_pr_on_lower_or_equal(self):
        uid = "pr-none"
        session = SessionLocal()
        try:
            _seed(session, uid, "데드리프트", date(2026, 6, 1), 140, 5, sets=1)
            session.commit()
        finally:
            session.close()
        # 동일 기록 → PR 없음.
        self.assertEqual(
            self._detect(uid, [{"exercise": "데드리프트",
                                "weight": 140, "sets": 1, "reps": 5}]), [])
        # 더 가벼운 기록 → PR 없음.
        self.assertEqual(
            self._detect(uid, [{"exercise": "데드리프트",
                                "weight": 120, "sets": 1, "reps": 5}]), [])

    def test_warmup_excluded_from_prior(self):
        uid = "pr-warmup"
        session = SessionLocal()
        try:
            # 예전 본세트 60, 워밍업으로 100(통계 제외돼야 함).
            _seed(session, uid, "오버헤드프레스", date(2026, 6, 1), 60, 5, sets=1)
            _seed(session, uid, "오버헤드프레스", date(2026, 6, 1), 100, 5,
                  sets=1, is_warmup=True)
            session.commit()
        finally:
            session.close()
        prs = self._detect(uid, [{"exercise": "오버헤드프레스",
                                  "weight": 70, "sets": 1, "reps": 5}])
        # 워밍업 100 은 무시 → 70 은 이전 본세트 60 대비 중량 PR.
        self.assertIn("weight", _types(prs))

    def test_session_volume_pr(self):
        uid = "pr-volume"
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", date(2026, 6, 1), 60, 5, sets=2)  # vol 600
            session.commit()
        finally:
            session.close()
        # 같은 무게·반복이지만 세트 더 많음 → 세션 볼륨 경신(중량/e1RM 은 아님).
        prs = self._detect(uid, [{"exercise": "벤치프레스",
                                  "weight": 60, "sets": 4, "reps": 5}])  # vol 1200
        types = _types(prs)
        self.assertIn("volume", types)
        self.assertNotIn("weight", types)

    def test_normalizes_exercise_alias(self):
        uid = "pr-alias"
        session = SessionLocal()
        try:
            _seed(session, uid, "벤치프레스", date(2026, 6, 1), 80, 5, sets=1)
            session.commit()
        finally:
            session.close()
        # 저장은 정규화명, 감지 입력도 정규화명(log_workout 이 normalize 후 호출).
        prs = self._detect(uid, [{"exercise": "벤치프레스",
                                  "weight": 90, "sets": 1, "reps": 5}])
        self.assertIn("weight", _types(prs))


class PRHeadlineTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(pr_headline([]), "")

    def test_weight_priority_over_volume(self):
        prs = [
            {"exercise": "벤치프레스", "type": "volume", "value": 1200, "prev": 900, "unit": "kg"},
            {"exercise": "벤치프레스", "type": "weight", "value": 90, "prev": 85, "unit": "kg"},
        ]
        head = pr_headline(prs)
        self.assertIn("최고 중량 경신", head)
        self.assertIn("그 외 기록 1개", head)


class LogWorkoutPRIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_log_workout_surfaces_pr(self):
        uid = "pr-integ"
        # 첫 기록: PR 없음.
        r1 = log_workout(uid, "벤치 80 5x5", confirm_with_history=False)
        self.assertEqual(r1["prs"], [])
        # 더 무거운 기록: 중량 PR 감지 + 노트에 축하 문구.
        r2 = log_workout(uid, "벤치 85 1x5", confirm_with_history=False)
        self.assertTrue(any(p["type"] == "weight" for p in r2["prs"]))
        self.assertIn("경신", r2["base_note"])

    def test_no_pr_no_celebration(self):
        uid = "pr-integ-none"
        log_workout(uid, "스쿼트 100 5x5", confirm_with_history=False)
        r = log_workout(uid, "스쿼트 100 5x5", confirm_with_history=False)
        self.assertEqual(r["prs"], [])
        self.assertNotIn("경신", r["base_note"])


if __name__ == "__main__":
    unittest.main()
