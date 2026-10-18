import unittest

from app.database import initialise_database, run_query


class DatabaseTests(unittest.TestCase):

    def test_database_initialises(self):
        initialise_database()

        results = run_query("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
        """)

        table_names = [row["name"] for row in results]

        self.assertIn("experiments", table_names)
        self.assertIn("metrics", table_names)


if __name__ == "__main__":
    unittest.main()