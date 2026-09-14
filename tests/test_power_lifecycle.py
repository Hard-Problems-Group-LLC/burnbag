"""Power safety and capability regressions with stateful D-Bus service fakes."""

from __future__ import annotations

import contextlib
import io
import os
import signal
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


class PowerService:
    """Model actual state independently of accepted or failed Set replies."""

    def __init__(self, active="balanced", profiles=None):
        self.active = active
        self.profiles = profiles or ["power-saver", "balanced", "performance"]
        self.calls = []
        self.fail_reads = False
        self.fail_before_set = set()
        self.fail_after_set = set()
        self.ignore_sets = set()

    def call_sync(self, method, parameters, flags, timeout, cancellable):
        self.calls.append((method, parameters.value, timeout))
        if method == "Get":
            if self.fail_reads:
                raise RuntimeError("service read unavailable")
            if parameters.value[1] == "Profiles":
                return Variant("(v)", ([{"Profile": name} for name in self.profiles],))
            return Variant("(v)", (self.active,))
        target = parameters.value[2].value
        if target in self.fail_before_set:
            raise RuntimeError("Set was rejected")
        if target not in self.ignore_sets:
            self.active = target
        if target in self.fail_after_set:
            raise TimeoutError("Set reply lost after applying change")
        return Variant("()", ())

    @property
    def set_targets(self):
        return [parameters[2].value for method, parameters, _timeout in self.calls if method == "Set"]


class SleepService:
    def __init__(self, capability="yes", action_error=None):
        self.capability = capability
        self.action_error = action_error
        self.calls = []

    def call_sync(self, method, parameters, flags, timeout, cancellable):
        self.calls.append((method, timeout))
        if method.startswith("Can"):
            return Variant("(s)", (self.capability,))
        if self.action_error:
            raise self.action_error
        return Variant("()", ())


class UPowerService:
    def __init__(self, present=True, closed=False):
        self.properties = {"LidIsPresent": present, "LidIsClosed": closed}

    def call_sync(self, method, parameters, flags, timeout, cancellable):
        if method != "org.freedesktop.DBus.Properties.Get":
            raise RuntimeError("UnknownMethod")
        return Variant("(v)", (self.properties[parameters.value[1]],))


class PowerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.errors = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.errors))
        self.stack.enter_context(mock.patch.object(
            burnbag, "GLib", SimpleNamespace(Variant=Variant, source_remove=lambda _id: True)
        ))
        self.stack.enter_context(mock.patch.object(
            burnbag, "Gio", SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0))
        ))

    def manager(self, mode="run-cool", ignore_lid=False, minutes=None):
        return burnbag.LidCloseManager(
            mode=mode,
            suspend_after_minutes=minutes,
            no_inhibit_auto_suspend=False,
            ignore_lid=ignore_lid,
            do_not_touch_backlight=True,
            terminal_style=burnbag.TerminalStyle(False, False),
        )

    def test_normal_retains_verified_balanced_profile_after_teardown(self):
        manager = self.manager("normal")
        service = PowerService(active="power-saver")
        manager.power_proxy = service
        manager.execute_immediate_action()
        manager.teardown()

        self.assertEqual(service.active, "balanced")
        self.assertEqual(service.set_targets, ["balanced"])
        self.assertTrue(manager.power_profile_retained)
        self.assertTrue(manager.power_profile_change_verified)
        self.assertFalse(manager.power_profile_restore_attempted)
        self.assertTrue(manager.goal_achieved)

    def test_temporary_profile_is_restored_and_verified_once(self):
        manager = self.manager()
        service = PowerService()
        manager.power_proxy = service
        self.assertTrue(manager.save_and_set_power_profile("power-saver"))
        self.assertEqual(service.active, "power-saver")
        manager.teardown()
        manager.teardown()

        self.assertEqual(service.active, "balanced")
        self.assertEqual(service.set_targets, ["power-saver", "balanced"])
        self.assertTrue(manager.power_profile_restore_verified)
        self.assertEqual(manager.active_power_profile, "balanced")
        self.assertTrue(all(timeout == burnbag.DBUS_CALL_TIMEOUT_MILLISECONDS for _, _, timeout in service.calls))

    def test_unreadable_original_profile_prevents_mutation(self):
        manager = self.manager()
        service = PowerService(active="performance")
        service.fail_reads = True
        manager.power_proxy = service
        with self.assertRaises(SystemExit):
            manager.save_and_set_power_profile("power-saver")
        self.assertEqual(service.set_targets, [])
        self.assertIsNone(manager.original_power_profile)
        self.assertEqual(manager.exit_code, 1)

    def test_run_without_profile_request_can_continue_when_daemon_read_fails(self):
        manager = self.manager("run")
        service = PowerService()
        service.fail_reads = True
        manager.power_proxy = service
        self.assertFalse(manager.save_and_set_power_profile(None))
        self.assertEqual(service.set_targets, [])
        self.assertEqual(manager.exit_code, 0)

    def test_unavailable_requested_profile_fails_without_a_set(self):
        manager = self.manager("run-hot")
        service = PowerService(profiles=["power-saver", "balanced"])
        manager.power_proxy = service
        with self.assertRaises(SystemExit):
            manager.save_and_set_power_profile("performance")
        self.assertEqual(service.set_targets, [])
        self.assertEqual(manager.exit_code, 1)
        self.assertIn("advertised profiles: power-saver, balanced", self.errors.getvalue())

    def test_missing_profile_service_refuses_request_and_allows_plain_run(self):
        manager = self.manager()
        with self.assertRaises(SystemExit):
            manager.save_and_set_power_profile("power-saver")
        self.assertEqual(manager.exit_code, 1)
        manager = self.manager("run")
        self.assertTrue(manager.save_and_set_power_profile(None))
        self.assertEqual(manager.exit_code, 0)
        self.assertIn("leaving the profile untouched", self.errors.getvalue())

    def test_lost_set_reply_still_restores_snapshot(self):
        manager = self.manager()
        service = PowerService()
        service.fail_after_set.add("power-saver")
        manager.power_proxy = service
        with self.assertRaises(SystemExit):
            manager.save_and_set_power_profile("power-saver")
        self.assertEqual(service.set_targets, ["power-saver", "balanced"])
        self.assertEqual(service.active, "balanced")
        self.assertTrue(manager.power_profile_restore_verified)
        self.assertFalse(manager.power_profile_change_verified)
        self.assertEqual(manager.exit_code, 1)

    def test_failed_normal_change_rolls_back_instead_of_retaining_uncertain_state(self):
        manager = self.manager("normal")
        service = PowerService(active="power-saver")
        service.fail_after_set.add("balanced")
        manager.power_proxy = service
        with self.assertRaises(SystemExit):
            manager.execute_immediate_action()
        self.assertEqual(service.active, "power-saver")
        self.assertFalse(manager.power_profile_retained)
        self.assertTrue(manager.power_profile_restore_verified)
        self.assertFalse(manager.goal_achieved)

    def test_success_reply_without_expected_profile_is_not_success(self):
        manager = self.manager()
        service = PowerService()
        service.ignore_sets.add("power-saver")
        manager.power_proxy = service
        with self.assertRaises(SystemExit):
            manager.save_and_set_power_profile("power-saver")
        self.assertFalse(manager.power_profile_change_verified)
        self.assertEqual(manager.exit_code, 1)
        self.assertIn("verification read", self.errors.getvalue())

    def test_failed_restoration_sets_nonzero_and_unknown_state(self):
        manager = self.manager()
        service = PowerService()
        manager.power_proxy = service
        manager.save_and_set_power_profile("power-saver")
        service.fail_before_set.add("balanced")
        manager.goal_achieved = True
        manager.teardown()
        self.assertEqual(service.active, "power-saver")
        self.assertEqual(manager.exit_code, 1)
        self.assertFalse(manager.goal_achieved)
        self.assertTrue(manager.power_profile_restore_attempted)
        self.assertFalse(manager.power_profile_restore_verified)
        self.assertIsNone(manager.active_power_profile)

    def test_every_inhibitor_close_is_attempted_despite_close_and_warning_failures(self):
        manager = self.manager()
        first, second = os.pipe()
        manager.inhibitor_fds = [first, second]
        original_close = os.close
        attempted = []

        def close_then_error(fd):
            attempted.append(fd)
            original_close(fd)
            if fd == first:
                raise OSError("injected close error after release")

        with mock.patch.object(burnbag.os, "close", side_effect=close_then_error), \
                mock.patch.object(manager, "_warn", side_effect=OSError("stderr unavailable")):
            manager.release_inhibitor_fds()
        self.assertEqual(attempted, [first, second])
        self.assertEqual(manager.inhibitor_fds, [])
        self.assertTrue(manager.inhibitor_release_failed)
        self.assertEqual(manager.exit_code, 1)
        for fd in (first, second):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_lid_capability_is_required_except_for_untimed_ignore_lid(self):
        for ignore_lid, minutes, allowed in ((False, None, False), (True, 5, False), (True, None, True)):
            with self.subTest(ignore_lid=ignore_lid, minutes=minutes):
                manager = self.manager(ignore_lid=ignore_lid, minutes=minutes)
                manager.upower_proxy = UPowerService(present=False)
                if allowed:
                    manager.validate_lid_monitoring()
                    self.assertEqual(manager.exit_code, 0)
                    self.assertIn("await SIGINT/SIGTERM", self.errors.getvalue())
                else:
                    with self.assertRaises(SystemExit):
                        manager.validate_lid_monitoring()
                    self.assertEqual(manager.exit_code, 1)

    def test_nonboolean_initial_lid_state_fails_instead_of_becoming_closed(self):
        manager = self.manager()
        manager.upower_proxy = UPowerService(closed="false")
        with self.assertRaises(SystemExit):
            manager.check_initial_lid_state()
        self.assertFalse(manager.current_lid_closed_state)

    def test_invalidated_lid_property_is_reread_and_processed(self):
        manager = self.manager(ignore_lid=True)
        manager.upower_proxy = UPowerService(closed=True)
        manager._on_upower_properties_changed(
            manager.upower_proxy, Variant("a{sv}", {}), ["LidIsClosed"]
        )
        self.assertTrue(manager.current_lid_closed_state)
        self.assertTrue(manager.lid_was_closed_during_session)

    def test_unknown_sleep_capabilities_never_dispatch_sleep(self):
        for mode in ("suspend", "hibernate"):
            for capability in ("no", "na", "inhibited", "inhibitor-blocked", "garbage", None):
                with self.subTest(mode=mode, capability=capability):
                    manager = self.manager(mode)
                    service = SleepService(capability)
                    manager.logind_proxy = service
                    with self.assertRaises(SystemExit):
                        manager.execute_immediate_action()
                    self.assertEqual([method for method, _timeout in service.calls], ["Can" + mode.title()])
                    self.assertEqual(manager.exit_code, 1)
                    self.assertFalse(manager.goal_achieved)

    def test_immediate_sleep_allows_policy_challenge_and_bounds_action_timeout(self):
        manager = self.manager("suspend")
        service = SleepService("challenge")
        manager.logind_proxy = service
        manager.execute_immediate_action()
        self.assertEqual(service.calls, [
            ("CanSuspend", burnbag.DBUS_CALL_TIMEOUT_MILLISECONDS),
            ("Suspend", burnbag.POWER_ACTION_TIMEOUT_MILLISECONDS),
        ])
        self.assertTrue(manager.goal_achieved)

    def test_failed_suspend_timer_is_nonzero_and_quits_loop(self):
        manager = self.manager(minutes=1)
        manager.logind_proxy = SleepService(action_error=TimeoutError("request reply timeout"))
        manager.mainloop = mock.Mock()
        manager.suspend_timer_id = 17
        self.assertFalse(manager._on_suspend_timer_expired())
        manager.mainloop.quit.assert_called_once_with()
        self.assertIsNone(manager.suspend_timer_id)
        self.assertEqual(manager.exit_code, 1)
        self.assertFalse(manager.goal_achieved)
        self.assertIn("Timer-triggered suspend failed", manager.shutdown_reason)

    def test_supported_suspend_timer_marks_success_after_acceptance(self):
        manager = self.manager(minutes=1)
        manager.logind_proxy = SleepService()
        manager.mainloop = mock.Mock()
        self.assertFalse(manager._on_suspend_timer_expired())
        self.assertTrue(manager.goal_achieved)
        self.assertEqual(manager.exit_code, 0)

    def test_stop_during_profile_reads_prevents_later_set(self):
        for mode, target in (("run-cool", "power-saver"), ("normal", "balanced")):
            for boundary in ("ActiveProfile", "Profiles"):
                for stop_kind in ("signal", "failure"):
                    with self.subTest(mode=mode, boundary=boundary, stop_kind=stop_kind):
                        manager = self.manager(mode)
                        service = PowerService(active="performance")
                        manager.power_proxy = service
                        original_call = service.call_sync

                        def stop_after_read(method, parameters, *arguments):
                            result = original_call(method, parameters, *arguments)
                            if method == "Get" and parameters.value[1] == boundary:
                                if stop_kind == "signal":
                                    manager.request_signal_shutdown(signal.SIGINT)
                                else:
                                    manager._record_failure("Diagnostic channel failed")
                            return result

                        with mock.patch.object(service, "call_sync", side_effect=stop_after_read):
                            with self.assertRaises(burnbag.ShutdownRequested):
                                if mode == "normal":
                                    manager.execute_immediate_action()
                                else:
                                    manager.save_and_set_power_profile(target)
                        manager.teardown()
                        self.assertEqual(service.set_targets, [])
                        self.assertFalse(manager.power_profile_retained)
                        self.assertEqual(manager.exit_code, 0 if stop_kind == "signal" else 1)

    def test_signal_during_normal_set_leaves_restoration_available(self):
        manager = self.manager("normal")
        service = PowerService(active="power-saver")
        manager.power_proxy = service
        original_call = service.call_sync

        def stop_after_set(method, *arguments):
            result = original_call(method, *arguments)
            if method == "Set":
                manager.request_signal_shutdown(signal.SIGINT)
            return result

        with mock.patch.object(service, "call_sync", side_effect=stop_after_set):
            with self.assertRaises(burnbag.ShutdownRequested):
                manager.execute_immediate_action()
        manager.teardown()
        self.assertEqual(service.set_targets, ["balanced", "power-saver"])
        self.assertFalse(manager.power_profile_retained)
        self.assertTrue(manager.power_profile_restore_verified)
        self.assertEqual(service.active, "power-saver")

    def test_stop_during_sleep_capability_read_prevents_action(self):
        for mode in ("suspend", "hibernate", "timer"):
            for stop_kind in ("signal", "failure"):
                with self.subTest(mode=mode, stop_kind=stop_kind):
                    manager = self.manager(mode if mode != "timer" else "run", minutes=1)
                    service = SleepService()
                    manager.logind_proxy = service
                    original_call = service.call_sync

                    def stop_after_capability(method, *arguments):
                        result = original_call(method, *arguments)
                        if stop_kind == "signal":
                            manager.request_signal_shutdown(signal.SIGINT)
                        else:
                            manager._record_failure("Diagnostic channel failed")
                        return result

                    with mock.patch.object(service, "call_sync", side_effect=stop_after_capability):
                        with self.assertRaises(burnbag.ShutdownRequested):
                            if mode == "timer":
                                manager._on_suspend_timer_expired()
                            else:
                                manager.execute_immediate_action()
                    self.assertEqual(len(service.calls), 1)
                    self.assertTrue(service.calls[0][0].startswith("Can"))
                    self.assertEqual(manager.exit_code, 0 if stop_kind == "signal" else 1)

    def test_failed_sleep_intent_output_prevents_action_dispatch(self):
        class BrokenOutput(io.StringIO):
            def write(self, text):
                raise OSError("output channel lost")

        manager = self.manager("suspend")
        service = SleepService()
        manager.logind_proxy = service
        with contextlib.redirect_stdout(BrokenOutput()):
            with self.assertRaises(burnbag.ShutdownRequested):
                manager.execute_immediate_action()
        self.assertEqual(service.calls, [("CanSuspend", burnbag.DBUS_CALL_TIMEOUT_MILLISECONDS)])
        self.assertTrue(manager.stop_requested)
        self.assertEqual(manager.exit_code, 1)

    def test_pending_stop_prevents_inhibitor_acquisition(self):
        manager = self.manager()
        manager.logind_proxy = mock.Mock()
        manager.request_signal_shutdown(signal.SIGINT)
        with self.assertRaises(burnbag.ShutdownRequested):
            manager.acquire_inhibitor_locks()
        manager.logind_proxy.call_with_unix_fd_list_sync.assert_not_called()
        self.assertEqual(manager.inhibitor_fds, [])

    def test_stop_recorded_with_profile_intent_prevents_set(self):
        manager = self.manager()
        service = PowerService()
        manager.power_proxy = service
        original_log = manager._log_only

        def stop_after_intent(event, *arguments):
            original_log(event, *arguments)
            if event == "power_profile_change_intent":
                manager._record_failure("Logging diagnostic requested shutdown")

        with mock.patch.object(manager, "_log_only", side_effect=stop_after_intent):
            with self.assertRaises(burnbag.ShutdownRequested):
                manager.save_and_set_power_profile("power-saver")
        self.assertEqual(service.set_targets, [])
        self.assertTrue(manager.stop_requested)
        self.assertEqual(manager.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
