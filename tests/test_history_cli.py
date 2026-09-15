"""CLI warning envelopes, real merged-history rendering and time validation."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import burnbag
import burnbag_graph
import burnbag_history
import burnbag_service


class HistoryCLITests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="history-cli.", dir=base))

    def tearDown(self):
        shutil.rmtree(self.root)

    def invoke(self, args, states=None):
        output, errors = io.StringIO(), io.StringIO()
        states = states or [{"status": "absent"}, {"status": "absent"}]
        with mock.patch.object(burnbag_service, "probe_service", side_effect=states), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                status = burnbag.main(args)
            except SystemExit as exc:
                status = exc.code
        return status, output.getvalue(), errors.getvalue()

    def test_warning_wraps_help_without_creating_history_or_loading_gi(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}), \
                mock.patch.object(burnbag, "load_pygobject", side_effect=AssertionError("help loaded GI")):
            status, output, errors = self.invoke(["--help", "--no-color"])
        self.assertEqual(status, 0)
        self.assertEqual(errors, "")
        self.assertTrue(output.splitlines()[0].startswith("[WARNING]"))
        self.assertTrue(output.splitlines()[-1].startswith("[WARNING]"))
        self.assertIn("--prudent-writes", output)
        self.assertFalse(list(self.root.iterdir()))

    def test_warning_wraps_no_args_and_invalid_arguments(self):
        for args in ([], ["bad-mode"], ["run", "--suspend-after-minutes", "bad"],
                     ["--from", "2026-01-01"], ["run", "--start-service"]):
            with self.subTest(args=args):
                status, output, errors = self.invoke(args)
                self.assertEqual(status, 2)
                self.assertTrue(errors.splitlines()[0].startswith("[WARNING]"))
                self.assertTrue(errors.splitlines()[-1].startswith("[WARNING]"))

    def test_footer_rechecks_collector_state(self):
        with mock.patch.object(burnbag_service, "warning_for_service", side_effect=["Initially absent", None]):
            status, output, errors = self.invoke(["--help"])
        self.assertEqual(status, 0)
        self.assertEqual(output.count("[WARNING]"), 1)

    def test_management_flags_dispatch_without_operational_mode(self):
        for scope in (None, "user", "system"):
            for action in ("start", "stop", "enable", "disable", "status"):
                middle = "" if scope is None else scope + "-"
                with self.subTest(scope=scope, action=action), \
                        mock.patch.object(burnbag_service, "manage_service", return_value=0) as manage:
                    status, _, _ = self.invoke([f"--{action}-{middle}service"])
                    self.assertEqual(status, 0)
                    manage.assert_called_once_with(action, scope)

    def test_prudent_option_rejected_for_unrelated_actions(self):
        for args in (["--status-service", "--prudent-writes"], ["--graph", "--prudent-writes"]):
            self.assertEqual(self.invoke(args)[0], 2)

    def test_missing_history_query_creates_nothing(self):
        with mock.patch.object(burnbag_history, "SYSTEM_DATABASE", self.root / "system.sqlite3"), \
                mock.patch.object(burnbag_history, "user_database_path", return_value=self.root / "user.sqlite3"):
            status, output, errors = self.invoke(["--graph", "--from", "2025-01-01T00:00:00Z", "--to", "2025-01-02T00:00:00Z"])
        self.assertEqual(status, 0, errors)
        self.assertIn("No valid battery observations", output)
        self.assertFalse(list(self.root.iterdir()))

    def test_real_history_plot_and_summary(self):
        path = self.root / "history.sqlite3"
        start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        writer = burnbag_history.TelemetryWriter(path, "user")
        for i in range(8):
            writer.submit("sample", {"batteries": {"BAT0": {"percentage": 90 - i,
                          "status": "Discharging", "present": True}}},
                          captured_at=start + i * 5, boottime=100 + i * 5)
        writer.submit("lid_closed", {}, captured_at=start + 5, boottime=105, event=True)
        writer.submit("lid_opened", {}, captured_at=start + 30, boottime=130, event=True)
        writer.submit("sleep_interval", {"started_at": start + 10, "ended_at": start + 20,
                      "start_boottime": 110, "end_boottime": 120, "sleep_kind": "hibernate"},
                      captured_at=start + 20, boottime=120)
        writer.close()
        with mock.patch.object(burnbag_history, "SYSTEM_DATABASE", self.root / "missing.sqlite3"), \
                mock.patch.object(burnbag_history, "user_database_path", return_value=path):
            status, output, errors = self.invoke(["--graph", "--from", "2026-01-01T00:00:00Z",
                                                 "--to", "2026-01-01T00:01:00Z", "--no-color"])
        self.assertEqual(status, 0, errors)
        self.assertIn("BAT0", output)
        self.assertIn("close=1/open=1", output)
        self.assertIn("hibernate=1", output)
        self.assertIn("avg", output)
        self.assertIn("H", output)

    def test_graph_inserts_gap_on_boot_change_and_missing_coverage(self):
        records = []
        for i, (stamp, boot) in enumerate(((100, "a"), (105, "b"), (200, "b"))):
            records.append({"id": str(i), "captured_at": stamp, "kind": "sample",
                            "boot_id": boot, "machine_id": "m", "data": {
                                "batteries": {"BAT0": {"percentage": 90 - i}}}})
        _, samples, _, _, _ = burnbag_graph.graph_observations(burnbag, records, 90, 210)
        self.assertEqual(sum(not sample.percentages for sample in samples), 2)

    def test_malformed_nested_history_does_not_hide_usable_observations(self):
        records = [{"id": str(i), "captured_at": 100 + i * 5, "kind": "sample",
                    "boot_id": "b", "machine_id": "m", "data": {"batteries": value}}
                   for i, value in enumerate(([], {"BAT0": []}, {"BAT0": {"percentage": 90}}))]
        devices, samples, _, _, issues = burnbag_graph.graph_observations(burnbag, records, 90, 120)
        self.assertEqual(len(issues), 2)
        self.assertEqual(len(samples), 1)
        self.assertEqual(devices[0].name, "BAT0")

    def test_representative_spacing_uses_actual_coverage(self):
        records = [{"id": str(i), "captured_at": stamp, "kind": "sample", "boot_id": "b",
                    "machine_id": "m", "data": {"batteries": {"BAT0": {"percentage": 90 - i}}},
                    "coverage_segments": {"batteries/BAT0/percentage": "b:c:1"}}
                   for i, stamp in enumerate((100, 10000))]
        _, samples, _, _, _ = burnbag_graph.graph_observations(burnbag, records, 90, 11000)
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(sample.percentages for sample in samples))

    def test_reduced_query_retains_brief_known_sensor_gap(self):
        records = [{"id": str(i), "captured_at": stamp, "kind": "sample", "boot_id": "b",
                    "machine_id": "m", "data": {"batteries": {"BAT0": {"percentage": 90 - i}}},
                    "coverage_segments": {"batteries/BAT0/percentage": "b:c:" + str(i)}}
                   for i, stamp in enumerate((100, 110))]
        _, samples, _, _, _ = burnbag_graph.graph_observations(burnbag, records, 90, 120)
        self.assertEqual(len(samples), 3)
        self.assertEqual(samples[1].percentages, {})

    def test_unreadable_history_is_reported_instead_of_treated_as_missing(self):
        inaccessible = self.root / "private" / "history.sqlite3"
        with mock.patch.object(burnbag_history, "SYSTEM_DATABASE", inaccessible), \
                mock.patch.object(burnbag_history, "user_database_path", return_value=inaccessible), \
                mock.patch.object(Path, "lstat", side_effect=PermissionError("permission denied")):
            status, _, errors = self.invoke(["--graph", "--from", "2025-01-01T00:00:00Z",
                                             "--to", "2025-01-02T00:00:00Z"])
        self.assertEqual(status, 1)
        self.assertIn("Cannot inspect system history", errors)
        self.assertIn("Cannot inspect user history", errors)

    def test_query_wholly_inside_sleep_preserves_event_timeline(self):
        path = self.root / "history.sqlite3"
        start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        writer = burnbag_history.TelemetryWriter(path, "user")
        writer.submit("sleep_interval", {"started_at": start, "ended_at": start + 3600,
                      "sleep_kind": "hibernate"}, captured_at=start + 3600, boottime=4000)
        writer.close()
        with mock.patch.object(burnbag_history, "SYSTEM_DATABASE", self.root / "missing.sqlite3"), \
                mock.patch.object(burnbag_history, "user_database_path", return_value=path):
            status, output, errors = self.invoke(["--graph", "--from", "2026-01-01T00:10:00Z",
                                                 "--to", "2026-01-01T00:20:00Z", "--no-color"])
        self.assertEqual(status, 0, errors)
        self.assertIn("Event timeline", output)
        self.assertIn("hibernate=1", output)
        self.assertEqual(sum("HHHH" in line for line in output.splitlines()), 25)


class HistoryTimeTests(unittest.TestCase):
    def test_offsets_and_default_interval(self):
        self.assertEqual(burnbag_graph.parse_history_time("2026-01-01T01:00:00+01:00"),
                         burnbag_graph.parse_history_time("2026-01-01T00:00:00Z"))
        self.assertEqual(burnbag_graph.history_range(None, None, now=100000), (13600, 100000))
        with self.assertRaises(ValueError):
            burnbag_graph.history_range("2026-02-01", "2026-01-01")
        for invalid in ("2026-01-01Z", "2026-01-01+02:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                burnbag_graph.parse_history_time(invalid)

    @unittest.skipUnless(hasattr(time, "tzset"), "requires POSIX timezone handling")
    def test_dst_ambiguous_and_nonexistent_local_times_require_offset(self):
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
                time.tzset()
                for value in ("2026-03-08T02:30:00", "2026-11-01T01:30:00"):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        burnbag_graph.parse_history_time(value)
                self.assertIsInstance(burnbag_graph.parse_history_time("2026-11-01T01:30:00-07:00"), float)
                self.assertIsInstance(burnbag_graph.parse_history_time("2026-01-01T12:00:00"), float)
        finally:
            time.tzset()


if __name__ == "__main__":
    unittest.main()
