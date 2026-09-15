"""Real SQLite durability, bounded history, and Linux telemetry reader tests."""

from __future__ import annotations

from datetime import datetime
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import burnbag_history as history


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP = ROOT / ".local" / "tmp"


class HistoryTests(unittest.TestCase):
    def setUp(self):
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="burnbag-history-test.", dir=LOCAL_TMP))
        self.writers = []

    def tearDown(self):
        for writer in self.writers:
            try:
                writer.close()
            except history.HistoryError:
                pass
        shutil.rmtree(self.root)

    def writer(self, name="user", scope="user", **options):
        writer = history.TelemetryWriter(self.root / name / "history.sqlite3", scope, **options)
        self.writers.append(writer)
        return writer

    def records(self, writer, start=0, end=10**12, limit=100000):
        records, warnings = history.read_history([(writer.scope, writer.path)], start, end, limit)
        self.assertFalse(warnings, warnings)
        return records

    @staticmethod
    def payload(value=50, name="BAT0"):
        return {"batteries": {name: {"percentage": value}}, "errors": []}

    @staticmethod
    def wait_for(predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError("Timed out waiting for asynchronous history state")
            time.sleep(0.005)

    def test_xdg_selection_requires_absolute_paths(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}, clear=True):
            self.assertEqual(history.user_database_path(), self.root / "burnbag" / "history.sqlite3")
        with mock.patch.dict(os.environ, {"HOME": str(self.root)}, clear=True):
            self.assertEqual(history.user_database_path(), self.root / ".local/state/burnbag/history.sqlite3")
        for environment in ({}, {"HOME": "relative"}, {"XDG_STATE_HOME": "relative"}):
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(history.HistoryError):
                    history.user_database_path()

    def test_real_database_permissions_scope_and_offline_read(self):
        for scope, file_mode, directory_mode in (("user", 0o600, 0o700), ("system", 0o644, 0o755)):
            writer = self.writer(scope, scope)
            record_id = writer.submit("sample", self.payload(), captured_at=100, boottime=10)
            writer.close()
            self.assertEqual(stat.S_IMODE(writer.path.stat().st_mode), file_mode)
            self.assertEqual(stat.S_IMODE(writer.path.parent.stat().st_mode), directory_mode)
            records = self.records(writer)
            self.assertEqual(records[0]["id"], record_id)
            self.assertEqual(records[0]["scope"], scope)
            self.assertEqual(records[0]["data"], self.payload())
            with closing(sqlite3.connect(writer.path)) as connection, connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_batch_is_invisible_until_durable_flush_and_input_is_frozen(self):
        writer = self.writer()
        payload = self.payload()
        writer.submit("sample", payload)
        payload["batteries"]["BAT0"]["percentage"] = 0
        self.assertEqual(self.records(writer), [])
        self.assertEqual(writer.status()["pending_records"], 1)
        writer.flush()
        self.assertEqual(self.records(writer)[0]["data"]["batteries"]["BAT0"]["percentage"], 50)
        status = writer.status()
        self.assertEqual(status["pending_records"], 0)
        self.assertEqual(status["committed_sequence"], 1)
        self.assertIsInstance(status["last_commit"], float)

    def test_timed_batch_event_and_size_thresholds(self):
        for trigger in ("timer", "event", "size", "urgent"):
            writer = self.writer(trigger)
            writer.BATCH_SECONDS = 0.07 if trigger == "timer" else 60
            writer.EVENT_SECONDS = 0.07
            if trigger == "size":
                writer.BATCH_BYTES = 1
            writer.submit("sample", self.payload(), event=trigger == "event", urgent=trigger == "urgent")
            self.wait_for(lambda: writer.status()["committed_sequence"] == 1)
            self.assertEqual(len(self.records(writer)), 1)

    def test_prudent_mode_commits_each_update_and_can_be_released(self):
        writer = self.writer(prudent=True)
        commits = []
        original = writer._commit

        def observe(connection, batch):
            commits.append(len(batch))
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 3)
            original(connection, batch)

        writer._commit = observe
        for _ in range(4):
            writer.submit("sample", self.payload())
        writer.flush()
        self.assertEqual(commits, [1, 1, 1, 1])
        writer.set_prudent(False)
        writer.submit("sample", self.payload())
        self.assertEqual(writer.status()["committed_sequence"], 4)
        writer.flush()
        self.assertEqual(len(self.records(writer)), 5)

    def test_queue_overflow_is_explicit_and_does_not_accept_record(self):
        writer = self.writer()
        writer.MAX_PENDING_RECORDS = 1
        writer.submit("sample", self.payload())
        with self.assertRaisesRegex(history.HistoryError, "queue is full"):
            writer.submit("sample", self.payload())
        self.assertEqual(writer.status()["dropped_records"], 1)
        self.assertEqual(writer.status()["last_sequence"], 1)
        writer.flush()
        self.assertEqual(len(self.records(writer)), 1)

    def test_invalid_payload_and_timestamps_are_rejected_before_acceptance(self):
        writer = self.writer()
        for payload in ({"bad": float("nan")}, {"bad": object()}, [], {"large": "x" * 65536}):
            with self.assertRaises(history.HistoryError):
                writer.submit("sample", payload)
        for stamp in (float("inf"), datetime(2020, 1, 1), "not-a-time"):
            with self.assertRaises(history.HistoryError):
                writer.submit("sample", {}, captured_at=stamp)
        with self.assertRaises(history.HistoryError):
            writer.submit("sample", {}, boottime=-1)
        self.assertEqual(writer.status()["last_sequence"], 0)

    def test_symlink_hardlink_and_unsafe_parent_are_rejected(self):
        target = self.root / "preserve"
        target.write_text("preserve me", encoding="utf-8")
        directory = self.root / "unsafe"
        directory.mkdir(mode=0o700)
        linked = directory / "history.sqlite3"
        linked.symlink_to(target)
        with self.assertRaises(history.HistoryError):
            history.TelemetryWriter(linked, "user")
        self.assertEqual(target.read_text(), "preserve me")
        linked.unlink()
        os.link(target, linked)
        with self.assertRaises(history.HistoryError):
            history.TelemetryWriter(linked, "user")
        linked.unlink()
        directory.chmod(0o777)
        with self.assertRaises(history.HistoryError):
            history.TelemetryWriter(linked, "user")
        directory.chmod(0o700)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(history.HistoryError):
            history.TelemetryWriter(parent_link / "history.sqlite3", "user")

    def test_symlink_journal_is_rejected(self):
        directory = self.root / "journal"
        directory.mkdir(mode=0o700)
        target = self.root / "preserve"
        target.write_text("preserve me")
        (directory / "history.sqlite3-journal").symlink_to(target)
        with self.assertRaises(history.HistoryError):
            history.TelemetryWriter(directory / "history.sqlite3", "user")
        self.assertEqual(target.read_text(), "preserve me")

    def test_unrelated_and_future_schema_databases_are_not_overwritten(self):
        for future in (False, True):
            path = self.root / ("future" if future else "unrelated") / "history.sqlite3"
            path.parent.mkdir(mode=0o700)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE unrelated (value TEXT)")
                connection.execute("INSERT INTO unrelated VALUES ('preserved')")
                if future:
                    connection.execute("PRAGMA user_version=999")
            with self.assertRaises(history.HistoryError):
                history.TelemetryWriter(path, "user")
            with closing(sqlite3.connect(path)) as connection, connection:
                self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "preserved")

    def test_sqlite_failure_reports_pending_data_and_fails_later_calls(self):
        errors = []
        writer = self.writer(on_error=errors.append)
        with closing(sqlite3.connect(writer.path)) as connection, connection:
            connection.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON records "
                               "BEGIN SELECT RAISE(FAIL,'injected storage failure'); END")
        writer.submit("sample", self.payload())
        with self.assertRaisesRegex(history.HistoryError, "injected storage failure"):
            writer.flush()
        self.wait_for(lambda: bool(errors))
        self.assertFalse(writer.status()["healthy"])
        self.assertEqual(writer.status()["pending_records"], 1)
        self.assertEqual(writer.status()["committed_sequence"], 0)
        with self.assertRaises(history.HistoryError):
            writer.submit("sample", self.payload())
        with self.assertRaises(history.HistoryError):
            writer.close()
        self.assertEqual(self.records(writer), [])

    def test_crash_retains_committed_records_and_loses_uncommitted_ram_only(self):
        path = self.root / "crash" / "history.sqlite3"
        code = (
            "import os,sys; from pathlib import Path; from burnbag_history import TelemetryWriter; "
            "w=TelemetryWriter(Path(sys.argv[1]),'user'); "
            "w.submit('sample',{'batteries':{'BAT0':{'percentage':80}}},captured_at=100,boottime=10); "
            "w.flush(); w.submit('sample',{'batteries':{'BAT0':{'percentage':79}}},captured_at=105,boottime=15); "
            "os._exit(0)"
        )
        result = subprocess.run([sys.executable, "-B", "-c", code, str(path)], cwd=ROOT,
                                timeout=10, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        records, warnings = history.read_history([("user", path)], 0, 1000)
        self.assertFalse(warnings)
        self.assertEqual([record["captured_at"] for record in records], [100])

    def test_concurrent_submitters_and_live_reads_keep_valid_records(self):
        writer = self.writer(prudent=True)
        failures = []

        def submit(worker):
            try:
                for index in range(15):
                    writer.submit("lid_open", {"worker": worker, "index": index})
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=submit, args=(worker,)) for worker in range(3)]
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            self.records(writer)
        for thread in threads:
            thread.join()
        writer.flush()
        self.assertFalse(failures)
        records = self.records(writer)
        self.assertEqual(len(records), 45)
        self.assertEqual(len({record["id"] for record in records}), 45)

    def test_missing_failed_and_empty_sources_are_distinguished(self):
        writer = self.writer()
        broken = self.root / "broken"
        broken.write_text("not SQLite")
        records, warnings = history.read_history(
            [("empty", writer.path), ("absent", self.root / "missing"), ("broken", broken)], 0, 100
        )
        self.assertEqual(records, [])
        self.assertEqual(len(warnings), 2)
        self.assertIn("absent is missing", warnings[0])
        self.assertIn("broken failed", warnings[1])

    def test_query_bounds_span_entire_interval_and_keep_events(self):
        writer = self.writer()
        for tick in range(200):
            writer.submit("sample", self.payload(), captured_at=tick, boottime=tick)
        for tick in (13, 77, 156):
            writer.submit("lid_open", {"closed": False}, captured_at=tick, boottime=tick)
        writer.flush()
        records, warnings = history.read_history([("user", writer.path)], 0, 199, limit=12)
        samples = [record for record in records if record["kind"] == "sample"]
        self.assertEqual(len(records), 15)
        self.assertEqual(len(samples), 12)
        self.assertEqual((samples[0]["captured_at"], samples[-1]["captured_at"]), (0, 199))
        self.assertEqual(len([record for record in records if record["kind"] == "lid_open"]), 3)
        self.assertTrue(any("representative" in warning for warning in warnings))
        again, _ = history.read_history([("user", writer.path)], 0, 199, limit=12)
        self.assertEqual(records, again)

    def test_excessive_events_are_bounded_with_explicit_warning(self):
        writer = self.writer()
        for tick in range(20):
            writer.submit("lid_open", {}, captured_at=tick, boottime=tick)
        writer.flush()
        records, warnings = history.read_history([("user", writer.path)], 0, 19, limit=4)
        self.assertEqual(len(records), 4)
        self.assertEqual((records[0]["captured_at"], records[-1]["captured_at"]), (0, 19))
        self.assertTrue(any("events exceed" in warning for warning in warnings))

    def test_sleep_interval_is_found_when_its_record_timestamp_follows_query(self):
        writer = self.writer()
        writer.submit("sleep_interval", {"started_at": 10, "ended_at": 100,
                                         "sleep_kind": "suspend"},
                      captured_at=110, boottime=100)
        writer.submit("sleep_interval", {"started_at": 200, "ended_at": 300,
                                         "sleep_kind": "hibernate"},
                      captured_at=310, boottime=300)
        writer.flush()
        records, warnings = history.read_history([("user", writer.path)], 20, 30)
        self.assertFalse(warnings)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["sleep_kind"], "suspend")

    def test_sleep_interval_bounds_are_validated(self):
        writer = self.writer()
        for data in ({}, {"started_at": 10, "ended_at": 5},
                     {"started_at": 10, "ended_at": float("inf")}):
            with self.assertRaises(history.HistoryError):
                writer.submit("sleep_interval", data)

    def test_system_coverage_does_not_bridge_failures_or_missing_metrics(self):
        system = self.writer("system", "system")
        user = self.writer("user", "user")
        for tick, data in ((0, self.payload()), (5, {"batteries": {}}),
                           (10, self.payload()), (50, self.payload()), (55, self.payload())):
            system.submit("sample", data, captured_at=tick, boottime=tick)
        for tick in (5, 30, 52):
            user.submit("sample", {"batteries": {"BAT0": {"percentage": 40, "power_w": 5}}},
                        captured_at=tick, boottime=tick)
        system.flush()
        user.flush()
        records, warnings = history.read_history([("user", user.path), ("system", system.path)], 0, 60)
        local = {row["captured_at"]: row["data"]["batteries"]["BAT0"]
                 for row in records if row["collector_id"] == user.collector_id}
        self.assertIn("percentage", local[5])
        self.assertIn("percentage", local[30])
        self.assertNotIn("percentage", local[52])
        self.assertEqual(local[52]["power_w"], 5)
        self.assertTrue(any("overlap" in warning for warning in warnings))

    def test_clock_jump_splits_coverage_instead_of_claiming_intermediate_time(self):
        system = self.writer("system", "system")
        user = self.writer("user", "user")
        system.submit("sample", self.payload(), captured_at=100, boottime=10)
        system.submit("sample", self.payload(), captured_at=1000, boottime=15)
        user.submit("sample", self.payload(), captured_at=500, boottime=12)
        system.flush()
        user.flush()
        records, warnings = history.read_history([("system", system.path), ("user", user.path)], 0, 2000)
        self.assertEqual(len(records), 3)
        self.assertFalse(warnings)

    def test_closed_system_database_is_readable_without_writable_directory(self):
        writer = self.writer("system", "system")
        writer.submit("sample", self.payload())
        writer.close()
        writer.path.chmod(0o444)
        writer.path.parent.chmod(0o555)
        try:
            self.assertEqual(len(self.records(writer)), 1)
            self.assertFalse(Path(str(writer.path) + "-journal").exists())
        finally:
            writer.path.parent.chmod(0o755)

    def test_system_precedence_is_per_device_and_does_not_deduplicate_equal_time_events(self):
        system = self.writer("system", "system")
        user = self.writer("user", "user")
        for tick in (10, 20):
            system.submit("sample", self.payload(80), captured_at=tick, boottime=tick)
        user.submit("sample", self.payload(79), captured_at=5, boottime=5)
        user.submit("sample", {"batteries": {"BAT0": {"percentage": 70}, "BAT1": {"percentage": 60}}},
                    captured_at=15, boottime=15)
        user.submit("sample", self.payload(69), captured_at=25, boottime=25)
        user.submit("lid_close", {}, captured_at=15, boottime=15)
        system.submit("lid_open", {}, captured_at=15, boottime=15)
        system.flush()
        user.flush()
        records, warnings = history.read_history([("user", user.path), ("system", system.path)], 0, 30)
        inside = [row for row in records if row["kind"] == "sample" and row["captured_at"] == 15][0]
        self.assertEqual(inside["data"]["batteries"], {"BAT1": {"percentage": 60}})
        self.assertEqual(len([row for row in records if row["kind"].startswith("lid_")]), 2)
        self.assertTrue(any("overlap" in warning for warning in warnings))
        original = self.records(user)
        self.assertIn("BAT0", next(row for row in original if row["kind"] == "sample" and row["captured_at"] == 15)["data"]["batteries"])

    def test_distinct_boots_and_adjacent_samples_do_not_collide(self):
        system = self.writer("system", "system")
        user = self.writer("user", "user")
        system.submit("sample", self.payload(), captured_at=10, boottime=10)
        user.submit("sample", self.payload(), captured_at=11, boottime=11)
        user.boot_id = "another-boot"
        user.submit("sample", self.payload(), captured_at=10, boottime=10)
        system.flush()
        user.flush()
        records, warnings = history.read_history([("system", system.path), ("user", user.path)], 0, 20)
        self.assertEqual(len(records), 3)
        self.assertFalse(warnings)

    def test_identical_record_id_collision_warns_and_system_wins(self):
        system = self.writer("system", "system")
        user = self.writer("user", "user")
        record_id = system.submit("lid_open", {"origin": "system"}, captured_at=10, boottime=10)
        user.submit("lid_close", {"origin": "user"}, captured_at=10, boottime=10)
        system.flush()
        user.flush()
        with closing(sqlite3.connect(user.path)) as connection, connection:
            connection.execute("UPDATE records SET id=?", (record_id,))
        for sources in ([("system", system.path), ("user", user.path)], [("user", user.path), ("system", system.path)]):
            records, warnings = history.read_history(sources, 0, 20)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["data"]["origin"], "system")
            self.assertTrue(any("duplicate record IDs" in warning for warning in warnings))


