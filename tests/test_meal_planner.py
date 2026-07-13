import random
import unittest

from meal_db.catalog import MEAL_CATALOG, validate_catalog
from meal_db.evidence import EVIDENCE_SOURCES
from tools.meal_planner import build_meal_plan as _build_meal_plan, parse_food_preferences


def build_meal_plan(*args, **kwargs):
    kwargs.setdefault("options", MEAL_CATALOG)
    return _build_meal_plan(*args, **kwargs)


def _all_selected_text(plan):
    return " ".join(
        " ".join([meal["name"], *meal["components"].values()])
        for meal in plan["meals"]
    )


class MealPlannerTest(unittest.TestCase):
    def test_database_seed_catalog_has_seventy_two_unique_balanced_options(self):
        self.assertTrue(validate_catalog())
        self.assertEqual(len(MEAL_CATALOG), 72)
        self.assertEqual(len({row["option_id"] for row in MEAL_CATALOG}), 72)
        for meal_type in ("아침", "점심", "저녁", "간식"):
            self.assertEqual(
                sum(row["meal_type"] == meal_type for row in MEAL_CATALOG), 18)

    def test_every_option_has_explicit_sports_nutrition_metadata_and_valid_sources(self):
        source_ids = {source["id"] for source in EVIDENCE_SOURCES}
        for option in MEAL_CATALOG:
            self.assertTrue(option["training_contexts"])
            self.assertTrue(option["recovery_roles"])
            self.assertTrue(option["micronutrient_focus"])
            self.assertTrue(option["evidence_source_ids"])
            self.assertLessEqual(set(option["evidence_source_ids"]), source_ids)
            self.assertFalse(option["nutrition_verified"])
            self.assertEqual(
                option["review_status"], "principle_based_unverified_portion")

    def test_parses_mixed_korean_likes_dislikes_and_allergies(self):
        parsed = parse_food_preferences(
            "생선은 싫어하고 닭고기와 두부를 좋아해. 견과류 알레르기가 있어"
        )
        self.assertEqual(parsed["liked"], ["닭고기", "두부"])
        self.assertEqual(parsed["disliked"], ["생선"])
        self.assertEqual(parsed["allergens"], ["견과류"])

    def test_connector_does_not_leak_allergy_and_lactose_is_supported(self):
        parsed = parse_food_preferences("견과류 알레르기가 있고 두부를 좋아해. 유당불내증이 있어")
        self.assertEqual(parsed["liked"], ["두부"])
        self.assertEqual(parsed["allergens"], ["견과류", "유제품"])

    def test_allergy_wins_and_unsafe_constraint_is_not_a_preference(self):
        parsed = parse_food_preferences(
            "땅콩을 좋아하지만 땅콩 알레르기가 있어. 하루 700칼로리만 먹고 두부는 좋아해"
        )
        self.assertEqual(parsed["allergens"], ["땅콩"])
        self.assertNotIn("땅콩", parsed["liked"])
        self.assertEqual(parsed["liked"], ["두부"])
        self.assertTrue(parsed["ignored_constraints"])

    def test_every_goal_returns_structured_balanced_meals_without_numbers(self):
        for goal in ("증량", "감량", "유지", "bulk", "다이어트"):
            with self.subTest(goal=goal):
                plan = build_meal_plan(goal, ["아침", "점심", "저녁", "간식"], seed=11)
                self.assertEqual(len(plan["meals"]), 4)
                self.assertTrue(plan["goal_focus"])
                self.assertEqual(len({meal["option_id"] for meal in plan["meals"]}), 4)
                for meal in plan["meals"]:
                    self.assertGreaterEqual(set(meal["components"]), {"protein", "carbohydrate", "produce"})
                    self.assertGreaterEqual(set(meal["balance_axes"]), {"단백질", "복합 탄수화물", "채소·과일"})
                    self.assertTrue(meal["selection_reason"])
                self.assertFalse(any(unit in _all_selected_text(plan).lower() for unit in ("kcal", "칼로리", "그램")))

    def test_dislikes_and_group_allergy_are_strictly_excluded(self):
        plan = build_meal_plan(
            "유지", ["아침", "점심", "저녁", "간식"],
            "생선과 해산물은 싫고 견과류 알레르기가 있어", seed=3,
        )
        text = _all_selected_text(plan)
        for food in ("연어", "고등어", "흰살생선", "새우", "호두", "아몬드", "땅콩"):
            self.assertNotIn(food, text)

    def test_explicit_allergen_tags_hard_exclude_soy_wheat_sesame_and_buckwheat(self):
        cases = {
            "대두 알레르기": "soy",
            "밀 알레르기": "wheat",
            "참깨 알레르기": "sesame",
            "메밀 알레르기": "buckwheat",
        }
        for preference, allergen in cases.items():
            with self.subTest(allergen=allergen):
                plan = build_meal_plan(
                    "유지", ["아침", "점심", "저녁", "간식"],
                    preference, seed=17,
                )
                self.assertTrue(all(
                    allergen not in meal["allergens"] for meal in plan["meals"]
                ))

    def test_liked_food_is_preferred_once_without_robotic_suffix(self):
        plan = build_meal_plan("증량", ["아침", "점심", "저녁"], "두부를 좋아해", seed=7)
        self.assertEqual(sum("두부" in meal["components"]["protein"] for meal in plan["meals"]), 1)
        self.assertTrue(any(meal["matched_preferences"] == ["두부"] for meal in plan["meals"]))
        self.assertTrue(any("음식 선호를 반영" in meal["selection_reason"] for meal in plan["meals"]))
        self.assertNotIn("두부를 좋아해", str(plan["meals"]))
        self.assertNotIn("선호:", str(plan["meals"]))

    def test_seed_is_reproducible_and_other_seeds_add_variety(self):
        first = build_meal_plan("유지", seed=19)
        self.assertEqual(first, build_meal_plan("유지", seed=19))
        variants = {
            tuple(meal["option_id"] for meal in build_meal_plan("유지", seed=seed)["meals"])
            for seed in range(12)
        }
        self.assertGreaterEqual(len(variants), 3)

    def test_repeated_meal_type_never_duplicates_an_option(self):
        plan = build_meal_plan("감량", ["간식", "간식", "간식", "간식"], rng=random.Random(4))
        ids = [meal["option_id"] for meal in plan["meals"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rejects_conflicting_rng_controls_and_unknown_meal_type(self):
        with self.assertRaisesRegex(ValueError, "either seed or rng"):
            build_meal_plan("유지", seed=1, rng=random.Random(1))
        with self.assertRaisesRegex(ValueError, "unsupported meal types"):
            build_meal_plan("유지", ["야식"])
        with self.assertRaisesRegex(ValueError, "isolated meal database"):
            _build_meal_plan("유지", options=[])


if __name__ == "__main__":
    unittest.main()
