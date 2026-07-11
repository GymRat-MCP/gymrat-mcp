import unittest

from tools.persona import (
    DEFAULT_PERSONA,
    PERSONA_REWRITE_INSTRUCTION,
    SUPPORTED_PERSONAS,
    USER_RESPONSE_INSTRUCTION,
    apply_persona,
    build_persona_context,
    persona_response_fields,
)


REQUIRED_CONTEXT_KEYS = {
    "name",
    "role",
    "tone",
    "intensity",
    "warmth",
    "prefer_phrases",
    "avoid_phrases",
    "guardrails",
}

UNSAFE_PHRASES = [
    "굶",
    "먹지 마",
    "먹지마",
    "벌 받아",
    "한심",
    "칼로리 정확히",
    "그램 정확히",
]

PERSONA_EXPECTATIONS = {
    "악마": {
        "must_include_any": ["악마모드", "변명", "대충", "지금"],
        "must_not_include": ["괜찮아요", "천천히"],
        "intensity": "high",
        "warmth": "low",
    },
    "천사": {
        "must_include_any": ["천사모드", "천천히", "괜찮", "한 가지만"],
        "must_not_include": ["변명은 여기까지", "대충 넘기면"],
        "intensity": "low",
        "warmth": "high",
    },
    "현실파이터": {
        "must_include_any": ["현실파이터", "완벽", "가능한", "갑시다"],
        "must_not_include": ["악마모드", "천사모드"],
        "intensity": "medium",
        "warmth": "medium",
    },
    "코치": {
        "must_include_any": ["코치모드", "운동", "스트레스", "몸"],
        "must_not_include": ["김동현"],
        "intensity": "medium",
        "warmth": "medium",
    },
}


class PersonaHarnessTest(unittest.TestCase):
    def test_supported_personas_have_complete_context_contract(self):
        self.assertEqual(set(SUPPORTED_PERSONAS), set(PERSONA_EXPECTATIONS))

        for persona in SUPPORTED_PERSONAS:
            with self.subTest(persona=persona):
                context = build_persona_context(persona)
                expected = PERSONA_EXPECTATIONS[persona]

                self.assertTrue(REQUIRED_CONTEXT_KEYS.issubset(context))
                self.assertEqual(context["name"], persona)
                self.assertEqual(context["intensity"], expected["intensity"])
                self.assertEqual(context["warmth"], expected["warmth"])
                self.assertGreaterEqual(len(context["prefer_phrases"]), 2)
                self.assertGreaterEqual(len(context["avoid_phrases"]), 2)
                self.assertGreaterEqual(len(context["guardrails"]), 3)
                self.assertIn("말투", " ".join(context["guardrails"]))

    def test_persona_response_fields_are_rewrite_ready(self):
        base_message = "단백질이 조금 부족해 보여요. 다음 끼니에서 보강해봐요."

        for persona in SUPPORTED_PERSONAS:
            with self.subTest(persona=persona):
                fields = persona_response_fields(persona, base_message)

                self.assertIn("assistant_message", fields)
                self.assertIn("display_text", fields)
                self.assertIn("message", fields)
                self.assertNotEqual(fields["assistant_message"], base_message)
                self.assertEqual(fields["display_text"], fields["assistant_message"])
                self.assertEqual(fields["message"], fields["assistant_message"])
                self.assertEqual(fields["base_message"], base_message)
                self.assertEqual(fields["persona_context"]["name"], persona)
                self.assertEqual(fields["rewrite_instruction"], PERSONA_REWRITE_INSTRUCTION)
                self.assertIn("base_message", fields["rewrite_instruction"])
                self.assertIn("가드레일", fields["rewrite_instruction"])
                self.assertIn("말투", fields["rewrite_instruction"])
                self.assertEqual(fields["response_meta"]["base_message"], base_message)
                self.assertEqual(fields["response_meta"]["persona_context"]["name"], persona)
                self.assertEqual(
                    fields["response_meta"]["rewrite_instruction"],
                    PERSONA_REWRITE_INSTRUCTION,
                )
                self.assertEqual(
                    fields["user_response_contract"]["mode"],
                    "use_assistant_message",
                )
                self.assertEqual(
                    fields["user_response_contract"]["primary_field"],
                    "assistant_message",
                )
                self.assertEqual(
                    fields["user_response_contract"]["alias_fields"],
                    ["display_text", "message"],
                )
                self.assertEqual(
                    fields["user_response_contract"]["instruction"],
                    USER_RESPONSE_INSTRUCTION,
                )

    def test_unknown_persona_falls_back_to_default_contract(self):
        context = build_persona_context("무리수")
        fields = persona_response_fields("무리수", "기본 피드백")
        rendered = apply_persona("기본 피드백", "무리수")

        self.assertEqual(DEFAULT_PERSONA, "천사")
        self.assertEqual(context["name"], DEFAULT_PERSONA)
        self.assertEqual(fields["persona_context"]["name"], DEFAULT_PERSONA)
        self.assertEqual(fields["assistant_message"], rendered)
        self.assertEqual(fields["display_text"], rendered)
        self.assertEqual(fields["message"], rendered)
        self.assertIn("천사모드", rendered)

    def test_compatibility_rendering_matches_persona_expectations(self):
        base_message = "탄수화물과 곁들임은 보여요. 다음 끼니엔 단백질을 보강해봐요."

        for persona, expected in PERSONA_EXPECTATIONS.items():
            with self.subTest(persona=persona):
                rendered = apply_persona(base_message, persona)

                self.assertTrue(
                    any(phrase in rendered for phrase in expected["must_include_any"]),
                    rendered,
                )
                self.assertFalse(
                    any(phrase in rendered for phrase in expected["must_not_include"]),
                    rendered,
                )
                self.assertFalse(
                    any(phrase in rendered for phrase in UNSAFE_PHRASES),
                    rendered,
                )

    def test_persona_suffix_rotates_but_is_deterministic(self):
        # BUG6: 예전엔 매 응답 끝에 같은 상투구가 그대로 반복됐다. 내용 기반으로
        # 꼬리 문구를 로테이션 → 같은 입력은 항상 같은 출력(결정론), 여러 입력에선
        # 두 가지 이상 문구가 등장(반복 완화).
        from tools.persona import _PERSONA_STYLE

        for persona in SUPPORTED_PERSONAS:
            with self.subTest(persona=persona):
                self.assertEqual(apply_persona("같은 문장이에요.", persona),
                                 apply_persona("같은 문장이에요.", persona))
                _, phrases = _PERSONA_STYLE[persona]
                used = set()
                for i in range(40):
                    rendered = apply_persona(f"피드백 문장 번호 {i} 입니다.", persona)
                    for p in phrases:
                        if rendered.endswith(p):
                            used.add(p)
                            break
                self.assertGreater(len(used), 1)   # 상투구 하나로 고정되지 않음

    def test_persona_context_avoids_unsafe_or_exact_person_imitation(self):
        for persona in SUPPORTED_PERSONAS:
            with self.subTest(persona=persona):
                context_text = " ".join(
                    str(value)
                    for value in build_persona_context(persona).values()
                )

                self.assertFalse(any(phrase in context_text for phrase in UNSAFE_PHRASES))
                if persona == "코치":
                    self.assertNotIn("김동현", context_text)
                    self.assertIn("특정 인물", context_text)


if __name__ == "__main__":
    unittest.main()
