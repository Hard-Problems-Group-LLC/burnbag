"""Observed lid transitions, durable metadata, and ignore-lid reporting tests."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import burnbag


class Variant:
    def __init__(self, signature, value):
        self.signature = signature
        self.value = value

    def unpack(self):
        return self.value


class UPowerBoundary:
    def __init__(self, closed=False):
        self.closed = closed

    def call_sync(self, method, parameters, *_arguments):
        if method != "org.freedesktop.DBus.Properties.Get":
            raise RuntimeError("UnknownMethod")
        return Variant("(v)", (self.closed,))


class RecordingLog:
    """Capture owned log calls; durability itself has real-file test coverage."""

    path = Path("/unused/burnbag.log")

    def __init__(self, fail_event=None):
        self.failed_reason = None
        self.fail_event = fail_event
        self.records = []
        self.final_details = None
        self.closed = False

    def append(self, event, level, message, details=None):
        if event == self.fail_event:
            self.failed_reason = "injected event-log failure"
            raise burnbag.RunningLogError(self.failed_reason)
        self.records.append((event, details or {}))

    def end_session(self, **details):
        self.final_details = details

    def close(self):
        self.closed = True


class LidEventTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.errors = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.errors))
        self.stack.enter_context(mock.patch.object(burnbag, "GLib", SimpleNamespace(Variant=Variant)))
        self.stack.enter_context(mock.patch.object(
            burnbag, "Gio", SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0))
        ))

    def manager(self, ignore_lid=True, no_plot=False, running_log=None):
        return burnbag.LidCloseManager(
            "run", None, False, ignore_lid,
            do_not_touch_backlight=True,
            no_plot=no_plot,
            started_boottime=100.0,
            terminal_style=burnbag.TerminalStyle(False, False),
            running_log=running_log,
        )

    def change(self, manager, closed):
        manager._on_upower_properties_changed(
            manager.upower_proxy, Variant("a{sv}", {"LidIsClosed": closed}), []
        )

    def test_initial_closed_snapshot_is_not_a_close_event(self):
        manager = self.manager()
        manager.upower_proxy = UPowerBoundary(closed=True)
        manager.check_initial_lid_state()
        self.assertTrue(manager.current_lid_closed_state)
        self.assertTrue(manager.lid_was_closed_during_session)
        self.assertEqual(manager.lid_events, [])
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (0, 0))

        self.change(manager, False)
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (0, 1))
        self.assertEqual([event.closed for event in manager.lid_events], [False])

    def test_duplicate_state_notifications_do_not_inflate_counts(self):
        log = RecordingLog()
        manager = self.manager(running_log=log)
        manager.upower_proxy = UPowerBoundary()
        manager.check_initial_lid_state()
        for state in (False, True, True, False, False, True, False):
            self.change(manager, state)
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (2, 2))
        self.assertEqual([event.closed for event in manager.lid_events], [True, False, True, False])
        recorded = [(event, details) for event, details in log.records if event in {"lid_closed", "lid_opened"}]
        self.assertEqual(len(recorded), 4)
        self.assertEqual([
            (details["lid_close_count"], details["lid_open_count"])
            for _event, details in recorded
        ], [(1, 0), (1, 1), (2, 1), (2, 2)])

    def test_transition_uses_battery_boottime_and_local_timestamp(self):
        log = RecordingLog()
        manager = self.manager(running_log=log)
        observed = datetime(2026, 9, 14, 12, 0, 1, 234567, tzinfo=timezone.utc)
        with mock.patch.object(burnbag, "linux_boottime", return_value=120.75), \
                mock.patch.object(burnbag.time, "monotonic", return_value=7.0), \
                mock.patch.object(burnbag, "datetime") as clock:
            clock.now.return_value = observed
            self.change(manager, True)
        event = manager.lid_events[0]
        self.assertEqual(event.elapsed_seconds, 20.75)
        self.assertEqual(event.captured_at, observed.astimezone())
        self.assertTrue(event.closed)
        details = next(details for name, details in log.records if name == "lid_closed")
        self.assertEqual(details["elapsed_seconds"], 20.75)
        self.assertEqual(details["timebase"], "CLOCK_BOOTTIME")
        self.assertEqual(details["captured_at_local"], observed.astimezone().isoformat(timespec="microseconds"))

    def test_invalidated_property_counts_only_an_observed_state_change(self):
        manager = self.manager()
        manager.upower_proxy = UPowerBoundary()
        manager.check_initial_lid_state()
        manager.upower_proxy.closed = True
        for _ in range(2):
            manager._on_upower_properties_changed(
                manager.upower_proxy, Variant("a{sv}", {}), ["LidIsClosed"]
            )
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (1, 0))
        self.assertEqual(len(manager.lid_events), 1)

    def test_invalid_property_is_not_recorded_as_an_event(self):
        manager = self.manager()
        with self.assertRaises(RuntimeError):
            self.change(manager, "false")
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (0, 0))
        self.assertEqual(manager.lid_events, [])

    def test_sensor_recovery_with_same_state_clears_unavailable_without_counting(self):
        manager = self.manager()
        manager.lid_capability_checked = True
        manager.lid_monitoring_available = True
        manager._on_upower_properties_changed(
            None, Variant("a{sv}", {"LidIsPresent": False}), []
        )
        self.assertFalse(manager.lid_monitoring_available)
        manager._on_upower_properties_changed(
            None, Variant("a{sv}", {"LidIsPresent": True}), []
        )
        self.assertFalse(manager.lid_monitoring_available)
        self.change(manager, False)
        self.assertTrue(manager.lid_monitoring_available)
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (0, 0))
        self.assertEqual(manager.lid_events, [])

    def test_initial_state_read_updates_telemetry_availability(self):
        manager = self.manager()
        manager.upower_proxy = UPowerBoundary()
        manager.check_initial_lid_state()
        self.assertTrue(manager.lid_monitoring_available)
        manager.lid_capability_checked = True
        with mock.patch.object(manager.upower_proxy, "call_sync", side_effect=RuntimeError("unavailable")):
            manager.check_initial_lid_state()
        self.assertFalse(manager.lid_monitoring_available)
        manager.print_shutdown_narrative()
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (0, 0))
        self.assertIn("close=0/open=0; lid telemetry unavailable", self.output.getvalue())

    def test_log_failure_cannot_erase_observed_transition(self):
        manager = self.manager(running_log=RecordingLog(fail_event="lid_closed"))
        with self.assertRaises(burnbag.RunningLogError):
            self.change(manager, True)
        self.assertEqual((manager.lid_close_count, manager.lid_open_count), (1, 0))
        self.assertEqual(len(manager.lid_events), 1)
        self.assertTrue(manager.current_lid_closed_state)
        self.assertTrue(manager.lid_was_closed_during_session)
        self.assertEqual(manager.exit_code, 1)

    def test_counts_remain_in_final_log_without_serializing_event_history(self):
        log = RecordingLog()
        manager = self.manager(no_plot=True, running_log=log)
        for state in (True, False, True):
            self.change(manager, state)
        manager.teardown()
        manager.print_shutdown_narrative()
        final_state = log.final_details["final_state"]
        self.assertEqual(final_state["lid_close_count"], 2)
        self.assertEqual(final_state["lid_open_count"], 1)
        self.assertNotIn("lid_events", final_state)
        self.assertTrue(log.closed)
        self.assertEqual(self.output.getvalue().count("Lid Events Detected"), 1)
        self.assertIn("close=2/open=1", self.output.getvalue())

    def test_zero_counts_are_visible_and_missing_sensor_is_qualified(self):
        manager = self.manager(no_plot=True)
        manager.lid_capability_checked = True
        manager.lid_monitoring_available = False
        manager.teardown()
        manager.print_shutdown_narrative()
        self.assertIn("Lid Events Detected", self.output.getvalue())
        self.assertIn("close=0/open=0; lid telemetry unavailable", self.output.getvalue())

    def test_normal_lid_cycle_narrative_does_not_add_ignore_lid_counts(self):
        manager = self.manager(ignore_lid=False, no_plot=True)
        self.change(manager, True)
        self.change(manager, False)
        manager.teardown()
        manager.print_shutdown_narrative()
        self.assertNotIn("Lid Events Detected", self.output.getvalue())
        self.assertTrue(manager.goal_achieved)

    def test_only_ignore_lid_passes_events_to_chart_and_no_plot_skips_chart(self):
        for ignore_lid, no_plot in ((True, False), (False, False), (True, True)):
            with self.subTest(ignore_lid=ignore_lid, no_plot=no_plot):
                manager = self.manager(ignore_lid=ignore_lid, no_plot=no_plot)
                self.change(manager, True)
                with mock.patch.object(burnbag, "render_battery_depletion_chart", return_value="") as render:
                    manager.print_battery_plot()
                if no_plot:
                    render.assert_not_called()
                else:
                    self.assertEqual(render.call_args.kwargs["lid_events"], manager.lid_events if ignore_lid else ())
                self.assertEqual(manager.lid_close_count, 1)


if __name__ == "__main__":
    unittest.main()
