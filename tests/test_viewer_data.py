"""Read-only dual-source tests for the GTK history viewer's data layer."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from burnbag_viewer_data import HistorySources, flatten_data


class HistorySourcesTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="viewer-data-", dir=str(temp_root))
        self.root = Path(self.temp.name)
        self.system = self.root / "system.sqlite3"
        self.user = self.root / "user.sqlite3"
        self._create(self.system)
        self._create(self.user)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _create(path):
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version=1")
        connection.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, captured_at REAL NOT NULL, boottime REAL NOT NULL, machine_id TEXT NOT NULL, boot_id TEXT NOT NULL, collector_id TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL, interval_start REAL, interval_end REAL)")
        connection.execute("CREATE TABLE coverage (collector_id TEXT NOT NULL, machine_id TEXT NOT NULL, boot_id TEXT NOT NULL, stream TEXT NOT NULL, segment INTEGER NOT NULL, first_boot REAL NOT NULL, last_boot REAL NOT NULL, first_wall REAL NOT NULL, last_wall REAL NOT NULL, PRIMARY KEY(collector_id,stream,segment))")
        connection.commit()
        connection.close()

    @staticmethod
    def _insert(path, identity, stamp, payload):
        connection = sqlite3.connect(path)
        connection.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (identity, "sample", stamp, stamp, "machine", "boot",
                            "collector", "system", json.dumps(payload), None, None))
        connection.commit()
        connection.close()

    def test_merges_pages_by_time_and_id_preferring_system_collision(self):
        self._insert(self.system, "shared", 2, {"battery": {"percentage": 60}})
        self._insert(self.system, "s2", 3, {"battery": {"percentage": 59}})
        self._insert(self.user, "shared", 2, {"battery": {"percentage": 61}})
        self._insert(self.user, "u1", 1, {"cpu": {"usage": 8}})
        reader = HistorySources([("system", self.system), ("user", self.user)])
        try:
            first = reader.page(limit=2)
            self.assertEqual(["u1", "shared"], [row["id"] for row in first])
            self.assertEqual("system", first[1]["source"])
            self.assertTrue(reader.warnings)
            second = reader.page((first[-1]["captured_at"], first[-1]["id"]), 2)
            self.assertEqual(["s2"], [row["id"] for row in second])
        finally:
            reader.close()

    def test_different_collision_timestamps_do_not_skip_intervening_rows(self):
        self._insert(self.system, "shared", 5, {"battery": {"percentage": 55}})
        self._insert(self.user, "shared", 1, {"battery": {"percentage": 54}})
        self._insert(self.user, "between", 2, {"cpu": {"usage": 8}})
        reader = HistorySources([("system", self.system), ("user", self.user)])
        try:
            first = reader.page(limit=1)
            self.assertEqual(["between"], [row["id"] for row in first])
            second = reader.page((first[-1]["captured_at"], first[-1]["id"]), 1)
            self.assertEqual(["shared"], [row["id"] for row in second])
            self.assertEqual("system", second[0]["source"])
            self.assertTrue(any("ID collision" in warning for warning in reader.warnings))
        finally:
            reader.close()

    def test_absent_sources_are_reported_without_being_created(self):
        missing = self.root / "absent.sqlite3"
        reader = HistorySources([("user", missing)])
        try:
            self.assertIn("user", reader.errors)
            self.assertFalse(missing.exists())
            self.assertEqual([], reader.page())
        finally:
            reader.close()

    def test_database_files_remain_unchanged_by_reader(self):
        self._insert(self.system, "s1", 1, {"batteries": {"b": {"percentage": 80}}})
        before = (self.system.read_bytes(), self.system.stat().st_mtime_ns)
        reader = HistorySources([("system", self.system)])
        try:
            reader.page()
        finally:
            reader.close()
        self.assertEqual(before, (self.system.read_bytes(), self.system.stat().st_mtime_ns))

    def test_flatten_data_preserves_nested_measurement_names(self):
        self.assertEqual({"battery.main.percentage": 80,
                          "battery.main.name": "A",
                          "items": '["x"]'},
                         flatten_data({"battery": {"main": {"percentage": 80, "name": "A"}},
                                       "items": ["x"]}))

    def test_search_pages_all_record_metadata_and_measurements(self):
        self._insert(self.system, "one", 1, {"sensor": {"temperature_c": 21}})
        self._insert(self.system, "two", 2, {"sensor": {"temperature_c": 20}})
        self._insert(self.user, "three", 3, {"battery": {"percentage": 80}})
        reader = HistorySources([("system", self.system), ("user", self.user)])
        try:
            first = reader.search_page("temperature", limit=1)
            self.assertEqual(["one"], [row["id"] for row in first])
            second = reader.search_page("temperature", (first[-1]["captured_at"], first[-1]["id"]), 1)
            self.assertEqual(["two"], [row["id"] for row in second])
            self.assertEqual([], reader.search_page("absent"))
        finally:
            reader.close()

    def test_system_coverage_suppresses_overlapping_user_measurements(self):
        self._insert(self.system, "system", 5, {"batteries": {"b": {"percentage": 55}}})
        self._insert(self.user, "user", 5, {"batteries": {"b": {
            "percentage": 54, "current_ma": 20, "percentage_source": "gauge"}}})
        connection = sqlite3.connect(self.system)
        connection.execute("INSERT INTO coverage VALUES (?,?,?,?,?,?,?,?,?)",
                           ("collector", "machine", "boot", "batteries/b/percentage",
                            0, 0, 10, 0, 10))
        connection.commit()
        connection.close()
        reader = HistorySources([("system", self.system), ("user", self.user)])
        try:
            rows = reader.page(limit=10)
            user = next(row for row in rows if row["id"] == "user")
            self.assertEqual({"current_ma": 20}, user["data"]["batteries"]["b"])
            self.assertTrue(any("coverage takes precedence" in warning for warning in reader.warnings))
        finally:
            reader.close()

    def test_full_history_overview_includes_late_fields_and_downsamples_boundedly(self):
        for index in range(503):
            payload = {"battery": {"percentage": 80 - index % 10}}
            if index == 502:
                payload["late_sensor"] = {"temperature_c": 31}
            self._insert(self.system, "row-%04d" % index, index + 1, payload)
        reader = HistorySources([("system", self.system)])
        try:
            overview = reader.overview(max_buckets=50)
            self.assertEqual(503, overview["count"])
            self.assertEqual([1.0, 503.0], overview["range"])
            self.assertIn("late_sensor.temperature_c", overview["columns"])
            points = overview["series"]["late_sensor.temperature_c"]
            self.assertTrue(points)
            self.assertEqual(31.0, points[-1][1])
            self.assertLessEqual(len(overview["series"]["battery.percentage"]), 100)
        finally:
            reader.close()


if __name__ == "__main__":
    unittest.main()
