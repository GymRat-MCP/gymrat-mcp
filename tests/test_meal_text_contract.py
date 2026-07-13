import inspect
import os
import tempfile
import unittest


os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"

from db.models import MealLog
from db.session import SessionLocal, init_db
from server import log_meal as mcp_log_meal
from tools.logging_tools import log_meal


class MealTextContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_public_and_internal_contracts_use_meal_text(self):
        for function in (mcp_log_meal, log_meal):
            parameters = inspect.signature(function).parameters
            self.assertIn("meal_text", parameters)
            self.assertNotIn("photo_analysis", parameters)

        columns = MealLog.__table__.columns
        self.assertIn("meal_text", columns)
        self.assertNotIn("photo_analysis", columns)

    def test_meal_text_is_saved_without_image_contract(self):
        result = log_meal(
            "meal-text-contract",
            meal_text="닭가슴살 현미밥 브로콜리",
            meal_time="점심",
        )

        self.assertTrue(result["saved"])
        self.assertEqual(result["meal_text"], "닭가슴살 현미밥 브로콜리")

        session = SessionLocal()
        try:
            saved = session.query(MealLog).filter_by(
                user_id="meal-text-contract").one()
            self.assertEqual(saved.meal_text, "닭가슴살 현미밥 브로콜리")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
