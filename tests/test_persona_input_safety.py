import unittest
from unittest.mock import patch

from tools.coaching import (
    generate_meal_plan,
    get_recommendation,
    suggest_meal_adjustment,
)


EMPTY_TREND = {
    "direction": "flat",
    "flag": "insufficient_data",
    "count": 0,
}


class PersonaInputSafetyTest(unittest.TestCase):
    def test_meal_plan_rejects_numeric_and_fasting_constraints_but_keeps_food_preferences(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "감량", "persona": "현실파이터"},
        ):
            result = generate_meal_plan(
                "preference-safety",
                preferences=(
                    "생선은 싫어하고 닭고기와 두부를 좋아해. "
                    "하루 700kcal 이하, 음식별 정확히 100g, 저녁은 굶기"
                ),
                schedule=["08:00"],
            )

        self.assertEqual(
            result["accepted_preferences"],
            "생선은 싫어하고 닭고기와 두부를 좋아해",
        )
        self.assertEqual(
            set(result["rejected_preference_categories"]),
            {
                "exact_calorie_limit",
                "exact_gram_limit",
                "fasting_or_meal_skipping",
            },
        )
        self.assertTrue(result["preference_guardrail_applied"])
        serialized = str(result)
        self.assertIn("닭고기와 두부", serialized)
        self.assertNotIn("700", serialized)
        self.assertNotIn("100g", serialized)
        self.assertNotIn("굶기", serialized)
        self.assertIn("반영하지 않았어요", result["assistant_message"])

    def test_safe_preferences_are_preserved_without_guardrail_warning(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "천사"},
        ):
            result = generate_meal_plan(
                "safe-preference",
                preferences="견과류 알레르기가 있고 두부를 좋아해",
                schedule=["12:00"],
            )

        self.assertEqual(
            result["accepted_preferences"],
            "견과류 알레르기가 있고 두부를 좋아해",
        )
        self.assertFalse(result["preference_guardrail_applied"])
        self.assertEqual(result["rejected_preference_categories"], [])
        self.assertEqual(result["meal_catalog_source"], "isolated_meal_database")
        self.assertEqual(result["meal_catalog_size"], 72)
        self.assertEqual(result["preference_profile"]["allergens"], ["견과류"])
        self.assertEqual(result["preference_profile"]["liked"], ["두부"])
        self.assertNotIn("견과류", str(result["meals"]))
        self.assertNotIn("알레르기", result["meals"][0]["base_guide"])
        self.assertNotIn("선호:", result["meals"][0]["base_guide"])
        self.assertIn("실제 메뉴 선택에 반영", result["base_note"])

    def test_preferences_change_selection_without_repeating_robotic_suffix(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "코치"},
        ):
            result = generate_meal_plan(
                "preference-selection",
                preferences="생선은 싫어하고 닭고기와 두부를 좋아해",
                schedule=["08:00", "12:00", "18:00"],
            )

        self.assertEqual(result["preference_profile"]["disliked"], ["생선"])
        self.assertEqual(result["preference_profile"]["liked"], ["닭고기", "두부"])
        selected = " ".join(
            " ".join([meal["option_name"], *meal["components"].values()])
            for meal in result["meals"]
        )
        self.assertFalse(any(food in selected for food in ("연어", "고등어", "흰살생선")))
        self.assertTrue(any(meal["matched_preferences"] for meal in result["meals"]))
        for meal in result["meals"]:
            self.assertNotIn("좋아해", meal["base_guide"])
            self.assertNotIn("선호:", meal["base_guide"])
            self.assertGreaterEqual(
                set(meal["balance_axes"]),
                {"단백질", "복합 탄수화물", "채소·과일"},
            )

    def test_food_preference_after_unsafe_constraint_is_still_preserved(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "감량", "persona": "천사"},
        ):
            result = generate_meal_plan(
                "unsafe-first",
                preferences="하루 700칼로리 이하로 먹고 닭고기와 두부는 좋아해",
                schedule=["18:00"],
            )

        self.assertEqual(result["accepted_preferences"], "닭고기와 두부는 좋아해")
        self.assertEqual(
            result["rejected_preference_categories"], ["exact_calorie_limit"])
        self.assertNotIn("700", str(result))

    @patch("tools.coaching.analyze_trend", return_value=EMPTY_TREND)
    def test_english_persona_override_is_normalized_and_source_is_request(self, _trend):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "천사"},
        ):
            result = get_recommendation("english-override", persona_override=" DEVIL ")

        self.assertEqual(result["persona"], "악마")
        self.assertEqual(result["persona_source"], "request_override")
        self.assertIsNone(result["persona_override_status"])
        self.assertEqual(result["persona_context"]["name"], "악마")

    @patch("tools.coaching.analyze_trend", return_value=EMPTY_TREND)
    def test_invalid_override_keeps_valid_profile_persona_and_reports_fallback(self, _trend):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "코치"},
        ):
            result = get_recommendation("invalid-override", persona_override="devl")

        self.assertEqual(result["persona"], "코치")
        self.assertEqual(result["persona_source"], "profile")
        self.assertEqual(result["persona_override_status"], "invalid_ignored")
        self.assertEqual(result["persona_context"]["name"], "코치")

    @patch("tools.coaching.analyze_trend", return_value=EMPTY_TREND)
    def test_blank_override_keeps_profile_persona_and_reports_fallback(self, _trend):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "악마"},
        ):
            result = get_recommendation("blank-override", persona_override="   ")

        self.assertEqual(result["persona"], "악마")
        self.assertEqual(result["persona_source"], "profile")
        self.assertEqual(result["persona_override_status"], "blank_ignored")

    def test_meal_plan_supports_request_scoped_persona_override(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "천사"},
        ):
            result = generate_meal_plan(
                "plan-persona-override",
                schedule=["08:00"],
                persona_override="devil",
            )

        self.assertEqual(result["persona"], "악마")
        self.assertEqual(result["persona_source"], "request_override")
        self.assertIsNone(result["persona_override_status"])
        self.assertIn("악마모드", result["assistant_message"])
        self.assertNotIn("악마모드", result["meals"][0]["guide"])

    def test_meal_adjustment_invalid_override_keeps_profile_persona(self):
        with patch(
            "tools.coaching._profile",
            return_value={"goal": "유지", "persona": "현실파이터"},
        ), patch(
            "tools.coaching._body_context",
            return_value={},
        ), patch(
            "tools.coaching._workout_context",
            return_value={},
        ), patch(
            "tools.coaching._recent_meal_pattern",
            return_value={"recent_classifications": []},
        ):
            result = suggest_meal_adjustment(
                "adjustment-persona-override",
                current_meal_text="닭가슴살 현미밥 브로콜리",
                persona_override="unknown",
            )

        self.assertEqual(result["persona"], "현실파이터")
        self.assertEqual(result["persona_source"], "profile")
        self.assertEqual(result["persona_override_status"], "invalid_ignored")


if __name__ == "__main__":
    unittest.main()
