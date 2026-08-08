#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
burnbag — Clamshell Mode & Power Profile Management Utility for Fedora / GNOME
Target Platform: Fedora 44 / Red Hat Enterprise Linux family (Python 3.9+)

This utility temporarily inhibits systemd-logind lid-switch and idle-suspend events,
manages power-profiles-daemon profiles, and monitors UPower lid state to allow a laptop
to continue running when the lid is shut (e.g., while inside a bag or docked).

It uses D-Bus inhibitor file descriptors so that all overrides are strictly ephemeral:
if this script terminates, crashes, or is killed, systemd automatically drops the locks
and restores normal safety defaults.

Copyright (C)2026 Hard Problems Group, LLC.
Released under the MIT License.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, TextIO, Tuple
import uuid

Gio: Any = None
GLib: Any = None


@dataclass(frozen=True)
class TerminalStyle:
    """Render optional ANSI styling without making color carry meaning."""

    stdout_color: bool
    stderr_color: bool

    RESET = "\033[0m"
    BOLD = "1"
    DIM_CYAN = "2;36"
    CYAN = "36"
    BLUE = "34"
    GREEN = "32"
    YELLOW = "33"
    RED = "31"
    MAGENTA = "35"

    @classmethod
    def detect(
        cls,
        no_color: bool = False,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
    ) -> "TerminalStyle":
        """Enable color only for capable TTY streams unless explicitly disabled."""
        selected_stdout = sys.stdout if stdout is None else stdout
        selected_stderr = sys.stderr if stderr is None else stderr
        environment_disables = (
            "NO_COLOR" in os.environ
            or os.environ.get("TERM", "").lower() == "dumb"
        )
        disabled = no_color or environment_disables

        def supports_color(stream: TextIO) -> bool:
            if disabled:
                return False
            try:
                return bool(stream.isatty())
            except (AttributeError, OSError, ValueError):
                return False

        return cls(
            stdout_color=supports_color(selected_stdout),
            stderr_color=supports_color(selected_stderr),
        )

    def enabled_for(self, stream: TextIO) -> bool:
        """Return the precomputed capability for the selected standard stream."""
        return self.stderr_color if stream is sys.stderr else self.stdout_color

    def paint(
        self, text: str, code: str, stream: Optional[TextIO] = None
    ) -> str:
        """Wrap text in ANSI SGR sequences when styling is active."""
        selected_stream = sys.stdout if stream is None else stream
        if not self.enabled_for(selected_stream):
            return text
        return f"\033[{code}m{text}{self.RESET}"

    def status_prefix(
        self, label: str, stream: Optional[TextIO] = None
    ) -> str:
        """Color a textual status label while retaining the accessible label."""
        selected_stream = sys.stdout if stream is None else stream
        color_by_label = {
            "INFO": self.BLUE,
            "OK": self.GREEN,
            "EVENT": self.MAGENTA,
            "WARNING": self.YELLOW,
            "ERROR": self.RED,
            "FATAL ERROR": f"{self.BOLD};{self.RED}",
        }
        return self.paint(
            f"[{label}]", color_by_label.get(label, self.CYAN), selected_stream
        )

    def write_status(
        self,
        label: str,
        message: str,
        stream: Optional[TextIO] = None,
        timestamp: Optional[str] = None,
        leading_newline: bool = False,
    ) -> None:
        """Write one labeled status message with optional timestamp and spacing."""
        selected_stream = sys.stdout if stream is None else stream
        pieces = []
        if timestamp:
            pieces.append(
                self.paint(f"[{timestamp}]", self.DIM_CYAN, selected_stream)
            )
        pieces.append(self.status_prefix(label, selected_stream))
        prefix = " ".join(pieces)
        newline = "\n" if leading_newline else ""
        selected_stream.write(f"{newline}{prefix} {message}\n")

    def format_help(self, text: str, stream: TextIO) -> str:
        """Add hierarchy to argparse text without changing its plain content."""
        if not self.enabled_for(stream):
            return text

        rendered: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in {"positional arguments:", "options:", "optional arguments:"}:
                rendered.append(self.paint(line, f"{self.BOLD};{self.CYAN}", stream))
                continue
            if stripped.startswith("usage:"):
                prefix, remainder = line.split("usage:", 1)
                rendered.append(
                    f"{prefix}{self.paint('usage:', f'{self.BOLD};{self.CYAN}', stream)}"
                    f"{remainder}"
                )
                continue
            invocation = re.match(r"^(\s{2})(\S.*?)(\s{2,}.*)$", line)
            if invocation:
                rendered.append(
                    f"{invocation.group(1)}"
                    f"{self.paint(invocation.group(2), self.GREEN, stream)}"
                    f"{invocation.group(3)}"
                )
                continue
            if line.startswith("  ") and (
                stripped.startswith("-") or stripped.startswith("{")
            ):
                # Argparse wraps descriptions for long invocations onto the
                # next line. Style those action-only lines consistently with
                # shorter options that retain an inline description.
                rendered.append(self.paint(line, self.GREEN, stream))
                continue
            if line.startswith("  burnbag "):
                rendered.append(self.paint(line, self.GREEN, stream))
                continue
            rendered.append(line)
        return "\n".join(rendered) + ("\n" if text.endswith("\n") else "")


class StyledArgumentParser(argparse.ArgumentParser):
    """Argparse parser that styles only at the final output boundary."""

    def __init__(self, *args: Any, terminal_style: TerminalStyle, **kwargs: Any):
        self.terminal_style = terminal_style
        # Python 3.14 added its own automatic argparse color. Disable that
        # independent layer so burnbag's TTY, environment, and --no-color
        # policy remains authoritative and consistent across Python versions.
        if sys.version_info >= (3, 14):
            kwargs["color"] = False
        super().__init__(*args, **kwargs)

    def print_usage(self, file: Optional[TextIO] = None) -> None:
        stream = file or sys.stdout
        self._print_message(
            self.terminal_style.format_help(self.format_usage(), stream), stream
        )

    def print_help(self, file: Optional[TextIO] = None) -> None:
        stream = file or sys.stdout
        self._print_message(
            self.terminal_style.format_help(self.format_help(), stream), stream
        )

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        rendered = (
            f"{self.prog}: {self.terminal_style.status_prefix('ERROR', sys.stderr)} "
            f"{message}\n"
        )
        self.exit(2, rendered)


class RunningLogError(RuntimeError):
    """Raised when the mandatory running log cannot meet its durability contract."""


