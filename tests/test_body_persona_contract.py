import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.session import init_db
from tools.logging_tools import log_weight
from tools.profile import update_profile


class BodyPersonaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_weight_log_returns_persona_user_message_contract(self):
        user_id = "weight-persona-contract"
        update_profile(user_id, persona="현실파이터")

        result = log_weight(
            user_id,
            weight=71.2,
            body_fat=18.4,
            date="2026-07-12",
        )

        self.assertTrue(result["saved"])
        self.assertEqual(result["persona"], "현실파이터")
        self.assertEqual(result["weight"], 71.2)
        self.assertEqual(result["body_fat"], 18.4)
        self.assertIn("체중 71.2kg", result["base_note"])
        self.assertIn("체지방률 18.4%", result["base_note"])
        self.assertEqual(result["assistant_message"], result["note"])
        self.assertEqual(result["display_text"], result["assistant_message"])
        self.assertEqual(result["message"], result["assistant_message"])
        self.assertEqual(
            result["user_response_contract"]["fallback_field"],
            "note",
        )


if __name__ == "__main__":
    unittest.main()
