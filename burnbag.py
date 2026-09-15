#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
burnbag — Clamshell Mode & Power Profile Management Utility for Linux
Target Platforms: Ubuntu/Debian and Fedora/RHEL; x86-64 and ARM64 (Python 3.9+)

This utility temporarily inhibits systemd-logind lid-switch and idle-suspend events,
manages power-profiles-daemon profiles, monitors UPower lid state, and samples installed
battery percentages to allow a laptop to continue running when the lid is shut (e.g.,
while inside a bag or docked) with an observable depletion history.

Its D-Bus inhibitor file descriptors are process-owned: termination releases
these locks. Handled exits separately attempt and verify backlight and temporary
power-profile restoration; abrupt process death cannot restore persistent changes.

Copyright (C)2026 Hard Problems Group, LLC.
Released under the MIT License.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import statistics
import sys
import textwrap
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, Tuple
import uuid

Gio: Any = None
GLib: Any = None


class ShutdownRequested(Exception):
    """Unwind at an explicit lifecycle boundary after a termination signal."""


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
            "burnbag uses distribution packages for /usr/bin/python3.\n"
            "Install or verify it with:\n"
            "    ./scripts/install_prerequisites.sh\n"
            "Ubuntu/Debian:\n"
            "    sudo apt-get install python3-gi gir1.2-glib-2.0\n"
            "Fedora/RHEL:\n"
            "    sudo dnf install python3-gobject\n"
            "If these packages are already installed, launch burnbag with /usr/bin/python3.\n"
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

# D-Bus names, paths, and interfaces shared by supported Linux desktops
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
# Explicit method deadline; GI proxy construction uses its own library defaults.
DBUS_CALL_TIMEOUT_MILLISECONDS = 10_000
POWER_ACTION_TIMEOUT_MILLISECONDS = 30_000

BACKLIGHT_SYSFS_ROOT = Path("/sys/class/backlight")
BACKLIGHT_OFF_DELAY_SECONDS = 3.0
BACKLIGHT_VERIFY_ATTEMPTS = 10
BACKLIGHT_VERIFY_INTERVAL_SECONDS = 0.05
BATTERY_SYSFS_ROOT = Path("/sys/class/power_supply")
BATTERY_SAMPLE_INTERVAL_MILLISECONDS = 15_000
BATTERY_PLOT_ROWS = 25
BATTERY_PLOT_FALLBACK_COLUMNS = 80


def linux_boottime() -> float:
    """Return suspend-inclusive monotonic time on Linux.

    ``CLOCK_MONOTONIC`` stops while the system is suspended. Battery-rate
    durations use ``CLOCK_BOOTTIME`` so an auto-suspend interval cannot be
    mistaken for an ordinary fifteen-second gauge update.
    """
    clock_id = getattr(time, "CLOCK_BOOTTIME", None)
    if clock_id is None:
        # The supported platform is Linux, but retaining this fallback keeps
        # import-time and documentation tooling usable on other systems.
        return time.monotonic()
    return time.clock_gettime(clock_id)

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


@dataclass(frozen=True)
class BatteryDevice:
    """One read-only Linux power-supply battery selected for this run."""

    name: str
    capacity_path: Optional[Path]
    present_path: Optional[Path] = None
    status_path: Optional[Path] = None
    remaining_path: Optional[Path] = None
    full_path: Optional[Path] = None

    @property
    def percentage_source(self) -> str:
        """Identify the fixed native or matched-unit gauge source for this run."""
        if self.capacity_path is not None:
            return "capacity"
        if self.remaining_path is None or self.full_path is None:
            raise ValueError(f"Battery {self.name!r} has no percentage source")
        return f"{self.remaining_path.name}/{self.full_path.name}"


@dataclass(frozen=True)
class BatterySample:
    """One sampling cycle, including gaps caused by unavailable devices."""

    captured_at: datetime
    elapsed_seconds: float
    percentages: Dict[str, int]
    statuses: Dict[str, str] = field(default_factory=dict)
    present: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class LidEvent:
    """One detected lid transition on the battery plot's elapsed timebase."""

    captured_at: datetime
    elapsed_seconds: float
    closed: bool


@dataclass(frozen=True)
class SuspendInterval:
    """Clock-confirmed sleep duration with estimated graph boundaries."""

    started_at: datetime
    ended_at: datetime
    start_elapsed_seconds: float
    end_elapsed_seconds: float
    boundary_uncertainty_seconds: float = 0.0
    observed_start_elapsed_seconds: float = 0.0
    observed_end_elapsed_seconds: float = 0.0

    def to_log_details(self) -> Dict[str, Any]:
        return {
            "start_local_estimate": self.started_at.isoformat(timespec="microseconds"),
            "end_local_estimate": self.ended_at.isoformat(timespec="microseconds"),
            "start_elapsed_seconds": self.start_elapsed_seconds,
            "end_elapsed_seconds": self.end_elapsed_seconds,
            "suspended_seconds": self.end_elapsed_seconds - self.start_elapsed_seconds,
            "boundary_uncertainty_seconds": self.boundary_uncertainty_seconds,
            "observed_start_elapsed_seconds": self.observed_start_elapsed_seconds,
            "observed_end_elapsed_seconds": self.observed_end_elapsed_seconds,
            "timebase": "CLOCK_BOOTTIME",
        }


@dataclass(frozen=True)
class SuspendClockSample:
    """Paired kernel clocks, with an upper bound on sequential-read error."""

    captured_at: datetime
    boottime: float
    monotonic: float
    uncertainty_seconds: float = 0.0

    @property
    def offset(self) -> float:
        return self.boottime - self.monotonic


def read_suspend_clocks() -> SuspendClockSample:
    """Bracket MONOTONIC with BOOTTIME; never silently substitute a clock.

    BOOTTIME bracketing also exposes a suspend between the individual reads.
    Keep the tightest of three pairs to reduce scheduling and syscall noise.
    """
    clock_id = getattr(time, "CLOCK_BOOTTIME", None)
    if clock_id is None:
        raise RuntimeError("Linux CLOCK_BOOTTIME is unavailable")
    candidates = []
    for _ in range(3):
        before = time.clock_gettime(clock_id)
        monotonic = time.monotonic()
        captured_at = datetime.now().astimezone()
        after = time.clock_gettime(clock_id)
        if not all(math.isfinite(value) for value in (before, monotonic, after)) or after < before:
            raise RuntimeError("Invalid or backwards kernel clock reading")
        candidates.append(SuspendClockSample(
            captured_at, (before + after) / 2.0, monotonic, (after - before) / 2.0,
        ))
    return min(candidates, key=lambda sample: sample.uncertainty_seconds)


