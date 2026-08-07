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
import os
import signal
import sys
import time
from typing import Optional, List, Dict, Any

Gio: Any = None
GLib: Any = None


def load_pygobject() -> None:
    """Load the system D-Bus bindings after dependency-free CLI parsing."""
    global Gio, GLib

    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio as imported_gio, GLib as imported_glib
    except (ImportError, ValueError) as exc:
        sys.stderr.write(
            "[FATAL ERROR] PyGObject is unavailable to the active Python interpreter.\n"
            f"Active interpreter: {sys.executable}\n"
            "burnbag uses the Fedora/RHEL system package 'python3-gobject'.\n"
            "Install or verify it with:\n"
            "    ./scripts/install_prerequisites.sh\n"
            "or:\n"
            "    sudo dnf install python3-gobject\n"
            "The PyPI package named 'gobject' is unrelated and does not provide 'gi'.\n"
            f"Underlying exception details: {exc}\n"
        )
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

POWER_BUS_NAME = "net.hadess.PowerProfiles"
POWER_OBJECT_PATH = "/net/hadess/PowerProfiles"
POWER_IFACE = "net.hadess.PowerProfiles"

UPOWER_BUS_NAME = "org.freedesktop.UPower"
UPOWER_OBJECT_PATH = "/org/freedesktop/UPower"
UPOWER_IFACE = "org.freedesktop.UPower"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# Mapping from our CLI profile modes to net.hadess.PowerProfiles profile strings
PROFILE_MAP: Dict[str, str] = {
    "run-cool": "power-saver",
    "run-balanced": "balanced",
    "run-hot": "performance",
}


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
    ):
        # Configuration parameters from CLI arguments
        self.mode: str = mode
        self.suspend_after_minutes: Optional[int] = suspend_after_minutes
        self.no_inhibit_auto_suspend: bool = no_inhibit_auto_suspend
        self.ignore_lid: bool = ignore_lid

        # State tracking variables for clean teardown and narrative reporting
        self.original_power_profile: Optional[str] = None
        self.active_power_profile: Optional[str] = None
        self.inhibitor_fds: List[int] = []  # Open file descriptors holding systemd locks
        self.lid_was_closed_during_session: bool = False
        self.current_lid_closed_state: bool = False
        self.suspend_timer_id: Optional[int] = None
        self.shutdown_reason: str = "Unknown / Undefined"
        self.goal_achieved: bool = False
        self.deviations: List[str] = []

        # D-Bus connection and proxy placeholders
        self.bus: Optional[Gio.DBusConnection] = None
        self.logind_proxy: Optional[Gio.DBusProxy] = None
        self.power_proxy: Optional[Gio.DBusProxy] = None
        self.upower_proxy: Optional[Gio.DBusProxy] = None
        self.mainloop: Optional[GLib.MainLoop] = None

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

        # Apply new target profile if specified and different from current
        if target_profile and target_profile != self.original_power_profile:
            try:
                self.power_proxy.call_sync(
                    "Set",
                    GLib.Variant("(ssv)", (POWER_IFACE, "ActiveProfile", GLib.Variant("s", target_profile))),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                self.active_power_profile = target_profile
                print(f"[INFO] Power profile successfully switched to: '{target_profile}'.")
            except Exception as exc:
                err_msg = (
                    f"Failed to set power profile to '{target_profile}' ({exc}). "
                    "Remaining on default profile."
                )
                self._warn(err_msg)
                self.deviations.append(err_msg)

    def restore_power_profile(self) -> None:
        """
        Restores the power profile that was active before burnbag started.
        """
        if not self.power_proxy or not self.original_power_profile:
            return

        if self.active_power_profile != self.original_power_profile:
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
                print(f"[INFO] Restored system power profile to original state: '{self.original_power_profile}'.")
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
            print("[INFO] --no-inhibit-auto-suspend specified: normal OS background idle timers remain active.")

        what_string = ":".join(locks_to_acquire)
        who_string = "burnbag (User Utility)"
        why_string = f"User requested burnbag mode '{self.mode}' to continue operation with closed lid."
        mode_string = "block"  # 'block' prevents sleep; 'delay' only postpones it

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
            print(f"[INFO] Successfully acquired systemd-logind inhibitor lock for: [{what_string}].")
        except Exception as exc:
            self._fatal_error(
                f"Failed to acquire systemd-logind inhibitor lock for [{what_string}]: {exc}"
            )

    def release_inhibitor_fds(self) -> None:
        """
        Closes all open file descriptors for inhibitor locks, signaling systemd-logind
        to immediately drop our sleep/lid prohibitions.
        """
        for fd in self.inhibitor_fds:
            try:
                os.close(fd)
                print(f"[INFO] Released D-Bus inhibitor lock (closed FD {fd}).")
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
            print(f"[INFO] Initial hardware lid state detected as: {state_str}.")
            if self.current_lid_closed_state:
                self.lid_was_closed_during_session = True
                self._handle_lid_closed_event()
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
                    print("\n[EVENT] Lid closure detected.")
                    self.lid_was_closed_during_session = True
                    self._handle_lid_closed_event()
                else:
                    print("\n[EVENT] Lid opening detected.")
                    self._handle_lid_opened_event()

    def _handle_lid_closed_event(self) -> None:
        """
        Executed when the laptop lid is closed. Starts the optional suspend timer.
        """
        if self.suspend_after_minutes is not None and self.suspend_after_minutes > 0:
            delay_seconds = self.suspend_after_minutes * 60
            print(
                f"[INFO] Starting suspend countdown timer: machine will unconditionally "
                f"suspend in {self.suspend_after_minutes} minute(s)."
            )
            # Cancel any previously running timer to prevent duplicates
            if self.suspend_timer_id is not None:
                GLib.source_remove(self.suspend_timer_id)
            self.suspend_timer_id = GLib.timeout_add_seconds(
                delay_seconds, self._on_suspend_timer_expired
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
            print("[INFO] Suspend countdown timer cancelled because lid was reopened.")

        # --ignore-lid changes only lid-open termination. Lid monitoring and
        # timer cancellation remain active so subsequent closures can start a
        # fresh safety countdown.
        if self.ignore_lid:
            print("[INFO] --ignore-lid active: continuing after lid opening.")
            return

        # If we observed a full Close -> Open cycle, our job is done
        if self.lid_was_closed_during_session:
            self.shutdown_reason = "Lid cycle completed (lid was closed and subsequently reopened)"
            self.goal_achieved = True
            if self.mainloop:
                self.mainloop.quit()

    def _on_suspend_timer_expired(self) -> bool:
        """
        Callback triggered when `--suspend-after-minutes` reaches zero.
        Forces an immediate OS suspend and terminates the script loop.
        """
        print(f"\n[EVENT] Suspend timer ({self.suspend_after_minutes} min) expired.")
        self.suspend_timer_id = None
        self.shutdown_reason = f"Timeout expired after {self.suspend_after_minutes} minutes of lid closure"
        self.goal_achieved = True

        # Trigger system suspend via D-Bus call to systemd-logind
        try:
            print("[INFO] Sending D-Bus Suspend command to systemd-logind...")
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
            print("[INFO] Applying '--normal' defaults: switching power mode to 'balanced'...")
            self.save_and_set_power_profile("balanced")
            self.goal_achieved = True
            self.shutdown_reason = "Normal system defaults explicitly requested and applied"
            return

        if self.mode == "suspend":
            print("[INFO] Mode 'suspend' selected. Initiating immediate system suspend...")
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
            return

        if self.mode == "hibernate":
            print("[INFO] Mode 'hibernate' selected. Verifying system hibernation capability...")
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

            if can_hibernate_str in ("no", "na"):
                self.deviations.append("System reported hibernation is unsupported ('no'/'na').")
                self._fatal_error(
                    "Hibernation is not supported on this system.\n"
                    "        Note: Fedora uses zram by default, which does not support suspend-to-disk.\n"
                    "        A dedicated disk swap partition or swapfile must be configured."
                )

            print(f"[INFO] Hibernation capability confirmed ('{can_hibernate_str}'). Initiating hibernate...")
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
            return

    # --------------------------------------------------------------------------
    # NARRATIVE REPORTING (STARTUP & SHUTDOWN)
    # --------------------------------------------------------------------------

    def print_startup_narrative(self) -> None:
        """
        Prints a detailed, human-readable summary of the utility's intended actions
        and system modifications prior to execution.
        """
        print("=" * 80)
        print("                   BURNBAG — STARTUP NARRATIVE STATEMENT                    ")
        print("=" * 80)
        print(f"  • Operating Mode          : {self.mode.upper()}")

        # Profile explanation
        target_profile = PROFILE_MAP.get(self.mode, "Unchanged (keep active)")
        print(f"  • Target Power Profile    : {target_profile}")

        # Inhibitor locks explanation
        if self.mode.startswith("run"):
            lid_inhibit_str = "YES (Lid switch sleep blocked)"
            idle_inhibit_str = (
                "NO (OS background idle timers active)"
                if self.no_inhibit_auto_suspend
                else "YES (Background idle sleep blocked)"
            )
            print(f"  • Lid-Switch Inhibition   : {lid_inhibit_str}")
            print(f"  • Idle Sleep Inhibition   : {idle_inhibit_str}")
            lid_exit_str = (
                "DISABLED (--ignore-lid active)"
                if self.ignore_lid
                else "ENABLED (default close/open cycle ends the session)"
            )
            print(f"  • Lid-Open Termination    : {lid_exit_str}")

            if self.suspend_after_minutes:
                print(f"  • Unconditional Timeout   : {self.suspend_after_minutes} minute(s) after lid close")
            else:
                print("  • Unconditional Timeout   : Disabled")
        else:
            print("  • Inhibition Locks        : None (immediate one-shot operation)")

        print("  • Expected Lifecycle      : ", end="")
        if self.mode.startswith("run"):
            if self.ignore_lid:
                print("Persist across lid openings until a configured timer")
                print("                              expires, SIGINT, or SIGTERM is received.")
            else:
                print("Persist until lid is closed and subsequently reopened,")
                print("                              timer expires, SIGINT, or SIGTERM is received.")
        else:
            print("Execute requested action immediately and exit.")
        print("=" * 80 + "\n")

    def print_shutdown_narrative(self) -> None:
        """
        Prints a detailed final status report explaining achievement of goals,
        any operational deviations, and the final state of locks and power profiles.
        """
        print("\n" + "=" * 80)
        print("                  BURNBAG — SHUTDOWN & TEARDOWN NARRATIVE                   ")
        print("=" * 80)
        status_str = "ACHIEVED SUCCESSFULLY" if self.goal_achieved else "TERMINATED / INCOMPLETE"
        print(f"  • Primary Mission Status  : {status_str}")
        print(f"  • Final Reason for Exit   : {self.shutdown_reason}")

        print("  • Deviations Observed     : ", end="")
        if not self.deviations:
            print("None (execution proceeded exactly as specified)")
        else:
            print(f"{len(self.deviations)} deviation(s) recorded:")
            for idx, dev in enumerate(self.deviations, 1):
                print(f"        {idx}. {dev}")

        print("  • Final System State      : ")
        print("        - D-Bus Inhibitors  : All inhibitor locks released (OS safety defaults restored)")

        # Explain active power profile status
        final_prof = self.original_power_profile if self.original_power_profile else "Unknown"
        if self.mode == "normal":
            final_prof = "balanced"
        print(f"        - Power Profile     : Restored to '{final_prof}'")
        print("=" * 80)

    # --------------------------------------------------------------------------
    # ERROR & WARNING LOGGING
    # --------------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        """Outputs a timestamped warning message to standard error."""
        timestamp = time.strftime("%H:%M:%S")
        sys.stderr.write(f"[{timestamp}] [WARNING] {message}\n")

    def _fatal_error(self, message: str) -> None:
        """
        Records an error, executes clean teardown narrative, and terminates immediately.
        """
        timestamp = time.strftime("%H:%M:%S")
        sys.stderr.write(f"\n[{timestamp}] [FATAL ERROR] {message}\n")
        self.shutdown_reason = f"Fatal Error: {message}"
        self.goal_achieved = False
        self.release_inhibitor_fds()
        self.restore_power_profile()
        self.print_shutdown_narrative()
        sys.exit(1)


# ==============================================================================
# MAIN ORCHESTRATOR FUNCTION
# ==============================================================================

def main() -> None:
    """
    Parses arguments, initializes D-Bus monitoring, installs POSIX signal handlers,
    and runs the appropriate mode lifecycle.
    """
    parser = argparse.ArgumentParser(
        prog="burnbag",
        description="Fedora 44 / GNOME Clamshell & Power Profile Control Utility ('burnbag')",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Define mutually exclusive operational modes
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

    args = parser.parse_args()

    # Validate logical constraints on CLI options
    if args.suspend_after_minutes is not None and args.suspend_after_minutes <= 0:
        sys.stderr.write("[ERROR] --suspend-after-minutes must be a positive integer.\n")
        sys.exit(1)

    if not args.mode.startswith("run") and (
        args.suspend_after_minutes is not None
        or args.no_inhibit_auto_suspend
        or args.ignore_lid
    ):
        print(
            "[WARNING] --suspend-after-minutes, --no-inhibit-auto-suspend, "
            "and --ignore-lid "
            "have no effect unless a 'run*' mode is selected."
        )

    # argparse and argument validation do not require the runtime D-Bus binding.
    load_pygobject()

    # Instantiate our manager
    manager = LidCloseManager(
        mode=args.mode,
        suspend_after_minutes=args.suspend_after_minutes,
        no_inhibit_auto_suspend=args.no_inhibit_auto_suspend,
        ignore_lid=args.ignore_lid,
    )

    # State reporting before doing any work
    manager.print_startup_narrative()

    # Establish D-Bus communication
    manager.connect_dbus()

    # Handle immediate one-shot modes ('suspend', 'hibernate', 'normal')
    if not args.mode.startswith("run"):
        try:
            manager.execute_immediate_action()
        finally:
            manager.print_shutdown_narrative()
        sys.exit(0)

    # --------------------------------------------------------------------------
    # PERSISTENT 'RUN*' MODE LIFECYCLE
    # --------------------------------------------------------------------------

    # 1. Set requested power profile
    target_prof = PROFILE_MAP.get(args.mode, None)
    manager.save_and_set_power_profile(target_prof)

    # 2. Acquire D-Bus inhibitor locks
    manager.acquire_inhibitor_fds_wrap = manager.acquire_inhibitor_locks()

    # 3. Register UPower listener for physical lid events
    manager.setup_upower_signal_listener()
    manager.check_initial_lid_state()

    # 4. Set up POSIX signal handling for clean exit on Ctrl-C / SIGTERM
    def sig_handler(signum: int, frame: Any) -> None:
        sig_name = "SIGINT (Ctrl-C)" if signum == signal.SIGINT else "SIGTERM"
        print(f"\n[EVENT] Received interrupt signal: {sig_name}.")
        manager.shutdown_reason = f"User termination signal received ({sig_name})"
        manager.goal_achieved = True
        if manager.mainloop:
            manager.mainloop.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # 5. Execute GLib Event MainLoop
    manager.mainloop = GLib.MainLoop()
    wait_target = "lid events" if args.ignore_lid else "lid cycle"
    print(f"[INFO] Entering persistent event loop. Waiting for {wait_target} or interrupt...")
    try:
        manager.mainloop.run()
    except Exception as exc:
        manager._warn(f"Unhandled exception in main event loop: {exc}")
        manager.deviations.append(f"Main loop terminated unexpectedly: {exc}")
        manager.shutdown_reason = f"Unhandled exception: {exc}"
    finally:
        # Guarantee inhibitor cleanup and profile restoration on any exit path
        if manager.suspend_timer_id is not None:
            GLib.source_remove(manager.suspend_timer_id)
            manager.suspend_timer_id = None
        manager.release_inhibitor_fds()
        manager.restore_power_profile()
        manager.print_shutdown_narrative()


if __name__ == "__main__":
    main()
