from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from econ import store
from econ.models import Reading


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        env = {
            "ECON_SQLITE_PATH": self.db_path,
            "DATABASE_URL": "",
            "POSTGRES_URL": "",
            "NEON_DATABASE_URL": "",
        }
        self.env_patch = patch.dict(os.environ, env, clear=False)
        self.env_patch.start()
        store.init_db()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_upsert_tracks_new_unchanged_and_revised_readings(self) -> None:
        original = Reading(
            indicator_key="cpi",
            series_label="Headline YoY",
            period=date(2026, 5, 1),
            value=2.7,
            unit="%",
            source="test",
        )

        self.assertEqual(store.upsert_readings([original])["new"], 1)
        self.assertEqual(store.upsert_readings([original])["unchanged"], 1)

        revised = Reading(
            indicator_key="cpi",
            series_label="Headline YoY",
            period=date(2026, 5, 1),
            value=2.8,
            unit="%",
            source="test",
        )
        stats = store.upsert_readings([revised])
        saved = store.latest_reading("cpi", "Headline YoY")

        self.assertEqual(stats["revised"], 1)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.value, 2.8)
        self.assertEqual(saved.prior_value, 2.7)

    def test_meta_round_trips(self) -> None:
        self.assertIsNone(store.get_meta("last_refresh"))
        store.set_meta("last_refresh", "2026-06-14T10:00:00")
        self.assertEqual(store.get_meta("last_refresh"), "2026-06-14T10:00:00")


if __name__ == "__main__":
    unittest.main()
