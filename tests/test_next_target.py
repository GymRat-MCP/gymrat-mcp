"""P3: 오늘의 구체적 목표 무게/반복(_next_target) 표면화 테스트."""
import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from tools.routine import _next_target, _fmt_kg


class FmtKgTest(unittest.TestCase):
    def test_bodyweight(self):
        self.assertEqual(_fmt_kg(None), "맨몸")

    def test_integerish(self):
        self.assertEqual(_fmt_kg(70.0), "70kg")
        self.assertEqual(_fmt_kg(72.5), "72.5kg")


class NextTargetTest(unittest.TestCase):
    def test_first_time_no_history(self):
        t = _next_target("벤치프레스", {}, "가슴", sets=3, base_reps=8,
                         load=None, ex_reps=8, deload=False, stalled=set())
        self.assertIsNone(t["weight"])
        self.assertEqual(t["scheme"], "3×8")
        self.assertIn("첫 기록", t["note"])

    def test_progression_weight_up(self):
        # 지난번 72.5kg 5회 달성 → 오늘 75kg 도전(직접 이름 매칭 폴백 경로).
        last_idx = {"벤치프레스": {"weight": 72.5, "sets": 5, "reps": 5}}
        t = _next_target("벤치프레스", last_idx, "가슴", sets=5, base_reps=5,
                         load=75.0, ex_reps=5, deload=False, stalled=set())
        self.assertEqual(t["weight"], 75.0)
        self.assertIn("도전", t["note"])
        self.assertIn("75kg", t["note"])
        self.assertIn("72.5kg", t["note"])   # 미달 시 백업 안내

    def test_rep_bump_when_missed(self):
        # 무게 유지 + 반복수 +1(더블 프로그레션 미달 케이스).
        last_idx = {"스쿼트": {"weight": 100.0, "sets": 5, "reps": 5}}
        t = _next_target("스쿼트", last_idx, "하체", sets=5, base_reps=8,
                         load=100.0, ex_reps=6, deload=False, stalled=set())
        self.assertEqual(t["weight"], 100.0)
        self.assertIn("반복수 늘리기", t["note"])

    def test_deload_note(self):
        last_idx = {"데드리프트": {"weight": 140.0, "sets": 5, "reps": 5}}
        t = _next_target("데드리프트", last_idx, "하체", sets=3, base_reps=5,
                         load=126.0, ex_reps=5, deload=True, stalled=set())
        self.assertIn("회복 주간", t["note"])

    def test_stalled_backoff_note(self):
        last_idx = {"벤치프레스": {"weight": 80.0, "sets": 5, "reps": 5}}
        t = _next_target("벤치프레스", last_idx, "가슴", sets=3, base_reps=5,
                         load=72.0, ex_reps=5, deload=False,
                         stalled={"벤치프레스"})
        self.assertIn("정체", t["note"])


if __name__ == "__main__":
    unittest.main()
