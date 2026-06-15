from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from econ import store
from econ.models import Reading


class StoreTests(unittest.TestCase):
    def test_unchanged_reading_is_not_written_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "econ.db"
            old_env = {
                name: os.environ.pop(name, None)
                for name in (*store.DATABASE_URL_NAMES, "ECON_SQLITE_PATH")
            }
            os.environ["ECON_SQLITE_PATH"] = str(db_path)
            try:
                store.init_db()
                reading = Reading("claims", "Initial", date(2026, 6, 1), 240, "K")
                self.assertEqual(store.upsert_readings([reading])["new"], 1)
                first_fetched_at = _fetched_at(db_path)
                time.sleep(1.1)
                stats = store.upsert_readings([reading])
                second_fetched_at = _fetched_at(db_path)
            finally:
                os.environ.pop("ECON_SQLITE_PATH", None)
                for name, value in old_env.items():
                    if value is not None:
                        os.environ[name] = value

        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(first_fetched_at, second_fetched_at)


def _fetched_at(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT fetched_at FROM readings").fetchone()
    return row[0]


if __name__ == "__main__":
    unittest.main()
