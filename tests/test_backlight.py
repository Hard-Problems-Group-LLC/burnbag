"""Backlight lifecycle tests using a fake logind session and sysfs tree."""

from __future__ import annotations

import contextlib
import io
import os
import signal
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import burnbag


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP = PROJECT_ROOT / ".local" / "tmp"


class FakeVariant:
    """Retain a D-Bus signature and value tuple for boundary assertions."""

    def __init__(self, signature: str, values: tuple[object, ...]) -> None:
        self.signature = signature
        self.values = values


class FakeGLib:
    """Provide the GLib APIs used by backlight scheduling and D-Bus calls."""

    Variant = FakeVariant
    scheduled: list[tuple[int, object]] = []
    removed: list[int] = []

    @classmethod
    def timeout_add(cls, milliseconds: int, callback: object) -> int:
        cls.scheduled.append((milliseconds, callback))
        return 71

    @classmethod
    def source_remove(cls, source_id: int) -> None:
        cls.removed.append(source_id)


class FakeDBusCallFlags:
    NONE = 0


class FakeDBusProxyFlags:
    NONE = 0


class FakeDBusProxyFactory:
    return_proxy: object = None
    calls: list[tuple[object, ...]] = []
    proxies: dict[tuple[str, str], object] = {}

    @classmethod
    def new_sync(cls, *arguments: object) -> object:
        cls.calls.append(arguments)
        object_path = arguments[4]
        interface_name = arguments[5]
        if isinstance(object_path, str) and isinstance(interface_name, str):
            selected = cls.proxies.get((object_path, interface_name))
            if selected is not None:
                return selected
        return cls.return_proxy


class FakeGio:
    """Expose only the call flag consumed by the owned D-Bus wrapper."""

    DBusCallFlags = FakeDBusCallFlags
    DBusProxyFlags = FakeDBusProxyFlags
    DBusProxy = FakeDBusProxyFactory


class FakeResult:
    def __init__(self, value: tuple[object, ...]) -> None:
        self.value = value

    def unpack(self) -> tuple[object, ...]:
        return self.value


class FakeProperty:
    def __init__(self, value: object) -> None:
        self.value = value

    def unpack(self) -> object:
        return self.value


class FakePropertyProxy:
    def __init__(self, properties: dict[str, object]) -> None:
        self.properties = properties

    def get_cached_property(self, name: str) -> FakeProperty | None:
        if name not in self.properties:
            return None
        return FakeProperty(self.properties[name])


class FakeManagerProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, FakeVariant]] = []
        self.responses: dict[str, FakeResult | Exception] = {
            "GetSessionByPID": FakeResult(
                ("/org/freedesktop/login1/session/_test",)
            ),
            "GetSession": FakeResult(("/org/freedesktop/login1/session/_test",)),
            "GetUser": FakeResult(("/org/freedesktop/login1/user/_test",)),
        }

    def call_sync(
        self,
        method: str,
        parameters: FakeVariant,
        _flags: int,
        _timeout: int,
        _cancellable: object,
    ) -> FakeResult:
        self.calls.append((method, parameters))
        response = self.responses[method]
        if isinstance(response, Exception):
            raise response
        return response


class FakeMainLoop:
    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


class FakeSessionProxy(FakePropertyProxy):
    """Apply SetBrightness requests to disposable sysfs-shaped files."""

    def __init__(
        self,
        root: Path,
        *,
        active: bool = True,
        remote: bool = False,
        uid: int | None = None,
    ) -> None:
        session_uid = os.geteuid() if uid is None else uid
        super().__init__(
            {
                "User": (session_uid, f"/org/freedesktop/login1/user/_{session_uid}"),
                "Active": active,
                "Remote": remote,
            }
        )
        self.root = root
        self.fail_zero_for: set[str] = set()
        self.fail_positive_for: set[str] = set()
        self.stale_actual_zero_for: set[str] = set()
        self.calls: list[tuple[str, int]] = []

    def call_sync(
        self,
        method: str,
        parameters: FakeVariant,
        _flags: int,
        _timeout: int,
        _cancellable: object,
    ) -> None:
        if method != "SetBrightness" or parameters.signature != "(ssu)":
            raise AssertionError(f"Unexpected D-Bus call: {method} {parameters.signature}")
        subsystem, name, brightness = parameters.values
        if subsystem != "backlight" or not isinstance(name, str):
            raise AssertionError(f"Unexpected backlight target: {parameters.values!r}")
        if not isinstance(brightness, int):
            raise AssertionError(f"Unexpected brightness value: {brightness!r}")

        self.calls.append((name, brightness))
        if brightness == 0 and name in self.fail_zero_for:
            raise RuntimeError("injected power-down failure")
        if brightness > 0 and name in self.fail_positive_for:
            raise RuntimeError("injected restoration failure")

        device_path = self.root / name
        (device_path / "brightness").write_text(f"{brightness}\n", encoding="ascii")
        if brightness != 0 or name not in self.stale_actual_zero_for:
            (device_path / "actual_brightness").write_text(
                f"{brightness}\n", encoding="ascii"
            )


