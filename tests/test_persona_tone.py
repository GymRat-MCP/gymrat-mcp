import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db
from tools.analysis import analyze_trend
from tools.coaching import generate_meal_plan, get_recommendation
from tools.logging_tools import log_meal, log_weight
from tools.profile import update_profile


class PersonaToneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_devil_persona_applies_to_diet_outputs(self):
        user_id = "devil-tone"
        update_profile(user_id, goal="증량", persona="악마")
        log_weight(user_id, 72.0, date="2026-06-20")
        log_weight(user_id, 71.2, date="2026-06-27")

        meal = log_meal(user_id, "밥과 김치", "점심")
        trend = analyze_trend(user_id, "meal", 30)
        plan = generate_meal_plan(user_id, schedule=["08:00"])
        recommendation = get_recommendation(user_id)

        self.assertIn("악마모드", meal["qualitative_note"])
        self.assertIn("악마모드", trend["summary"])
        self.assertIn("악마모드", plan["note"])
        self.assertIn("악마모드", plan["meals"][0]["guide"])
        self.assertIn("악마모드", recommendation["recommendation"])
        self.assertEqual(recommendation["persona"], "악마")

    def test_repeated_missing_protein_flags_needs_balance(self):
        user_id = "meal-balance"
        update_profile(user_id, persona="악마")
        for text in ["밥과 김치", "밥과 샐러드", "현미와 야채", "밥과 김치"]:
            log_meal(user_id, text)

        trend = analyze_trend(user_id, "meal", 30)

        self.assertEqual(trend["direction"], "down")
        self.assertEqual(trend["flag"], "needs_balance")


if __name__ == "__main__":
    unittest.main()
