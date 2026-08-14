"""Battery discovery, sampling cadence, safety, and chart behavior tests."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest import mock

import burnbag


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP = PROJECT_ROOT / ".local" / "tmp"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class FakeGLib:
    """Small deterministic timer boundary for manager lifecycle tests."""

    scheduled = []
    removed = []

    @classmethod
    def timeout_add(cls, milliseconds, callback):
        source_id = len(cls.scheduled) + 1
        cls.scheduled.append((source_id, milliseconds, callback))
        return source_id

    @classmethod
    def source_remove(cls, source_id):
        cls.removed.append(source_id)
        return True


class CapturingLog:
    """Owned in-memory logger fake; filesystem durability is tested elsewhere."""

    failed_reason = None

    def __init__(self):
        self.records = []

    def append(self, event, level, message, details=None):
        self.records.append((event, level, message, details or {}))


class BatteryMonitoringTests(unittest.TestCase):
    def setUp(self):
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.run_root = Path(
            tempfile.mkdtemp(prefix="burnbag-battery-test.", dir=LOCAL_TMP)
        )
        self.sysfs_root = self.run_root / "power_supply"
        self.sysfs_root.mkdir()
        self.original_glib = burnbag.GLib
        FakeGLib.scheduled = []
        FakeGLib.removed = []
        burnbag.GLib = FakeGLib

    def tearDown(self):
        burnbag.GLib = self.original_glib
        shutil.rmtree(self.run_root)

    def add_supply(
        self,
        name,
        supply_type="Battery",
        capacity=80,
        present="1",
        status=None,
    ):
        supply = self.sysfs_root / name
        supply.mkdir()
        (supply / "type").write_text(f"{supply_type}\n", encoding="ascii")
        if present is not None:
            (supply / "present").write_text(f"{present}\n", encoding="ascii")
        if capacity is not None:
            (supply / "capacity").write_text(f"{capacity}\n", encoding="ascii")
        if status is not None:
            (supply / "status").write_text(f"{status}\n", encoding="ascii")
        return supply

    def make_manager(self, no_plot=False, running_log=None):
        manager = burnbag.LidCloseManager(
            mode="run-cool",
            suspend_after_minutes=None,
            no_inhibit_auto_suspend=False,
            ignore_lid=False,
            do_not_touch_backlight=True,
            no_plot=no_plot,
            terminal_style=burnbag.TerminalStyle(False, False),
            running_log=running_log,
        )
        manager.battery_monitor = burnbag.BatteryMonitor(
            self.sysfs_root, manager.started_boottime
        )
        return manager

    def test_discovery_selects_two_present_batteries_in_kernel_name_order(self):
        self.add_supply("AC", supply_type="Mains", capacity=None, present=None)
        self.add_supply("BAT1", capacity=71, status="Discharging")
        self.add_supply("BAT0", capacity=82, present=None)
        self.add_supply("BAT2", capacity=63)
        self.add_supply("BATX", capacity=50, present="0")
        monitor = burnbag.BatteryMonitor(self.sysfs_root, 10.0)

        errors = monitor.discover()
        sample, sample_errors = monitor.sample(
            captured_at=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
            elapsed_seconds=15.0,
        )

        self.assertEqual(errors, [])
        self.assertEqual([device.name for device in monitor.devices], ["BAT0", "BAT1"])
        self.assertEqual(monitor.unselected_names, ["BAT2"])
        self.assertEqual(sample.percentages, {"BAT0": 82, "BAT1": 71})
        self.assertEqual(sample.statuses, {"BAT1": "Discharging"})
        self.assertEqual(sample.present, {"BAT0": True, "BAT1": True})
        self.assertEqual(sample_errors, [])

    def test_default_sample_elapsed_time_uses_linux_boottime(self):
        self.add_supply("BAT0", capacity=82)
        monitor = burnbag.BatteryMonitor(self.sysfs_root, 100.0)
        monitor.discover()

        with mock.patch.object(burnbag, "linux_boottime", return_value=115.25):
            sample, errors = monitor.sample()

        self.assertEqual(errors, [])
        self.assertEqual(sample.elapsed_seconds, 15.25)

    def test_missing_invalid_and_failed_capacity_reads_are_explicit_gaps(self):
        self.add_supply("BAT0", capacity=None)
        bad = self.add_supply("BAT1", capacity="unknown")
        monitor = burnbag.BatteryMonitor(self.sysfs_root, 0.0)

        discovery_errors = monitor.discover()
        sample, sample_errors = monitor.sample(
            captured_at=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
            elapsed_seconds=0.0,
        )

        self.assertIn("does not expose a capacity", discovery_errors[0])
        self.assertEqual([device.name for device in monitor.devices], ["BAT1"])
        self.assertEqual(sample.percentages, {})
        self.assertRegex(sample_errors[0], "Could not read battery 'BAT1'")

        (bad / "capacity").write_text("101\n", encoding="ascii")
        recovered_sample, out_of_range_errors = monitor.sample(
            captured_at=datetime(2026, 8, 13, 9, 1, tzinfo=timezone.utc),
            elapsed_seconds=60.0,
        )
        self.assertEqual(recovered_sample.percentages, {})
        self.assertIn("0--100", out_of_range_errors[0])

    def test_initial_periodic_and_final_samples_use_fifteen_second_timer(self):
        bat0 = self.add_supply("BAT0", capacity=88)
        bat1 = self.add_supply("BAT1", capacity=77)
        log = CapturingLog()
        manager = self.make_manager(no_plot=True, running_log=log)

        with contextlib.redirect_stdout(io.StringIO()):
            manager.start_battery_monitoring()

        self.assertEqual(len(manager.battery_monitor.samples), 1)
        self.assertEqual(len(FakeGLib.scheduled), 1)
        source_id, milliseconds, callback = FakeGLib.scheduled[0]
        self.assertEqual(milliseconds, 15_000)

        (bat0 / "capacity").write_text("87\n", encoding="ascii")
        (bat1 / "capacity").write_text("76\n", encoding="ascii")
        self.assertTrue(callback())
        self.assertEqual(len(manager.battery_monitor.samples), 2)

        with contextlib.redirect_stdout(io.StringIO()):
            manager.teardown()

        self.assertEqual(FakeGLib.removed, [source_id])
        self.assertEqual(len(manager.battery_monitor.samples), 3)
        reasons = [
            details["reason"]
            for event, _level, _message, details in log.records
            if event == "battery_sample"
        ]
        self.assertEqual(reasons, ["initial", "periodic", "final"])
        self.assertIn("battery_monitor_summary", [record[0] for record in log.records])
        summary = next(
            details
            for event, _level, _message, details in log.records
            if event == "battery_monitor_summary"
        )
        self.assertEqual(summary["statistics"][0]["timebase"], "CLOCK_BOOTTIME")
        self.assertEqual(summary["statistics"][0]["statistics_version"], 2)

    def test_read_failure_selects_nonzero_but_cannot_prevent_teardown(self):
        battery = self.add_supply("BAT0", capacity=50)
        manager = self.make_manager()
        manager.start_battery_monitoring()
        (battery / "capacity").write_text("broken\n", encoding="ascii")
        manager.restore_backlights = mock.Mock(return_value=True)
        manager.release_inhibitor_fds = mock.Mock()
        manager.restore_power_profile = mock.Mock()

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            manager.teardown()

        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(manager.teardown_complete)
        self.assertTrue(any("BAT0" in deviation for deviation in manager.deviations))
        manager.restore_backlights.assert_called_once_with()
        manager.release_inhibitor_fds.assert_called_once_with()
        manager.restore_power_profile.assert_called_once_with()

    def test_no_battery_is_normal_and_does_not_schedule_a_timer(self):
        manager = self.make_manager()

        with contextlib.redirect_stdout(io.StringIO()):
            manager.start_battery_monitoring()

        self.assertEqual(manager.exit_code, 0)
        self.assertEqual(manager.battery_monitor.devices, [])
        self.assertEqual(manager.battery_monitor.samples, [])
        self.assertEqual(FakeGLib.scheduled, [])

    def make_chart_data(self):
        devices = [
            burnbag.BatteryDevice("BAT0", Path("/unused/BAT0")),
            burnbag.BatteryDevice("BAT1", Path("/unused/BAT1")),
        ]
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone(timedelta(hours=-7)))
        samples = [
            burnbag.BatterySample(start, 0.0, {"BAT0": 80, "BAT1": 80}),
            burnbag.BatterySample(
                start + timedelta(minutes=15),
                900.0,
                {"BAT0": 75, "BAT1": 78},
            ),
            burnbag.BatterySample(
                start + timedelta(minutes=30),
                1800.0,
                {"BAT0": 70, "BAT1": 70},
            ),
        ]
        return devices, samples

    def test_chart_is_full_width_twenty_five_rows_and_data_bounded(self):
        devices, samples = self.make_chart_data()
        rendered = burnbag.render_battery_depletion_chart(
            devices,
            samples,
            burnbag.TerminalStyle(False, False),
            io.StringIO(),
            columns=80,
        )
        lines = rendered.splitlines()
        plot_lines = [line for line in lines if " |" in line]

        self.assertEqual(len(plot_lines), 25)
        self.assertTrue(all(len(line) == 80 for line in plot_lines))
        self.assertIn("Observed Y range: 70%--80%", rendered)
        self.assertNotRegex(rendered, r"(?m)^\s*0% \|")
        self.assertIn("80% |", rendered)
        self.assertIn("70% |", rendered)
        self.assertIn("08:00", rendered)
        self.assertIn("08:30", rendered)
        self.assertIn("1=BAT0", rendered)
        self.assertIn("2=BAT1", rendered)
        self.assertIn("X=overlap", rendered)
        self.assertIn("X", "".join(plot_lines))
        observed_labels = {
            int(match.group(1))
            for line in plot_lines
            if (match := re.match(r"\s*(\d+)% \|", line)) is not None
        }
        self.assertEqual(observed_labels, {70, 75, 78, 80})

    def test_hour_long_wide_chart_callouts_have_visible_separation(self):
        devices = [
            burnbag.BatteryDevice("BAT0", Path("/unused/BAT0")),
            burnbag.BatteryDevice("BAT1", Path("/unused/BAT1")),
        ]
        start = datetime(2026, 8, 13, 13, 31, tzinfo=timezone(timedelta(hours=-7)))
        # Match the operator's reported 252-cycle run: 251 fifteen-second
        # intervals put the last real sample at 14:33:45 local time.
        samples = []
        for index in range(252):
            elapsed = float(index * 15)
            samples.append(
                burnbag.BatterySample(
                    start + timedelta(seconds=elapsed),
                    elapsed,
                    {
                        "BAT0": 5,
                        "BAT1": max(87, 98 - int(index * 11 / 251)),
                    },
                )
            )

        rendered = burnbag.render_battery_depletion_chart(
            devices,
            samples,
            burnbag.TerminalStyle(False, False),
            io.StringIO(),
            columns=190,
        )
        lines = rendered.splitlines()
        axis_index = next(
            index for index, line in enumerate(lines) if re.match(r"^\s+\+[-+]", line)
        )
        axis_line = lines[axis_index]
        label_line = lines[axis_index + 1]
        callouts = list(re.finditer(r"\d{2}:\d{2}", label_line))

        self.assertGreater(len(callouts), 3)
        self.assertEqual(callouts[0].group(), "13:31")
        self.assertEqual(callouts[-1].group(), "14:33")
        for previous, current in zip(callouts, callouts[1:]):
            blank_columns = current.start() - previous.end()
            self.assertGreaterEqual(blank_columns, 2)
        self.assertEqual(axis_line.count("+"), len(callouts))

    def test_ansi_chart_uses_requested_series_and_overlap_colors(self):
        devices, samples = self.make_chart_data()
        rendered = burnbag.render_battery_depletion_chart(
            devices,
            samples,
            burnbag.TerminalStyle(True, False),
            io.StringIO(),
            columns=72,
        )
        plain = ANSI_ESCAPE.sub("", rendered)
        plot_lines = [line for line in plain.splitlines() if " |" in line]

        self.assertIn("\x1b[33m", rendered)
        self.assertIn("\x1b[34m", rendered)
        self.assertIn("\x1b[32m", rendered)
        self.assertEqual(len(plot_lines), 25)
        self.assertTrue(all(len(line) == 72 for line in plot_lines))

    def test_constant_series_is_centered_with_only_observed_y_label(self):
        device = burnbag.BatteryDevice("BAT0", Path("/unused/BAT0"))
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        samples = [
            burnbag.BatterySample(start, 0.0, {"BAT0": 95}),
            burnbag.BatterySample(start + timedelta(seconds=15), 15.0, {"BAT0": 95}),
        ]
        rendered = burnbag.render_battery_depletion_chart(
            [device],
            samples,
            burnbag.TerminalStyle(False, False),
            io.StringIO(),
            columns=60,
        )
        plot_lines = [line for line in rendered.splitlines() if " |" in line]

        self.assertEqual(len(plot_lines), 25)
        self.assertIn("95% |", plot_lines[12])
        self.assertEqual(sum("% |" in line for line in plot_lines), 1)

    def test_missing_middle_reading_is_not_interpolated(self):
        device = burnbag.BatteryDevice("BAT0", Path("/unused/BAT0"))
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        samples = [
            burnbag.BatterySample(start, 0.0, {"BAT0": 90}),
            burnbag.BatterySample(start + timedelta(minutes=1), 60.0, {}),
            burnbag.BatterySample(
                start + timedelta(minutes=2), 120.0, {"BAT0": 80}
            ),
        ]
        rendered = burnbag.render_battery_depletion_chart(
            [device],
            samples,
            burnbag.TerminalStyle(False, False),
            io.StringIO(),
            columns=60,
        )
        plot_cells = "".join(
            line.split("|", 1)[1]
            for line in rendered.splitlines()
            if " |" in line
        )

        self.assertEqual(plot_cells.count("1"), 2)
        self.assertNotIn("08:01", rendered)

    def make_statistics_data(self):
        """Build a quantized staircase with deliberately uneven level timing."""
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        transitions = {5: 99, 9: 98, 15: 97, 20: 96, 28: 95, 35: 94}
        percentage = 100
        samples = []
        for minute in range(36):
            percentage = transitions.get(minute, percentage)
            samples.append(
                burnbag.BatterySample(
                    start + timedelta(minutes=minute),
                    float(minute * 60),
                    {"BAT0": percentage},
                    {"BAT0": "Discharging"},
                    {"BAT0": True},
                )
            )
        return samples

    def test_statistics_use_ols_and_duration_weighted_transition_rates(self):
        result = burnbag.summarize_battery_statistics(
            "BAT0", self.make_statistics_data()
        )

        self.assertEqual(result.trend_kind, "depleting")
        self.assertAlmostEqual(result.trend_depletion_pp_per_hour, 9.976834, places=5)
        self.assertAlmostEqual(result.r_squared, 0.962904, places=5)
        self.assertEqual(result.transition_count, 6)
        self.assertEqual(result.local_rate_count, 5)
        self.assertAlmostEqual(
            result.weighted_mean_depletion_pp_per_hour, 10.0, places=6
        )
        self.assertAlmostEqual(result.weighted_sigma_pp_per_hour, 2.478479, places=5)
        self.assertAlmostEqual(
            result.coefficient_of_variation_percent, 24.784788, places=5
        )
        self.assertAlmostEqual(
            result.average_reported_change_pp_per_minute,
            -0.166667,
            places=5,
        )
        self.assertAlmostEqual(
            result.reported_change_sigma_pp_per_minute,
            0.041308,
            places=5,
        )
        self.assertEqual(result.median_minutes_per_pp, 6.0)
        self.assertEqual(result.observed_reversals, 0)
        self.assertEqual(result.observed_statuses, ("Discharging",))
        log_details = result.to_log_details()
        json.dumps(log_details, allow_nan=False)
        self.assertEqual(log_details["statistics_version"], 2)
        self.assertAlmostEqual(
            log_details[
                "average_reported_change_percentage_points_per_minute"
            ],
            -0.166667,
            places=5,
        )
        self.assertAlmostEqual(
            log_details[
                "standard_deviation_reported_change_percentage_points_per_minute"
            ],
            0.041308,
            places=5,
        )

    def test_operator_session_shape_regresses_to_reviewed_metrics(self):
        """Replay the 252-cycle BAT1 staircase from the reported live run."""
        start = datetime(2026, 8, 13, 13, 31, tzinfo=timezone.utc)
        reported_transitions = {
            0: 98,
            14: 97,
            33: 96,
            51: 95,
            68: 94,
            87: 93,
            109: 92,
            129: 91,
            151: 90,
            177: 89,
            206: 88,
            229: 87,
        }
        bat1 = 98
        samples = []
        for index in range(252):
            bat1 = reported_transitions.get(index, bat1)
            elapsed = float(index * 15)
            samples.append(
                burnbag.BatterySample(
                    start + timedelta(seconds=elapsed),
                    elapsed,
                    {"BAT0": 5, "BAT1": bat1},
                )
            )

        bat0_result = burnbag.summarize_battery_statistics("BAT0", samples)
        bat1_result = burnbag.summarize_battery_statistics("BAT1", samples)

        self.assertEqual(bat0_result.trend_kind, "constant")
        self.assertEqual(bat1_result.transition_count, 11)
        self.assertEqual(bat1_result.local_rate_count, 10)
        self.assertAlmostEqual(bat1_result.trend_depletion_pp_per_hour, 11.0, places=1)
        self.assertAlmostEqual(bat1_result.r_squared, 0.99, places=2)
        self.assertAlmostEqual(bat1_result.weighted_sigma_pp_per_hour, 1.8, places=1)
        self.assertAlmostEqual(bat1_result.median_minutes_per_pp, 5.25, places=2)
        self.assertAlmostEqual(
            bat1_result.average_reported_change_pp_per_minute,
            -0.186,
            places=3,
        )
        self.assertAlmostEqual(
            bat1_result.reported_change_sigma_pp_per_minute,
            0.030,
            places=3,
        )

    def test_constant_gauge_does_not_claim_zero_drain(self):
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        samples = [
            burnbag.BatterySample(
                start + timedelta(seconds=index * 75),
                float(index * 75),
                {"BAT0": 5},
            )
            for index in range(5)
        ]

        result = burnbag.summarize_battery_statistics("BAT0", samples)

        self.assertEqual(result.trend_kind, "constant")
        self.assertIsNone(result.trend_depletion_pp_per_hour)
        self.assertEqual(
            result.trend_validity_reason,
            "no reported whole-percentage change",
        )
        self.assertIsNone(result.weighted_sigma_pp_per_hour)
        self.assertIsNone(result.average_reported_change_pp_per_minute)
        self.assertIsNone(result.reported_change_sigma_pp_per_minute)
        self.assertEqual(
            result.variability_validity_reason,
            "no observed level transitions",
        )

    def test_missing_reading_and_status_change_break_local_continuity(self):
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        values = [100, 99, 98, 99, 100, 101, 101]
        statuses = [
            "Discharging",
            "Discharging",
            "Discharging",
            "Charging",
            "Charging",
            "Charging",
            "Charging",
        ]
        samples = [
            burnbag.BatterySample(
                start + timedelta(minutes=index),
                float(index * 60),
                {"BAT0": value},
                {"BAT0": statuses[index]},
            )
            for index, value in enumerate(values)
        ]

        mixed = burnbag.summarize_battery_statistics("BAT0", samples)
        self.assertTrue(mixed.mixed_history)
        self.assertEqual(mixed.trend_kind, "mixed")
        self.assertEqual(mixed.status_break_count, 1)
        self.assertEqual(mixed.excluded_gap_count, 0)
        self.assertEqual(mixed.segment_count, 2)
        self.assertEqual(mixed.observed_reversals, 1)

        samples[3] = burnbag.BatterySample(
            start + timedelta(minutes=3), 180.0, {}, {}
        )
        gapped = burnbag.summarize_battery_statistics("BAT0", samples)
        self.assertEqual(gapped.excluded_gap_count, 1)
        self.assertGreaterEqual(gapped.segment_count, 2)

    def test_statistics_renderer_is_colored_and_width_bounded(self):
        result = burnbag.summarize_battery_statistics(
            "BAT0", self.make_statistics_data()
        )
        plain = burnbag.render_battery_statistics(
            [result],
            burnbag.TerminalStyle(False, False),
            io.StringIO(),
            columns=40,
        )
        colored = burnbag.render_battery_statistics(
            [result],
            burnbag.TerminalStyle(True, False),
            io.StringIO(),
            columns=140,
        )

        self.assertIn("gauge-rate unevenness", plain)
        self.assertIn("avgΔ−.17", plain)
        self.assertIn("σ.04pp/min", plain)
        self.assertIn("not watts", plain)
        self.assertTrue(all(len(line) <= 40 for line in plain.splitlines()))
        self.assertIn("\x1b[33m", colored)
        self.assertIn("\x1b[35m", colored)
        self.assertIn("gauge depletion-rate variability", colored)
        self.assertIn("avg reported-gauge Δ/min −0.17 pp/min", colored)
        self.assertIn("σ 0.04 pp/min", colored)

    def test_no_plot_suppresses_chart_but_not_sampling_or_statistics(self):
        self.add_supply("BAT0", capacity=90)
        manager = self.make_manager(no_plot=True)
        manager.start_battery_monitoring()
        manager.stop_battery_monitoring()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            manager.print_battery_plot()

        self.assertNotIn("BATTERY DEPLETION", output.getvalue())
        self.assertIn("BATTERY SUMMARY", output.getvalue())
        self.assertEqual(len(manager.battery_monitor.samples), 2)
        self.assertEqual(len(FakeGLib.scheduled), 1)

    def test_shutdown_narrative_places_chart_at_end(self):
        devices, samples = self.make_chart_data()
        manager = self.make_manager()
        manager.battery_monitor.devices = list(devices)
        manager.battery_monitor.samples = list(samples)
        manager.battery_statistics = [
            burnbag.summarize_battery_statistics(device.name, samples)
            for device in devices
        ]
        manager.battery_monitor_stopped = True
        manager.teardown_complete = True
        manager.goal_achieved = True
        manager.shutdown_reason = "Test run complete."
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            manager.print_shutdown_narrative()

        rendered = output.getvalue()
        self.assertLess(
            rendered.index("BURNBAG — SHUTDOWN & TEARDOWN"),
            rendered.index("BATTERY DEPLETION - 15-second samples"),
        )
        self.assertIn("BAT0=70%, BAT1=70%; 3 sample(s)", rendered)

    def test_help_documents_no_plot(self):
        output = io.StringIO()
        parser = burnbag.build_argument_parser(burnbag.TerminalStyle(False, False))
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exited:
            parser.parse_args(["--help"])

        self.assertEqual(exited.exception.code, 0)
        self.assertIn("--no-plot", output.getvalue())
        self.assertIn("sampling", output.getvalue())


if __name__ == "__main__":
    unittest.main()
