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
        self.assertIn("변명은 여기까지", meal["qualitative_note"])
        self.assertEqual(meal["base_message"], meal["base_qualitative_note"])
        self.assertEqual(meal["persona_context"]["name"], "악마")
        self.assertIn("base_message", meal["rewrite_instruction"])
        self.assertIn("악마모드", trend["summary"])
        self.assertEqual(trend["base_message"], trend["base_summary"])
        self.assertEqual(trend["persona_context"]["tone"], "짧고 직설적이며 핑계를 줄이는 말투")
        self.assertIn("악마모드", plan["note"])
        self.assertIn("악마모드", plan["meals"][0]["guide"])
        self.assertIn("base_guide", plan["meals"][0])
        self.assertEqual(plan["persona_context"]["name"], "악마")
        self.assertIn("악마모드", recommendation["recommendation"])
        self.assertEqual(recommendation["base_message"], recommendation["base_recommendation"])
        self.assertEqual(recommendation["persona_context"]["name"], "악마")
        for basis in recommendation["based_on"]:
            self.assertNotIn("base_message", basis)
            self.assertNotIn("persona_context", basis)
            self.assertNotIn("rewrite_instruction", basis)
        self.assertEqual(recommendation["persona"], "악마")

    def test_repeated_missing_protein_flags_needs_balance(self):
        user_id = "meal-balance"
        update_profile(user_id, persona="악마")
        for text in ["밥과 김치", "밥과 샐러드", "현미와 야채", "밥과 김치"]:
            log_meal(user_id, text)

        trend = analyze_trend(user_id, "meal", 30)

        self.assertEqual(trend["direction"], "down")
        self.assertEqual(trend["flag"], "needs_balance")

    def test_default_coach_persona_has_coach_tone(self):
        user_id = "coach-tone"
        update_profile(user_id, goal="유지", persona="코치")

        meal = log_meal(user_id, "닭가슴살 밥 샐러드", "점심")

        self.assertIn("코치모드", meal["qualitative_note"])
        self.assertIn("운동 많이 될 거야", meal["qualitative_note"])
        self.assertIn("스트레스 조금 받을 거야", meal["qualitative_note"])
        self.assertEqual(meal["persona_context"]["name"], "코치")
        self.assertIn("운동 밈 느낌", meal["persona_context"]["tone"])


if __name__ == "__main__":
    unittest.main()