class BacklightTests(unittest.TestCase):
    def setUp(self) -> None:
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.run_root = Path(
            tempfile.mkdtemp(prefix="burnbag-backlight-test.", dir=LOCAL_TMP)
        )
        self.sysfs_root = self.run_root / "backlight"
        self.sysfs_root.mkdir()

        self.original_glib = burnbag.GLib
        self.original_gio = burnbag.Gio
        self.original_sysfs_root = burnbag.BACKLIGHT_SYSFS_ROOT
        self.original_verify_attempts = burnbag.BACKLIGHT_VERIFY_ATTEMPTS
        self.original_verify_interval = burnbag.BACKLIGHT_VERIFY_INTERVAL_SECONDS
        burnbag.GLib = FakeGLib
        burnbag.Gio = FakeGio
        burnbag.BACKLIGHT_SYSFS_ROOT = self.sysfs_root
        burnbag.BACKLIGHT_VERIFY_ATTEMPTS = 2
        burnbag.BACKLIGHT_VERIFY_INTERVAL_SECONDS = 0
        FakeGLib.scheduled = []
        FakeGLib.removed = []
        FakeDBusProxyFactory.calls = []
        FakeDBusProxyFactory.return_proxy = None
        FakeDBusProxyFactory.proxies = {}

    def tearDown(self) -> None:
        burnbag.GLib = self.original_glib
        burnbag.Gio = self.original_gio
        burnbag.BACKLIGHT_SYSFS_ROOT = self.original_sysfs_root
        burnbag.BACKLIGHT_VERIFY_ATTEMPTS = self.original_verify_attempts
        burnbag.BACKLIGHT_VERIFY_INTERVAL_SECONDS = self.original_verify_interval
        shutil.rmtree(self.run_root)

    def add_device(
        self,
        name: str,
        brightness: int = 42,
        actual_brightness: int | None = None,
        maximum: int = 100,
    ) -> Path:
        device_path = self.sysfs_root / name
        device_path.mkdir()
        actual = brightness if actual_brightness is None else actual_brightness
        (device_path / "brightness").write_text(f"{brightness}\n", encoding="ascii")
        (device_path / "actual_brightness").write_text(
            f"{actual}\n", encoding="ascii"
        )
        (device_path / "max_brightness").write_text(
            f"{maximum}\n", encoding="ascii"
        )
        return device_path

    def make_manager(
        self, *, do_not_touch_backlight: bool = False
    ) -> tuple[burnbag.LidCloseManager, FakeSessionProxy]:
        manager = burnbag.LidCloseManager(
            mode="run-cool",
            suspend_after_minutes=None,
            no_inhibit_auto_suspend=False,
            ignore_lid=False,
            do_not_touch_backlight=do_not_touch_backlight,
            started_monotonic=time.monotonic(),
        )
        proxy = FakeSessionProxy(self.sysfs_root)
        manager.logind_session_proxy = proxy
        manager.mainloop = FakeMainLoop()
        return manager, proxy

    def test_delayed_power_down_and_teardown_restore_are_verified(self) -> None:
        device_path = self.add_device("panel0", brightness=42)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()

        with contextlib.redirect_stdout(io.StringIO()) as output:
            manager.schedule_backlight_power_down()
            self.assertEqual(len(FakeGLib.scheduled), 1)
            delay_ms, callback = FakeGLib.scheduled[0]
            self.assertGreater(delay_ms, 0)
            self.assertLessEqual(delay_ms, 3000)
            self.assertFalse(callback())
            manager.teardown()
            manager.teardown()

        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "42\n"
        )
        self.assertEqual(proxy.calls, [("panel0", 0), ("panel0", 42)])
        self.assertTrue(manager.backlight_powered_down)
        self.assertTrue(manager.backlight_restore_attempted)
        self.assertTrue(manager.backlight_restore_verified)
        self.assertEqual(manager.exit_code, 0)
        self.assertIn("turned off and verified", output.getvalue())
        self.assertIn("verified on", output.getvalue())

    def test_prepare_resolves_callers_logind_session_and_snapshots_devices(self) -> None:
        self.add_device("panel0", brightness=42)
        manager, session_proxy = self.make_manager()
        manager_proxy = FakeManagerProxy()
        manager.bus = object()
        manager.logind_proxy = manager_proxy
        FakeDBusProxyFactory.return_proxy = session_proxy

        manager.prepare_backlight_control()

        self.assertEqual(len(manager_proxy.calls), 1)
        method, parameters = manager_proxy.calls[0]
        self.assertEqual(method, "GetSessionByPID")
        self.assertEqual(parameters.signature, "(u)")
        self.assertEqual(len(manager.backlight_devices), 1)
        self.assertIs(manager.logind_session_proxy, session_proxy)
        self.assertEqual(manager.logind_session_source, "process PID")
        self.assertEqual(len(FakeDBusProxyFactory.calls), 1)
        self.assertEqual(
            FakeDBusProxyFactory.calls[0][5], burnbag.LOGIND_SESSION_IFACE
        )

    def test_prepare_falls_back_to_user_primary_display_when_pid_has_no_session(self) -> None:
        self.add_device("panel0", brightness=42)
        manager, session_proxy = self.make_manager()
        manager_proxy = FakeManagerProxy()
        manager_proxy.responses["GetSessionByPID"] = RuntimeError(
            "org.freedesktop.login1.NoSessionForPID"
        )
        manager.bus = object()
        manager.logind_proxy = manager_proxy

        user_path = "/org/freedesktop/login1/user/_test"
        display_path = "/org/freedesktop/login1/session/_display"
        manager_proxy.responses["GetUser"] = FakeResult((user_path,))
        FakeDBusProxyFactory.proxies = {
            (user_path, burnbag.LOGIND_USER_IFACE): FakePropertyProxy(
                {"Display": ("2", display_path)}
            ),
            (display_path, burnbag.LOGIND_SESSION_IFACE): session_proxy,
        }

        with mock.patch.dict(os.environ, {"XDG_SESSION_ID": ""}, clear=False):
            manager.prepare_backlight_control()

        self.assertEqual(
            [method for method, _parameters in manager_proxy.calls],
            ["GetSessionByPID", "GetUser"],
        )
        self.assertIs(manager.logind_session_proxy, session_proxy)
        self.assertEqual(manager.logind_session_path, display_path)
        self.assertEqual(manager.logind_session_source, "user primary display")

    def test_prepare_uses_inherited_session_id_before_user_display(self) -> None:
        self.add_device("panel0", brightness=42)
        manager, session_proxy = self.make_manager()
        manager_proxy = FakeManagerProxy()
        manager_proxy.responses["GetSessionByPID"] = RuntimeError("no PID session")
        inherited_path = "/org/freedesktop/login1/session/_inherited"
        manager_proxy.responses["GetSession"] = FakeResult((inherited_path,))
        manager.bus = object()
        manager.logind_proxy = manager_proxy
        FakeDBusProxyFactory.proxies = {
            (inherited_path, burnbag.LOGIND_SESSION_IFACE): session_proxy,
        }

        with mock.patch.dict(os.environ, {"XDG_SESSION_ID": "7"}, clear=False):
            manager.prepare_backlight_control()

        self.assertEqual(
            [method for method, _parameters in manager_proxy.calls],
            ["GetSessionByPID", "GetSession"],
        )
        self.assertEqual(manager.logind_session_source, "inherited XDG_SESSION_ID")

    def test_remote_pid_session_is_rejected_in_favor_of_local_display(self) -> None:
        self.add_device("panel0", brightness=42)
        manager, local_session_proxy = self.make_manager()
        manager_proxy = FakeManagerProxy()
        pid_path = "/org/freedesktop/login1/session/_remote"
        user_path = "/org/freedesktop/login1/user/_test"
        display_path = "/org/freedesktop/login1/session/_display"
        manager_proxy.responses["GetSessionByPID"] = FakeResult((pid_path,))
        manager_proxy.responses["GetUser"] = FakeResult((user_path,))
        manager.bus = object()
        manager.logind_proxy = manager_proxy
        FakeDBusProxyFactory.proxies = {
            (pid_path, burnbag.LOGIND_SESSION_IFACE): FakeSessionProxy(
                self.sysfs_root, remote=True
            ),
            (user_path, burnbag.LOGIND_USER_IFACE): FakePropertyProxy(
                {"Display": ("2", display_path)}
            ),
            (display_path, burnbag.LOGIND_SESSION_IFACE): local_session_proxy,
        }

        with mock.patch.dict(os.environ, {"XDG_SESSION_ID": ""}, clear=False):
            manager.prepare_backlight_control()

        self.assertEqual(manager.logind_session_path, display_path)
        self.assertEqual(manager.logind_session_source, "user primary display")

    def test_resolution_rejects_other_uid_and_summarizes_attempts(self) -> None:
        manager, _session_proxy = self.make_manager()
        manager_proxy = FakeManagerProxy()
        manager_proxy.responses["GetSessionByPID"] = RuntimeError("no PID session")
        user_path = "/org/freedesktop/login1/user/_test"
        display_path = "/org/freedesktop/login1/session/_other_user"
        manager_proxy.responses["GetUser"] = FakeResult((user_path,))
        manager.bus = object()
        manager.logind_proxy = manager_proxy
        FakeDBusProxyFactory.proxies = {
            (user_path, burnbag.LOGIND_USER_IFACE): FakePropertyProxy(
                {"Display": ("9", display_path)}
            ),
            (display_path, burnbag.LOGIND_SESSION_IFACE): FakeSessionProxy(
                self.sysfs_root, uid=os.geteuid() + 1
            ),
        }

        with mock.patch.dict(os.environ, {"XDG_SESSION_ID": ""}, clear=False):
            with self.assertRaisesRegex(
                RuntimeError,
                "Attempts: process PID: .*user primary display: .*not effective UID",
            ):
                manager._resolve_logind_session_proxy()

    def test_startup_zero_restores_to_visible_fallback(self) -> None:
        device_path = self.add_device("panel0", brightness=0, maximum=200)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()

        manager._on_backlight_power_down()
        manager.teardown()

        self.assertEqual(proxy.calls, [("panel0", 0), ("panel0", 20)])
        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "20\n"
        )
        self.assertTrue(manager.backlight_restore_verified)

    def test_opt_out_does_not_discover_schedule_or_mutate_backlight(self) -> None:
        device_path = self.add_device("panel0", brightness=42)
        manager, proxy = self.make_manager(do_not_touch_backlight=True)

        manager.schedule_backlight_power_down()
        manager.teardown()

        self.assertEqual(FakeGLib.scheduled, [])
        self.assertEqual(proxy.calls, [])
        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "42\n"
        )

    def test_partial_power_down_failure_restores_changed_devices_and_exits_nonzero(self) -> None:
        first_path = self.add_device("panel0", brightness=42)
        second_path = self.add_device("panel1", brightness=55)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()
        proxy.fail_zero_for.add("panel1")

        with contextlib.redirect_stderr(io.StringIO()):
            manager._on_backlight_power_down()

        self.assertEqual(
            (first_path / "actual_brightness").read_text(encoding="ascii"), "42\n"
        )
        self.assertEqual(
            (second_path / "actual_brightness").read_text(encoding="ascii"), "55\n"
        )
        self.assertEqual(
            proxy.calls,
            [("panel0", 0), ("panel1", 0), ("panel0", 42), ("panel1", 55)],
        )
        self.assertTrue(manager.mainloop.quit_called)
        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(manager.backlight_restore_verified)
        self.assertTrue(any("power-down failed" in item for item in manager.deviations))

    def test_stop_between_backlights_restores_first_without_mutating_second(self) -> None:
        self.add_device("panel0", brightness=42)
        self.add_device("panel1", brightness=55)
        for stop_kind in ("signal", "failure"):
            with self.subTest(stop_kind=stop_kind):
                manager, proxy = self.make_manager()
                manager.mainloop = None
                manager.backlight_devices = manager._discover_backlight_devices()
                original_set = manager._set_backlight_brightness

                def stop_after_first(device, brightness):
                    original_set(device, brightness)
                    if device.name == "panel0" and brightness == 0:
                        if stop_kind == "signal":
                            manager.request_signal_shutdown(signal.SIGINT)
                        else:
                            manager._record_failure("Diagnostic channel failed")

                with mock.patch.object(manager, "_set_backlight_brightness", side_effect=stop_after_first), \
                        contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(burnbag.ShutdownRequested):
                        manager._on_backlight_power_down()
                    manager.teardown()
                self.assertEqual(proxy.calls, [("panel0", 0), ("panel0", 42)])
                self.assertTrue(manager.backlight_restore_verified)
                self.assertFalse(any(device.changed for device in manager.backlight_devices))
                self.assertEqual(manager.exit_code, 0 if stop_kind == "signal" else 1)

    def test_failed_off_verification_restores_device_and_exits_nonzero(self) -> None:
        device_path = self.add_device("panel0", brightness=42)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()
        proxy.stale_actual_zero_for.add("panel0")

        with contextlib.redirect_stderr(io.StringIO()):
            manager._on_backlight_power_down()

        self.assertEqual(proxy.calls, [("panel0", 0), ("panel0", 42)])
        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "42\n"
        )
        self.assertTrue(manager.backlight_restore_verified)
        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(any("did not verify" in item for item in manager.deviations))

    def test_restoration_failure_is_reported_and_exits_nonzero(self) -> None:
        device_path = self.add_device("panel0", brightness=42)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()
        manager._on_backlight_power_down()
        proxy.fail_positive_for.add("panel0")

        with contextlib.redirect_stderr(io.StringIO()):
            manager.teardown()

        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "0\n"
        )
        self.assertTrue(manager.backlight_restore_attempted)
        self.assertFalse(manager.backlight_restore_verified)
        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(any("Failed to restore" in item for item in manager.deviations))

    def test_exit_before_delay_cancels_timer_without_mutation(self) -> None:
        device_path = self.add_device("panel0", brightness=42)
        manager, proxy = self.make_manager()
        manager.backlight_devices = manager._discover_backlight_devices()

        manager.schedule_backlight_power_down()
        manager.teardown()

        self.assertEqual(FakeGLib.removed, [71])
        self.assertEqual(proxy.calls, [])
        self.assertEqual(
            (device_path / "actual_brightness").read_text(encoding="ascii"), "42\n"
        )
        self.assertFalse(manager.backlight_restore_attempted)

    def test_narratives_report_default_opt_out_and_verified_final_state(self) -> None:
        default_manager, _ = self.make_manager()
        opt_out_manager, _ = self.make_manager(do_not_touch_backlight=True)

        with contextlib.redirect_stdout(io.StringIO()) as default_output:
            default_manager.print_startup_narrative()
            default_manager.backlight_restore_attempted = True
            default_manager.backlight_restore_verified = True
            default_manager.print_shutdown_narrative()
        with contextlib.redirect_stdout(io.StringIO()) as opt_out_output:
            opt_out_manager.print_startup_narrative()
            opt_out_manager.print_shutdown_narrative()

        self.assertIn("OFF after 3 seconds", default_output.getvalue())
        self.assertIn("On (restoration verified)", default_output.getvalue())
        self.assertIn(
            "UNTOUCHED (--do-not-touch-backlight active)", opt_out_output.getvalue()
        )
        self.assertIn("Untouched by explicit operator request", opt_out_output.getvalue())

    def test_fatal_error_is_reported_as_shutdown_deviation(self) -> None:
        manager, _proxy = self.make_manager(do_not_touch_backlight=True)

        with contextlib.redirect_stdout(io.StringIO()) as output:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    manager._fatal_error("injected setup failure")

        self.assertIn("Fatal error: injected setup failure", manager.deviations)
        self.assertNotIn("None (execution proceeded exactly", output.getvalue())


if __name__ == "__main__":
    unittest.main()
