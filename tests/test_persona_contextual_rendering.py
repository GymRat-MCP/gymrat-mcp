import unittest

from tools.persona import SUPPORTED_PERSONAS, apply_persona, persona_response_fields


class PersonaContextualRenderingTest(unittest.TestCase):
    def test_recovery_message_never_adds_push_through_language(self):
        base = (
            "운동을 더 늘리기보다 회복, 수면, 강도 조절을 먼저 잡는 게 좋아요."
        )

        for persona in SUPPORTED_PERSONAS:
            with self.subTest(persona=persona):
                rendered = apply_persona(base, persona)
                self.assertNotIn("힘들면 그게 크는 신호", rendered)
                self.assertNotIn("딱 계획대로 가자", rendered)
                self.assertIn("회복", rendered)

    def test_injury_message_preserves_caution_without_workout_suffix(self):
        base = "어깨 통증이 있으면 무게를 낮추거나 대체 동작을 추천해줄게요."
        rendered = apply_persona(base, "코치")

        self.assertIn("통증", rendered)
        self.assertIn("무게를 낮", rendered)
        self.assertIn("회복", rendered)
        self.assertNotIn("한 세트", rendered)
        self.assertNotIn("가보자", rendered)

    def test_confirmation_question_is_not_pressuring(self):
        base = (
            "이 식단은 아직 단정하기 어려워요. "
            "단백질 반찬이 있었는지만 알려주면 더 정확히 볼게요."
        )
        rendered = apply_persona(base, "악마")

        self.assertIn("확인", rendered)
        self.assertIn("단백질 반찬", rendered)
        self.assertNotIn("내일도 똑같", rendered)
        self.assertNotIn("변명", rendered)
        self.assertEqual(rendered.count("악마모드:"), 1)

    def test_error_message_uses_error_tone_without_motivational_suffix(self):
        base = "체중 기록 저장에 실패했어요. 입력 내용을 다시 확인해볼게요."
        rendered = apply_persona(base, "코치")

        self.assertIn("점검", rendered)
        self.assertIn("실패", rendered)
        self.assertNotIn("힘들면", rendered)
        self.assertNotIn("한 세트", rendered)

    def test_personas_rewrite_body_not_only_label_and_suffix(self):
        base = "단백질이 부족해 보여요. 다음 끼니에서 보강해봐요."
        messages = {persona: apply_persona(base, persona) for persona in SUPPORTED_PERSONAS}

        self.assertIn("보강하세요", messages["악마"])
        self.assertIn("보강해봅시다", messages["코치"])
        self.assertIn("보강합시다", messages["현실파이터"])
        self.assertIn("보강해봐요", messages["천사"])
        self.assertEqual(len(set(messages.values())), len(SUPPORTED_PERSONAS))

    def test_structured_meal_lines_do_not_repeat_persona_badges(self):
        rendered = apply_persona(
            "아침: 단백질과 채소를 먼저 챙겨봐요.",
            "악마",
        )

        self.assertTrue(rendered.startswith("아침:"), rendered)
        self.assertNotIn("악마모드", rendered)
        self.assertNotIn("변명", rendered)
        self.assertIn("챙기세요", rendered)

    def test_rendering_is_idempotent(self):
        once = apply_persona("다음 끼니에서 단백질을 보강해봐요.", "코치")
        twice = apply_persona(once, "코치")
        self.assertEqual(once, twice)

    def test_status_message_does_not_add_workout_push_suffix(self):
        rendered = apply_persona(
            "체중 70.0kg 기록을 저장했어요. 다음 추세 분석에 반영할게요.",
            "코치",
        )

        self.assertIn("기록", rendered)
        self.assertNotIn("힘들면", rendered)
        self.assertNotIn("몸 풀고", rendered)
        self.assertNotIn("한 세트", rendered)

    def test_meal_plan_note_uses_plan_specific_tone_without_suffix(self):
        rendered = apply_persona(
            "유지 목표에 맞춰 정밀 수치보다 끼니별 균형을 우선으로 잡았어요.",
            "코치",
        )

        self.assertIn("식사 계획", rendered)
        self.assertNotIn("힘들면", rendered)
        self.assertNotIn("한 세트", rendered)

    def test_response_contract_aliases_still_match(self):
        fields = persona_response_fields(
            "코치",
            "회복과 수면을 먼저 챙겨봐요.",
            fallback_field="note",
        )

        self.assertEqual(fields["assistant_message"], fields["display_text"])
        self.assertEqual(fields["assistant_message"], fields["message"])
        self.assertEqual(fields["base_message"], "회복과 수면을 먼저 챙겨봐요.")
        self.assertEqual(fields["user_response_contract"]["fallback_field"], "note")


if __name__ == "__main__":
    unittest.main()
