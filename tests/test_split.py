"""커스텀 분할 저장/조회/해제 라운드트립 — DB 필요(임시 sqlite)."""
import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db                       # noqa: E402
from tools.routine import (                          # noqa: E402
    set_workout_split, get_workout_split, clear_workout_split)
from tools.profile import update_profile, get_profile  # noqa: E402


class TestCustomSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_set_get_clear_roundtrip(self):
        uid = "split-roundtrip"
        res = set_workout_split(uid, [
            {"label": "가슴·삼두", "parts": ["가슴삼두"]},   # 붙여쓰기 분해
            {"parts": ["등", "이두"]},                       # label 자동 생성
            {"parts": ["다리"]},                             # 별칭 → 하체
        ])
        self.assertTrue(res["updated"])
        self.assertEqual(res["day_count"], 3)

        got = get_workout_split(uid)
        self.assertEqual(got["source"], "custom")
        self.assertEqual(got["days"][0]["parts"], ["가슴", "삼두"])
        self.assertEqual(got["days"][1]["label"], "등·이두")   # 자동 라벨
        self.assertEqual(got["days"][2]["parts"], ["하체"])

        cleared = clear_workout_split(uid)
        self.assertTrue(cleared["updated"])
        self.assertEqual(get_workout_split(uid)["source"], "preset")

    def test_set_rejects_all_invalid_parts(self):
        res = set_workout_split("split-bad", [{"parts": ["asdf", "zzz"]}])
        self.assertFalse(res["updated"])
        self.assertIn("error", res)

    def test_preset_reflects_profile_style_and_days(self):
        uid = "split-preset"
        update_profile(uid, experience="중급", training_days=5, split_style="부위별")
        prof = get_profile(uid)
        self.assertEqual(prof["training_days"], 5)
        self.assertEqual(prof["split_style"], "부위별")
        got = get_workout_split(uid)
        self.assertEqual(got["source"], "preset")
        self.assertEqual(got["split_style"], "부위별")
        self.assertEqual(got["training_days"], 5)
        self.assertEqual(got["day_count"], 5)

    def test_update_profile_rejects_bad_split_style(self):
        res = update_profile("split-badstyle", split_style="이상한값")
        self.assertFalse(res["updated"])
        self.assertIn("error", res)

    def test_training_days_clamped(self):
        update_profile("split-clamp", training_days=99)
        self.assertEqual(get_profile("split-clamp")["training_days"], 6)


if __name__ == "__main__":
    unittest.main()
