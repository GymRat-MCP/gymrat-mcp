import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db
from tools.analysis import analyze_trend
from tools.coaching import (
    generate_meal_plan,
    get_recommendation,
    suggest_meal_adjustment,
)
from tools.logging_tools import (
    confirm_meal_details,
    log_meal,
    log_weight,
    log_workout,
)
from tools.meal_intel import classify_meal_text
from tools.profile import update_profile
from tools.routine import generate_routine


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
        self.assertEqual(meal["assistant_message"], meal["qualitative_note"])
        self.assertEqual(meal["display_text"], meal["assistant_message"])
        self.assertEqual(meal["message"], meal["assistant_message"])
        self.assertEqual(meal["user_response_contract"]["mode"], "use_assistant_message")
        self.assertEqual(meal["user_response_contract"]["primary_field"], "assistant_message")
        self.assertEqual(meal["user_response_contract"]["fallback_field"], "qualitative_note")
        self.assertEqual(meal["base_message"], meal["base_qualitative_note"])
        self.assertEqual(meal["response_meta"]["base_message"], meal["base_qualitative_note"])
        self.assertEqual(meal["persona_context"]["name"], "악마")
        self.assertIn("base_message", meal["rewrite_instruction"])
        self.assertIn("악마모드", trend["summary"])
        self.assertEqual(trend["assistant_message"], trend["summary"])
        self.assertEqual(trend["display_text"], trend["assistant_message"])
        self.assertEqual(trend["base_message"], trend["base_summary"])
        self.assertEqual(trend["persona_context"]["tone"], "짧고 직설적이며 핑계를 줄이는 말투")
        self.assertIn("악마모드", plan["note"])
        self.assertEqual(plan["assistant_message"], plan["note"])
        self.assertEqual(plan["display_text"], plan["assistant_message"])
        self.assertIn("악마모드", plan["meals"][0]["guide"])
        self.assertIn("base_guide", plan["meals"][0])
        self.assertEqual(plan["persona_context"]["name"], "악마")
        self.assertIn("악마모드", recommendation["recommendation"])
        self.assertEqual(recommendation["assistant_message"], recommendation["recommendation"])
        self.assertEqual(recommendation["display_text"], recommendation["assistant_message"])
        self.assertEqual(recommendation["message"], recommendation["assistant_message"])
        self.assertEqual(recommendation["base_message"], recommendation["base_recommendation"])
        self.assertEqual(recommendation["persona_context"]["name"], "악마")
        for basis in recommendation["based_on"]:
            self.assertNotIn("assistant_message", basis)
            self.assertNotIn("base_message", basis)
            self.assertNotIn("persona_context", basis)
            self.assertNotIn("rewrite_instruction", basis)
            self.assertNotIn("response_meta", basis)
            self.assertNotIn("user_response_contract", basis)
            self.assertNotIn("display_text", basis)
            self.assertNotIn("message", basis)
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
        self.assertEqual(meal["assistant_message"], meal["qualitative_note"])
        self.assertEqual(meal["persona_context"]["name"], "코치")
        self.assertIn("운동 밈 느낌", meal["persona_context"]["tone"])

    def test_missing_persona_defaults_to_angel_tone(self):
        user_id = "default-angel-tone"

        meal = log_meal(user_id, "닭가슴살 밥 샐러드", "점심")

        self.assertEqual(meal["persona"], "천사")
        self.assertIn("천사모드", meal["qualitative_note"])
        self.assertEqual(meal["assistant_message"], meal["qualitative_note"])
        self.assertEqual(meal["persona_context"]["name"], "천사")

    def test_recommendation_uses_current_numeric_context_before_db_defaults(self):
        user_id = "current-context-first"
        update_profile(user_id, goal="감량", persona="천사")

        recommendation = get_recommendation(
            user_id,
            persona_override="악마",
            goal_override="증량",
            current_context={
                "weekly_sessions": 5,
                "target_weekly_sessions": 4,
                "sleep_quality": "낮음",
                "fatigue": "높음",
            },
        )

        self.assertEqual(recommendation["persona"], "악마")
        self.assertEqual(recommendation["persona_source"], "request_override")
        self.assertEqual(recommendation["goal"], "증량")
        self.assertEqual(recommendation["goal_source"], "request_override")
        self.assertTrue(recommendation["current_context_used"])
        self.assertEqual(recommendation["evaluation"]["status"], "needs_recovery")
        self.assertEqual(recommendation["evaluation"]["basis"], "current_context")
        self.assertEqual(recommendation["evaluation"]["values"]["weekly_sessions"], 5.0)
        self.assertIn("악마모드", recommendation["assistant_message"])
        self.assertIn("회복", recommendation["assistant_message"])
        for basis in recommendation["based_on"]:
            self.assertNotIn("summary", basis)
            self.assertNotIn("base_summary", basis)
            self.assertNotIn("persona", basis)

    def test_workout_log_uses_persona_assistant_message(self):
        user_id = "workout-harness"
        update_profile(user_id, persona="악마")

        result = log_workout(
            user_id,
            "벤치 80kg 5세트 8회",
            [{"exercise": "벤치", "weight": 80, "sets": 5, "reps": 8}],
            date="2026-06-30",
        )

        self.assertTrue(result["saved"])
        self.assertEqual(result["persona"], "악마")
        self.assertIn("악마모드", result["note"])
        self.assertEqual(result["assistant_message"], result["note"])
        self.assertEqual(result["display_text"], result["assistant_message"])
        self.assertEqual(result["message"], result["assistant_message"])
        self.assertEqual(result["base_message"], result["base_note"])
        self.assertEqual(result["user_response_contract"]["fallback_field"], "note")

    def test_routine_uses_persona_assistant_message(self):
        user_id = "routine-harness"
        update_profile(user_id, goal="증량", experience="중급", persona="코치")

        with patch("tools.routine._query_exercises", return_value=[]):
            result = generate_routine(user_id, focus="가슴", available_days=3,
                                      session_minutes=40)

        self.assertEqual(result["persona"], "코치")
        self.assertIn("코치모드", result["rationale"])
        self.assertEqual(result["assistant_message"], result["rationale"])
        self.assertEqual(result["display_text"], result["assistant_message"])
        self.assertEqual(result["message"], result["assistant_message"])
        self.assertEqual(result["base_message"], result["base_rationale"])
        self.assertEqual(result["user_response_contract"]["fallback_field"], "rationale")

    def test_recommendation_normalizes_request_overrides(self):
        user_id = "override-normalization"
        update_profile(user_id, goal="감량", persona="악마")

        result = get_recommendation(
            user_id,
            persona_override="devil",
            goal_override="bulk",
            current_context={
                "weekly_sessions": 4,
                "target_weekly_sessions": 4,
            },
        )

        self.assertEqual(result["persona"], "천사")
        self.assertEqual(result["persona_context"]["name"], "천사")
        self.assertEqual(result["goal"], "증량")
        self.assertEqual(result["evaluation"]["status"], "frequency_on_track_for_gain")
        self.assertIn("천사모드", result["assistant_message"])

    def test_meal_plan_normalizes_goal_override(self):
        user_id = "meal-plan-goal-normalization"
        update_profile(user_id, goal="감량", persona="천사")

        result = generate_meal_plan(user_id, goal_override="bulk",
                                    schedule=["08:00"])

        self.assertIn("증량 목표", result["base_note"])
        self.assertIn("단백질을 먼저", result["meals"][0]["base_guide"])
        self.assertEqual(result["assistant_message"], result["note"])

    def test_log_meal_returns_text_classification(self):
        user_id = "meal-text-classification"
        update_profile(user_id, persona="천사")

        result = log_meal(user_id, "김밥이랑 라떼", "점심")

        self.assertTrue(result["saved"])
        self.assertEqual(result["meal_text"], "김밥이랑 라떼")
        self.assertIn("carb", result["meal_tags"])
        self.assertIn("vegetable", result["meal_tags"])
        self.assertIn("sweet_drink", result["meal_tags"])
        self.assertIn("protein", result["missing_axes"])
        self.assertEqual(result["balance_flag"], "needs_balance")
        self.assertEqual(result["confidence"], "medium")
        self.assertTrue(result["needs_follow_up"])
        self.assertIn("고기, 계란, 두부, 생선", result["follow_up_questions"][0])
        self.assertEqual(result["assistant_message"], result["qualitative_note"])
        self.assertIn("천사모드", result["assistant_message"])

    def test_meal_parser_marks_ambiguous_records_as_follow_up(self):
        result = classify_meal_text("도시락 먹음")

        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["balance_flag"], "needs_more_info")
        self.assertTrue(result["needs_follow_up"])
        self.assertIn("broad_dish_name", result["uncertainty_signals"])
        self.assertIn("processed", result["risk_flags"])
        self.assertIn("단백질 반찬", result["follow_up_questions"][0])

    def test_ambiguous_meal_requires_confirmation_before_save(self):
        user_id = "meal-confirmation-pending"
        update_profile(user_id, persona="악마")

        pending = log_meal(user_id, "도시락 먹음", "점심")
        trend_before_confirm = analyze_trend(user_id, "meal", 30)

        self.assertFalse(pending["saved"])
        self.assertTrue(pending["pending_confirmation"])
        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(pending["confidence"], "low")
        self.assertIn("pending_meal_confirmation", pending)
        self.assertEqual(
            pending["pending_meal_confirmation"]["original_meal_text"],
            "도시락 먹음",
        )
        self.assertIn("악마모드", pending["assistant_message"])
        self.assertEqual(
            trend_before_confirm["flag"],
            "insufficient_data",
        )

        confirmed = confirm_meal_details(
            user_id,
            original_meal_text=pending["pending_meal_confirmation"]["original_meal_text"],
            clarification_text="계란이랑 밥 김치가 있었어",
            meal_time=pending["pending_meal_confirmation"]["meal_time"],
        )
        trend_after_confirm = analyze_trend(user_id, "meal", 30)

        self.assertTrue(confirmed["saved"])
        self.assertTrue(confirmed["confirmed"])
        self.assertFalse(confirmed["pending_confirmation"])
        self.assertIn("protein", confirmed["meal_tags"])
        self.assertIn("carb", confirmed["meal_tags"])
        self.assertIn("vegetable", confirmed["meal_tags"])
        self.assertIn("보충:", confirmed["meal_text"])
        self.assertIn("악마모드", confirmed["assistant_message"])
        self.assertIn(trend_after_confirm["flag"], {"low_meal_logging", None})

    def test_meal_parser_extracts_high_confidence_balanced_meal(self):
        result = classify_meal_text("점심에 닭가슴살 샐러드랑 고구마 한 개")

        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["balance_flag"], "balanced")
        self.assertEqual(result["meal_time_detected"], "점심")
        self.assertIn("protein", result["meal_tags"])
        self.assertIn("vegetable", result["meal_tags"])
        self.assertIn("carb", result["meal_tags"])
        self.assertFalse(result["needs_follow_up"])
        self.assertTrue(result["portion_hints"])

    def test_recent_records_can_resolve_vague_meal_without_overriding_current_text(self):
        recent = [
            classify_meal_text("닭가슴살 현미밥 샐러드"),
            classify_meal_text("계란 밥 김치"),
            classify_meal_text("두부 덮밥 나물"),
        ]

        result = classify_meal_text(
            "오늘도 대충 집밥",
            recent_classifications=recent,
        )

        self.assertIsNotNone(result["recent_resolution"])
        self.assertEqual(result["recent_resolution"]["basis"], "recent_user_meals")
        self.assertIn("protein", result["meal_tags"])
        self.assertIn("vegetable", result["meal_tags"])
        self.assertIn("대충", result["recent_resolution"]["matched_vague_terms"])

    def test_suggest_meal_adjustment_uses_body_workout_and_meal_pattern(self):
        user_id = "meal-adjustment-context"
        update_profile(user_id, goal="증량", persona="악마")
        log_weight(user_id, 75.0)
        log_workout(
            user_id,
            "벤치 70kg 5세트 5회",
            [{"exercise": "벤치", "weight": 70, "sets": 5, "reps": 5}],
        )
        log_meal(user_id, "밥 김치 라떼", "점심")
        log_meal(user_id, "김밥과 콜라", "저녁")

        result = suggest_meal_adjustment(
            user_id,
            current_meal_text="김밥 라떼",
            meal_time="점심",
            current_context={"height_cm": 175},
        )

        self.assertEqual(result["persona"], "악마")
        self.assertEqual(result["goal"], "증량")
        self.assertTrue(result["body_context"]["bmi_available"])
        self.assertGreaterEqual(result["workout_context"]["weekly_workouts"], 1)
        self.assertIn("protein", result["current_meal"]["missing_axes"])
        self.assertIn("protein", result["meal_pattern"]["common_missing_axes"])
        self.assertIn("follow_up_needed_count", result["meal_pattern"])
        self.assertNotIn("recent_classifications", result["meal_pattern"])
        self.assertIn("악마모드", result["assistant_message"])
        self.assertEqual(result["assistant_message"], result["recommendation"])
        self.assertNotIn("kcal", result["base_recommendation"].lower())
        self.assertNotIn("그램", result["base_recommendation"])


if __name__ == "__main__":
    unittest.main()