class RunningLog:
    """Append synchronized, process-safe JSON Lines records for one session.

    This class deliberately uses unbuffered descriptor operations. A record is
    successful only after the complete line has been written and ``fsync`` has
    returned while an exclusive advisory lock is still held.
    """

    SCHEMA_VERSION = 1
    MAX_RECORD_BYTES = 65_536
    DEFAULT_RELATIVE_PATH = Path("burnbag") / "burnbag.log"
    LEVELS = {"INFO", "OK", "EVENT", "WARNING", "ERROR", "FATAL"}
    EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

    def __init__(
        self,
        path: Path,
        file_descriptor: int,
        mode: str,
        started_monotonic: float,
        partial_tail_detected: bool = False,
    ) -> None:
        self.path = path
        self.file_descriptor: Optional[int] = file_descriptor
        self.mode = mode
        self.started_monotonic = started_monotonic
        self.partial_tail_detected = partial_tail_detected
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        self.session_started = False
        self.session_ended = False
        self.failed_reason: Optional[str] = None

    @classmethod
    def select_path(cls, explicit_path: Optional[str]) -> Tuple[Path, bool]:
        """Resolve an explicit path or the invoking environment's XDG state path.

        The boolean result identifies the managed default directory. Burnbag
        intentionally does not consult the passwd database when HOME is
        isolated or redirected: the invoking environment remains the selected
        user-state boundary.
        """
        if explicit_path is not None:
            selected = Path(explicit_path)
            if not selected.is_absolute():
                raise RunningLogError(
                    f"--log-file requires an absolute path: {explicit_path}"
                )
            managed_directory = False
        else:
            xdg_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
            if xdg_state_home:
                state_root = Path(xdg_state_home)
                if not state_root.is_absolute():
                    raise RunningLogError(
                        "XDG_STATE_HOME must be absolute to select the running log"
                    )
            else:
                home = os.environ.get("HOME", "").strip()
                if not home:
                    raise RunningLogError(
                        "HOME or XDG_STATE_HOME is required for the running log"
                    )
                home_path = Path(home)
                if not home_path.is_absolute():
                    raise RunningLogError(
                        "HOME must be absolute to select the running log"
                    )
                state_root = home_path / ".local" / "state"
            selected = state_root / cls.DEFAULT_RELATIVE_PATH
            managed_directory = True

        # Normalize dot components without resolving symlinks; the secure open
        # and ownership checks below remain authoritative for filesystem state.
        normalized = Path(os.path.abspath(os.fspath(selected)))
        if not normalized.name:
            raise RunningLogError("Running-log path must name a file")
        return normalized, managed_directory

    @classmethod
    def open(
        cls,
        path: Path,
        mode: str,
        started_monotonic: float,
        managed_directory: bool = False,
    ) -> "RunningLog":
        """Securely open and synchronize the append target before host mutation."""
        if not path.is_absolute():
            raise RunningLogError(f"Running-log path must be absolute: {path}")

        parent = path.parent
        try:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            parent_state = parent.lstat()
        except OSError as exc:
            raise RunningLogError(
                f"Could not prepare running-log directory {parent}: {exc}"
            ) from exc

        if stat.S_ISLNK(parent_state.st_mode) or not stat.S_ISDIR(
            parent_state.st_mode
        ):
            raise RunningLogError(
                f"Running-log parent must be a real directory: {parent}"
            )
        if parent_state.st_uid != os.geteuid():
            raise RunningLogError(
                f"Running-log directory {parent} is owned by UID "
                f"{parent_state.st_uid}, not effective UID {os.geteuid()}"
            )
        if parent_state.st_mode & 0o022:
            raise RunningLogError(
                f"Running-log directory must not be group/world writable: {parent}"
            )

        try:
            if managed_directory:
                os.chmod(parent, 0o700)
            flags = os.O_APPEND | os.O_CREAT | os.O_RDWR
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RunningLogError(f"Could not open running log {path}: {exc}") from exc

        try:
            file_state = os.fstat(file_descriptor)
            if not stat.S_ISREG(file_state.st_mode):
                raise RunningLogError(f"Running log must be a regular file: {path}")
            if file_state.st_uid != os.geteuid():
                raise RunningLogError(
                    f"Running log {path} is owned by UID {file_state.st_uid}, "
                    f"not effective UID {os.geteuid()}"
                )
            if file_state.st_nlink != 1:
                raise RunningLogError(
                    f"Running log must have exactly one hard link: {path}"
                )

            os.fchmod(file_descriptor, 0o600)

            # An interrupted low-level write can leave a non-newline tail.
            # Preserve that forensic fragment, but terminate it before this
            # session appends JSON so a later record is never concatenated to
            # bytes from the interrupted process.
            partial_tail_detected = False
            fcntl.flock(file_descriptor, fcntl.LOCK_EX)
            try:
                current_size = os.fstat(file_descriptor).st_size
                if current_size > 0:
                    final_byte = os.pread(file_descriptor, 1, current_size - 1)
                    if final_byte != b"\n":
                        os.write(file_descriptor, b"\n")
                        partial_tail_detected = True
                os.fsync(file_descriptor)
            finally:
                fcntl.flock(file_descriptor, fcntl.LOCK_UN)

            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_descriptor = os.open(parent, directory_flags)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except (OSError, RunningLogError) as exc:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
            if isinstance(exc, RunningLogError):
                raise
            raise RunningLogError(
                f"Could not validate or synchronize running log {path}: {exc}"
            ) from exc

        return cls(
            path,
            file_descriptor,
            mode,
            started_monotonic,
            partial_tail_detected=partial_tail_detected,
        )

    @staticmethod
    def _utc_timestamp() -> str:
        """Return a stable UTC timestamp without depending on the local timezone."""
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def append(
        self,
        event: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append, lock, and synchronize one complete record.

        Sequence advances only after ``fsync`` succeeds. Once one record fails,
        later writes are refused so callers cannot mistake an incomplete log
        for a healthy durability boundary.
        """
        if self.file_descriptor is None:
            raise RunningLogError("Running log is already closed")
        if self.failed_reason is not None:
            raise RunningLogError(self.failed_reason)

        if not self.EVENT_PATTERN.fullmatch(event):
            self.failed_reason = f"Invalid running-log event code: {event!r}"
            raise RunningLogError(self.failed_reason)
        if level not in self.LEVELS:
            self.failed_reason = f"Invalid running-log level: {level!r}"
            raise RunningLogError(self.failed_reason)
        if not isinstance(message, str) or not message:
            self.failed_reason = "Running-log message must be a non-empty string"
            raise RunningLogError(self.failed_reason)
        if details is not None and not isinstance(details, dict):
            self.failed_reason = "Running-log details must be a JSON object"
            raise RunningLogError(self.failed_reason)

        next_sequence = self.sequence + 1
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "timestamp": self._utc_timestamp(),
            "elapsed_seconds": round(
                max(0.0, time.monotonic() - self.started_monotonic), 6
            ),
            "session_id": self.session_id,
            "sequence": next_sequence,
            "pid": os.getpid(),
            "uid": os.geteuid(),
            "mode": self.mode,
            "event": event,
            "level": level,
            "message": message,
            "details": {} if details is None else details,
        }
        try:
            payload = (
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError) as exc:
            self.failed_reason = f"Could not serialize running-log record: {exc}"
            raise RunningLogError(self.failed_reason) from exc

        if len(payload) > self.MAX_RECORD_BYTES:
            self.failed_reason = (
                f"Running-log record is {len(payload)} bytes; maximum is "
                f"{self.MAX_RECORD_BYTES}"
            )
            raise RunningLogError(self.failed_reason)

        descriptor = self.file_descriptor
        locked = False
        failure: Optional[OSError] = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("running-log write made no forward progress")
                written += count
            os.fsync(descriptor)
        except OSError as exc:
            failure = exc
        finally:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError as exc:
                    if failure is None:
                        failure = exc

        if failure is not None:
            self.failed_reason = (
                f"Could not append and synchronize running log {self.path}: "
                f"{failure}"
            )
            raise RunningLogError(self.failed_reason) from failure

        self.sequence = next_sequence

    def start_session(self, configuration: Dict[str, Any]) -> None:
        """Write the mandatory first record before runtime initialization."""
        if self.session_started:
            raise RunningLogError("Running-log session has already started")
        start_details = dict(configuration)
        start_details["partial_tail_detected"] = self.partial_tail_detected
        self.append(
            "session_start",
            "INFO",
            "Burnbag operational session started.",
            start_details,
        )
        self.session_started = True

    def end_session(
        self,
        exit_code: int,
        goal_achieved: bool,
        shutdown_reason: str,
        deviations: Sequence[str],
        final_state: Dict[str, Any],
    ) -> None:
        """Write the final handled record after teardown; idempotent on success."""
        if self.session_ended:
            return
        self.append(
            "session_end",
            "OK" if exit_code == 0 and goal_achieved else "ERROR",
            "Burnbag operational session ended after handled teardown.",
            {
                "exit_code": exit_code,
                "goal_achieved": goal_achieved,
                "shutdown_reason": shutdown_reason,
                "deviations": list(deviations),
                "final_state": final_state,
            },
        )
        self.session_ended = True

    def close(self) -> None:
        """Close the owned descriptor; repeated calls are harmless."""
        if self.file_descriptor is None:
            return
        descriptor = self.file_descriptor
        self.file_descriptor = None
        try:
            os.close(descriptor)
        except OSError as exc:
            self.failed_reason = f"Could not close running log {self.path}: {exc}"
            raise RunningLogError(self.failed_reason) from exc


def load_pygobject(
    terminal_style: TerminalStyle, running_log: Optional[RunningLog] = None
) -> None:
    """Load the system D-Bus bindings after dependency-free CLI parsing."""
    global Gio, GLib

    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio as imported_gio, GLib as imported_glib
    except (ImportError, ValueError) as exc:
        message = (
            "PyGObject is unavailable to the active Python interpreter.\n"
            f"Active interpreter: {sys.executable}\n"
            "burnbag uses the Fedora/RHEL system package 'python3-gobject'.\n"
            "Install or verify it with:\n"
            "    ./scripts/install_prerequisites.sh\n"
            "or:\n"
            "    sudo dnf install python3-gobject\n"
            "The PyPI package named 'gobject' is unrelated and does not provide 'gi'.\n"
            f"Underlying exception details: {exc}"
        )
        if running_log is not None and running_log.failed_reason is None:
            try:
                running_log.append("fatal_error", "FATAL", message)
            except RunningLogError as log_exc:
                terminal_style.write_status(
                    "FATAL ERROR",
                    f"Running log failed while recording prerequisite failure: {log_exc}",
                    sys.stderr,
                )
        terminal_style.write_status("FATAL ERROR", message, sys.stderr)
        sys.exit(1)

    Gio = imported_gio
    GLib = imported_glib

# ==============================================================================
# CONSTANTS & D-BUS IDENTIFIERS
# ==============================================================================

# D-Bus Names, Paths, and Interfaces used across Fedora/GNOME
LOGIND_BUS_NAME = "org.freedesktop.login1"
LOGIND_OBJECT_PATH = "/org/freedesktop/login1"
LOGIND_MANAGER_IFACE = "org.freedesktop.login1.Manager"
LOGIND_SESSION_IFACE = "org.freedesktop.login1.Session"
LOGIND_USER_IFACE = "org.freedesktop.login1.User"

POWER_BUS_NAME = "net.hadess.PowerProfiles"
POWER_OBJECT_PATH = "/net/hadess/PowerProfiles"
POWER_IFACE = "net.hadess.PowerProfiles"

UPOWER_BUS_NAME = "org.freedesktop.UPower"
UPOWER_OBJECT_PATH = "/org/freedesktop/UPower"
UPOWER_IFACE = "org.freedesktop.UPower"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

BACKLIGHT_SYSFS_ROOT = Path("/sys/class/backlight")
BACKLIGHT_OFF_DELAY_SECONDS = 3.0
BACKLIGHT_VERIFY_ATTEMPTS = 10
BACKLIGHT_VERIFY_INTERVAL_SECONDS = 0.05

# Mapping from our CLI profile modes to net.hadess.PowerProfiles profile strings
PROFILE_MAP: Dict[str, str] = {
    "run-cool": "power-saver",
    "run-balanced": "balanced",
    "run-hot": "performance",
}


@dataclass
class BacklightDeviceState:
    """Snapshot and teardown state for one kernel screen-backlight device."""

    name: str
    brightness_path: Path
    verification_path: Path
    original_brightness: int
    original_actual_brightness: int
    maximum_brightness: int
    changed: bool = False

    @property
    def restore_brightness(self) -> int:
        """Return a visible restoration target even if startup brightness was zero."""
        if self.original_brightness > 0:
            return self.original_brightness
        return max(1, self.maximum_brightness // 10)


# ==============================================================================
# CORE CONTROLLER CLASS
# ==============================================================================

class LidCloseManager:
    """
    Manages the lifecycle of D-Bus inhibitor locks, power profile states,
    UPower lid monitoring, and narrative console reporting for burnbag.
    """

    def __init__(
        self,
        mode: str,
        suspend_after_minutes: Optional[int],
        no_inhibit_auto_suspend: bool,
        ignore_lid: bool,
        do_not_touch_backlight: bool = False,
        started_monotonic: Optional[float] = None,
        terminal_style: Optional[TerminalStyle] = None,
        running_log: Optional[RunningLog] = None,
    ):
        # Configuration parameters from CLI arguments
        self.mode: str = mode
        self.suspend_after_minutes: Optional[int] = suspend_after_minutes
        self.no_inhibit_auto_suspend: bool = no_inhibit_auto_suspend
        self.ignore_lid: bool = ignore_lid
        self.do_not_touch_backlight: bool = do_not_touch_backlight
        self.started_monotonic: float = (
            time.monotonic() if started_monotonic is None else started_monotonic
        )
        self.terminal_style = terminal_style or TerminalStyle.detect()
        self.running_log = running_log

        # State tracking variables for clean teardown and narrative reporting
        self.original_power_profile: Optional[str] = None
        self.active_power_profile: Optional[str] = None
        self.inhibitor_fds: List[int] = []  # Open file descriptors holding systemd locks
        self.lid_was_closed_during_session: bool = False
        self.current_lid_closed_state: bool = False
        self.suspend_timer_id: Optional[int] = None
        self.backlight_timer_id: Optional[int] = None
        self.backlight_devices: List[BacklightDeviceState] = []
        self.backlight_powered_down: bool = False
        self.backlight_restore_attempted: bool = False
        self.backlight_restore_verified: bool = False
        self.shutdown_reason: str = "Unknown / Undefined"
        self.goal_achieved: bool = False
        self.deviations: List[str] = []
        self.exit_code: int = 0
        self.teardown_complete: bool = False
        self.teardown_in_progress: bool = False
        self.shutdown_narrative_printed: bool = False
        self.running_log_finished: bool = False
        self.log_failure_reported: bool = False

        # D-Bus connection and proxy placeholders
        self.bus: Optional[Gio.DBusConnection] = None
        self.logind_proxy: Optional[Gio.DBusProxy] = None
        self.logind_session_proxy: Optional[Gio.DBusProxy] = None
        self.logind_session_path: Optional[str] = None
        self.logind_session_source: Optional[str] = None
        self.power_proxy: Optional[Gio.DBusProxy] = None
        self.upower_proxy: Optional[Gio.DBusProxy] = None
        self.mainloop: Optional[GLib.MainLoop] = None

    def _mark_running_log_failure(self, error: RunningLogError) -> None:
        """Mark a durability failure without routing the report back into the log."""
        message = f"Running-log durability failure: {error}"
        if message not in self.deviations:
            self.deviations.append(message)
        self.shutdown_reason = message
        self.goal_achieved = False
        self.exit_code = 1
        # Enter the recovery phase immediately. The first failed append still
        # raises to abort its caller before the next mutation, but restoration
        # helpers invoked while unwinding must not be interrupted by the now
        # unavailable log.
        self.teardown_in_progress = True

        # This path must not recurse through _fatal_error or another logging
        # helper: the running log is already known to be unavailable.
        if not self.log_failure_reported:
            self.log_failure_reported = True
            self.terminal_style.write_status(
                "FATAL ERROR",
                f"{message}. Ending the session and preserving teardown.",
                sys.stderr,
            )
        if self.mainloop:
            try:
                self.mainloop.quit()
            except Exception:
                # Teardown remains the authoritative recovery path even if an
                # event-loop implementation rejects a duplicate quit request.
                pass

    def _append_running_log(
        self,
        event: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Synchronize one record and fail closed unless teardown is underway."""
        if self.running_log is None:
            return
        if self.running_log.failed_reason is not None:
            if not self.teardown_in_progress:
                raise RunningLogError(self.running_log.failed_reason)
            return
        was_teardown_in_progress = self.teardown_in_progress
        try:
            self.running_log.append(event, level, message, details)
        except RunningLogError as exc:
            self._mark_running_log_failure(exc)
            # A log failure before teardown prevents the next host mutation.
            # During teardown, continuing restoration is more important than
            # raising from an unavailable diagnostic channel.
            if not was_teardown_in_progress:
                raise

    def _log_only(
        self,
        event: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a safety-relevant event that does not need console output."""
        self._append_running_log(event, level, message, details)

    def _info(
        self,
        message: str,
        event: str = "runtime_status",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write an informational runtime message."""
        self._append_running_log(event, "INFO", message, details)
        self.terminal_style.write_status("INFO", message)

    def _ok(
        self,
        message: str,
        event: str = "operation_succeeded",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a successful runtime outcome."""
        self._append_running_log(event, "OK", message, details)
        self.terminal_style.write_status("OK", message)

    def _event(
        self,
        message: str,
        event: str = "lifecycle_event",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write an asynchronous lifecycle event with visual separation."""
        self._append_running_log(event, "EVENT", message, details)
        self.terminal_style.write_status("EVENT", message, leading_newline=True)

    def finish_running_log(self) -> None:
        """Synchronize the handled session end after teardown and close the log."""
        if self.running_log is None or self.running_log_finished:
            return
        self.running_log_finished = True

        if self.running_log.failed_reason is None:
            try:
                self.running_log.end_session(
                    exit_code=self.exit_code,
                    goal_achieved=self.goal_achieved,
                    shutdown_reason=self.shutdown_reason,
                    deviations=self.deviations,
                    final_state={
                        "teardown_complete": self.teardown_complete,
                        "inhibitor_count": len(self.inhibitor_fds),
                        "backlight_powered_down": self.backlight_powered_down,
                        "backlight_restore_attempted": self.backlight_restore_attempted,
                        "backlight_restore_verified": self.backlight_restore_verified,
                        "active_power_profile": self.active_power_profile,
                        "original_power_profile": self.original_power_profile,
                        "lid_was_closed": self.lid_was_closed_during_session,
                    },
                )
            except RunningLogError as exc:
                self._mark_running_log_failure(exc)

        try:
            self.running_log.close()
        except RunningLogError as exc:
            self._mark_running_log_failure(exc)

    def _narrative_rule(self) -> None:
        """Draw a subdued narrative boundary."""
        rule = "═" * 80 if self.terminal_style.stdout_color else "=" * 80
        print(self.terminal_style.paint(rule, TerminalStyle.DIM_CYAN))

    def _narrative_title(self, title: str) -> None:
        """Draw a centered narrative title."""
        print(
            self.terminal_style.paint(
                f"{title:^80}", f"{TerminalStyle.BOLD};{TerminalStyle.CYAN}"
            )
        )

    def _narrative_field(
        self, label: str, value: str, value_color: Optional[str] = None
    ) -> None:
        """Render one aligned labeled field with an optional value emphasis."""
        prefix = self.terminal_style.paint(
            f"  • {label:<24}: ", f"{TerminalStyle.BOLD};{TerminalStyle.CYAN}"
        )
        rendered_value = (
            self.terminal_style.paint(value, value_color)
            if value_color
            else value
        )
        print(f"{prefix}{rendered_value}")

    def _narrative_subfield(
        self, label: str, value: str, value_color: Optional[str] = None
    ) -> None:
        """Render one indented final-state field."""
        prefix = self.terminal_style.paint(
            f"        - {label:<18}: ", TerminalStyle.CYAN
        )
        rendered_value = (
            self.terminal_style.paint(value, value_color)
            if value_color
            else value
        )
        print(f"{prefix}{rendered_value}")

    # --------------------------------------------------------------------------
    # D-BUS INITIALIZATION & CONNECTION HELPERS
    # --------------------------------------------------------------------------

    def connect_dbus(self) -> None:
        """
        Establishes synchronous connection to the system D-Bus and initializes
        proxies for systemd-logind, power-profiles-daemon, and UPower.
        """
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except Exception as exc:
            self._fatal_error(f"Failed to connect to System D-Bus: {exc}")
        self._log_only(
            "dbus_system_connected",
            "OK",
            "Connected to the system D-Bus.",
        )

        # Initialize logind proxy (required for all modes)
        try:
            self.logind_proxy = Gio.DBusProxy.new_sync(
                self.bus,
                Gio.DBusProxyFlags.NONE,
                None,
                LOGIND_BUS_NAME,
                LOGIND_OBJECT_PATH,
                LOGIND_MANAGER_IFACE,
                None,
            )
        except Exception as exc:
            self._fatal_error(f"Failed to create D-Bus proxy for systemd-logind: {exc}")
        self._log_only(
            "dbus_service_ready",
            "OK",
            "systemd-logind manager proxy is ready.",
            {"service": LOGIND_BUS_NAME},
        )

        # Initialize UPower proxy (required to read lid state)
        try:
            self.upower_proxy = Gio.DBusProxy.new_sync(
                self.bus,
                Gio.DBusProxyFlags.NONE,
                None,
                UPOWER_BUS_NAME,
                UPOWER_OBJECT_PATH,
                UPOWER_IFACE,
                None,
            )
        except Exception as exc:
            self._warn(f"Failed to create UPower proxy: {exc}. Lid-state monitoring may fail.")
        else:
            self._log_only(
                "dbus_service_ready",
                "OK",
                "UPower proxy is ready.",
                {"service": UPOWER_BUS_NAME},
            )

        # Initialize Power Profiles proxy (optional; only needed if daemon is active)
        try:
            self.power_proxy = Gio.DBusProxy.new_sync(
                self.bus,
                Gio.DBusProxyFlags.NONE,
                None,
                POWER_BUS_NAME,
                POWER_OBJECT_PATH,
                DBUS_PROPERTIES_IFACE,
                None,
            )
        except Exception as exc:
            self._warn(
                f"power-profiles-daemon proxy unreachable ({exc}). "
                "Power mode switching will be disabled."
            )
        else:
            self._log_only(
                "dbus_service_ready",
                "OK",
                "power-profiles-daemon proxy is ready.",
                {"service": POWER_BUS_NAME},
            )

    # --------------------------------------------------------------------------
    # SCREEN BACKLIGHT MANAGEMENT
    # --------------------------------------------------------------------------

    @staticmethod
    def _read_backlight_value(path: Path, description: str) -> int:
        """Read and validate a non-negative integer from a backlight sysfs file."""
        try:
            raw_value = path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise RuntimeError(f"Could not read {description} at {path}: {exc}") from exc

        try:
            value = int(raw_value)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid integer for {description} at {path}: {raw_value!r}"
            ) from exc
        if value < 0:
            raise RuntimeError(f"Negative {description} at {path}: {value}")
        return value

    def _discover_backlight_devices(self) -> List[BacklightDeviceState]:
        """Snapshot every kernel screen-backlight device before mutation."""
        try:
            device_paths = sorted(
                path for path in BACKLIGHT_SYSFS_ROOT.iterdir() if path.is_dir()
            )
        except OSError as exc:
            raise RuntimeError(
                f"Could not enumerate screen backlights under {BACKLIGHT_SYSFS_ROOT}: {exc}"
            ) from exc

        if not device_paths:
            raise RuntimeError(
                f"No screen-backlight devices were found under {BACKLIGHT_SYSFS_ROOT}"
            )

        devices: List[BacklightDeviceState] = []
        for device_path in device_paths:
            brightness_path = device_path / "brightness"
            actual_path = device_path / "actual_brightness"
            verification_path = actual_path if actual_path.is_file() else brightness_path
            maximum = self._read_backlight_value(
                device_path / "max_brightness", "maximum brightness"
            )
            requested = self._read_backlight_value(
                brightness_path, "requested brightness"
            )
            actual = self._read_backlight_value(
                verification_path, "actual brightness"
            )
            if maximum <= 0:
                raise RuntimeError(
                    f"Backlight {device_path.name!r} reports invalid maximum brightness {maximum}"
                )
            if requested > maximum or actual > maximum:
                raise RuntimeError(
                    f"Backlight {device_path.name!r} reports brightness outside 0..{maximum} "
                    f"(requested={requested}, actual={actual})"
                )
            devices.append(
                BacklightDeviceState(
                    name=device_path.name,
                    brightness_path=brightness_path,
                    verification_path=verification_path,
                    original_brightness=requested,
                    original_actual_brightness=actual,
                    maximum_brightness=maximum,
                )
            )
        return devices

    @staticmethod
    def _validate_dbus_object_path(value: Any, description: str) -> str:
        """Reject empty or root sentinel paths before proxy construction."""
        if not isinstance(value, str) or not value.startswith("/") or value == "/":
            raise RuntimeError(f"Invalid {description}: {value!r}")
        return value

    @staticmethod
    def _cached_proxy_property(proxy: Any, name: str, description: str) -> Any:
        """Read one synchronously cached property from a newly created proxy."""
        try:
            value = proxy.get_cached_property(name)
        except Exception as exc:
            raise RuntimeError(f"Could not read {description}: {exc}") from exc
        if value is None:
            raise RuntimeError(f"Required {description} is unavailable")
        try:
            return value.unpack()
        except Exception as exc:
            raise RuntimeError(f"Could not unpack {description}: {exc}") from exc

    def _new_logind_proxy(self, object_path: str, interface_name: str) -> Any:
        """Construct a synchronous logind proxy on the established system bus."""
        if not self.bus:
            raise RuntimeError("system D-Bus connection is not initialized")
        return Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            LOGIND_BUS_NAME,
            object_path,
            interface_name,
            None,
        )

    def _validated_session_proxy(self, session_path: str, source: str) -> Any:
        """Bind only an active, local session owned by the effective user."""
        session_path = self._validate_dbus_object_path(
            session_path, f"logind session path from {source}"
        )
        proxy = self._new_logind_proxy(session_path, LOGIND_SESSION_IFACE)
        user_value = self._cached_proxy_property(
            proxy, "User", f"session user for {source}"
        )
        if not isinstance(user_value, tuple) or len(user_value) != 2:
            raise RuntimeError(
                f"Invalid session user property for {source}: {user_value!r}"
            )
        session_uid = user_value[0]
        if not isinstance(session_uid, int) or session_uid != os.geteuid():
            raise RuntimeError(
                f"Session from {source} belongs to UID {session_uid!r}, "
                f"not effective UID {os.geteuid()}"
            )

        active = self._cached_proxy_property(
            proxy, "Active", f"session active state for {source}"
        )
        remote = self._cached_proxy_property(
            proxy, "Remote", f"session remote state for {source}"
        )
        if active is not True:
            raise RuntimeError(f"Session from {source} is not active")
        if remote is not False:
            raise RuntimeError(f"Session from {source} is remote")

        self.logind_session_path = session_path
        self.logind_session_source = source
        return proxy

    def _resolve_logind_session_proxy(self) -> Any:
        """Resolve a safe brightness session across common launcher scopes."""
        if not self.logind_proxy:
            raise RuntimeError("logind manager proxy is not initialized")

        failures: List[str] = []

        # Prefer the process-owned session. This is exact when burnbag was
        # launched directly from a login shell, but logind legitimately cannot
        # resolve PIDs owned by tmux servers or user-service scopes.
        try:
            result = self.logind_proxy.call_sync(
                "GetSessionByPID",
                GLib.Variant("(u)", (os.getpid(),)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            session_path = result.unpack()[0]
            return self._validated_session_proxy(session_path, "process PID")
        except Exception as exc:
            failures.append(f"process PID: {exc}")

        # A tmux server may retain the graphical session ID in its environment
        # even though its current PID is outside logind's process accounting.
        inherited_session_id = os.environ.get("XDG_SESSION_ID", "").strip()
        if inherited_session_id:
            try:
                result = self.logind_proxy.call_sync(
                    "GetSession",
                    GLib.Variant("(s)", (inherited_session_id,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                session_path = result.unpack()[0]
                return self._validated_session_proxy(
                    session_path, "inherited XDG_SESSION_ID"
                )
            except Exception as exc:
                failures.append(f"inherited XDG_SESSION_ID: {exc}")

        # User.Display is logind's authoritative primary graphical session and
        # is the safe fallback for user services and detached shell scopes.
        try:
            result = self.logind_proxy.call_sync(
                "GetUser",
                GLib.Variant("(u)", (os.geteuid(),)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            user_path = self._validate_dbus_object_path(
                result.unpack()[0], "logind user path"
            )
            user_proxy = self._new_logind_proxy(user_path, LOGIND_USER_IFACE)
            display_value = self._cached_proxy_property(
                user_proxy, "Display", "user primary display session"
            )
            if not isinstance(display_value, tuple) or len(display_value) != 2:
                raise RuntimeError(
                    f"Invalid user Display property: {display_value!r}"
                )
            session_path = display_value[1]
            return self._validated_session_proxy(
                session_path, "user primary display"
            )
        except Exception as exc:
            failures.append(f"user primary display: {exc}")

        failure_summary = "; ".join(failures)
        raise RuntimeError(
            "Could not resolve an active local logind display session for "
            f"effective UID {os.geteuid()}. Attempts: {failure_summary}"
        )

    def prepare_backlight_control(self) -> None:
        """Discover devices and bind the supported logind session control API."""
        if self.do_not_touch_backlight or not self.mode.startswith("run"):
            return
        if not self.logind_proxy or not self.bus:
            self._fatal_error(
                "Cannot prepare screen-backlight control: logind is not initialized."
            )

        try:
            devices = self._discover_backlight_devices()
            self.logind_session_proxy = self._resolve_logind_session_proxy()
            self.backlight_devices = devices
        except Exception as exc:
            self._fatal_error(f"Failed to prepare screen-backlight control: {exc}")

        device_summary = ", ".join(
            f"{device.name}={device.original_actual_brightness}/{device.maximum_brightness}"
            for device in self.backlight_devices
        )
        self._info(
            f"Screen-backlight state recorded: {device_summary}.",
            event="backlight_state_recorded",
            details={
                "devices": [
                    {
                        "name": device.name,
                        "requested_brightness": device.original_brightness,
                        "actual_brightness": device.original_actual_brightness,
                        "maximum_brightness": device.maximum_brightness,
                    }
                    for device in self.backlight_devices
                ]
            },
        )
        self._info(
            f"Screen-backlight control session: {self.logind_session_path} "
            f"({self.logind_session_source}).",
            event="backlight_control_session_resolved",
            details={
                "session_path": self.logind_session_path,
                "source": self.logind_session_source,
            },
        )

    def _set_backlight_brightness(
        self, device: BacklightDeviceState, brightness: int
    ) -> None:
        """Set one device through the caller's logind session boundary."""
        if not self.logind_session_proxy:
            raise RuntimeError("logind session proxy is not initialized")
        if brightness < 0 or brightness > device.maximum_brightness:
            raise RuntimeError(
                f"Brightness {brightness} for {device.name!r} is outside "
                f"0..{device.maximum_brightness}"
            )
        try:
            self.logind_session_proxy.call_sync(
                "SetBrightness",
                GLib.Variant("(ssu)", ("backlight", device.name, brightness)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception as exc:
            raise RuntimeError(
                f"logind could not set backlight {device.name!r} to {brightness}: {exc}"
            ) from exc

    def _verify_backlight(
        self,
        device: BacklightDeviceState,
        expected_on: bool,
    ) -> int:
        """Poll actual brightness briefly and require the requested on/off state."""
        last_value: Optional[int] = None
        for attempt in range(BACKLIGHT_VERIFY_ATTEMPTS):
            last_value = self._read_backlight_value(
                device.verification_path, "actual brightness"
            )
            if (last_value > 0) == expected_on:
                return last_value
            if attempt + 1 < BACKLIGHT_VERIFY_ATTEMPTS:
                time.sleep(BACKLIGHT_VERIFY_INTERVAL_SECONDS)
        expected = "nonzero (on)" if expected_on else "zero (off)"
        raise RuntimeError(
            f"Backlight {device.name!r} did not verify as {expected}; "
            f"last observed value was {last_value}"
        )

    def _on_backlight_power_down(self) -> bool:
        """GLib timer callback: turn off and verify all discovered backlights."""
        self.backlight_timer_id = None
        try:
            for device in self.backlight_devices:
                self._log_only(
                    "backlight_power_down_intent",
                    "INFO",
                    f"Requesting brightness zero for backlight {device.name!r}.",
                    {"device": device.name, "target_brightness": 0},
                )
                # Mark the device before crossing D-Bus: a transport failure can
                # be ambiguous about whether logind applied the mutation.
                device.changed = True
                self._set_backlight_brightness(device, 0)
                observed = self._verify_backlight(device, expected_on=False)
                self._log_only(
                    "backlight_power_down_verified",
                    "OK",
                    f"Backlight {device.name!r} verified off.",
                    {"device": device.name, "observed_brightness": observed},
                )
            self.backlight_powered_down = True
            self._ok(
                "Screen backlight turned off and verified after three seconds.",
                event="backlight_power_down_complete",
            )
        except RunningLogError:
            # _append_running_log already marked the session failed and asked
            # the loop to stop. Compensate any brightness already changed.
            self.restore_backlights()
            if self.mainloop:
                self.mainloop.quit()
        except Exception as exc:
            message = f"Screen-backlight power-down failed: {exc}"
            self._warn(message)
            self.deviations.append(message)
            self.shutdown_reason = message
            self.goal_achieved = False
            self.exit_code = 1
            self.restore_backlights()
            if self.mainloop:
                self.mainloop.quit()
        return False

    def schedule_backlight_power_down(self) -> None:
        """Schedule default power-down relative to process start, not setup end."""
        if self.do_not_touch_backlight or not self.mode.startswith("run"):
            return
        if not self.backlight_devices or not self.logind_session_proxy:
            self._fatal_error("Screen-backlight control was not prepared before scheduling.")

        remaining_seconds = max(
            0.0,
            self.started_monotonic + BACKLIGHT_OFF_DELAY_SECONDS - time.monotonic(),
        )
        delay_milliseconds = max(1, int(round(remaining_seconds * 1000)))
        try:
            self.backlight_timer_id = GLib.timeout_add(
                delay_milliseconds, self._on_backlight_power_down
            )
        except Exception as exc:
            self._fatal_error(f"Failed to schedule screen-backlight power-down: {exc}")
        self._info(
            "Screen backlight will turn off three seconds after process startup.",
            event="backlight_power_down_scheduled",
            details={"delay_milliseconds": delay_milliseconds},
        )

    def restore_backlights(self) -> bool:
        """Restore every touched device and verify it is on before returning."""
        changed_devices = [device for device in self.backlight_devices if device.changed]
        if not changed_devices:
            return True

        self.backlight_restore_attempted = True
        restoration_ok = True
        for device in changed_devices:
            try:
                target = device.restore_brightness
                self._log_only(
                    "backlight_restore_intent",
                    "INFO",
                    f"Restoring backlight {device.name!r} to {target}.",
                    {"device": device.name, "target_brightness": target},
                )
                self._set_backlight_brightness(device, target)
                observed = self._verify_backlight(device, expected_on=True)
                device.changed = False
                self._ok(
                    f"Restored backlight {device.name!r} to {target}; "
                    f"verified on at {observed}.",
                    event="backlight_restore_verified",
                    details={
                        "device": device.name,
                        "target_brightness": target,
                        "observed_brightness": observed,
                    },
                )
            except Exception as exc:
                restoration_ok = False
                message = f"Failed to restore and verify backlight {device.name!r}: {exc}"
                self._warn(message)
                self.deviations.append(message)

        self.backlight_restore_verified = restoration_ok
        if not restoration_ok:
            self.exit_code = 1
        return restoration_ok

    def teardown(self) -> None:
        """Run the idempotent handled-exit cleanup path in safety-first order."""
        if self.teardown_complete:
            return
        # From this point forward a failed log write may change the final exit
        # status, but it must never interrupt restoration of persistent state.
        self.teardown_in_progress = True
        self._log_only(
            "teardown_started",
            "INFO",
            "Handled teardown started in safety-first order.",
        )
        if self.backlight_timer_id is not None:
            try:
                GLib.source_remove(self.backlight_timer_id)
            except Exception as exc:
                self._warn(f"Could not cancel screen-backlight timer: {exc}")
                self.deviations.append(f"Could not cancel screen-backlight timer: {exc}")
                self.exit_code = 1
            self.backlight_timer_id = None
        if self.suspend_timer_id is not None:
            try:
                GLib.source_remove(self.suspend_timer_id)
            except Exception as exc:
                self._warn(f"Could not cancel suspend timer: {exc}")
                self.deviations.append(f"Could not cancel suspend timer: {exc}")
                self.exit_code = 1
            self.suspend_timer_id = None

        # Brightness persists independently of this process, so restore and
        # verify it before releasing automatically scoped inhibitors.
        self.restore_backlights()
        self.release_inhibitor_fds()
        self.restore_power_profile()
        self.teardown_complete = True
        self._log_only(
            "teardown_completed",
            "OK" if self.exit_code == 0 else "ERROR",
            "Handled teardown completed.",
            {"exit_code": self.exit_code},
        )

    # --------------------------------------------------------------------------
    # POWER PROFILE MANAGEMENT
    # --------------------------------------------------------------------------

    def save_and_set_power_profile(self, target_profile: Optional[str]) -> None:
        """
        Queries and records the current system power profile, then applies the
        target profile if requested.
        """
        if not self.power_proxy:
            if target_profile:
                self.deviations.append(
                    f"Requested power profile '{target_profile}' could not be applied "
                    "(power-profiles-daemon unreachable)."
                )
            return

        try:
            # Query current profile via DBus.Properties.Get
            result = self.power_proxy.call_sync(
                "Get",
                GLib.Variant("(ss)", (POWER_IFACE, "ActiveProfile")),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self.original_power_profile = result.unpack()[0]
            self.active_power_profile = self.original_power_profile
        except Exception as exc:
            self._warn(f"Could not read current power profile: {exc}")
            self.original_power_profile = "balanced"  # Safe default assumption
        else:
            self._log_only(
                "power_profile_recorded",
                "OK",
                f"Recorded original power profile {self.original_power_profile!r}.",
                {"profile": self.original_power_profile},
            )

        # Apply new target profile if specified and different from current
        if target_profile and target_profile != self.original_power_profile:
            self._log_only(
                "power_profile_change_intent",
                "INFO",
                f"Requesting power profile {target_profile!r}.",
                {
                    "original_profile": self.original_power_profile,
                    "target_profile": target_profile,
                },
            )
            try:
                self.power_proxy.call_sync(
                    "Set",
                    GLib.Variant("(ssv)", (POWER_IFACE, "ActiveProfile", GLib.Variant("s", target_profile))),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                self.active_power_profile = target_profile
            except Exception as exc:
                err_msg = (
                    f"Failed to set power profile to '{target_profile}' ({exc}). "
                    "Remaining on default profile."
                )
                self._warn(err_msg)
                self.deviations.append(err_msg)
            else:
                self._info(
                    f"Power profile successfully switched to: '{target_profile}'.",
                    event="power_profile_changed",
                    details={"active_profile": target_profile},
                )

    def restore_power_profile(self) -> None:
        """
        Restores the power profile that was active before burnbag started.
        """
        if not self.power_proxy or not self.original_power_profile:
            return

        if self.active_power_profile != self.original_power_profile:
            self._log_only(
                "power_profile_restore_intent",
                "INFO",
                f"Restoring original power profile {self.original_power_profile!r}.",
                {
                    "active_profile": self.active_power_profile,
                    "target_profile": self.original_power_profile,
                },
            )
            try:
                self.power_proxy.call_sync(
                    "Set",
                    GLib.Variant(
                        "(ssv)",
                        (POWER_IFACE, "ActiveProfile", GLib.Variant("s", self.original_power_profile)),
                    ),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                self.active_power_profile = self.original_power_profile
                self._info(
                    "Restored system power profile to original state: "
                    f"'{self.original_power_profile}'.",
                    event="power_profile_restored",
                    details={"active_profile": self.original_power_profile},
                )
            except Exception as exc:
                self._warn(f"Failed to restore original power profile '{self.original_power_profile}': {exc}")

    # --------------------------------------------------------------------------
    # INHIBITOR LOCK MANAGEMENT
    # --------------------------------------------------------------------------

    def acquire_inhibitor_locks(self) -> None:
        """
        Acquires systemd-logind inhibitor locks for lid-switch (and idle if requested).
        Each call returns a Unix file descriptor; holding the FD open maintains the lock.
        """
        if not self.logind_proxy:
            self._fatal_error("Cannot acquire inhibitor locks: logind proxy is not initialized.")

        # Determine which events to inhibit
        locks_to_acquire = ["handle-lid-switch"]
        if not self.no_inhibit_auto_suspend:
            locks_to_acquire.append("idle")
        else:
            self._info(
                "--no-inhibit-auto-suspend specified: normal OS background "
                "idle timers remain active."
            )

        what_string = ":".join(locks_to_acquire)
        who_string = "burnbag (User Utility)"
        why_string = f"User requested burnbag mode '{self.mode}' to continue operation with closed lid."
        mode_string = "block"  # 'block' prevents sleep; 'delay' only postpones it

        self._log_only(
            "inhibitor_acquire_intent",
            "INFO",
            f"Requesting systemd-logind inhibitor for [{what_string}].",
            {"what": what_string, "inhibit_mode": mode_string},
        )
        try:
            # call_with_unix_fd_list_sync allows receiving file descriptors over D-Bus
            res, out_fd_list = self.logind_proxy.call_with_unix_fd_list_sync(
                "Inhibit",
                GLib.Variant("(ssss)", (what_string, who_string, why_string, mode_string)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                None,
            )
            # Unpack the returned handle index and retrieve the OS file descriptor
            fd_index = res.unpack()[0]
            os_fd = out_fd_list.get(fd_index)
            self.inhibitor_fds.append(os_fd)
        except Exception as exc:
            self._fatal_error(
                f"Failed to acquire systemd-logind inhibitor lock for [{what_string}]: {exc}"
            )
        else:
            self._info(
                "Successfully acquired systemd-logind inhibitor lock for: "
                f"[{what_string}].",
                event="inhibitor_acquired",
                details={"what": what_string, "file_descriptor": os_fd},
            )

    def release_inhibitor_fds(self) -> None:
        """
        Closes all open file descriptors for inhibitor locks, signaling systemd-logind
        to immediately drop our sleep/lid prohibitions.
        """
        for fd in self.inhibitor_fds:
            try:
                self._log_only(
                    "inhibitor_release_intent",
                    "INFO",
                    f"Closing inhibitor file descriptor {fd}.",
                    {"file_descriptor": fd},
                )
                os.close(fd)
                self._info(
                    f"Released D-Bus inhibitor lock (closed FD {fd}).",
                    event="inhibitor_released",
                    details={"file_descriptor": fd},
                )
            except OSError as exc:
                self._warn(f"Error closing inhibitor file descriptor {fd}: {exc}")
        self.inhibitor_fds.clear()

    # --------------------------------------------------------------------------
    # LID STATE & SIGNAL MONITORING
    # --------------------------------------------------------------------------

    def check_initial_lid_state(self) -> None:
        """
        Queries UPower for the current 'LidIsClosed' boolean state on startup.
        """
        if not self.upower_proxy:
            return
        try:
            result = self.upower_proxy.call_sync(
                "Get",
                GLib.Variant("(ss)", (UPOWER_IFACE, "LidIsClosed")),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self.current_lid_closed_state = result.unpack()[0]
            state_str = "CLOSED" if self.current_lid_closed_state else "OPEN"
            self._info(
                f"Initial hardware lid state detected as: {state_str}.",
                event="lid_initial_state",
                details={"closed": self.current_lid_closed_state},
            )
            if self.current_lid_closed_state:
                self.lid_was_closed_during_session = True
                self._handle_lid_closed_event()
        except RunningLogError:
            raise
        except Exception as exc:
            self._warn(
                f"Could not read initial 'LidIsClosed' property from UPower ({exc}). "
                "Will rely on D-Bus property change signals."
            )

    def setup_upower_signal_listener(self) -> None:
        """
        Subscribes to UPower 'PropertiesChanged' signals to detect physical lid events.
        """
        if not self.upower_proxy:
            return
        self.upower_proxy.connect("g-properties-changed", self._on_upower_properties_changed)
        self._log_only(
            "lid_listener_ready",
            "OK",
            "Subscribed to UPower lid-state changes.",
        )

    def _on_upower_properties_changed(
        self,
        proxy: Gio.DBusProxy,
        changed_properties: GLib.Variant,
        invalidated_properties: List[str],
    ) -> None:
        """
        Callback triggered whenever UPower broadcasts property changes.
        """
        unpacked_changes = changed_properties.unpack()
        if "LidIsClosed" in unpacked_changes:
            new_state: bool = bool(unpacked_changes["LidIsClosed"])
            if new_state != self.current_lid_closed_state:
                self.current_lid_closed_state = new_state
                if new_state:
                    self._event(
                        "Lid closure detected.",
                        event="lid_closed",
                        details={"closed": True},
                    )
                    self.lid_was_closed_during_session = True
                    self._handle_lid_closed_event()
                else:
                    self._event(
                        "Lid opening detected.",
                        event="lid_opened",
                        details={"closed": False},
                    )
                    self._handle_lid_opened_event()

    def _handle_lid_closed_event(self) -> None:
        """
        Executed when the laptop lid is closed. Starts the optional suspend timer.
        """
        if self.suspend_after_minutes is not None and self.suspend_after_minutes > 0:
            delay_seconds = self.suspend_after_minutes * 60
            self._info(
                "Starting suspend countdown timer: machine will unconditionally "
                f"suspend in {self.suspend_after_minutes} minute(s).",
                event="suspend_timer_start_intent",
                details={"minutes": self.suspend_after_minutes},
            )
            # Cancel any previously running timer to prevent duplicates
            if self.suspend_timer_id is not None:
                GLib.source_remove(self.suspend_timer_id)
            self.suspend_timer_id = GLib.timeout_add_seconds(
                delay_seconds, self._on_suspend_timer_expired
            )
            self._log_only(
                "suspend_timer_started",
                "OK",
                "Suspend countdown timer started.",
                {
                    "minutes": self.suspend_after_minutes,
                    "source_id": self.suspend_timer_id,
                },
            )

    def _handle_lid_opened_event(self) -> None:
        """
        Cancel any active safety countdown when the lid opens. By default, a
        completed close/open cycle also ends the session; --ignore-lid keeps
        the event loop alive for later lid cycles.
        """
        # Cancel any active suspend timer since the user opened the lid
        if self.suspend_timer_id is not None:
            GLib.source_remove(self.suspend_timer_id)
            self.suspend_timer_id = None
            self._info(
                "Suspend countdown timer cancelled because lid was reopened.",
                event="suspend_timer_cancelled",
            )

        # --ignore-lid changes only lid-open termination. Lid monitoring and
        # timer cancellation remain active so subsequent closures can start a
        # fresh safety countdown.
        if self.ignore_lid:
            self._info("--ignore-lid active: continuing after lid opening.")
            return

        # If we observed a full Close -> Open cycle, our job is done
        if self.lid_was_closed_during_session:
            self.shutdown_reason = "Lid cycle completed (lid was closed and subsequently reopened)"
            self.goal_achieved = True
            self._log_only(
                "lid_cycle_completed",
                "OK",
                self.shutdown_reason,
            )
            if self.mainloop:
                self.mainloop.quit()

    def _on_suspend_timer_expired(self) -> bool:
        """
        Callback triggered when `--suspend-after-minutes` reaches zero.
        Forces an immediate OS suspend and terminates the script loop.
        """
        self._event(
            f"Suspend timer ({self.suspend_after_minutes} min) expired.",
            event="suspend_timer_expired",
            details={"minutes": self.suspend_after_minutes},
        )
        self.suspend_timer_id = None
        self.shutdown_reason = f"Timeout expired after {self.suspend_after_minutes} minutes of lid closure"
        self.goal_achieved = True

        # Synchronize intent before crossing the suspend mutation boundary.
        self._info(
            "Sending D-Bus Suspend command to systemd-logind...",
            event="suspend_request_intent",
            details={"source": "lid_close_timer"},
        )
        try:
            self.logind_proxy.call_sync(
                "Suspend",
                GLib.Variant("(b)", (True,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception as exc:
            self._warn(f"D-Bus Suspend command failed: {exc}")
            self.deviations.append(f"Failed to execute unconditional suspend ({exc}).")
        else:
            self._log_only(
                "suspend_request_sent",
                "OK",
                "systemd-logind accepted the timer-triggered suspend request.",
                {"source": "lid_close_timer"},
            )

        # Exit main loop after initiating sleep
        if self.mainloop:
            self.mainloop.quit()
        return False  # Returning False removes the timeout source from GLib

    # --------------------------------------------------------------------------
    # IMMEDIATE ACTION MODES: suspend, hibernate, normal
    # --------------------------------------------------------------------------

    def execute_immediate_action(self) -> None:
        """
        Handles non-persistent modes ('suspend', 'hibernate', 'normal') and exits.
        """
        if self.mode == "normal":
            # Set profile back to balanced and ensure no locks are held
            self._info(
                "Applying '--normal' defaults: switching power mode to 'balanced'..."
            )
            self.save_and_set_power_profile("balanced")
            self.goal_achieved = True
            self.shutdown_reason = "Normal system defaults explicitly requested and applied"
            return

        if self.mode == "suspend":
            self._info(
                "Mode 'suspend' selected. Initiating immediate system suspend...",
                event="suspend_request_intent",
                details={"source": "immediate_mode"},
            )
            try:
                self.logind_proxy.call_sync(
                    "Suspend",
                    GLib.Variant("(b)", (True,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                self.goal_achieved = True
                self.shutdown_reason = "Immediate system suspend triggered"
            except Exception as exc:
                self._fatal_error(f"Failed to trigger system suspend via D-Bus: {exc}")
            else:
                self._log_only(
                    "suspend_request_sent",
                    "OK",
                    "systemd-logind accepted the immediate suspend request.",
                    {"source": "immediate_mode"},
                )
            return

        if self.mode == "hibernate":
            self._info(
                "Mode 'hibernate' selected. Verifying system hibernation capability...",
                event="hibernate_capability_query_intent",
            )
            try:
                # Check CanHibernate before attempting, as default Fedora 44 uses zram (no swap disk)
                res = self.logind_proxy.call_sync(
                    "CanHibernate",
                    None,
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                can_hibernate_str = res.unpack()[0]
            except Exception as exc:
                self._fatal_error(f"Failed to query system hibernation capabilities: {exc}")
            self._log_only(
                "hibernate_capability_recorded",
                "OK",
                f"systemd-logind reported CanHibernate={can_hibernate_str!r}.",
                {"capability": can_hibernate_str},
            )

            if can_hibernate_str in ("no", "na"):
                self.deviations.append("System reported hibernation is unsupported ('no'/'na').")
                self._fatal_error(
                    "Hibernation is not supported on this system.\n"
                    "        Note: Fedora uses zram by default, which does not support suspend-to-disk.\n"
                    "        A dedicated disk swap partition or swapfile must be configured."
                )

            self._info(
                f"Hibernation capability confirmed ('{can_hibernate_str}'). "
                "Initiating hibernate...",
                event="hibernate_request_intent",
            )
            try:
                self.logind_proxy.call_sync(
                    "Hibernate",
                    GLib.Variant("(b)", (True,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                self.goal_achieved = True
                self.shutdown_reason = "Immediate system hibernation triggered"
            except Exception as exc:
                self._fatal_error(f"Failed to execute hibernation command via D-Bus: {exc}")
            else:
                self._log_only(
                    "hibernate_request_sent",
                    "OK",
                    "systemd-logind accepted the hibernate request.",
                )
            return

    # --------------------------------------------------------------------------
    # NARRATIVE REPORTING (STARTUP & SHUTDOWN)
    # --------------------------------------------------------------------------

    def print_startup_narrative(self) -> None:
        """
        Prints a detailed, human-readable summary of the utility's intended actions
        and system modifications prior to execution.
        """
        self._narrative_rule()
        self._narrative_title("BURNBAG — STARTUP NARRATIVE")
        self._narrative_rule()
        self._narrative_field(
            "Operating Mode", self.mode.upper(), TerminalStyle.MAGENTA
        )
        if self.running_log is not None:
            self._narrative_field(
                "Running Log",
                f"{self.running_log.path} (append + fsync per record)",
            )

        # Profile explanation
        target_profile = PROFILE_MAP.get(self.mode, "Unchanged (keep active)")
        self._narrative_field("Target Power Profile", target_profile)

        # Inhibitor locks explanation
        if self.mode.startswith("run"):
            lid_inhibit_str = "YES (Lid switch sleep blocked)"
            idle_inhibit_str = (
                "NO (OS background idle timers active)"
                if self.no_inhibit_auto_suspend
                else "YES (Background idle sleep blocked)"
            )
            self._narrative_field("Lid-Switch Inhibition", lid_inhibit_str)
            self._narrative_field("Idle Sleep Inhibition", idle_inhibit_str)
            lid_exit_str = (
                "DISABLED (--ignore-lid active)"
                if self.ignore_lid
                else "ENABLED (default close/open cycle ends the session)"
            )
            self._narrative_field("Lid-Open Termination", lid_exit_str)

            if self.suspend_after_minutes:
                self._narrative_field(
                    "Unconditional Timeout",
                    f"{self.suspend_after_minutes} minute(s) after lid close",
                )
            else:
                self._narrative_field("Unconditional Timeout", "Disabled")
            backlight_str = (
                "UNTOUCHED (--do-not-touch-backlight active)"
                if self.do_not_touch_backlight
                else "OFF after 3 seconds; restored and verified ON at exit"
            )
            self._narrative_field("Screen Backlight", backlight_str)
        else:
            self._narrative_field(
                "Inhibition Locks", "None (immediate one-shot operation)"
            )
            self._narrative_field(
                "Screen Backlight", "Unchanged (operation exits before delay)"
            )

        if self.mode.startswith("run"):
            if self.ignore_lid:
                self._narrative_field(
                    "Expected Lifecycle",
                    "Persist across lid openings until a configured timer",
                )
                print("                              expires, SIGINT, or SIGTERM is received.")
            else:
                self._narrative_field(
                    "Expected Lifecycle",
                    "Persist until lid is closed and subsequently reopened,",
                )
                print("                              timer expires, SIGINT, or SIGTERM is received.")
        else:
            self._narrative_field(
                "Expected Lifecycle", "Execute requested action immediately and exit."
            )
        self._narrative_rule()
        print()

    def print_shutdown_narrative(self) -> None:
        """
        Prints a detailed final status report explaining achievement of goals,
        any operational deviations, and the final state of locks and power profiles.
        """
        if self.shutdown_narrative_printed:
            return
        # The final record must describe post-teardown state and be synchronized
        # before the human narrative claims that the handled lifecycle ended.
        self.finish_running_log()
        self.shutdown_narrative_printed = True

        print()
        self._narrative_rule()
        self._narrative_title("BURNBAG — SHUTDOWN & TEARDOWN")
        self._narrative_rule()
        status_str = "ACHIEVED SUCCESSFULLY" if self.goal_achieved else "TERMINATED / INCOMPLETE"
        status_color = TerminalStyle.GREEN if self.goal_achieved else TerminalStyle.RED
        self._narrative_field("Primary Mission Status", status_str, status_color)
        self._narrative_field("Final Reason for Exit", self.shutdown_reason)

        if not self.deviations:
            self._narrative_field(
                "Deviations Observed",
                "None (execution proceeded exactly as specified)",
                TerminalStyle.GREEN,
            )
        else:
            self._narrative_field(
                "Deviations Observed",
                f"{len(self.deviations)} deviation(s) recorded:",
                TerminalStyle.YELLOW,
            )
            for idx, dev in enumerate(self.deviations, 1):
                print(f"        {idx}. {dev}")

        self._narrative_field("Final System State", "")
        self._narrative_subfield(
            "D-Bus Inhibitors",
            "All inhibitor locks released (OS safety defaults restored)",
            TerminalStyle.GREEN,
        )

        if self.do_not_touch_backlight:
            backlight_status = "Untouched by explicit operator request"
        elif not self.mode.startswith("run"):
            backlight_status = "Unchanged (one-shot operation)"
        elif self.backlight_restore_attempted and self.backlight_restore_verified:
            backlight_status = "On (restoration verified)"
        elif self.backlight_restore_attempted:
            backlight_status = "RESTORATION FAILED"
        elif self.backlight_powered_down:
            backlight_status = "RESTORATION NOT ATTEMPTED"
        else:
            backlight_status = "Unchanged (three-second timer did not fire)"
        backlight_color = (
            TerminalStyle.RED
            if "FAILED" in backlight_status or "NOT ATTEMPTED" in backlight_status
            else TerminalStyle.GREEN
        )
        self._narrative_subfield(
            "Screen Backlight", backlight_status, backlight_color
        )

        # Explain active power profile status
        final_prof = self.original_power_profile if self.original_power_profile else "Unknown"
        if self.mode == "normal":
            final_prof = "balanced"
        self._narrative_subfield(
            "Power Profile", f"Restored to '{final_prof}'", TerminalStyle.GREEN
        )
        if self.running_log is not None:
            if self.running_log.failed_reason is None:
                running_log_status = f"Session synchronized to {self.running_log.path}"
                running_log_color = TerminalStyle.GREEN
            else:
                running_log_status = (
                    f"INCOMPLETE ({self.running_log.failed_reason})"
                )
                running_log_color = TerminalStyle.RED
            self._narrative_subfield(
                "Running Log", running_log_status, running_log_color
            )
        self._narrative_rule()

    # --------------------------------------------------------------------------
    # ERROR & WARNING LOGGING
    # --------------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        """Outputs a timestamped warning message to standard error."""
        timestamp = time.strftime("%H:%M:%S")
        try:
            self._append_running_log("warning", "WARNING", message)
        except RunningLogError:
            # Preserve the originating diagnostic even when its durable copy
            # failed; the running-log failure was already reported directly.
            self.terminal_style.write_status(
                "WARNING", message, sys.stderr, timestamp=timestamp
            )
            raise
        self.terminal_style.write_status(
            "WARNING", message, sys.stderr, timestamp=timestamp
        )

    def _fatal_error(self, message: str) -> None:
        """
        Records an error, executes clean teardown narrative, and terminates immediately.
        """
        timestamp = time.strftime("%H:%M:%S")
        self.shutdown_reason = f"Fatal Error: {message}"
        fatal_deviation = f"Fatal error: {message}"
        if fatal_deviation not in self.deviations:
            self.deviations.append(fatal_deviation)
        self.goal_achieved = False
        self.exit_code = 1
        try:
            self._append_running_log("fatal_error", "FATAL", message)
        except RunningLogError:
            self.terminal_style.write_status(
                "FATAL ERROR",
                message,
                sys.stderr,
                timestamp=timestamp,
                leading_newline=True,
            )
            raise
        self.terminal_style.write_status(
            "FATAL ERROR",
            message,
            sys.stderr,
            timestamp=timestamp,
            leading_newline=True,
        )
        self.teardown()
        self.print_shutdown_narrative()
        sys.exit(1)


# ==============================================================================
# MAIN ORCHESTRATOR FUNCTION
# ==============================================================================

def build_argument_parser(terminal_style: TerminalStyle) -> StyledArgumentParser:
    """Build the dependency-free CLI, including styled help and examples."""
    parser = StyledArgumentParser(
        prog="burnbag",
        description="Fedora 44 / GNOME Clamshell & Power Profile Control Utility ('burnbag')",
        epilog=(
            "Examples:\n"
            "  burnbag run-cool --suspend-after-minutes 20\n"
            "  burnbag run-cool --ignore-lid\n"
            "  burnbag run --do-not-touch-backlight\n"
            "  burnbag normal\n\n"
            "Color is automatic for interactive terminals. Use --no-color, "
            "NO_COLOR, or TERM=dumb for plain output. Operational sessions "
            "append and fsync a JSON Lines running log."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        terminal_style=terminal_style,
        allow_abbrev=False,
    )

    parser.add_argument(
        "mode",
        choices=["suspend", "hibernate", "run", "run-cool", "run-balanced", "run-hot", "normal"],
        help=(
            "Operational mode:\n"
            "  suspend       : Immediately suspend system when called.\n"
            "  hibernate     : Immediately hibernate system (requires disk swap).\n"
            "  run           : Inhibit lid-close suspend; maintain current power profile.\n"
            "  run-cool      : Inhibit lid-close suspend; switch to 'power-saver' profile.\n"
            "  run-balanced  : Inhibit lid-close suspend; switch to 'balanced' profile.\n"
            "  run-hot       : Inhibit lid-close suspend; switch to 'performance' profile.\n"
            "  normal        : Clear overrides and restore system defaults ('balanced' mode)."
        ),
    )

    parser.add_argument(
        "--suspend-after-minutes",
        type=int,
        default=None,
        metavar="MIN",
        help="Unconditionally suspend after MIN minutes of continuous lid closure.",
    )

    parser.add_argument(
        "--no-inhibit-auto-suspend",
        action="store_true",
        help="Allow OS background idle timers to suspend the system normally.",
    )

    parser.add_argument(
        "--ignore-lid",
        action="store_true",
        help=(
            "Keep a run mode active when the lid opens; lid opening still "
            "cancels its active suspend countdown."
        ),
    )

    parser.add_argument(
        "--do-not-touch-backlight",
        action="store_true",
        help=(
            "Do not turn the screen backlight off after three seconds or "
            "restore it during teardown."
        ),
    )

    parser.add_argument(
        "--log-file",
        metavar="FILE",
        help=(
            "Write the mandatory synchronized running log to absolute FILE "
            "instead of the XDG state default."
        ),
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in all runtime, help, usage, and error output.",
    )
    return parser


def print_no_argument_guide(
    parser: StyledArgumentParser, terminal_style: TerminalStyle
) -> None:
    """Print a compact quick-start guide when no operational mode is supplied."""
    stream = sys.stderr
    terminal_style.write_status("ERROR", "An operational mode is required.", stream)
    parser.print_usage(stream)
    stream.write("\n")
    stream.write(
        terminal_style.paint(
            "Quick start", f"{TerminalStyle.BOLD};{TerminalStyle.CYAN}", stream
        )
        + "\n"
    )
    for description, command in (
        ("Cool closed-lid run", "burnbag run-cool"),
        ("20-minute safety fuse", "burnbag run-cool --suspend-after-minutes 20"),
        ("Leave backlight alone", "burnbag run --do-not-touch-backlight"),
    ):
        rendered_command = terminal_style.paint(command, TerminalStyle.GREEN, stream)
        stream.write(f"  {description:<24} {rendered_command}\n")
    stream.write(
        "\n"
        + terminal_style.paint("More help:", TerminalStyle.CYAN, stream)
        + " burnbag --help\n"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Parses arguments, initializes D-Bus monitoring, installs POSIX signal handlers,
    and runs the appropriate mode lifecycle.
    """
    process_started_at = time.monotonic()
    arguments = list(sys.argv[1:] if argv is None else argv)
    terminal_style = TerminalStyle.detect(no_color="--no-color" in arguments)
    parser = build_argument_parser(terminal_style)
    if not arguments:
        print_no_argument_guide(parser, terminal_style)
        return 2

    args = parser.parse_args(arguments)

    # Validate logical constraints on CLI options
    if args.suspend_after_minutes is not None and args.suspend_after_minutes <= 0:
        terminal_style.write_status(
            "ERROR",
            "--suspend-after-minutes must be a positive integer.",
            sys.stderr,
        )
        return 1

    running_log: Optional[RunningLog] = None
    try:
        log_path, managed_log_directory = RunningLog.select_path(args.log_file)
        running_log = RunningLog.open(
            path=log_path,
            mode=args.mode,
            started_monotonic=process_started_at,
            managed_directory=managed_log_directory,
        )
        running_log.start_session(
            {
                "suspend_after_minutes": args.suspend_after_minutes,
                "inhibit_auto_suspend": not args.no_inhibit_auto_suspend,
                "ignore_lid": args.ignore_lid,
                "manage_backlight": not args.do_not_touch_backlight,
                "color_stdout": terminal_style.stdout_color,
                "color_stderr": terminal_style.stderr_color,
                "log_path": str(log_path),
            }
        )
    except RunningLogError as exc:
        if running_log is not None:
            try:
                running_log.close()
            except RunningLogError:
                pass
        terminal_style.write_status(
            "FATAL ERROR",
            f"Could not establish the mandatory synchronized running log: {exc}",
            sys.stderr,
        )
        return 1
    assert running_log is not None

    manager: Optional[LidCloseManager] = None
    result_code = 1
    pre_manager_reason = "Runtime initialization did not complete."
    try:
        if not args.mode.startswith("run") and (
            args.suspend_after_minutes is not None
            or args.no_inhibit_auto_suspend
            or args.ignore_lid
        ):
            warning = (
                "--suspend-after-minutes, --no-inhibit-auto-suspend, and "
                "--ignore-lid have no effect unless a 'run*' mode is selected."
            )
            running_log.append("warning", "WARNING", warning)
            terminal_style.write_status("WARNING", warning)

        # Argument validation remains dependency-free, but every accepted
        # operational session is durably started before PyGObject is loaded.
        load_pygobject(terminal_style, running_log)
        pre_manager_reason = "Controller initialization did not complete."

        manager = LidCloseManager(
            mode=args.mode,
            suspend_after_minutes=args.suspend_after_minutes,
            no_inhibit_auto_suspend=args.no_inhibit_auto_suspend,
            ignore_lid=args.ignore_lid,
            do_not_touch_backlight=args.do_not_touch_backlight,
            started_monotonic=process_started_at,
            terminal_style=terminal_style,
            running_log=running_log,
        )
        manager._log_only(
            "startup_plan",
            "INFO",
            "Recorded the requested operational plan before host mutation.",
            {
                "target_power_profile": PROFILE_MAP.get(args.mode),
                "persistent_run_mode": args.mode.startswith("run"),
                "suspend_after_minutes": args.suspend_after_minutes,
                "inhibit_auto_suspend": not args.no_inhibit_auto_suspend,
                "ignore_lid": args.ignore_lid,
                "manage_backlight": not args.do_not_touch_backlight,
            },
        )
        manager.print_startup_narrative()
        manager.connect_dbus()

        if not args.mode.startswith("run"):
            manager.execute_immediate_action()
        else:
            # --------------------------------------------------------------
            # PERSISTENT 'RUN*' MODE LIFECYCLE
            # --------------------------------------------------------------
            def sig_handler(signum: int, frame: Any) -> None:
                sig_name = (
                    "SIGINT (Ctrl-C)" if signum == signal.SIGINT else "SIGTERM"
                )
                manager._event(
                    f"Received interrupt signal: {sig_name}.",
                    event="signal_received",
                    details={"signal": signum, "name": sig_name},
                )
                manager.shutdown_reason = (
                    f"User termination signal received ({sig_name})"
                )
                manager.goal_achieved = True
                if manager.mainloop:
                    manager.mainloop.quit()

            try:
                # 1. Snapshot screen-backlight state and bind the caller's
                # logind session. The opt-out returns before discovery.
                manager.prepare_backlight_control()

                # 2. Set requested power profile.
                target_prof = PROFILE_MAP.get(args.mode, None)
                manager.save_and_set_power_profile(target_prof)

                # 3. Acquire D-Bus inhibitor locks.
                manager.acquire_inhibitor_locks()

                # 4. Register UPower listener for physical lid events.
                manager.setup_upower_signal_listener()
                manager.check_initial_lid_state()

                # 5. Set up signal handling for clean Ctrl-C/SIGTERM exit.
                signal.signal(signal.SIGINT, sig_handler)
                signal.signal(signal.SIGTERM, sig_handler)

                # 6. Run the event loop. Backlight delay remains measured from
                # process start, not from completion of setup.
                manager.mainloop = GLib.MainLoop()
                manager.schedule_backlight_power_down()
                wait_target = "lid events" if args.ignore_lid else "lid cycle"
                manager._info(
                    "Entering persistent event loop. "
                    f"Waiting for {wait_target} or interrupt...",
                    event="event_loop_entered",
                    details={"wait_target": wait_target},
                )
                manager.mainloop.run()
                manager._log_only(
                    "event_loop_exited",
                    "INFO",
                    "Persistent event loop returned to handled teardown.",
                )
            except KeyboardInterrupt:
                manager.shutdown_reason = (
                    "User termination signal received (SIGINT / Ctrl-C)"
                )
                manager.goal_achieved = True
            except RunningLogError:
                # The manager already marked the durability failure, requested
                # loop exit, and selected nonzero status. Do not log recursively.
                pass
            except SystemExit:
                # _fatal_error has already recorded failure and run teardown.
                raise
            except BaseException as exc:
                manager._warn(f"Unhandled exception in persistent lifecycle: {exc}")
                manager.deviations.append(
                    f"Persistent lifecycle terminated unexpectedly: {exc}"
                )
                manager.shutdown_reason = f"Unhandled exception: {exc}"
                manager.goal_achieved = False
                manager.exit_code = 1

        result_code = manager.exit_code
    except RunningLogError as exc:
        if manager is not None:
            if not manager.log_failure_reported:
                manager._mark_running_log_failure(exc)
            result_code = 1
        else:
            terminal_style.write_status(
                "FATAL ERROR",
                f"Mandatory running-log synchronization failed: {exc}",
                sys.stderr,
            )
            pre_manager_reason = f"Running-log synchronization failed: {exc}"
            result_code = 1
    finally:
        if manager is not None:
            # Explicit brightness and profile mutations require cleanup;
            # logging failures are not permitted to interrupt this path.
            manager.teardown()
            manager.print_shutdown_narrative()
            result_code = manager.exit_code
        elif running_log.file_descriptor is not None:
            # Dependency or controller setup failed after session_start but
            # before a manager could own the final record.
            if running_log.failed_reason is None:
                try:
                    running_log.end_session(
                        exit_code=1,
                        goal_achieved=False,
                        shutdown_reason=pre_manager_reason,
                        deviations=[],
                        final_state={"host_mutation_started": False},
                    )
                except RunningLogError as exc:
                    terminal_style.write_status(
                        "FATAL ERROR",
                        f"Could not synchronize the session-end record: {exc}",
                        sys.stderr,
                    )
            try:
                running_log.close()
            except RunningLogError as exc:
                terminal_style.write_status("FATAL ERROR", str(exc), sys.stderr)

    return result_code


if __name__ == "__main__":
    sys.exit(main())
