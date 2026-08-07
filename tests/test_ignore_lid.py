"""Behavior tests for burnbag's lid-open termination policy."""

from __future__ import annotations

import contextlib
import io
import unittest

import burnbag


class FakeMainLoop:
    """Record whether a lifecycle handler requested event-loop shutdown."""

    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


class FakeGLib:
    """Provide the timer-removal boundary used by lid-open handling."""

    removed_sources: list[int] = []
    added_timeouts: list[int] = []

    @classmethod
    def source_remove(cls, source_id: int) -> None:
        cls.removed_sources.append(source_id)

    @classmethod
    def timeout_add_seconds(cls, delay_seconds: int, _callback: object) -> int:
        cls.added_timeouts.append(delay_seconds)
        return 23


class IgnoreLidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_glib = burnbag.GLib
        FakeGLib.removed_sources = []
        FakeGLib.added_timeouts = []
        burnbag.GLib = FakeGLib

    def tearDown(self) -> None:
        burnbag.GLib = self.original_glib

    @staticmethod
    def make_manager(ignore_lid: bool) -> burnbag.LidCloseManager:
        manager = burnbag.LidCloseManager(
            mode="run-cool",
            suspend_after_minutes=20,
            no_inhibit_auto_suspend=False,
            ignore_lid=ignore_lid,
        )
        manager.lid_was_closed_during_session = True
        manager.mainloop = FakeMainLoop()
        return manager

    def test_default_lid_open_ends_completed_lid_cycle(self) -> None:
        manager = self.make_manager(ignore_lid=False)

        manager._handle_lid_opened_event()

        self.assertTrue(manager.mainloop.quit_called)
        self.assertTrue(manager.goal_achieved)
        self.assertIn("Lid cycle completed", manager.shutdown_reason)

    def test_ignore_lid_cancels_timer_without_ending_session(self) -> None:
        manager = self.make_manager(ignore_lid=True)
        manager.suspend_timer_id = 17

        with contextlib.redirect_stdout(io.StringIO()) as output:
            manager._handle_lid_opened_event()
            manager._handle_lid_closed_event()

        self.assertEqual(FakeGLib.removed_sources, [17])
        self.assertEqual(FakeGLib.added_timeouts, [20 * 60])
        self.assertEqual(manager.suspend_timer_id, 23)
        self.assertFalse(manager.mainloop.quit_called)
        self.assertFalse(manager.goal_achieved)
        self.assertEqual(manager.shutdown_reason, "Unknown / Undefined")
        self.assertIn("continuing after lid opening", output.getvalue())

    def test_startup_narrative_distinguishes_default_and_ignore_modes(self) -> None:
        expected_by_flag = {
            False: "ENABLED (default close/open cycle ends the session)",
            True: "DISABLED (--ignore-lid active)",
        }

        for ignore_lid, expected in expected_by_flag.items():
            with self.subTest(ignore_lid=ignore_lid):
                manager = self.make_manager(ignore_lid=ignore_lid)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    manager.print_startup_narrative()

                self.assertIn(expected, output.getvalue())


if __name__ == "__main__":
    unittest.main()
