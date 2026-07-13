import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class IsolatedMealDatabaseTest(unittest.TestCase):
    def test_schema_seed_and_main_database_are_physically_isolated(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="gymrat-meal-db-test-"))
        main_db = temp_dir / "main.db"
        meal_db = temp_dir / "meals.db"
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{main_db}",
            "MEAL_DATABASE_URL": f"sqlite:///{meal_db}",
        }
        code = textwrap.dedent(
            """
            from sqlalchemy import inspect, select

            from db.session import engine, init_db
            from meal_db.models import MealOptionRecord
            from meal_db.repository import seed_builtin_catalog
            from meal_db.session import MealSessionLocal, init_meal_db, meal_engine

            init_db()
            init_meal_db()
            second_seed = seed_builtin_catalog()

            main_tables = set(inspect(engine).get_table_names())
            meal_tables = set(inspect(meal_engine).get_table_names())
            assert "meal_options" not in main_tables, main_tables
            assert "users" not in meal_tables, meal_tables
            assert "meal_options" in meal_tables, meal_tables

            session = MealSessionLocal()
            try:
                count = len(session.scalars(select(MealOptionRecord.id)).all())
            finally:
                session.close()
            assert count == 72, count
            assert second_seed == {
                "catalog_size": 72,
                "inserted": 0,
                "enriched": 0,
                "evidence_inserted": 0,
            }, second_seed
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