class SuspendMonitor:
    """Observe actual suspended time independently of the GLib event loop.

    The worker reads clocks only. The main thread joins it before finalizing
    intervals or writing output/logs, so it never races device recovery or log
    ownership. Memory grows only with detected sleep windows, not uptime.
    """

    SAMPLE_SECONDS = 1.0
    DETECTION_FLOOR_SECONDS = 0.001
    WORKER_JOIN_SECONDS = 2.0

    def __init__(
        self, started_boottime: float,
        initial: Optional[SuspendClockSample] = None,
        reader: Optional[Callable[[], SuspendClockSample]] = None,
        initial_error: Optional[str] = None,
    ) -> None:
        self.started_boottime = started_boottime
        self.reader = read_suspend_clocks if reader is None else reader
        self.initial = initial
        self.latest = initial
        self.accounted = initial
        self.pending_start: Optional[SuspendClockSample] = None
        self.intervals: List[SuspendInterval] = []
        self.errors: List[str] = [initial_error] if initial_error else []
        self.started = False
        self.finished = False
        self.final_read_succeeded = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _error(self, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if message not in self.errors and len(self.errors) < 8:
            self.errors.append(message)

    def observe(self, current: SuspendClockSample) -> None:
        """Accumulate confirmed offset growth without counting read jitter."""
        values = (current.boottime, current.monotonic, current.uncertainty_seconds)
        if not all(math.isfinite(value) for value in values) or current.uncertainty_seconds < 0:
            raise ValueError("Invalid paired clock observation")
        if self.latest is None:
            self.initial = self.latest = self.accounted = current
            return
        previous = self.latest
        assert self.accounted is not None
        uncertainty = current.uncertainty_seconds + self.accounted.uncertainty_seconds
        change = current.offset - self.accounted.offset
        if (current.boottime < previous.boottime
                or current.monotonic < previous.monotonic
                or change < -max(self.DETECTION_FLOOR_SECONDS, uncertainty)):
            raise ValueError("Kernel clock continuity lost; suspend coverage is incomplete")
        if change > uncertainty and self.pending_start is None:
            self.pending_start = previous
        if change > max(self.DETECTION_FLOOR_SECONDS, uncertainty):
            start = self.pending_start or previous
            window_seconds = current.boottime - start.boottime
            suspended_seconds = min(change, window_seconds)
            awake_seconds = max(0.0, window_seconds - suspended_seconds)
            start_elapsed = max(0.0, start.boottime - self.started_boottime + awake_seconds / 2.0)
            end_elapsed = max(start_elapsed, current.boottime - self.started_boottime - awake_seconds / 2.0)
            if end_elapsed > start_elapsed:
                self.intervals.append(SuspendInterval(
                    current.captured_at - timedelta(seconds=current.boottime - self.started_boottime - start_elapsed),
                    current.captured_at - timedelta(seconds=current.boottime - self.started_boottime - end_elapsed),
                    start_elapsed, end_elapsed,
                    awake_seconds / 2.0 + uncertainty,
                    max(0.0, start.boottime - self.started_boottime),
                    max(0.0, current.boottime - self.started_boottime),
                ))
            self.accounted = current
            self.pending_start = None
        elif change <= uncertainty:
            self.pending_start = None
        self.latest = current

    def sample(self, worker: bool = False) -> bool:
        try:
            current = self.reader()
            with self._lock:
                if worker and self._stop.is_set():
                    return False
                self.observe(current)
        except Exception as exc:
            with self._lock:
                if worker and self._stop.is_set():
                    return False
                self._error(exc)
            return False
        return True

    def start(self) -> None:
        if self.started or self.finished:
            return
        self.started = True
        self.sample()
        try:
            self._thread = threading.Thread(target=self._run, name="burnbag-suspend-monitor", daemon=True)
            self._thread.start()
        except Exception as exc:
            self._thread = None
            self._error(exc)

    def _run(self) -> None:
        while not self._stop.wait(self.SAMPLE_SECONDS):
            self.sample(worker=True)

    def finish(self) -> None:
        """Stop the worker and reconcile through the pre-report clock read."""
        if self.finished:
            return
        self.finished = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.WORKER_JOIN_SECONDS)
            if self._thread.is_alive():
                with self._lock:
                    self._error(RuntimeError("Suspend clock worker did not stop"))
                return
        self.final_read_succeeded = self.sample()

    def to_log_details(self) -> Dict[str, Any]:
        total = (
            max(0.0, self.latest.offset - self.initial.offset)
            if self.latest is not None and self.initial is not None else None
        )
        return {
            "interval_count": len(self.intervals),
            "total_suspended_seconds": total,
            "coverage_complete": self.final_read_succeeded and not self.errors,
            "coverage_start_elapsed_seconds": (
                max(0.0, self.initial.boottime - self.started_boottime) if self.initial else None
            ),
            "coverage_end_elapsed_seconds": (
                max(0.0, self.latest.boottime - self.started_boottime) if self.latest else None
            ),
            "sample_interval_seconds": self.SAMPLE_SECONDS,
            "detection_floor_seconds": self.DETECTION_FLOOR_SECONDS,
            "boundaries_estimated": True,
            "rapid_cycles_may_merge": True,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class BatteryStatistics:
    """Descriptive fuel-gauge statistics for one battery and handled run."""

    name: str
    attempted_readings: int
    valid_readings: int
    first_percentage: Optional[int]
    last_percentage: Optional[int]
    span_seconds: Optional[float]
    net_change_pp: Optional[int]
    coverage_ratio: float
    attempt_cadence_seconds: float
    trend_kind: str
    trend_depletion_pp_per_hour: Optional[float]
    r_squared: Optional[float]
    trend_validity_reason: Optional[str]
    transition_count: int
    local_rate_count: int
    weighted_mean_depletion_pp_per_hour: Optional[float]
    weighted_sigma_pp_per_hour: Optional[float]
    coefficient_of_variation_percent: Optional[float]
    robust_mad_sigma_pp_per_hour: Optional[float]
    median_minutes_per_pp: Optional[float]
    observed_reversals: int
    mixed_history: bool
    segment_count: int
    excluded_gap_count: int
    status_break_count: int
    maximum_transition_bracket_seconds: Optional[float]
    variability_validity_reason: Optional[str]
    observed_statuses: Tuple[str, ...]

    @staticmethod
    def _finite_or_none(value: Optional[float]) -> Optional[float]:
        """Keep the structured JSON representation free of NaN and infinity."""
        if value is None or not math.isfinite(value):
            return None
        return value

    @property
    def average_reported_change_pp_per_minute(self) -> Optional[float]:
        """Return signed mean local gauge change in percentage points/minute.

        Local depletion rates use positive values, so negate before converting
        hours to minutes: falling state of charge is negative and rising state
        of charge is positive. This is a unit conversion of the already-gated
        transition-rate estimator, not a derivative of raw 15-second samples.
        """
        if self.weighted_mean_depletion_pp_per_hour is None:
            return None
        return -self.weighted_mean_depletion_pp_per_hour / 60.0

    @property
    def reported_change_sigma_pp_per_minute(self) -> Optional[float]:
        """Return local gauge-rate standard deviation in pp/minute."""
        if self.weighted_sigma_pp_per_hour is None:
            return None
        return self.weighted_sigma_pp_per_hour / 60.0

    def to_log_details(self) -> Dict[str, Any]:
        """Return a versioned, unit-bearing JSON object for the running log."""
        return {
            "statistics_version": 2,
            "battery": self.name,
            "timebase": "CLOCK_BOOTTIME",
            "attempted_readings": self.attempted_readings,
            "valid_readings": self.valid_readings,
            "coverage_ratio": self._finite_or_none(self.coverage_ratio),
            "first_percentage": self.first_percentage,
            "last_percentage": self.last_percentage,
            "span_seconds": self._finite_or_none(self.span_seconds),
            "net_change_percentage_points": self.net_change_pp,
            "attempt_cadence_seconds": self._finite_or_none(
                self.attempt_cadence_seconds
            ),
            "trend_kind": self.trend_kind,
            "trend_depletion_percentage_points_per_hour": self._finite_or_none(
                self.trend_depletion_pp_per_hour
            ),
            "r_squared": self._finite_or_none(self.r_squared),
            "trend_validity_reason": self.trend_validity_reason,
            "eligible_reported_transition_count": self.transition_count,
            "local_rate_count": self.local_rate_count,
            "weighted_mean_depletion_percentage_points_per_hour": (
                self._finite_or_none(
                    self.weighted_mean_depletion_pp_per_hour
                )
            ),
            "weighted_depletion_rate_sigma_percentage_points_per_hour": (
                self._finite_or_none(self.weighted_sigma_pp_per_hour)
            ),
            "average_reported_change_percentage_points_per_minute": (
                self._finite_or_none(
                    self.average_reported_change_pp_per_minute
                )
            ),
            "standard_deviation_reported_change_percentage_points_per_minute": (
                self._finite_or_none(
                    self.reported_change_sigma_pp_per_minute
                )
            ),
            "coefficient_of_variation_percent": self._finite_or_none(
                self.coefficient_of_variation_percent
            ),
            "robust_mad_sigma_percentage_points_per_hour": self._finite_or_none(
                self.robust_mad_sigma_pp_per_hour
            ),
            "median_minutes_per_percentage_point": self._finite_or_none(
                self.median_minutes_per_pp
            ),
            "observed_reversals": self.observed_reversals,
            "mixed_history": self.mixed_history,
            "segment_count": self.segment_count,
            "excluded_gap_count": self.excluded_gap_count,
            "status_break_count": self.status_break_count,
            "maximum_transition_bracket_seconds": self._finite_or_none(
                self.maximum_transition_bracket_seconds
            ),
            "variability_validity_reason": self.variability_validity_reason,
            "observed_statuses": list(self.observed_statuses),
        }


@dataclass(frozen=True)
class _BatteryTransition:
    """One interval-censored reported gauge-level change."""

    segment: int
    elapsed_seconds: float
    percentage: int
    change_pp: int
    bracket_seconds: float


class BatteryMonitor:
    """Discover and sample at most two kernel battery devices without mutation.

    The two-device limit is a presentation contract, not an assumption hidden
    in the sysfs reader: additional eligible names are returned explicitly so
    the controller can warn and record exactly which devices were selected.
    """

    MAX_PLOTTED_BATTERIES = 2

    def __init__(self, root: Path, started_boottime: float) -> None:
        self.root = root
        self.started_boottime = started_boottime
        self.devices: List[BatteryDevice] = []
        self.unselected_names: List[str] = []
        self.samples: List[BatterySample] = []

    @staticmethod
    def _read_sysfs_text(path: Path) -> str:
        """Read and normalize one small sysfs attribute."""
        return path.read_text(encoding="utf-8").strip()

    def discover(self) -> List[str]:
        """Select present battery devices in deterministic kernel-name order.

        Missing sysfs is normal on systems without Linux power-supply support.
        Other directory-level failures are returned for explicit reporting.
        Unreadable attributes on unrelated non-battery supplies are ignored,
        because their type cannot be established as in scope.
        """
        self.devices = []
        self.unselected_names = []
        try:
            entries = sorted(self.root.iterdir(), key=lambda path: path.name)
        except FileNotFoundError:
            return []
        except OSError as exc:
            return [f"Could not enumerate battery power supplies under {self.root}: {exc}"]

        eligible: List[BatteryDevice] = []
        errors: List[str] = []
        for entry in entries:
            try:
                supply_type = self._read_sysfs_text(entry / "type")
            except OSError:
                continue
            if supply_type.casefold() != "battery":
                continue

            try:
                present = self._read_sysfs_text(entry / "present")
            except FileNotFoundError:
                # The kernel documents `present` as optional. A battery whose
                # driver omits it is eligible when capacity can be read.
                present = "1"
            except OSError as exc:
                errors.append(
                    f"Could not determine whether battery {entry.name!r} is present: {exc}"
                )
                continue
            if present == "0":
                continue
            if present != "1":
                errors.append(
                    f"Battery {entry.name!r} reported invalid present value {present!r}."
                )
                continue

            capacity_path: Optional[Path] = entry / "capacity"
            remaining_path: Optional[Path] = None
            full_path: Optional[Path] = None
            if not capacity_path.exists():
                capacity_path = None
                # Not every kernel driver exposes a percentage. Prefer real
                # energy, then charge, with matching current/full units. Never
                # substitute design capacity, voltage, or mixed-unit values.
                for quantity in ("energy", "charge"):
                    candidate_now = entry / f"{quantity}_now"
                    candidate_full = entry / f"{quantity}_full"
                    if candidate_now.exists() and candidate_full.exists():
                        remaining_path = candidate_now
                        full_path = candidate_full
                        break
                if remaining_path is None:
                    errors.append(
                        f"Battery {entry.name!r} does not expose a capacity "
                        "percentage or a complete energy_now/energy_full or "
                        "charge_now/charge_full pair."
                    )
                    continue
            present_path = entry / "present"
            status_path = entry / "status"
            eligible.append(
                BatteryDevice(
                    entry.name,
                    capacity_path,
                    present_path if present_path.exists() else None,
                    status_path if status_path.exists() else None,
                    remaining_path,
                    full_path,
                )
            )

        self.devices = eligible[: self.MAX_PLOTTED_BATTERIES]
        self.unselected_names = [
            device.name for device in eligible[self.MAX_PLOTTED_BATTERIES :]
        ]
        return errors

    def _read_percentage(self, device: BatteryDevice) -> int:
        """Read the selected gauge source without switching sources on failure."""
        if device.capacity_path is not None:
            capacity = int(self._read_sysfs_text(device.capacity_path), 10)
            if not 0 <= capacity <= 100:
                raise ValueError(
                    f"percentage {capacity} is outside the inclusive 0--100 range"
                )
            return capacity

        if device.remaining_path is None or device.full_path is None:
            raise ValueError("no selected percentage source")
        remaining = int(self._read_sysfs_text(device.remaining_path), 10)
        full = int(self._read_sysfs_text(device.full_path), 10)
        if full <= 0 or remaining < 0 or remaining > full:
            raise ValueError(
                f"invalid {device.percentage_source} values "
                f"({remaining}/{full}); require 0 <= now <= full and full > 0"
            )
        # Round half up to whole percentage points. Integer arithmetic avoids
        # floating-point precision loss and keeps the quantized statistics
        # contract identical for native and derived gauges.
        return (200 * remaining + full) // (2 * full)

    def sample(
        self,
        captured_at: Optional[datetime] = None,
        elapsed_seconds: Optional[float] = None,
    ) -> Tuple[BatterySample, List[str]]:
        """Read all selected percentages and preserve device-level gaps."""
        selected_time = (
            datetime.now().astimezone() if captured_at is None else captured_at
        )
        if selected_time.tzinfo is None:
            raise ValueError("Battery sample wall-clock time must be timezone-aware")
        selected_elapsed = (
            max(0.0, linux_boottime() - self.started_boottime)
            if elapsed_seconds is None
            else max(0.0, elapsed_seconds)
        )

        percentages: Dict[str, int] = {}
        statuses: Dict[str, str] = {}
        present_devices: Dict[str, bool] = {}
        errors: List[str] = []
        for device in self.devices:
            if device.present_path is not None:
                try:
                    raw_present = self._read_sysfs_text(device.present_path)
                    if raw_present not in {"0", "1"}:
                        raise ValueError(
                            f"invalid present value {raw_present!r}"
                        )
                    is_present = raw_present == "1"
                    present_devices[device.name] = is_present
                    if not is_present:
                        # Removal or pack handoff is a continuity break, not a
                        # read failure and not a reason to mutate the device.
                        continue
                except (OSError, ValueError) as exc:
                    errors.append(
                        f"Could not read battery {device.name!r} presence: {exc}"
                    )
                    continue
            else:
                present_devices[device.name] = True

            if device.status_path is not None:
                try:
                    status_value = self._read_sysfs_text(device.status_path)
                    if status_value:
                        statuses[device.name] = status_value
                except OSError:
                    # Status is optional in the statistics contract. A driver
                    # that exposes but cannot currently read it loses only
                    # corroboration; capacity remains independently useful.
                    pass

            try:
                capacity = self._read_percentage(device)
            except (OSError, ValueError) as exc:
                errors.append(f"Could not read battery {device.name!r}: {exc}")
                continue
            percentages[device.name] = capacity

        sample = BatterySample(
            selected_time,
            selected_elapsed,
            percentages,
            statuses,
            present_devices,
        )
        self.samples.append(sample)
        return sample, errors


def summarize_battery_statistics(
    name: str, samples: Sequence[BatterySample]
) -> BatteryStatistics:
    """Calculate quantization-aware descriptive statistics for one battery.

    Whole-run OLS describes the reported percentage staircase. Local
    variability deliberately uses only eligible reported-level transitions;
    differentiating adjacent 15-second integer readings would manufacture
    alternating zero and 240 pp/h impulses from a smooth one-point change.
    """
    attempted = len(samples)
    positive_attempt_deltas = [
        later.elapsed_seconds - earlier.elapsed_seconds
        for earlier, later in zip(samples, samples[1:])
        if later.elapsed_seconds > earlier.elapsed_seconds
    ]
    attempt_cadence = (
        float(statistics.median(positive_attempt_deltas))
        if len(positive_attempt_deltas) >= 3
        else float(BATTERY_SAMPLE_INTERVAL_MILLISECONDS) / 1000.0
    )
    maximum_contiguous_delta = max(45.0, 3.0 * attempt_cadence)
    valid_points = [
        (index, sample, sample.percentages[name])
        for index, sample in enumerate(samples)
        if name in sample.percentages
    ]
    valid = len(valid_points)
    coverage = valid / attempted if attempted else 0.0
    observed_statuses = tuple(
        sorted(
            {
                sample.statuses[name]
                for sample in samples
                if name in sample.statuses
            }
        )
    )

    first_percentage: Optional[int] = None
    last_percentage: Optional[int] = None
    span_seconds: Optional[float] = None
    net_change: Optional[int] = None
    trend_depletion: Optional[float] = None
    r_squared: Optional[float] = None
    trend_reason: Optional[str] = None
    trend_kind = "unavailable"

    if valid_points:
        first_percentage = valid_points[0][2]
        last_percentage = valid_points[-1][2]
    if valid >= 2:
        span_seconds = max(
            0.0,
            valid_points[-1][1].elapsed_seconds
            - valid_points[0][1].elapsed_seconds,
        )
        net_change = last_percentage - first_percentage  # type: ignore[operator]

    ols_slope: Optional[float] = None
    unique_levels = {point[2] for point in valid_points}
    if valid == 0:
        trend_reason = "no valid readings"
    elif valid == 1:
        trend_reason = "only one valid reading"
    elif valid < 5:
        trend_reason = "need at least five valid readings"
    elif span_seconds is None or span_seconds < 300.0:
        trend_reason = "need at least five minutes of observations"
    elif len(unique_levels) == 1:
        trend_kind = "constant"
        trend_reason = "no reported whole-percentage change"
    else:
        elapsed_hours = [
            (point[1].elapsed_seconds - valid_points[0][1].elapsed_seconds)
            / 3600.0
            for point in valid_points
        ]
        percentages = [float(point[2]) for point in valid_points]
        mean_time = statistics.fmean(elapsed_hours)
        mean_percentage = statistics.fmean(percentages)
        time_sum_squares = sum(
            (value - mean_time) ** 2 for value in elapsed_hours
        )
        if time_sum_squares <= 0.0:
            trend_reason = "elapsed times do not establish a trend"
        else:
            ols_slope = sum(
                (elapsed - mean_time) * (percentage - mean_percentage)
                for elapsed, percentage in zip(elapsed_hours, percentages)
            ) / time_sum_squares
            trend_depletion = -ols_slope
            fitted = [
                mean_percentage + ols_slope * (elapsed - mean_time)
                for elapsed in elapsed_hours
            ]
            total_sum_squares = sum(
                (percentage - mean_percentage) ** 2
                for percentage in percentages
            )
            if total_sum_squares > 0.0:
                residual_sum_squares = sum(
                    (percentage - estimate) ** 2
                    for percentage, estimate in zip(percentages, fitted)
                )
                calculated_r_squared = 1.0 - (
                    residual_sum_squares / total_sum_squares
                )
                # Clamp only floating-point spill at the descriptive boundary.
                r_squared = min(1.0, max(0.0, calculated_r_squared))

    # Build per-device contiguous segments. A missing reading, long elapsed
    # interval, or known status change breaks local-rate continuity.
    segments: List[List[Tuple[int, BatterySample, int]]] = []
    missing_gap_runs = sum(
        name not in sample.percentages
        and (index == 0 or name in samples[index - 1].percentages)
        for index, sample in enumerate(samples)
    )
    long_or_invalid_gap_count = 0
    status_break_count = 0
    previous_valid: Optional[Tuple[int, BatterySample, int]] = None
    for point in valid_points:
        index, sample, _percentage = point
        continue_segment = False
        if previous_valid is not None:
            previous_index, previous_sample, _previous_percentage = previous_valid
            elapsed_delta = sample.elapsed_seconds - previous_sample.elapsed_seconds
            previous_status = previous_sample.statuses.get(name)
            current_status = sample.statuses.get(name)
            status_changed = (
                previous_status is not None
                and current_status is not None
                and previous_status != current_status
            )
            missing_between = index != previous_index + 1
            elapsed_gap = not (0.0 < elapsed_delta <= maximum_contiguous_delta)
            if status_changed:
                status_break_count += 1
            if not missing_between and elapsed_gap:
                long_or_invalid_gap_count += 1
            continue_segment = (
                not missing_between
                and not elapsed_gap
                and not status_changed
            )
        if not continue_segment:
            segments.append([])
        segments[-1].append(point)
        previous_valid = point

    excluded_gap_count = missing_gap_runs + long_or_invalid_gap_count
    transitions: List[_BatteryTransition] = []
    for segment_index, segment in enumerate(segments):
        for earlier, later in zip(segment, segment[1:]):
            _earlier_index, earlier_sample, earlier_percentage = earlier
            _later_index, later_sample, later_percentage = later
            if later_percentage == earlier_percentage:
                continue
            bracket_seconds = (
                later_sample.elapsed_seconds - earlier_sample.elapsed_seconds
            )
            if bracket_seconds <= 0.0:
                continue
            transitions.append(
                _BatteryTransition(
                    segment=segment_index,
                    elapsed_seconds=(
                        earlier_sample.elapsed_seconds + bracket_seconds / 2.0
                    ),
                    percentage=later_percentage,
                    change_pp=later_percentage - earlier_percentage,
                    bracket_seconds=bracket_seconds,
                )
            )

    transition_signs = [1 if item.change_pp > 0 else -1 for item in transitions]
    observed_reversals = sum(
        current != previous
        for previous, current in zip(transition_signs, transition_signs[1:])
    )
    upward_motion = sum(max(0, item.change_pp) for item in transitions)
    downward_motion = sum(max(0, -item.change_pp) for item in transitions)
    upward_transitions = sum(item.change_pp > 0 for item in transitions)
    downward_transitions = sum(item.change_pp < 0 for item in transitions)
    mixed_history = (
        upward_motion > 0
        and downward_motion > 0
        and (
            min(upward_motion, downward_motion) >= 2
            or min(upward_transitions, downward_transitions) >= 2
        )
    )

    if ols_slope is not None and span_seconds is not None and net_change is not None:
        fitted_change = ols_slope * (span_seconds / 3600.0)
        sign_agrees = (
            (net_change < 0 and fitted_change < 0)
            or (net_change > 0 and fitted_change > 0)
        )
        if mixed_history:
            trend_kind = "mixed"
        elif abs(net_change) >= 2 and abs(fitted_change) >= 2 and sign_agrees:
            trend_kind = "depleting" if fitted_change < 0 else "rising"
        else:
            trend_kind = "unresolved"
            trend_reason = "direction unresolved at whole-percentage resolution"

    # Rates are formed only between consecutive eligible transition events in
    # the same segment. Their elapsed duration is also the time weight.
    local_rates: List[Tuple[float, float, int]] = []
    for earlier, later in zip(transitions, transitions[1:]):
        if earlier.segment != later.segment:
            continue
        duration_seconds = later.elapsed_seconds - earlier.elapsed_seconds
        if duration_seconds <= 0.0:
            continue
        percentage_change = later.percentage - earlier.percentage
        rate = -percentage_change * 3600.0 / duration_seconds
        local_rates.append((rate, duration_seconds, percentage_change))

    weighted_mean: Optional[float] = None
    weighted_sigma: Optional[float] = None
    cv_percent: Optional[float] = None
    robust_mad_sigma: Optional[float] = None
    median_minutes_per_pp: Optional[float] = None
    variability_reason: Optional[str] = None
    if len(local_rates) < 3:
        variability_reason = (
            "no observed level transitions"
            if not transitions
            else f"need at least three local rates; observed {len(local_rates)}"
        )
    else:
        total_weight = sum(item[1] for item in local_rates)
        weighted_mean = sum(
            rate * duration for rate, duration, _change in local_rates
        ) / total_weight
        weighted_sigma = math.sqrt(
            sum(
                duration * (rate - weighted_mean) ** 2
                for rate, duration, _change in local_rates
            )
            / total_weight
        )
        unweighted_rates = [item[0] for item in local_rates]
        median_rate = float(statistics.median(unweighted_rates))
        robust_mad_sigma = 1.4826 * float(
            statistics.median(
                [abs(rate - median_rate) for rate in unweighted_rates]
            )
        )
        all_one_direction = len(set(transition_signs)) <= 1
        if (
            len(local_rates) >= 5
            and all_one_direction
            and weighted_mean != 0.0
        ):
            cv_percent = 100.0 * weighted_sigma / abs(weighted_mean)

    if not mixed_history and transition_signs:
        dominant_sign = transition_signs[0]
        cadence_intervals = [
            duration / 60.0
            for _rate, duration, percentage_change in local_rates
            if abs(percentage_change) == 1
            and (1 if percentage_change > 0 else -1) == dominant_sign
        ]
        if len(cadence_intervals) >= 2:
            median_minutes_per_pp = float(statistics.median(cadence_intervals))

    maximum_bracket = (
        max(item.bracket_seconds for item in transitions)
        if transitions
        else None
    )
    return BatteryStatistics(
        name=name,
        attempted_readings=attempted,
        valid_readings=valid,
        first_percentage=first_percentage,
        last_percentage=last_percentage,
        span_seconds=span_seconds,
        net_change_pp=net_change,
        coverage_ratio=coverage,
        attempt_cadence_seconds=attempt_cadence,
        trend_kind=trend_kind,
        trend_depletion_pp_per_hour=trend_depletion,
        r_squared=r_squared,
        trend_validity_reason=trend_reason,
        transition_count=len(transitions),
        local_rate_count=len(local_rates),
        weighted_mean_depletion_pp_per_hour=weighted_mean,
        weighted_sigma_pp_per_hour=weighted_sigma,
        coefficient_of_variation_percent=cv_percent,
        robust_mad_sigma_pp_per_hour=robust_mad_sigma,
        median_minutes_per_pp=median_minutes_per_pp,
        observed_reversals=observed_reversals,
        mixed_history=mixed_history,
        segment_count=len(segments),
        excluded_gap_count=excluded_gap_count,
        status_break_count=status_break_count,
        maximum_transition_bracket_seconds=maximum_bracket,
        variability_validity_reason=variability_reason,
        observed_statuses=observed_statuses,
    )


def _draw_battery_line(
    canvas: List[List[int]], start: Tuple[int, int], end: Tuple[int, int], mask: int
) -> None:
    """Rasterize one inclusive line segment with integer Bresenham steps."""
    x0, y0 = start
    x1, y1 = end
    delta_x = abs(x1 - x0)
    step_x = 1 if x0 < x1 else -1
    delta_y = -abs(y1 - y0)
    step_y = 1 if y0 < y1 else -1
    error = delta_x + delta_y
    while True:
        canvas[y0][x0] |= mask
        if x0 == x1 and y0 == y1:
            return
        doubled_error = 2 * error
        if doubled_error >= delta_y:
            error += delta_y
            x0 += step_x
        if doubled_error <= delta_x:
            error += delta_x
            y0 += step_y


def render_battery_depletion_chart(
    devices: Sequence[BatteryDevice],
    samples: Sequence[BatterySample],
    terminal_style: TerminalStyle,
    stream: Optional[TextIO] = None,
    columns: Optional[int] = None,
    lid_events: Sequence[LidEvent] = (),
    suspend_intervals: Sequence[SuspendInterval] = (),
    coverage_start: Optional[Tuple[datetime, float]] = None,
    coverage_end: Optional[Tuple[datetime, float]] = None,
) -> str:
    """Return the full-width 25-row battery chart, or an empty string.

    Only actual observations establish the Y range and Y labels. Monotonic
    elapsed time controls X placement so a wall-clock adjustment cannot reorder
    samples; the displayed labels remain actual local wall-clock `HH:mm` values.
    Suspend intervals cover all data rows, including battery and lid traces.
    Coverage endpoints retain setup and teardown time outside battery sampling.
    """
    selected_stream = sys.stdout if stream is None else stream
    selected_names = [device.name for device in devices[:2]]
    observed_values = [
        sample.percentages[name]
        for sample in samples
        for name in selected_names
        if name in sample.percentages
    ]
    if not selected_names or not observed_values:
        return ""

    terminal_columns = (
        shutil.get_terminal_size(
            fallback=(BATTERY_PLOT_FALLBACK_COLUMNS, 24)
        ).columns
        if columns is None
        else columns
    )
    terminal_columns = max(20, terminal_columns)
    observed_min = min(observed_values)
    observed_max = max(observed_values)

    def row_for(value: int) -> int:
        if observed_max == observed_min:
            return BATTERY_PLOT_ROWS // 2
        fraction = (observed_max - value) / (observed_max - observed_min)
        return int(round(fraction * (BATTERY_PLOT_ROWS - 1)))

    # Reserve both scale boundaries even when the observed range is constant.
    # The repeated value describes that degenerate range without inventing a
    # percentage span; the constant series itself remains vertically centered.
    labels_by_row: Dict[int, str] = {
        0: f"{observed_max}%",
        BATTERY_PLOT_ROWS - 1: f"{observed_min}%",
    }
    ordered_values = sorted(
        set(observed_values) - {observed_min, observed_max}, reverse=True
    )
    for value in ordered_values:
        labels_by_row.setdefault(row_for(value), f"{value}%")
    axis_width = max(len(label) for label in labels_by_row.values())
    plot_width = max(1, terminal_columns - axis_width - 2)
    canvas = [[0 for _ in range(plot_width)] for _ in range(BATTERY_PLOT_ROWS)]

    # Include event and run-coverage times even if battery reads at those times
    # failed. None of these endpoints creates a battery observation. Discard
    # invalid intervals so malformed suspend evidence cannot prevent reporting.
    if coverage_start is not None and not math.isfinite(coverage_start[1]):
        coverage_start = None
    if coverage_end is not None and not math.isfinite(coverage_end[1]):
        coverage_end = None
    if (coverage_start is not None and coverage_end is not None
            and coverage_end[1] < coverage_start[1]):
        coverage_start = coverage_end = None
    valid_intervals: List[Tuple[float, float]] = []
    timeline = [(item.captured_at, item.elapsed_seconds) for item in [*samples, *lid_events]]
    for interval in suspend_intervals:
        start_elapsed = interval.start_elapsed_seconds
        end_elapsed = interval.end_elapsed_seconds
        if (not math.isfinite(start_elapsed) or not math.isfinite(end_elapsed)
                or start_elapsed < 0 or end_elapsed <= start_elapsed):
            continue
        started_at, ended_at = interval.started_at, interval.ended_at
        if coverage_start is not None and start_elapsed < coverage_start[1]:
            started_at, start_elapsed = coverage_start
        if coverage_end is not None and end_elapsed > coverage_end[1]:
            ended_at, end_elapsed = coverage_end
        if end_elapsed <= start_elapsed:
            continue
        valid_intervals.append((start_elapsed, end_elapsed))
        timeline.extend(((started_at, start_elapsed), (ended_at, end_elapsed)))
    if coverage_start is not None:
        timeline.insert(0, coverage_start)
    if coverage_end is not None:
        timeline.append(coverage_end)
    first_observation = min(timeline, key=lambda item: item[1])
    last_observation = max(reversed(timeline), key=lambda item: item[1])
    first_elapsed = first_observation[1]
    last_elapsed = last_observation[1]

    def column_for(elapsed: float) -> int:
        if last_elapsed == first_elapsed or plot_width == 1:
            return 0
        fraction = (elapsed - first_elapsed) / (last_elapsed - first_elapsed)
        return int(round(fraction * (plot_width - 1)))

    for series_index, name in enumerate(selected_names):
        previous_point: Optional[Tuple[int, int]] = None
        mask = 1 << series_index
        for sample in samples:
            if name not in sample.percentages:
                # Do not manufacture a line through an unavailable reading.
                previous_point = None
                continue
            point = (
                column_for(sample.elapsed_seconds),
                row_for(sample.percentages[name]),
            )
            if previous_point is None:
                canvas[point[1]][point[0]] |= mask
            else:
                _draw_battery_line(canvas, previous_point, point, mask)
            previous_point = point

    color_enabled = terminal_style.enabled_for(selected_stream)
    event_columns = [0 for _ in range(plot_width)]
    for event in lid_events:
        event_columns[column_for(event.elapsed_seconds)] |= 1 if event.closed else 2
    suspend_columns = [False for _ in range(plot_width)]
    for start_elapsed, end_elapsed in valid_intervals:
        # Rasterize each interval separately. Very short suspends remain at
        # least one column wide; elapsed gaps between periods remain unfilled
        # whenever terminal resolution can represent them.
        for column in range(column_for(start_elapsed), column_for(end_elapsed) + 1):
            suspend_columns[column] = True

    def render_event(mask: int, row_index: int, header: bool = False) -> str:
        if mask == 0:
            return " "
        if header:
            symbol = {1: "C", 2: "O", 3: "B"}[mask]
        else:
            symbol = {1: "|", 2: "|" if color_enabled else ":", 3: "!"}[mask]
        # Fast close/open pairs may occupy the same screen column. Preserve
        # both colors down that column, with an explicit combined glyph.
        color = (
            TerminalStyle.MAGENTA
            if mask == 1 or (mask == 3 and row_index % 2 == 0)
            else TerminalStyle.YELLOW
        )
        return terminal_style.paint(symbol, color, selected_stream)

    def render_cell(mask: int, event_mask: int, row_index: int) -> str:
        if mask == 0:
            return render_event(event_mask, row_index)
        if not color_enabled:
            return {1: "1", 2: "2", 3: "X"}[mask]
        color = {
            1: TerminalStyle.YELLOW,
            2: TerminalStyle.BLUE,
            3: TerminalStyle.GREEN,
        }[mask]
        return terminal_style.paint("*", color, selected_stream)

    title = "BATTERY DEPLETION - 15-second samples"
    range_text = f"Observed Y range: {observed_min}%--{observed_max}%"
    output = [title[:terminal_columns], range_text[:terminal_columns]]
    if lid_events:
        # The marker header keeps events identifiable even where a battery
        # trace covers their vertical line. It is outside the 25 data rows.
        marker_header = "".join(render_event(mask, 0, header=True) for mask in event_columns)
        output.append(f"{' ' * (axis_width + 2)}{marker_header}")
    for row_index, row in enumerate(canvas):
        label = labels_by_row.get(row_index, "").rjust(axis_width)
        cells = "".join(
            terminal_style.paint("S", "37;41", selected_stream)
            if suspend_columns[column]
            else render_cell(cell, event_columns[column], row_index)
            for column, cell in enumerate(row)
        )
        output.append(f"{label} |{cells}")
    # Group interior callouts by displayed minute, but never deduplicate the
    # two domain boundaries. Even a single observation has two labeled bounds.
    candidate_groups: List[List[BatterySample]] = []
    plottable_samples = [
        sample
        for sample in samples
        if any(name in sample.percentages for name in selected_names)
    ]
    for sample in plottable_samples:
        sample_label = sample.captured_at.astimezone().strftime("%H:%M")
        if not candidate_groups:
            candidate_groups.append([sample])
            continue
        previous_label = (
            candidate_groups[-1][-1].captured_at.astimezone().strftime("%H:%M")
        )
        if sample_label == previous_label:
            candidate_groups[-1].append(sample)
        else:
            candidate_groups.append([sample])
    # Each tuple contains the tick's plot column and the inclusive screen-column
    # interval occupied by its centered (or edge-clamped) label.
    def make_callout(
        captured_at: datetime, sample_column: int
    ) -> Tuple[int, str, int, int]:
        label = captured_at.astimezone().strftime("%H:%M")
        start = max(
            0,
            min(plot_width - len(label), sample_column - len(label) // 2),
        )
        return sample_column, label, start, start + len(label) - 1

    first_callout = make_callout(first_observation[0], 0)
    final_callout = make_callout(last_observation[0], plot_width - 1)
    callout_candidates: List[Tuple[int, str, int, int]] = []
    for index, group in enumerate(candidate_groups):
        sample = group[0]
        candidate = make_callout(sample.captured_at, column_for(sample.elapsed_seconds))
        # End groups are already represented by their boundary labels; equal
        # endpoint times still remain separately visible at the two edges.
        if index == 0 and candidate[1] == first_callout[1]:
            continue
        if index == len(candidate_groups) - 1 and candidate[1] == final_callout[1]:
            continue
        callout_candidates.append(candidate)

    # Two visible blanks make adjacent HH:mm values unambiguous. Reserve the
    # two endpoints first; a greedy pass fills the remaining interior space.
    # The minimum 20-column chart fits both five-character endpoint labels.
    minimum_blank_columns = 2
    selected_callouts = [first_callout]
    for candidate in callout_candidates:
        if candidate[2] <= selected_callouts[-1][3] + minimum_blank_columns:
            continue
        if candidate[3] + minimum_blank_columns >= final_callout[2]:
            continue
        selected_callouts.append(candidate)
    selected_callouts.append(final_callout)

    # Align both boundary ticks with the corresponding data columns. In a
    # zero-duration domain they annotate equal bounds, not an invented span.
    axis_cells = ["-" for _ in range(plot_width)]
    for sample_column, _label, _start, _end in selected_callouts:
        axis_cells[sample_column] = "+"
    output.append(f"{' ' * (axis_width + 2)}{''.join(axis_cells)}")

    # Place the already collision-checked labels beneath their real ticks.
    label_line = [" " for _ in range(plot_width)]
    for _sample_column, label, start, _end in selected_callouts:
        label_line[start : start + len(label)] = label
    output.append(f"{' ' * (axis_width + 2)}{''.join(label_line)}")
    output.append("X: local wall clock (HH:mm); Y: observed battery percentage")

    if color_enabled:
        legend_parts = [
            terminal_style.paint(
                f"yellow *={selected_names[0]}",
                TerminalStyle.YELLOW,
                selected_stream,
            )
        ]
        if len(selected_names) > 1:
            legend_parts.extend(
                [
                    terminal_style.paint(
                        f"blue *={selected_names[1]}",
                        TerminalStyle.BLUE,
                        selected_stream,
                    ),
                    terminal_style.paint(
                        "green *=overlap", TerminalStyle.GREEN, selected_stream
                    ),
                ]
            )
    else:
        legend_parts = [f"1={selected_names[0]}"]
        if len(selected_names) > 1:
            legend_parts.extend([f"2={selected_names[1]}", "X=overlap"])
    output.append("Legend: " + "  ".join(legend_parts))
    if lid_events:
        close_key = terminal_style.paint("C/|=close", TerminalStyle.MAGENTA, selected_stream)
        open_key = terminal_style.paint(
            "O/|=open" if color_enabled else "O/:=open", TerminalStyle.YELLOW, selected_stream
        )
        output.append(f"Lid: {close_key}  {open_key}  B/!=both in one column")
    if valid_intervals:
        suspend_key = terminal_style.paint("S", "37;41", selected_stream)
        output.append(f"Suspend: {suspend_key}=suspended (full-height block); boundaries approximate")
    return "\n".join(output) + "\n"


def _format_statistics_duration(seconds: Optional[float]) -> str:
    """Format a measured duration without implying sub-second precision."""
    if seconds is None:
        return "n/a"
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{remaining_seconds:02d}s"
    if minutes:
        return f"{minutes}m{remaining_seconds:02d}s"
    return f"{remaining_seconds}s"


def _battery_statistics_plain_lines(
    result: BatteryStatistics, columns: int
) -> Tuple[List[str], str, str, str]:
    """Lay out one battery in no more than three visible terminal lines.

    The returned phrases identify the headline and variability spans that the
    ANSI layer may color without changing layout or plain-output semantics.
    """
    columns = max(40, columns)
    prefix = f"● {result.name}"
    data_phrase = f"data {result.valid_readings}/{result.attempted_readings}"
    quality_parts: List[str] = []
    if result.coverage_ratio < 0.8:
        quality_parts.append("low coverage")
    if result.excluded_gap_count:
        quality_parts.append(f"gapped {result.excluded_gap_count}")
    if result.status_break_count:
        quality_parts.append(f"status breaks {result.status_break_count}")

    mean_per_minute = result.average_reported_change_pp_per_minute
    sigma_per_minute = result.reported_change_sigma_pp_per_minute
    if mean_per_minute is not None and sigma_per_minute is not None:
        signed_mean = (
            f"{mean_per_minute:+.2f}" if mean_per_minute != 0.0 else "0.00"
        ).replace("-", "−")
        per_minute_phrase = (
            f"avg reported-gauge Δ/min {signed_mean} pp/min │ "
            f"σ {sigma_per_minute:.2f} pp/min"
        )
    else:
        per_minute_phrase = "avg reported-gauge Δ/min n/a │ σ n/a"
    per_minute_line = f"  ↳ {per_minute_phrase}"

    if result.valid_readings == 0:
        base = f"{prefix} no valid readings"
        headline = "statistics unavailable"
        return (
            [f"{base} │ {data_phrase}", f"  ↳ {headline}", per_minute_line],
            headline,
            headline,
            per_minute_phrase,
        )
    if result.valid_readings == 1:
        base = f"{prefix} {result.first_percentage}% only"
        headline = "statistics unavailable — only one valid reading"
        return (
            [f"{base} │ {data_phrase}", f"  ↳ {headline}", per_minute_line],
            headline,
            headline,
            per_minute_phrase,
        )

    net_change = result.net_change_pp or 0
    net_text = f"+{net_change}" if net_change > 0 else str(net_change)
    net_text = net_text.replace("-", "−")
    base = (
        f"{prefix} {result.first_percentage}→{result.last_percentage}%  "
        f"Δ{net_text} pp / {_format_statistics_duration(result.span_seconds)}"
    )

    trend_rate = result.trend_depletion_pp_per_hour
    normalized_statuses = {value.casefold() for value in result.observed_statuses}
    if result.trend_kind == "depleting" and trend_rate is not None:
        trend_label = (
            "depletion trend"
            if normalized_statuses == {"discharging"}
            else "falling SoC trend"
        )
        headline = f"{trend_label} {abs(trend_rate):.1f} pp/h"
    elif result.trend_kind == "rising" and trend_rate is not None:
        trend_label = (
            "charging trend"
            if normalized_statuses == {"charging"}
            else "rising SoC trend"
        )
        headline = f"{trend_label} {abs(trend_rate):.1f} pp/h"
    elif result.trend_kind == "mixed" and trend_rate is not None:
        direction = "down" if trend_rate > 0 else "up"
        headline = f"mixed history; OLS net drift {direction} {abs(trend_rate):.1f} pp/h"
    elif result.trend_kind == "constant":
        headline = "no reported whole-percentage change"
    elif trend_rate is not None:
        direction = "down" if trend_rate > 0 else "up"
        headline = f"direction unresolved; OLS drift {direction} {abs(trend_rate):.1f} pp/h"
    else:
        headline = result.trend_validity_reason or "trend unavailable"

    trend_parts = [headline]
    if result.r_squared is not None:
        trend_parts.append(f"R² {result.r_squared:.2f}".replace("0.", "."))
    trend_parts.append(data_phrase)
    trend_parts.extend(quality_parts)
    trend_line = " │ ".join(trend_parts)

    if result.weighted_sigma_pp_per_hour is not None:
        variability_phrase = (
            "gauge depletion-rate variability "
            f"σ {result.weighted_sigma_pp_per_hour:.1f} pp/h"
        )
        variability_context = ["weighted"]
        if result.coefficient_of_variation_percent is not None:
            variability_context.append(
                f"CV {result.coefficient_of_variation_percent:.0f}%"
            )
        variability_context.append(f"n={result.local_rate_count}")
        variability_parts = [
            f"{variability_phrase} ({', '.join(variability_context)})"
        ]
        if result.median_minutes_per_pp is not None:
            variability_parts.append(
                "median 1 pp / "
                f"{_format_statistics_duration(result.median_minutes_per_pp * 60.0)}"
            )
        variability_parts.append(f"reversals {result.observed_reversals}")
        variability_line = " │ ".join(variability_parts)
    else:
        variability_phrase = "gauge depletion-rate variability n/a"
        variability_line = (
            f"{variability_phrase} — "
            f"{result.variability_validity_reason or 'insufficient observations'}"
        )

    full_first = f"{base} │ {trend_line}"
    full_second = f"  ↳ {variability_line}"
    wide_lines = [full_first, full_second, per_minute_line]
    if max(len(line) for line in wide_lines) <= columns:
        return wide_lines, headline, variability_phrase, per_minute_phrase

    # Compact fallback retains the core meaning at the documented 40-column
    # minimum. Supporting CV/cadence/reversal fields yield to width before any
    # core endpoint, trend, variability, or coverage value is truncated.
    compact_base = base.replace("  ", " ").replace(" pp", "pp")
    if result.trend_kind == "depleting" and trend_rate is not None:
        compact_label = (
            "deplete"
            if normalized_statuses == {"discharging"}
            else "SoC fall"
        )
        compact_headline = f"{compact_label} {abs(trend_rate):.1f}pp/h"
    elif result.trend_kind == "rising" and trend_rate is not None:
        compact_label = (
            "charge" if normalized_statuses == {"charging"} else "SoC rise"
        )
        compact_headline = f"{compact_label} {abs(trend_rate):.1f}pp/h"
    elif result.trend_kind == "constant":
        compact_headline = "no whole-percentage change"
    elif trend_rate is not None:
        compact_headline = f"OLS drift {abs(trend_rate):.1f}pp/h"
    else:
        compact_headline = "trend n/a"
    compact_trend_parts = [compact_headline]
    if result.r_squared is not None:
        compact_trend_parts.append(
            f"R²{result.r_squared:.2f}".replace("0.", ".")
        )
    compact_trend_parts.append(
        f"{result.valid_readings}/{result.attempted_readings}"
    )
    compact_trend = " · ".join(compact_trend_parts)

    if result.weighted_sigma_pp_per_hour is not None:
        assert mean_per_minute is not None and sigma_per_minute is not None
        compact_mean = (
            f"{mean_per_minute:+.2f}" if mean_per_minute != 0.0 else "0.00"
        ).replace("-", "−")
        compact_mean = compact_mean.replace("+0.", "+.").replace("−0.", "−.")
        compact_sigma = f"{sigma_per_minute:.2f}".removeprefix("0")
        compact_variability = (
            f"σrate {result.weighted_sigma_pp_per_hour:.1f}pp/h · "
            f"avgΔ{compact_mean} σ{compact_sigma}pp/min"
        )
        supporting: List[str] = [f"n{result.local_rate_count}"]
        if result.coefficient_of_variation_percent is not None:
            supporting.append(
                f"CV{result.coefficient_of_variation_percent:.0f}%"
            )
        if result.median_minutes_per_pp is not None:
            supporting.append(
                f"med{_format_statistics_duration(result.median_minutes_per_pp * 60.0)}/pp"
            )
        if result.observed_reversals:
            supporting.append(f"rev{result.observed_reversals}")
        for item in supporting:
            proposed = f"{compact_variability} · {item}"
            if len(f"  {proposed}") <= columns:
                compact_variability = proposed
    else:
        compact_variability = "σrate n/a · avgΔ/min n/a · σ n/a"

    return (
        [compact_base, f"  {compact_trend}", f"  {compact_variability}"],
        compact_headline,
        compact_variability.split(" · ", 1)[0],
        compact_variability,
    )


def render_battery_statistics(
    results: Sequence[BatteryStatistics],
    terminal_style: TerminalStyle,
    stream: Optional[TextIO] = None,
    columns: Optional[int] = None,
) -> str:
    """Render sophisticated but gauge-honest per-battery summary lines."""
    if not results:
        return ""
    selected_stream = sys.stdout if stream is None else stream
    terminal_columns = (
        shutil.get_terminal_size(
            fallback=(BATTERY_PLOT_FALLBACK_COLUMNS, 24)
        ).columns
        if columns is None
        else columns
    )
    terminal_columns = max(40, terminal_columns)
    heading = "BATTERY SUMMARY — quantized fuel-gauge statistics"
    if len(heading) > terminal_columns:
        heading = "BATTERY SUMMARY"
    rendered = [
        terminal_style.paint(
            heading,
            f"{TerminalStyle.BOLD};{TerminalStyle.CYAN}",
            selected_stream,
        )
    ]
    color_by_index = [TerminalStyle.YELLOW, TerminalStyle.BLUE]
    for index, result in enumerate(results[:2]):
        (
            plain_lines,
            headline,
            variability_phrase,
            per_minute_phrase,
        ) = _battery_statistics_plain_lines(result, terminal_columns)
        series_color = color_by_index[index]
        for plain_line in plain_lines:
            line = plain_line.replace(
                f"● {result.name}",
                terminal_style.paint(
                    f"● {result.name}",
                    f"{TerminalStyle.BOLD};{series_color}",
                    selected_stream,
                ),
                1,
            )
            if headline in line:
                line = line.replace(
                    headline,
                    terminal_style.paint(
                        headline, series_color, selected_stream
                    ),
                    1,
                )
            if variability_phrase in line:
                line = line.replace(
                    variability_phrase,
                    terminal_style.paint(
                        variability_phrase,
                        TerminalStyle.MAGENTA,
                        selected_stream,
                    ),
                    1,
                )
            if per_minute_phrase in line and per_minute_phrase != variability_phrase:
                line = line.replace(
                    per_minute_phrase,
                    terminal_style.paint(
                        per_minute_phrase,
                        TerminalStyle.MAGENTA,
                        selected_stream,
                    ),
                    1,
                )
            for warning in ("low coverage", "gapped", "mixed history"):
                if warning in line:
                    line = line.replace(
                        warning,
                        terminal_style.paint(
                            warning, TerminalStyle.YELLOW, selected_stream
                        ),
                    )
            line = line.replace(
                "│", terminal_style.paint("│", TerminalStyle.DIM_CYAN, selected_stream)
            ).replace(
                "↳", terminal_style.paint("↳", TerminalStyle.CYAN, selected_stream)
            )
            rendered.append(line)
    footer = (
        "pp = percentage points; avg Δ/min is signed; σrate and σ/min "
        "describe gauge-rate unevenness, not watts."
    )
    footer_lines = textwrap.wrap(
        footer,
        width=terminal_columns,
        break_long_words=False,
        break_on_hyphens=False,
    )
    for footer_line in footer_lines:
        rendered.append(
            terminal_style.paint(
                footer_line, TerminalStyle.DIM_CYAN, selected_stream
            )
        )
    return "\n".join(rendered) + "\n"


# ==============================================================================
# CORE CONTROLLER CLASS
# ==============================================================================

class LidCloseManager:
    """
    Manages the lifecycle of D-Bus inhibitor locks, power profile states,
    UPower lid monitoring, read-only battery sampling, and narrative console
    reporting for burnbag.
    """

    def __init__(
        self,
        mode: str,
        suspend_after_minutes: Optional[int],
        no_inhibit_auto_suspend: bool,
        ignore_lid: bool,
        do_not_touch_backlight: bool = False,
        no_plot: bool = False,
        started_monotonic: Optional[float] = None,
        started_boottime: Optional[float] = None,
        terminal_style: Optional[TerminalStyle] = None,
        running_log: Optional[RunningLog] = None,
        suspend_clock_initial: Optional[SuspendClockSample] = None,
        suspend_clock_error: Optional[str] = None,
    ):
        # Configuration parameters from CLI arguments
        self.mode: str = mode
        self.suspend_after_minutes: Optional[int] = suspend_after_minutes
        self.no_inhibit_auto_suspend: bool = no_inhibit_auto_suspend
        self.ignore_lid: bool = ignore_lid
        self.do_not_touch_backlight: bool = do_not_touch_backlight
        self.no_plot: bool = no_plot
        self.started_monotonic: float = (
            time.monotonic() if started_monotonic is None else started_monotonic
        )
        self.started_boottime: float = (
            linux_boottime() if started_boottime is None else started_boottime
        )
        self.terminal_style = terminal_style or TerminalStyle.detect()
        self.running_log = running_log
        self.battery_monitor = BatteryMonitor(BATTERY_SYSFS_ROOT, self.started_boottime)
        self.suspend_monitor = SuspendMonitor(
            self.started_boottime, suspend_clock_initial, initial_error=suspend_clock_error,
        )
        self.suspend_report_finalized = False

        # State tracking variables for clean teardown and narrative reporting
        self.original_power_profile: Optional[str] = None
        self.active_power_profile: Optional[str] = None
        self.power_profile_changed: bool = False
        self.power_profile_change_verified: bool = False
        self.power_profile_restore_attempted: bool = False
        self.power_profile_restore_verified: bool = False
        self.power_profile_retained: bool = False
        self.inhibitor_release_failed: bool = False
        self.lid_capability_checked: bool = False
        self.lid_monitoring_available: bool = False
        self.inhibitor_fds: List[int] = []  # Open file descriptors holding systemd locks
        self.lid_was_closed_during_session: bool = False
        self.current_lid_closed_state: bool = False
        self.lid_events: List[LidEvent] = []
        self.lid_close_count: int = 0
        self.lid_open_count: int = 0
        self.suspend_timer_id: Optional[int] = None
        self.backlight_timer_id: Optional[int] = None
        self.battery_timer_id: Optional[int] = None
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
        self.battery_monitor_started: bool = False
        self.battery_monitor_stopped: bool = False
        self.battery_plot_printed: bool = False
        self.battery_statistics: List[BatteryStatistics] = []
        self.reported_battery_errors: set[str] = set()
        self.shutdown_signal: Optional[int] = None
        self.shutdown_signal_source_id: Optional[int] = None
        self.stop_requested: bool = False
        self.teardown_started: bool = False
        self.failed_output_streams: List[TextIO] = []

        # D-Bus connection and proxy placeholders
        self.bus: Optional[Gio.DBusConnection] = None
        self.logind_proxy: Optional[Gio.DBusProxy] = None
        self.logind_session_proxy: Optional[Gio.DBusProxy] = None
        self.logind_session_path: Optional[str] = None
        self.logind_session_source: Optional[str] = None
        self.power_proxy: Optional[Gio.DBusProxy] = None
        self.upower_proxy: Optional[Gio.DBusProxy] = None
        self.mainloop: Optional[GLib.MainLoop] = None

    def request_signal_shutdown(self, signum: int) -> None:
        """Remember termination without interrupting mutation bookkeeping.

        Queue loop exit so a signal immediately before MainLoop.run cannot be
        lost. Repeated signals do not interrupt recovery or duplicate sources.
        Logging is deliberately left to the ordinary finalization path.
        """
        if self.teardown_in_progress:
            return
        if self.shutdown_signal is None:
            self.shutdown_signal = signum
        if (
            self.mainloop is not None
            and not self.teardown_in_progress
            and self.shutdown_signal_source_id is None
        ):
            self.shutdown_signal_source_id = GLib.idle_add(
                self.guard_callback("signal shutdown", self._quit_for_signal)
            )

    def _quit_for_signal(self) -> bool:
        """Dispatch a pending signal after the GLib loop has actually started."""
        self.shutdown_signal_source_id = None
        if self.mainloop is not None:
            self.mainloop.quit()
        return False

    def check_shutdown_requested(self) -> None:
        """Stop setup at a safe boundary before starting another operation."""
        if self.shutdown_signal is not None or self.stop_requested:
            raise ShutdownRequested()

    def record_signal_shutdown(self) -> None:
        """Record the first termination signal outside its interrupt handler."""
        if self.shutdown_signal is None:
            return
        signum = self.shutdown_signal
        sig_name = signal.Signals(signum).name
        if signum == signal.SIGINT:
            sig_name += " (Ctrl-C)"
        if self.shutdown_reason == "Unknown / Undefined" or self.exit_code == 0:
            self.shutdown_reason = f"User termination signal received ({sig_name})"
            self.goal_achieved = self.exit_code == 0
        try:
            self._log_only(
                "signal_received",
                "EVENT",
                f"Received interrupt signal: {sig_name}.",
                {"signal": signum, "name": sig_name},
            )
        except RunningLogError:
            # The durability failure is already marked; cleanup still owns
            # restoration and the best available shutdown report.
            pass

    def _record_failure(self, message: str, event: str = "runtime_failure") -> None:
        """Retain a failed outcome even when both diagnostic channels fail."""
        if message not in self.deviations:
            self.deviations.append(message)
        if self.exit_code == 0 or self.shutdown_reason == "Unknown / Undefined":
            self.shutdown_reason = message
        self.exit_code = 1
        self.goal_achieved = False
        self.stop_requested = True
        try:
            self._log_only(event, "ERROR", message)
        except Exception:
            # Recovery must not depend on the availability of its own log.
            pass
        if self.mainloop is not None:
            try:
                self.mainloop.quit()
            except Exception:
                pass

    def _write_output(self, text: str, stream: TextIO) -> bool:
        """Flush output now, recording failures before the final log record."""
        if any(stream is failed for failed in self.failed_output_streams):
            return False
        try:
            stream.write(text)
            stream.flush()
            return True
        except Exception as exc:
            self.failed_output_streams.append(stream)
            name = "stderr" if stream is sys.stderr else "stdout"
            self._record_failure(
                f"Could not write {name}: {type(exc).__name__}: {exc}",
                "terminal_output_failed",
            )
            # A failed buffered stdout flush would otherwise be retried by
            # Python during interpreter shutdown, producing a second traceback
            # and changing the process status after session_end was recorded.
            if isinstance(exc, BrokenPipeError):
                try:
                    if stream.fileno() in (1, 2):
                        with open(os.devnull, "w") as sink:
                            os.dup2(sink.fileno(), stream.fileno())
                except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
                    pass
            return False

    def _console_status(
        self, label: str, message: str, stream: Optional[TextIO] = None,
        timestamp: Optional[str] = None, leading_newline: bool = False,
    ) -> None:
        """Try the requested terminal channel, then its surviving alternative."""
        preferred = sys.stdout if stream is None else stream
        alternate = sys.stdout if preferred is sys.stderr else sys.stderr
        for destination in (preferred, alternate):
            prefix = f"[{timestamp}] " if timestamp else ""
            try:
                prefix += self.terminal_style.status_prefix(label, destination)
            except Exception as exc:
                self._record_failure(f"Could not format terminal status: {exc}", "terminal_render_failed")
                prefix += f"[{label}]"
            text = ("\n" if leading_newline else "") + f"{prefix} {message}\n"
            if self._write_output(text, destination):
                return

    def guard_callback(
        self, label: str, callback: Callable[..., Any],
        source_attribute: Optional[str] = None,
    ) -> Callable[..., Any]:
        """Keep Python exceptions inside the application's GLib boundary."""
        def guarded(*arguments: Any) -> Any:
            if self.teardown_in_progress:
                return False
            try:
                result = callback(*arguments)
                if not result and source_attribute is not None:
                    setattr(self, source_attribute, None)
                return result
            except KeyboardInterrupt:
                self.request_signal_shutdown(signal.SIGINT)
            except ShutdownRequested:
                pass
            except SystemExit as exc:
                if not self.teardown_complete:
                    self._record_failure(f"{label} callback exited unexpectedly: {exc}", "callback_failed")
            except BaseException as exc:
                self._record_failure(
                    f"{label} callback failed: {type(exc).__name__}: {exc}",
                    "callback_failed",
                )
                self._console_status("ERROR", self.shutdown_reason, sys.stderr)
            if source_attribute is not None:
                setattr(self, source_attribute, None)
            if self.mainloop is not None:
                try:
                    self.mainloop.quit()
                except Exception as exc:
                    self._record_failure(f"Could not stop event loop: {exc}")
            return False
        return guarded

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
            self._console_status(
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
        if self.running_log is None or self.running_log_finished:
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
        self._console_status("INFO", message)

    def _ok(
        self,
        message: str,
        event: str = "operation_succeeded",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a successful runtime outcome."""
        self._append_running_log(event, "OK", message, details)
        self._console_status("OK", message)

    def _event(
        self,
        message: str,
        event: str = "lifecycle_event",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write an asynchronous lifecycle event with visual separation."""
        self._append_running_log(event, "EVENT", message, details)
        self._console_status("EVENT", message, leading_newline=True)

    def finish_running_log(self) -> None:
        """Synchronize the handled session end after teardown and close the log."""
        if self.exit_code != 0:
            self.goal_achieved = False
        if self.running_log is None or self.running_log_finished:
            return
        statistics_details = []
        for result in self.battery_statistics:
            try:
                statistics_details.append(result.to_log_details())
            except Exception as exc:
                self._record_failure(
                    f"Could not serialize battery statistics: {type(exc).__name__}: {exc}",
                    "final_state_serialization_failed",
                )
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
                        "power_profile_changed": getattr(self, "power_profile_changed", False),
                        "power_profile_change_verified": getattr(self, "power_profile_change_verified", False),
                        "power_profile_restore_attempted": getattr(self, "power_profile_restore_attempted", False),
                        "power_profile_restore_verified": getattr(self, "power_profile_restore_verified", False),
                        "power_profile_retained": getattr(self, "power_profile_retained", False),
                        "inhibitor_release_failed": getattr(self, "inhibitor_release_failed", False),
                        "terminal_output_failed": bool(self.failed_output_streams),
                        "lid_was_closed": self.lid_was_closed_during_session,
                        "lid_close_count": self.lid_close_count,
                        "lid_open_count": self.lid_open_count,
                        "suspend_monitor": self.suspend_monitor.to_log_details(),
                        "battery_names": [
                            device.name for device in self.battery_monitor.devices
                        ],
                        "battery_sample_count": len(self.battery_monitor.samples),
                        "battery_last_percentages": (
                            self.battery_monitor.samples[-1].percentages
                            if self.battery_monitor.samples
                            else {}
                        ),
                        "battery_plot_suppressed": self.no_plot,
                        "battery_statistics": statistics_details,
                    },
                )
            except Exception as exc:
                self._mark_running_log_failure(
                    exc if isinstance(exc, RunningLogError) else RunningLogError(str(exc))
                )

        try:
            self.running_log.close()
        except Exception as exc:
            self._mark_running_log_failure(
                exc if isinstance(exc, RunningLogError) else RunningLogError(str(exc))
            )

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
    # READ-ONLY BATTERY MONITORING & EXIT PLOT
    # --------------------------------------------------------------------------

    def _record_battery_error(self, message: str) -> None:
        """Report one observational failure without blocking safety teardown."""
        if message not in self.deviations:
            self.deviations.append(message)
        self.exit_code = 1
        if message in self.reported_battery_errors:
            return
        self.reported_battery_errors.add(message)
        try:
            self._warn(message)
        except RunningLogError:
            # The mandatory logger has already selected fail-closed shutdown.
            # A timer callback must not obscure that cause with another error.
            if not self.teardown_in_progress:
                raise

    def _take_battery_sample(self, reason: str) -> Optional[BatterySample]:
        """Take and synchronize one sample while retaining per-device gaps."""
        if not self.battery_monitor.devices:
            return None
        try:
            sample, errors = self.battery_monitor.sample()
        except Exception as exc:
            self._record_battery_error(f"Battery sampling failed: {exc}")
            return None

        self._log_only(
            "battery_sample",
            "OK" if not errors else "WARNING",
            f"Recorded {reason} battery sample.",
            {
                "reason": reason,
                "captured_at_local": sample.captured_at.isoformat(
                    timespec="seconds"
                ),
                "elapsed_seconds": round(sample.elapsed_seconds, 6),
                "timebase": "CLOCK_BOOTTIME",
                "percentages": dict(sample.percentages),
                "percentage_sources": {
                    device.name: device.percentage_source
                    for device in self.battery_monitor.devices
                },
                "statuses": dict(sample.statuses),
                "present": dict(sample.present),
                "errors": errors,
            },
        )
        for error in errors:
            self._record_battery_error(error)
        return sample

    def _on_battery_sample_timer(self) -> bool:
        """GLib callback for the fixed fifteen-second sampling cadence."""
        try:
            self._take_battery_sample("periodic")
        except RunningLogError:
            self.battery_timer_id = None
            return False
        return True

    def start_battery_monitoring(self) -> None:
        """Discover batteries, take the initial sample, and schedule run modes."""
        if self.battery_monitor_started:
            return
        self.battery_monitor_started = True
        discovery_errors = self.battery_monitor.discover()
        selected_names = [
            device.name for device in self.battery_monitor.devices
        ]
        self._log_only(
            "battery_discovery_completed",
            "OK" if not discovery_errors else "WARNING",
            "Completed read-only battery discovery.",
            {
                "selected_batteries": selected_names,
                "percentage_sources": {
                    device.name: device.percentage_source
                    for device in self.battery_monitor.devices
                },
                "unselected_batteries": self.battery_monitor.unselected_names,
                "errors": discovery_errors,
            },
        )
        for error in discovery_errors:
            self._record_battery_error(error)

        for device in self.battery_monitor.devices:
            if device.capacity_path is None:
                self._info(
                    f"Battery {device.name!r}: deriving whole percentages from "
                    f"{device.percentage_source} (rounded to nearest percent).",
                    event="battery_percentage_source",
                    details={
                        "battery": device.name,
                        "percentage_source": device.percentage_source,
                        "quantization": "nearest_integer_half_up",
                    },
                )

        if self.battery_monitor.unselected_names:
            message = (
                "More than two batteries were discovered; monitoring "
                f"{', '.join(selected_names)} and leaving "
                f"{', '.join(self.battery_monitor.unselected_names)} unplotted."
            )
            # This is an explicit presentation-limit warning, not a failure of
            # the selected two-battery monitoring contract.
            self._warn(message)

        if not self.battery_monitor.devices:
            self._info(
                "No installed system batteries were discovered; no depletion "
                "plot will be produced.",
                event="battery_monitor_unavailable",
            )
            return

        self._take_battery_sample("initial")
        if not self.mode.startswith("run"):
            return
        try:
            self.battery_timer_id = GLib.timeout_add(
                BATTERY_SAMPLE_INTERVAL_MILLISECONDS,
                self.guard_callback("battery sampling", self._on_battery_sample_timer, "battery_timer_id"),
            )
        except Exception as exc:
            self._record_battery_error(
                f"Could not schedule fifteen-second battery monitoring: {exc}"
            )
            return
        self._log_only(
            "battery_monitor_started",
            "OK",
            "Battery monitoring timer started.",
            {
                "interval_milliseconds": BATTERY_SAMPLE_INTERVAL_MILLISECONDS,
                "source_id": self.battery_timer_id,
                "batteries": selected_names,
            },
        )

    def stop_battery_monitoring(self) -> None:
        """Cancel periodic sampling and take the handled-exit observation."""
        if self.battery_monitor_stopped:
            return
        self.battery_monitor_stopped = True
        if self.battery_timer_id is not None:
            source_id = self.battery_timer_id
            self.battery_timer_id = None
            try:
                GLib.source_remove(source_id)
            except Exception as exc:
                self._record_battery_error(
                    f"Could not cancel battery monitoring timer: {exc}"
                )
            else:
                self._log_only(
                    "battery_monitor_stopped",
                    "OK",
                    "Battery monitoring timer stopped before teardown recovery.",
                    {"source_id": source_id},
                )

        if self.battery_monitor.devices:
            self._take_battery_sample("final")
            last_percentages = (
                self.battery_monitor.samples[-1].percentages
                if self.battery_monitor.samples
                else {}
            )
            statistics_errors: List[str] = []
            self.battery_statistics = []
            for device in self.battery_monitor.devices:
                try:
                    self.battery_statistics.append(
                        summarize_battery_statistics(
                            device.name, self.battery_monitor.samples
                        )
                    )
                except Exception as exc:
                    message = (
                        f"Could not calculate battery statistics for "
                        f"{device.name!r}: {exc}"
                    )
                    statistics_errors.append(message)
                    self._record_battery_error(message)
            self._log_only(
                "battery_monitor_summary",
                "OK" if not self.reported_battery_errors else "WARNING",
                "Battery monitoring completed for the handled run.",
                {
                    "sample_count": len(self.battery_monitor.samples),
                    "last_percentages": dict(last_percentages),
                    "percentage_sources": {
                        device.name: device.percentage_source
                        for device in self.battery_monitor.devices
                    },
                    "plot_suppressed": self.no_plot,
                    "statistics": [
                        result.to_log_details()
                        for result in self.battery_statistics
                    ],
                    "statistics_errors": statistics_errors,
                },
            )

    def print_battery_plot(self) -> None:
        """Print the optional chart and mandatory statistics after teardown."""
        if self.battery_plot_printed:
            return
        self.battery_plot_printed = True
        preferred = sys.stderr if any(sys.stdout is item for item in self.failed_output_streams) else sys.stdout
        output_parts: List[str] = []
        renderers = []
        if not self.no_plot:
            renderers.append(("battery chart", lambda: render_battery_depletion_chart(
                    self.battery_monitor.devices,
                    self.battery_monitor.samples,
                    self.terminal_style,
                    preferred,
                    lid_events=self.lid_events if self.ignore_lid else (),
                    suspend_intervals=self.suspend_monitor.intervals,
                    coverage_start=(
                        (self.suspend_monitor.initial.captured_at,
                         max(0.0, self.suspend_monitor.initial.boottime - self.started_boottime))
                        if self.suspend_monitor.started and self.suspend_monitor.initial else None
                    ),
                    coverage_end=(
                        (self.suspend_monitor.latest.captured_at,
                         max(0.0, self.suspend_monitor.latest.boottime - self.started_boottime))
                        if self.suspend_monitor.started and self.suspend_monitor.latest else None
                    ),
                )))
        renderers.append(("battery statistics", lambda: render_battery_statistics(
                self.battery_statistics,
                self.terminal_style,
                preferred,
            )))
        for label, render in renderers:
            try:
                output = render()
                if output:
                    output_parts.append(output.rstrip("\n"))
            except Exception as exc:
                message = f"Could not render {label}: {type(exc).__name__}: {exc}"
                self._record_failure(message, "terminal_render_failed")
                self._console_status("ERROR", message, sys.stderr)
        if output_parts:
            text = "\n" + "\n\n".join(output_parts) + "\n"
            if not self._write_output(text, preferred):
                alternate = sys.stdout if preferred is sys.stderr else sys.stderr
                self._write_output(text, alternate)

    def finish_suspend_monitoring(self) -> None:
        """Reconcile sleep after host recovery, before graph/report assembly."""
        if self.suspend_report_finalized or not self.suspend_monitor.started:
            return
        self.suspend_report_finalized = True
        self.suspend_monitor.finish()
        details = self.suspend_monitor.to_log_details()
        # Intervals remain separate records so a long run cannot overflow the
        # bounded final-session record with an embedded history array.
        if self.suspend_monitor.errors:
            message = "Suspend detection coverage is incomplete: " + "; ".join(self.suspend_monitor.errors)
            if message not in self.deviations:
                self.deviations.append(message)
            self._warn(message)
        for interval in self.suspend_monitor.intervals:
            self._log_only(
                "suspend_interval", "INFO", "Detected suspended time; boundaries are estimated.",
                interval.to_log_details(),
            )
        self._log_only(
            "suspend_monitor_summary", "INFO" if details["coverage_complete"] else "WARNING",
            "Reconciled suspend observations through the pre-report clock reading.", details,
        )

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
                DBUS_CALL_TIMEOUT_MILLISECONDS,
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
                    DBUS_CALL_TIMEOUT_MILLISECONDS,
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
                DBUS_CALL_TIMEOUT_MILLISECONDS,
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
                DBUS_CALL_TIMEOUT_MILLISECONDS,
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
                self.check_shutdown_requested()
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
        except ShutdownRequested:
            # Cancellation before a new device mutation is handled by the
            # common callback/finalization path, which restores prior devices.
            raise
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
                delay_milliseconds,
                self.guard_callback("backlight power-down", self._on_backlight_power_down, "backlight_timer_id"),
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
        if self.teardown_complete or self.teardown_started:
            return
        self.teardown_started = True
        self.teardown_in_progress = True

        def recover(label: str, action: Callable[[], Any]) -> None:
            try:
                action()
            except BaseException as exc:
                message = f"{label} failed during teardown: {type(exc).__name__}: {exc}"
                self._record_failure(message, "teardown_step_failed")
                self._console_status("ERROR", message, sys.stderr)

        recover(
            "Recording teardown start",
            lambda: self._log_only("teardown_started", "INFO", "Handled teardown started in safety-first order."),
        )
        recover("Final battery observation and statistics", self.stop_battery_monitoring)
        for attribute, label in (
            ("shutdown_signal_source_id", "Pending shutdown callback cancellation"),
            ("backlight_timer_id", "Backlight timer cancellation"),
            ("suspend_timer_id", "Suspend timer cancellation"),
        ):
            source_id = getattr(self, attribute)
            setattr(self, attribute, None)
            if source_id is not None:
                recover(label, lambda source_id=source_id: GLib.source_remove(source_id))

        recover("Backlight restoration", self.restore_backlights)
        recover("Inhibitor release", self.release_inhibitor_fds)
        recover("Power profile restoration", self.restore_power_profile)
        self.teardown_complete = True
        recover(
            "Recording teardown completion",
            lambda: self._log_only(
                "teardown_completed", "OK" if self.exit_code == 0 else "ERROR",
                "Handled teardown completed.", {"exit_code": self.exit_code},
            ),
        )

    # --------------------------------------------------------------------------
    # POWER PROFILE MANAGEMENT
    # --------------------------------------------------------------------------

    def _record_operation_failure(self, message: str) -> None:
        """Preserve failed recovery or action state before reporting the error."""
        self.exit_code = 1
        self.goal_achieved = False
        if message not in self.deviations:
            self.deviations.append(message)
        self._warn(message)

    def _read_power_profile(self) -> str:
        """Read and validate the daemon's current profile, never an assumed default."""
        result = self.power_proxy.call_sync(
            "Get",
            GLib.Variant("(ss)", (POWER_IFACE, "ActiveProfile")),
            Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MILLISECONDS,
            None,
        )
        profile = result.unpack()[0]
        if not isinstance(profile, str) or not profile.strip():
            raise RuntimeError(f"Invalid ActiveProfile value: {profile!r}")
        return profile

    def _available_power_profiles(self) -> List[str]:
        """Read advertised profiles before attempting a requested change."""
        result = self.power_proxy.call_sync(
            "Get",
            GLib.Variant("(ss)", (POWER_IFACE, "Profiles")),
            Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MILLISECONDS,
            None,
        )
        profiles = result.unpack()[0]
        if not isinstance(profiles, (list, tuple)) or not profiles:
            raise RuntimeError(f"Invalid Profiles value: {profiles!r}")
        names = []
        for profile in profiles:
            name = profile.get("Profile") if isinstance(profile, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise RuntimeError(f"Invalid profile entry: {profile!r}")
            names.append(name)
        return names

    def save_and_set_power_profile(self, target_profile: Optional[str]) -> bool:
        """Snapshot, apply, and verify a requested profile before taking inhibitors."""
        if not self.power_proxy:
            if target_profile:
                self._fatal_error(
                    f"Cannot apply requested power profile {target_profile!r}: "
                    "power-profiles-daemon is unavailable."
                )
            self._warn("power-profiles-daemon is unavailable; leaving the profile untouched.")
            return target_profile is None

        try:
            self.original_power_profile = self._read_power_profile()
            self.active_power_profile = self.original_power_profile
        except Exception as exc:
            self.original_power_profile = None
            self.active_power_profile = None
            message = f"Could not read the current power profile: {exc}"
            if target_profile:
                self._fatal_error(message + "; no profile change was attempted.")
            self._warn(message + "; leaving the profile untouched.")
            return False
        self._log_only(
            "power_profile_recorded",
            "OK",
            f"Recorded original power profile {self.original_power_profile!r}.",
            {"profile": self.original_power_profile},
        )
        self.check_shutdown_requested()
        if target_profile is None:
            return True
        if target_profile == self.original_power_profile:
            self.power_profile_change_verified = True
            return True

        try:
            available = self._available_power_profiles()
            if target_profile not in available:
                raise RuntimeError(
                    f"Requested profile {target_profile!r} is unavailable; "
                    f"advertised profiles: {', '.join(available)}"
                )
        except Exception as exc:
            self._fatal_error(f"Cannot select a power profile: {exc}")

        self._log_only(
            "power_profile_change_intent",
            "INFO",
            f"Requesting power profile {target_profile!r}.",
            {
                "original_profile": self.original_power_profile,
                "target_profile": target_profile,
            },
        )
        self.check_shutdown_requested()
        # A timeout or lost reply does not prove Set was rejected. Mark the
        # recovery obligation before dispatch so every uncertain mutation is
        # restored to the real snapshot during teardown.
        self.power_profile_changed = True
        self.active_power_profile = None
        try:
            self.power_proxy.call_sync(
                "Set",
                GLib.Variant(
                    "(ssv)",
                    (POWER_IFACE, "ActiveProfile", GLib.Variant("s", target_profile)),
                ),
                Gio.DBusCallFlags.NONE,
                DBUS_CALL_TIMEOUT_MILLISECONDS,
                None,
            )
            self.active_power_profile = self._read_power_profile()
            if self.active_power_profile != target_profile:
                raise RuntimeError(
                    f"verification read {self.active_power_profile!r}, "
                    f"expected {target_profile!r}"
                )
        except Exception as exc:
            self._fatal_error(
                f"Failed to apply and verify power profile {target_profile!r}: {exc}"
            )
        self.power_profile_change_verified = True
        self._info(
            f"Power profile switched and verified: {target_profile!r}.",
            event="power_profile_changed",
            details={"active_profile": target_profile, "verified": True},
        )
        # A signal during Set or failed result output must reach teardown
        # before normal mode can commit to retaining the changed profile.
        self.check_shutdown_requested()
        return True

    def restore_power_profile(self) -> None:
        """Restore and verify the snapshot after every temporary or uncertain Set."""
        if self.power_profile_retained or not self.power_profile_changed:
            return
        self.power_profile_restore_attempted = True
        self.power_profile_restore_verified = False
        if self.power_proxy is None or self.original_power_profile is None:
            self._record_operation_failure(
                "Cannot restore power profile: the daemon or original snapshot is unavailable."
            )
            return
        self._log_only(
            "power_profile_restore_intent",
            "INFO",
            f"Restoring original power profile {self.original_power_profile!r}.",
            {
                "active_profile": self.active_power_profile,
                "target_profile": self.original_power_profile,
            },
        )
        self.active_power_profile = None
        try:
            self.power_proxy.call_sync(
                "Set",
                GLib.Variant(
                    "(ssv)",
                    (POWER_IFACE, "ActiveProfile", GLib.Variant("s", self.original_power_profile)),
                ),
                Gio.DBusCallFlags.NONE,
                DBUS_CALL_TIMEOUT_MILLISECONDS,
                None,
            )
            self.active_power_profile = self._read_power_profile()
            if self.active_power_profile != self.original_power_profile:
                raise RuntimeError(
                    f"verification read {self.active_power_profile!r}, "
                    f"expected {self.original_power_profile!r}"
                )
        except Exception as exc:
            self._record_operation_failure(
                f"Failed to restore and verify original power profile "
                f"{self.original_power_profile!r}: {exc}"
            )
            return
        self.power_profile_changed = False
        self.power_profile_restore_verified = True
        self._info(
            f"Restored and verified original power profile: {self.original_power_profile!r}.",
            event="power_profile_restored",
            details={"active_profile": self.original_power_profile, "verified": True},
        )

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
        self.check_shutdown_requested()
        try:
            # call_with_unix_fd_list_sync allows receiving file descriptors over D-Bus
            res, out_fd_list = self.logind_proxy.call_with_unix_fd_list_sync(
                "Inhibit",
                GLib.Variant("(ssss)", (what_string, who_string, why_string, mode_string)),
                Gio.DBusCallFlags.NONE,
                DBUS_CALL_TIMEOUT_MILLISECONDS,
                None,
                None,
            )
            # Unpack the returned handle index and retrieve the OS file descriptor
            fd_index = res.unpack()[0]
            if type(fd_index) is not int or fd_index < 0 or out_fd_list is None:
                raise RuntimeError(f"Invalid inhibitor descriptor handle: {fd_index!r}")
            os_fd = out_fd_list.get(fd_index)
            if type(os_fd) is not int or os_fd < 0:
                raise RuntimeError(f"Invalid inhibitor file descriptor: {os_fd!r}")
            self.inhibitor_fds.append(os_fd)
            os.set_inheritable(os_fd, False)
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
        # Never retry a failed close: Linux may already have released the
        # descriptor number for reuse. Attempt every owned descriptor even if
        # another close or its diagnostic fails.
        owned_fds = self.inhibitor_fds
        self.inhibitor_fds = []
        failures: List[str] = []
        for fd in owned_fds:
            closed = False
            try:
                try:
                    self._log_only(
                        "inhibitor_release_intent",
                        "INFO",
                        f"Closing inhibitor file descriptor {fd}.",
                        {"file_descriptor": fd},
                    )
                finally:
                    os.close(fd)
                    closed = True
                self._info(
                    f"Released D-Bus inhibitor lock (closed FD {fd}).",
                    event="inhibitor_released",
                    details={"file_descriptor": fd},
                )
            except Exception as exc:
                if not closed:
                    self.inhibitor_release_failed = True
                failures.append(f"Error releasing inhibitor file descriptor {fd}: {exc}")
        for message in failures:
            try:
                self._record_operation_failure(message)
            except Exception:
                # Failure state was stored before diagnostics. All descriptors
                # have already received their close attempt.
                pass

    # --------------------------------------------------------------------------
    # LID STATE & SIGNAL MONITORING
    # --------------------------------------------------------------------------

    def _read_upower_boolean_property(self, name: str) -> bool:
        """Read an actual UPower boolean through the Properties interface."""
        if self.upower_proxy is None:
            raise RuntimeError("UPower is unavailable")
        result = self.upower_proxy.call_sync(
            "org.freedesktop.DBus.Properties.Get",
            GLib.Variant("(ss)", (UPOWER_IFACE, name)),
            Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MILLISECONDS,
            None,
        )
        value = result.unpack()[0]
        if type(value) is not bool:
            raise RuntimeError(f"Invalid UPower {name} value: {value!r}")
        return value

    def _lid_monitoring_required(self) -> bool:
        """A timed run or the default lid-cycle exit requires working lid telemetry."""
        return not self.ignore_lid or self.suspend_after_minutes is not None

    def validate_lid_monitoring(self) -> None:
        """Check required lid and timeout capabilities before operational mutation."""
        self.lid_capability_checked = True
        try:
            self.lid_monitoring_available = self._read_upower_boolean_property("LidIsPresent")
            if not self.lid_monitoring_available:
                raise RuntimeError("UPower reports no hardware lid sensor")
            # Validate state access now; startup reads it again after the
            # listener is installed to establish the initial event baseline.
            self._read_upower_boolean_property("LidIsClosed")
        except Exception as exc:
            self.lid_monitoring_available = False
            message = f"Lid monitoring is unavailable: {exc}"
            if self._lid_monitoring_required():
                self._fatal_error(message)
            self._warn(message + "; --ignore-lid without a timeout will await SIGINT/SIGTERM/SIGHUP.")
        if self.suspend_after_minutes is not None:
            try:
                self._require_sleep_capability("Suspend")
            except RunningLogError:
                raise
            except Exception as exc:
                self._fatal_error(f"Cannot establish the requested suspend timeout: {exc}")

    def check_initial_lid_state(self) -> None:
        """Read the initial lid state and arm the timeout for an already-closed lid."""
        if self.lid_capability_checked and not self.lid_monitoring_available:
            return
        try:
            self.current_lid_closed_state = self._read_upower_boolean_property("LidIsClosed")
        except Exception as exc:
            self.lid_monitoring_available = False
            message = f"Could not read initial 'LidIsClosed' property from UPower: {exc}"
            if self._lid_monitoring_required():
                self._fatal_error(message)
            self._warn(message + "; awaiting interrupt without lid monitoring.")
            return
        self.lid_monitoring_available = True
        state_str = "CLOSED" if self.current_lid_closed_state else "OPEN"
        self._info(
            f"Initial hardware lid state detected as: {state_str}.",
            event="lid_initial_state",
            details={"closed": self.current_lid_closed_state},
        )
        if self.current_lid_closed_state:
            self.lid_was_closed_during_session = True
            self._handle_lid_closed_event()

    def setup_upower_signal_listener(self) -> None:
        """
        Subscribes to UPower 'PropertiesChanged' signals to detect physical lid events.
        """
        if not self.upower_proxy:
            return
        self.upower_proxy.connect(
            "g-properties-changed",
            self.guard_callback("lid monitoring", self._on_upower_properties_changed),
        )
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
        """Process changed or invalidated lid properties without truthiness guesses."""
        unpacked_changes = changed_properties.unpack()
        if not isinstance(unpacked_changes, dict):
            raise RuntimeError("UPower property change payload is not a dictionary")
        for property_name in ("LidIsPresent", "LidIsClosed"):
            if property_name in invalidated_properties and property_name not in unpacked_changes:
                unpacked_changes[property_name] = self._read_upower_boolean_property(property_name)
            if property_name in unpacked_changes and type(unpacked_changes[property_name]) is not bool:
                raise RuntimeError(f"Invalid changed UPower {property_name} value")
        if unpacked_changes.get("LidIsPresent") is False:
            self.lid_monitoring_available = False
            if self._lid_monitoring_required():
                self._fatal_error("UPower reports that the hardware lid sensor disappeared.")
            self._warn("Hardware lid sensor unavailable; --ignore-lid session awaits interruption.")
            return
        if "LidIsClosed" not in unpacked_changes:
            return
        # A valid state observation establishes usable telemetry even when
        # recovery repeats the last state and therefore adds no transition.
        self.lid_monitoring_available = True
        new_state = unpacked_changes["LidIsClosed"]
        if new_state == self.current_lid_closed_state:
            return
        self.current_lid_closed_state = new_state
        # Retain the observation before crossing the logging boundary: a
        # failed append must not erase a transition already seen in this run.
        lid_event = LidEvent(
            datetime.now().astimezone(),
            max(0.0, linux_boottime() - self.started_boottime),
            new_state,
        )
        self.lid_events.append(lid_event)
        if new_state:
            self.lid_close_count += 1
            self.lid_was_closed_during_session = True
        else:
            self.lid_open_count += 1
        event_details = {
            "closed": new_state,
            "captured_at_local": lid_event.captured_at.isoformat(timespec="microseconds"),
            "elapsed_seconds": lid_event.elapsed_seconds,
            "timebase": "CLOCK_BOOTTIME",
            "lid_close_count": self.lid_close_count,
            "lid_open_count": self.lid_open_count,
        }
        if new_state:
            self._event(
                "Lid closure detected.",
                event="lid_closed",
                details=event_details,
            )
            self._handle_lid_closed_event()
        else:
            self._event(
                "Lid opening detected.",
                event="lid_opened",
                details=event_details,
            )
            self._handle_lid_opened_event()

    def _handle_lid_closed_event(self) -> None:
        """
        Executed when the laptop lid is closed. Starts the optional suspend timer.
        """
        if self.suspend_after_minutes is not None and self.suspend_after_minutes > 0:
            delay_seconds = self.suspend_after_minutes * 60
            if delay_seconds > 2 ** 32 - 1:
                self._fatal_error("Suspend timeout exceeds the GLib timer's supported range.")
            self._info(
                "Starting suspend countdown timer: requesting sleep after "
                f"{self.suspend_after_minutes} minute(s) of continuous lid closure.",
                event="suspend_timer_start_intent",
                details={"minutes": self.suspend_after_minutes},
            )
            # Cancel any previously running timer to prevent duplicates
            if self.suspend_timer_id is not None:
                GLib.source_remove(self.suspend_timer_id)
            self.suspend_timer_id = GLib.timeout_add_seconds(
                delay_seconds,
                self.guard_callback("suspend countdown", self._on_suspend_timer_expired, "suspend_timer_id"),
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

    def _require_sleep_capability(self, action: str) -> None:
        """Reject unsupported, denied, inhibited, or malformed sleep capabilities."""
        if self.logind_proxy is None:
            raise RuntimeError("systemd-logind is unavailable")
        event_prefix = action.lower()
        self._log_only(
            f"{event_prefix}_capability_query_intent",
            "INFO",
            f"Checking systemd-logind Can{action} capability.",
        )
        result = self.logind_proxy.call_sync(
            f"Can{action}",
            None,
            Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MILLISECONDS,
            None,
        )
        capability = result.unpack()[0]
        self._log_only(
            f"{event_prefix}_capability_recorded",
            "OK" if capability in ("yes", "challenge") else "WARNING",
            f"systemd-logind reported Can{action}={capability!r}.",
            {"capability": capability},
        )
        if capability not in ("yes", "challenge"):
            raise RuntimeError(
                f"{action} is unavailable or not permitted "
                f"(systemd-logind Can{action}={capability!r}). "
                "Check system sleep support, policy, and active inhibitors."
            )

    def _on_suspend_timer_expired(self) -> bool:
        """Request supported suspend, reporting success only after acceptance."""
        self.suspend_timer_id = None
        self.goal_achieved = False
        self.shutdown_reason = (
            f"Timeout expired after {self.suspend_after_minutes} minutes of lid closure"
        )
        try:
            self._event(
                f"Suspend timer ({self.suspend_after_minutes} min) expired.",
                event="suspend_timer_expired",
                details={"minutes": self.suspend_after_minutes},
            )
            self._require_sleep_capability("Suspend")
            self._info(
                "Sending D-Bus Suspend command to systemd-logind...",
                event="suspend_request_intent",
                details={"source": "lid_close_timer"},
            )
            self.check_shutdown_requested()
            self.logind_proxy.call_sync(
                "Suspend",
                GLib.Variant("(b)", (True,)),
                Gio.DBusCallFlags.NONE,
                POWER_ACTION_TIMEOUT_MILLISECONDS,
                None,
            )
            self._log_only(
                "suspend_request_sent",
                "OK",
                "systemd-logind accepted the timer-triggered suspend request.",
                {"source": "lid_close_timer"},
            )
            self.goal_achieved = self.exit_code == 0
        except (RunningLogError, ShutdownRequested):
            raise
        except Exception as exc:
            self.shutdown_reason = f"Timer-triggered suspend failed: {exc}"
            self._record_operation_failure(self.shutdown_reason)
        finally:
            if self.mainloop:
                self.mainloop.quit()
        return False

    # --------------------------------------------------------------------------
    # IMMEDIATE ACTION MODES: suspend, hibernate, normal
    # --------------------------------------------------------------------------

    def execute_immediate_action(self) -> None:
        """Perform a verified profile reset or a supported one-shot sleep request."""
        if self.mode == "normal":
            self._info("Applying normal mode: selecting the balanced power profile...")
            if self.save_and_set_power_profile("balanced"):
                # The operator explicitly requested this durable result. A
                # failed/uncertain Set has already gone through restoration;
                # only a verified successful result bypasses temporary rollback.
                self.power_profile_retained = True
                self.power_profile_changed = False
                self.goal_achieved = self.exit_code == 0
                self.shutdown_reason = "Balanced power profile explicitly requested and verified"
            return

        if self.mode not in ("suspend", "hibernate"):
            self._fatal_error(f"Unsupported immediate action: {self.mode!r}")
        action = "Suspend" if self.mode == "suspend" else "Hibernate"
        try:
            self._require_sleep_capability(action)
            self._info(
                f"Requesting immediate system {self.mode}...",
                event=f"{self.mode}_request_intent",
                details={"source": "immediate_mode"},
            )
            self.check_shutdown_requested()
            self.logind_proxy.call_sync(
                action,
                GLib.Variant("(b)", (True,)),
                Gio.DBusCallFlags.NONE,
                POWER_ACTION_TIMEOUT_MILLISECONDS,
                None,
            )
        except (RunningLogError, ShutdownRequested):
            raise
        except Exception as exc:
            self._fatal_error(f"Failed to request system {self.mode}: {exc}")
        self._log_only(
            f"{self.mode}_request_sent",
            "OK",
            f"systemd-logind accepted the immediate {self.mode} request.",
            {"source": "immediate_mode"},
        )
        self.goal_achieved = self.exit_code == 0
        self.shutdown_reason = f"Immediate system {self.mode} request accepted"

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

        if self.battery_monitor.devices:
            battery_names = ", ".join(
                device.name for device in self.battery_monitor.devices
            )
            plot_policy = (
                "statistics only at exit"
                if self.no_plot
                else "25-row exit plot + statistics"
            )
            self._narrative_field(
                "Battery Monitoring",
                f"{battery_names}; every 15 seconds; {plot_policy}",
            )
        else:
            self._narrative_field(
                "Battery Monitoring", "No installed system battery discovered"
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
                    "Lid-Closed Countdown",
                    f"{self.suspend_after_minutes} minute(s) after lid close",
                )
            else:
                self._narrative_field("Lid-Closed Countdown", "Disabled")
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
                print("                              expires, or SIGINT/SIGTERM/SIGHUP is received.")
            else:
                self._narrative_field(
                    "Expected Lifecycle",
                    "Persist until lid is closed and subsequently reopened,",
                )
                print("                              timer expires, or SIGINT/SIGTERM/SIGHUP is received.")
        else:
            self._narrative_field(
                "Expected Lifecycle", "Execute requested action immediately and exit."
            )
        self._narrative_rule()
        print()

    def print_shutdown_narrative(self) -> None:
        """Attempt independent reports, then synchronize their final outcome."""
        if self.shutdown_narrative_printed:
            return
        self.shutdown_narrative_printed = True
        try:
            self.finish_suspend_monitoring()
        except BaseException as exc:
            self._record_failure(f"Suspend reporting could not finish: {exc}")
        if self.exit_code != 0:
            self.goal_achieved = False

        def render_narrative() -> str:
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buffer:
                    self._render_shutdown_fields()
                return buffer.getvalue()
            except Exception as exc:
                self._record_failure(
                    f"Could not render shutdown narrative: {type(exc).__name__}: {exc}",
                    "terminal_render_failed",
                )
                return (
                    "\nBURNBAG — SHUTDOWN & TEARDOWN\n"
                    f"TERMINATED / INCOMPLETE: {self.shutdown_reason}\n"
                    + "\n".join(self.deviations) + "\n"
                )

        try:
            narrative = render_narrative()
            if not self._write_output(narrative, sys.stdout):
                # Re-render after a failed write so the surviving channel
                # reports that failure instead of repeating a success claim.
                self._write_output(render_narrative(), sys.stderr)
        finally:
            try:
                self.print_battery_plot()
            except BaseException as exc:
                self._record_failure(
                    f"Battery presentation failed: {type(exc).__name__}: {exc}",
                    "terminal_render_failed",
                )
            finally:
                self.finish_running_log()

    def _render_shutdown_fields(self) -> None:
        """Build the narrative separately from delivery and graph rendering."""
        print()
        self._narrative_rule()
        self._narrative_title("BURNBAG — SHUTDOWN & TEARDOWN")
        self._narrative_rule()
        success = self.goal_achieved and self.exit_code == 0
        status_str = "ACHIEVED SUCCESSFULLY" if success else "TERMINATED / INCOMPLETE"
        status_color = TerminalStyle.GREEN if success else TerminalStyle.RED
        self._narrative_field("Primary Mission Status", status_str, status_color)
        self._narrative_field("Final Reason for Exit", self.shutdown_reason)

        if self.suspend_monitor.started:
            suspend_details = self.suspend_monitor.to_log_details()
            count = suspend_details["interval_count"]
            if count:
                suspend_summary = (
                    f"{count} observed interval(s), "
                    f"{suspend_details['total_suspended_seconds']:.3f}s total; boundaries approximate"
                )
            elif suspend_details["coverage_complete"]:
                suspend_summary = "None detected (1 ms detection floor)"
            else:
                suspend_summary = "Unknown; no intervals verified"
            if not suspend_details["coverage_complete"]:
                suspend_summary += "; COVERAGE INCOMPLETE"
            self._narrative_field("Suspended Time", suspend_summary)

        if self.ignore_lid:
            lid_summary = f"close={self.lid_close_count}/open={self.lid_open_count}"
            if self.lid_capability_checked and not self.lid_monitoring_available:
                lid_summary += "; lid telemetry unavailable"
            self._narrative_field("Lid Events Detected", lid_summary)

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
        inhibitors_failed = bool(self.inhibitor_fds) or getattr(self, "inhibitor_release_failed", False)
        self._narrative_subfield(
            "D-Bus Inhibitors",
            "RELEASE FAILED; consult recorded errors" if inhibitors_failed
            else "All owned inhibitor descriptors released",
            TerminalStyle.RED if inhibitors_failed else TerminalStyle.GREEN,
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

        profile_color = TerminalStyle.GREEN
        if getattr(self, "power_profile_retained", False):
            profile_status = f"Retained verified '{self.active_power_profile}'"
        elif getattr(self, "power_profile_restore_verified", False):
            profile_status = f"Restored and verified '{self.active_power_profile}'"
        elif getattr(self, "power_profile_restore_attempted", False) or getattr(self, "power_profile_changed", False):
            profile_status = f"RESTORATION NOT VERIFIED; last observed '{self.active_power_profile}'"
            profile_color = TerminalStyle.RED
        elif self.active_power_profile is not None:
            profile_status = f"Unchanged; last observed '{self.active_power_profile}'"
        else:
            profile_status = "Unavailable; no profile change verified"
            profile_color = TerminalStyle.YELLOW
        self._narrative_subfield(
            "Power Profile", profile_status, profile_color
        )
        if self.running_log is not None:
            if self.running_log.failed_reason is None:
                running_log_status = f"Finalizing after this report: {self.running_log.path}"
                running_log_color = TerminalStyle.GREEN
            else:
                running_log_status = (
                    f"INCOMPLETE ({self.running_log.failed_reason})"
                )
                running_log_color = TerminalStyle.RED
            self._narrative_subfield(
                "Running Log", running_log_status, running_log_color
            )
        if self.battery_monitor.samples:
            last_sample = self.battery_monitor.samples[-1]
            battery_summary = ", ".join(
                f"{name}={percentage}%"
                for name, percentage in last_sample.percentages.items()
            )
            if not battery_summary:
                battery_summary = "Final readings unavailable"
            self._narrative_subfield(
                "Batteries",
                f"{battery_summary}; {len(self.battery_monitor.samples)} sample(s)",
            )
        else:
            self._narrative_subfield("Batteries", "No valid observations")
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
            self._console_status(
                "WARNING", message, sys.stderr, timestamp=timestamp
            )
            raise
        self._console_status(
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
            pass
        self._console_status(
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
        description="Linux Clamshell & Power Profile Control Utility ('burnbag')",
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
            "  hibernate     : Request hibernation after checking system capability.\n"
            "  run           : Inhibit lid-close suspend; maintain current power profile.\n"
            "  run-cool      : Inhibit lid-close suspend; switch to 'power-saver' profile.\n"
            "  run-balanced  : Inhibit lid-close suspend; switch to 'balanced' profile.\n"
            "  run-hot       : Inhibit lid-close suspend; switch to 'performance' profile.\n"
            "  normal        : Select, verify, and retain the 'balanced' power profile."
        ),
    )

    parser.add_argument(
        "--suspend-after-minutes",
        type=int,
        default=None,
        metavar="MIN",
        help="Request suspend after MIN minutes of continuous lid closure.",
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
            "cancels its active suspend countdown. Report close/open counts "
            "and mark their times on the exit graph."
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
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help=(
            "Suppress the 25-row battery depletion chart at exit; battery "
            "sampling, synchronized log records, and per-battery statistics "
            "remain enabled."
        ),
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
    suspend_clock_initial = None
    suspend_clock_error = None
    try:
        suspend_clock_initial = read_suspend_clocks()
    except Exception as exc:
        suspend_clock_error = f"Initial suspend clock reading failed: {type(exc).__name__}: {exc}"
    process_started_at = (
        suspend_clock_initial.monotonic if suspend_clock_initial else time.monotonic()
    )
    process_started_boottime = (
        suspend_clock_initial.boottime if suspend_clock_initial else linux_boottime()
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    terminal_style = TerminalStyle.detect(no_color="--no-color" in arguments)
    parser = build_argument_parser(terminal_style)
    if not arguments:
        print_no_argument_guide(parser, terminal_style)
        return 2

    args = parser.parse_args(arguments)

    # Validate logical constraints on CLI options
    if args.suspend_after_minutes is not None and not (
        1 <= args.suspend_after_minutes <= 0xFFFFFFFF // 60
    ):
        parser.error(
            "--suspend-after-minutes must be a positive integer no greater "
            f"than {0xFFFFFFFF // 60} (the timer backend limit)."
        )

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
                "show_battery_plot": not args.no_plot,
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
    previous_signal_handlers: Dict[int, Any] = {}
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
            no_plot=args.no_plot,
            started_monotonic=process_started_at,
            started_boottime=process_started_boottime,
            terminal_style=terminal_style,
            running_log=running_log,
            suspend_clock_initial=suspend_clock_initial,
            suspend_clock_error=suspend_clock_error,
        )

        def sig_handler(signum: int, frame: Any) -> None:
            manager.request_signal_shutdown(signum)

        # Protect every operational mode and setup step. Handlers only request
        # shutdown; safe checkpoints preserve resource ownership bookkeeping.
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, sig_handler)

        manager.suspend_monitor.start()
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
                "show_battery_plot": not args.no_plot,
            },
        )
        # Battery monitoring is read-only and begins before any operational
        # host mutation. Persistent modes schedule subsequent samples on the
        # same GLib loop used for lid and backlight lifecycle events.
        manager.start_battery_monitoring()
        manager.check_shutdown_requested()
        manager.print_startup_narrative()
        manager.check_shutdown_requested()
        manager.connect_dbus()
        manager.check_shutdown_requested()

        if not args.mode.startswith("run"):
            manager.execute_immediate_action()
        else:
            # --------------------------------------------------------------
            # PERSISTENT 'RUN*' MODE LIFECYCLE
            # --------------------------------------------------------------
            try:
                # Verify required lid telemetry and timed sleep capability
                # before changing any persistent host state.
                manager.validate_lid_monitoring()
                manager.check_shutdown_requested()

                # 1. Snapshot screen-backlight state and bind the caller's
                # logind session. The opt-out returns before discovery.
                manager.prepare_backlight_control()
                manager.check_shutdown_requested()

                # 2. Set requested power profile.
                target_prof = PROFILE_MAP.get(args.mode, None)
                manager.save_and_set_power_profile(target_prof)
                manager.check_shutdown_requested()

                # 3. Acquire D-Bus inhibitor locks.
                manager.acquire_inhibitor_locks()
                manager.check_shutdown_requested()

                # 4. Register UPower listener for physical lid events.
                manager.setup_upower_signal_listener()
                manager.check_shutdown_requested()
                manager.check_initial_lid_state()
                manager.check_shutdown_requested()

                # 5. Run the event loop. Backlight delay remains measured from
                # process start, not from completion of setup.
                manager.mainloop = GLib.MainLoop()
                manager.schedule_backlight_power_down()
                manager.check_shutdown_requested()
                wait_target = "lid events" if args.ignore_lid else "lid cycle"
                manager._info(
                    "Entering persistent event loop. "
                    f"Waiting for {wait_target} or interrupt...",
                    event="event_loop_entered",
                    details={"wait_target": wait_target},
                )
                manager.check_shutdown_requested()
                manager.mainloop.run()
                manager._log_only(
                    "event_loop_exited",
                    "INFO",
                    "Persistent event loop returned to handled teardown.",
                )
            except (ShutdownRequested, KeyboardInterrupt):
                raise
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
    except ShutdownRequested:
        # The first signal is recorded below, after setup has safely unwound.
        pass
    except KeyboardInterrupt:
        if manager is not None:
            manager.request_signal_shutdown(signal.SIGINT)
        else:
            pre_manager_reason = "Interrupted during runtime initialization."
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
    except Exception as exc:
        if manager is None:
            pre_manager_reason = f"Runtime initialization failed: {exc}"
            terminal_style.write_status("FATAL ERROR", pre_manager_reason, sys.stderr)
        else:
            manager.shutdown_reason = f"Operational lifecycle failed: {exc}"
            manager.deviations.append(manager.shutdown_reason)
            manager.goal_achieved = False
            manager.exit_code = 1
            try:
                manager._warn(manager.shutdown_reason)
            except (RunningLogError, OSError, ValueError):
                pass
    finally:
        if manager is not None:
            # Explicit brightness and profile mutations require cleanup;
            # logging failures are not permitted to interrupt this path.
            try:
                try:
                    manager.record_signal_shutdown()
                except BaseException as exc:
                    manager._record_failure(f"Could not record termination signal: {exc}")
                try:
                    manager.teardown()
                except BaseException as exc:
                    manager._record_failure(f"Teardown could not finish: {exc}")
                try:
                    manager.print_shutdown_narrative()
                except BaseException as exc:
                    manager._record_failure(f"Shutdown reporting could not finish: {exc}")
                    manager._console_status("ERROR", manager.shutdown_reason, sys.stderr)
                finally:
                    manager.finish_running_log()
                    result_code = manager.exit_code
            finally:
                for signum, previous_handler in previous_signal_handlers.items():
                    signal.signal(signum, previous_handler)
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