class PowerSamplerTests(unittest.TestCase):
    def setUp(self):
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="burnbag-sampler-test.", dir=LOCAL_TMP))
        self.sys = self.root / "sys"
        self.proc = self.root / "proc"
        self.sampler = history.PowerSampler(self.sys, self.proc)

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value) + "\n", encoding="utf-8")

    def battery(self, **attributes):
        entry = self.sys / "class/power_supply/qcom-battmgr-bat"
        self.write(entry / "type", "Battery")
        for key, value in attributes.items():
            self.write(entry / key, value)
        return entry

    def test_missing_optional_interfaces_are_normal(self):
        reading = self.sampler.sample()
        self.assertEqual(reading["batteries"], {})
        self.assertEqual(reading["errors"], [])

    def test_qualcomm_energy_fallback_and_si_units(self):
        self.battery(energy_now=30000000, energy_full=60000000, voltage_now=12000000,
                     current_now=500000, temp=305, present=1, status="Discharging")
        reading = self.sampler.sample()["batteries"]["qcom-battmgr-bat"]
        self.assertEqual(reading["percentage"], 50)
        self.assertEqual(reading["energy_wh"], 30)
        self.assertEqual(reading["full_wh"], 60)
        self.assertEqual(reading["voltage_v"], 12)
        self.assertEqual(reading["power_w"], 6)
        self.assertEqual(reading["temperature_c"], 30.5)
        self.assertTrue(reading["present"])
        self.assertEqual(reading["percentage_source"], "energy_now/energy_full")

    def test_native_capacity_and_power_take_precedence(self):
        self.battery(capacity=70, energy_now=30, energy_full=60, voltage_now=12000000,
                     current_now=500000, power_now=7000000)
        reading = self.sampler.sample()["batteries"]["qcom-battmgr-bat"]
        self.assertEqual(reading["percentage"], 70)
        self.assertEqual(reading["power_w"], 7)
        self.assertEqual(reading["percentage_source"], "capacity")

    def test_static_metadata_is_cached_but_dynamic_readings_update(self):
        entry = self.battery(capacity=70, model_name="original")
        first = self.sampler.sample()
        self.write(entry / "capacity", 60)
        self.write(entry / "model_name", "changed")
        second = self.sampler.sample()
        self.assertEqual(first["batteries"][entry.name]["percentage"], 70)
        self.assertEqual(second["batteries"][entry.name]["percentage"], 60)
        self.assertEqual(second["batteries"][entry.name]["metadata"]["model_name"], "original")

    def test_invalid_fields_are_explicit_gaps_without_nan_json(self):
        self.battery(capacity=150, energy_now="nan", energy_full=0, voltage_now="oops", present=2)
        reading = self.sampler.sample()
        battery = reading["batteries"]["qcom-battmgr-bat"]
        self.assertNotIn("percentage", battery)
        self.assertNotIn("voltage_v", battery)
        self.assertNotIn("energy_wh", battery)
        self.assertNotIn("present", battery)
        self.assertGreaterEqual(len(reading["errors"]), 4)
        json.dumps(reading, allow_nan=False)

    def test_supplies_thermal_backlight_and_cpu_deltas(self):
        supply = self.sys / "class/power_supply/AC"
        self.write(supply / "type", "Mains")
        self.write(supply / "online", 1)
        self.write(self.sys / "class/thermal/thermal_zone0/temp", 42000)
        self.write(self.sys / "class/backlight/panel/brightness", 200)
        self.write(self.sys / "class/backlight/panel/max_brightness", 1000)
        self.write(self.sys / "devices/system/cpu/cpufreq/policy0/scaling_cur_freq", 2500000)
        self.write(self.proc / "stat", "cpu  10 0 20 70 0 0 0 0")
        self.write(self.proc / "loadavg", "1.25 2.50 3.75 1/100 1")
        first = self.sampler.sample()
        self.assertNotIn("busy_percent", first["cpu"])
        self.write(self.proc / "stat", "cpu  20 0 30 80 0 0 0 0")
        reading = self.sampler.sample()
        self.assertEqual(reading["supplies"]["AC"]["online"], 1)
        self.assertEqual(reading["thermal_c"]["thermal_zone0"], 42)
        self.assertEqual(reading["backlight"]["panel"]["brightness"], 200)
        self.assertEqual(reading["cpu"]["frequency_mhz"]["policy0"], 2500)
        self.assertAlmostEqual(reading["cpu"]["busy_percent"], 200 / 3)
        self.assertEqual(reading["cpu"]["load_average"], [1.25, 2.50, 3.75])


if __name__ == "__main__":
    unittest.main()
