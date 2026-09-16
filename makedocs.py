#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
makedocs.py — Generates or checks checkout README.md and burnbag.1.
Bypasses web UI markdown parser bugs by avoiding nested code-fence literals.
"""

import argparse
import os
from pathlib import Path
import tempfile
import sys

# Programmatic code-fence delimiter to prevent UI markdown parser collisions
CB = chr(96) * 3

readme_lines = [
    "# burnbag",
    "",
    "**Clamshell control, continuous power history, historical graphs, and sleep diagnostics for Linux laptops.**",
    "",
    "`burnbag` is a desktop-agnostic, ephemeral D-Bus control utility for Ubuntu/Debian and Fedora/Red Hat Enterprise Linux family systems running GNOME or standard systemd/freedesktop stacks. It allows a laptop (such as a ThinkPad T480) to continue operating with its lid closed—whether docked on a desk or thrown into a backpack—while managing performance profiles and enforcing optional safety countdowns.",
    "",
    "---",
    "",
    "## Why \"burnbag\"?",
    "",
    "In intelligence and government work, a burn bag is where classified documents go for destruction. In systems engineering, it is what your backpack turns into when you throw a running laptop compiling code inside with zero airflow. `burnbag` controls power profiles and optional sleep countdowns. A countdown measures continuous lid-closed time; it does not measure temperature or establish a safe temperature limit.",
    "",
    "---",
    "",
    "## Architecture and recovery",
    "",
    "Unlike traditional lid-close scripts that permanently mutate `/etc/systemd/logind.conf` or set permanent `gsettings` overrides, `burnbag` uses **ephemeral D-Bus inhibitor file descriptors** (`org.freedesktop.login1.Manager.Inhibit`).",
    "",
    "* **Process-owned inhibitors:** Holding the returned Unix file descriptor open maintains the sleep/lid prohibition. If `burnbag` terminates normally, crashes, or is killed (`SIGINT`, `SIGTERM`, `SIGKILL`), the kernel closes the file descriptors, signaling `systemd-logind` to drop this process's inhibitor locks. Other inhibitors and OS policy still apply.",
    "* **Default Backlight Control:** Persistent `run*` modes record every kernel screen-backlight device, turn the backlight off three seconds after process startup, verify it is off, and restore and verify a nonzero brightness before every handled exit. `--do-not-touch-backlight` explicitly opts out.",
    "* **Validated Display Session:** Backlight control prefers the process's active local logind session. Launchers outside direct PID accounting, including tmux and user-service scopes, fall back through an inherited session ID to the operator's primary graphical session. Every candidate must match the effective UID, be active, and be local.",
    "* **Explicit State Restoration:** On normal completion, handled `SIGINT`/`SIGTERM`/`SIGHUP`, or a caught application error, `burnbag` attempts and verifies restoration of the backlight and any temporary power-profile change. Unverified restoration returns nonzero. `SIGKILL`, sudden power loss, and equivalent process destruction cannot run userspace teardown; unlike inhibitor FDs, explicit brightness and profile changes cannot be promised restoration in those cases.",
    "* **Narrative Verification:** Prints an explicit startup narrative before touching system state, and a structured teardown report upon exit detailing whether goals were achieved and any deviations observed.",
    "* **Adaptive Terminal Presentation:** Interactive terminals receive ANSI color and stronger visual hierarchy in runtime messages, help, usage tips, and errors. Redirected streams and explicit plain-output controls remain free of terminal escapes, and status meaning is always retained in text labels.",
    "* **Durable Running Log:** Every accepted operational session appends structured JSON Lines under the invoking user's XDG state directory. Each record is serialized across concurrent processes and synchronized with `fsync`; mutation intent is durable before safety-relevant host changes, and handled teardown is recorded before exit.",
    "* **Battery Depletion History & Statistics:** An optional system or user service collects available power measurements every five seconds. Without an accessible service, operational runs record to private user SQLite history. Up to two batteries feed a full-terminal-width, 25-row depletion chart plus quantization-aware trend and gauge-rate-variability statistics without changing charging or power-supply state.",
    "",
    "---",
    "",
    "## Requirements",
    "",
    "* **OS:** Ubuntu/Debian or Fedora/RHEL family Linux with systemd-logind; x86-64 and ARM64",
    "* **Python:** Distribution `/usr/bin/python3` (Python 3.9+)",
    "* **System Libraries:** PyGObject: `python3-gi gir1.2-glib-2.0` on Ubuntu/Debian; `python3-gobject` on Fedora/RHEL",
    "* **D-Bus Services:** `systemd-logind`; `UPower` for lid-driven behavior; `power-profiles-daemon` for requested profile changes.",
    "",
    "Install or verify the distribution-provided Python binding from the checkout:",
    "",
    f"{CB}bash",
    "./scripts/install_prerequisites.sh",
    "./scripts/install_prerequisites.sh --check",
    CB,
    "",
    "The PyPI package named `gobject` is unrelated and does not provide the `gi` module used by burnbag.",
    "",
    "---",
    "",
    "## Installation",
    "",
    "Install prerequisites, the terminal command, GTK viewer/controller, and manual pages under `/usr/local`:",
    "",
    f"{CB}bash",
    "./install.sh",
    CB,
    "",
    "The installer requests `sudo` only when package or system-file installation requires it. Use `./install.sh --check` for a read-only readiness check. `--destdir /absolute/staging/root` stages files without installing host packages, using sudo, or updating the host manual index. Paths containing `..`, escaping staging symlinks, and directory/symlink file targets are rejected. Use `./install.sh --help` for all options.",
    "",
    "For a repository-local development install, run:",
    "",
    f"{CB}bash",
    "./install.sh --mode dev",
    "command -v burnbag",
    CB,
    "",
    "In an interactive terminal, dev mode reports any competing `burnbag` command and asks whether bare invocations should prefer this checkout. If accepted, it installs managed launchers for `burnbag`, `burnbag-viewer` and `burnbag-viewerctl` under `~/.local/bin/` and verifies that command lookup selects each one. The user bin directory must already precede the installed command on `PATH`; the installer cannot change its parent shell's environment.",
    "",
    "Non-interactive dev installs leave existing launchers and command resolution unchanged unless policy is explicit. Declining the interactive prompt or reaching end-of-input also preserves them:",
    "",
    f"{CB}bash",
    "./install.sh --mode dev --dev-command local",
    "BURNBAG_DEV_LAUNCHER_MODE=local ./install.sh --mode dev",
    CB,
    "",
    "Use `--dev-command system` to remove the three managed user launchers and restore their other `PATH` results. Dev mode refuses to replace an unmanaged user launcher unless `--force` is explicit. When an automation environment supplies an isolated assistant `HOME`, pass `--user-home /absolute/operator/home`.",
    "",
    "With `--mode dev --install-user-service`, the installer copies the manual to `<user-home>/.local/share/man/man1/burnbag.1`. Rerun the installer after documentation changes to refresh that installed copy. The repository-local `.local/share/man/man1/burnbag.1` symlink continues to follow the checkout.",
    "",
    "---",
    "",
    "## Graphical history viewer",
    "",
    "`burnbag-viewer` opens the complete available system/user SQLite history in graph and paged-table tabs. Use `burnbag-viewer --last '5 hours'` for an initial viewport; add `--only` to keep queries, search, and navigation within that interval. `--only` requires `--last` or ISO `--from`/`--to` endpoints. Without `--only`, zoom/pan can leave the initial range. Months and years use the same local calendar subtraction and month-end adjustment as terminal graphs.",
    "",
    "The status line reports source counts; hover for database paths and failures. Graph/table double-clicks navigate between views, and F11 gives a graph-only fullscreen view. Reopen for a fresh snapshot of ongoing collection. GTK 4.6+ and system-Python Cairo integration are required (`python3-gi-cairo gir1.2-gtk-4.0` on Ubuntu/Debian). See `man burnbag-viewer` for data sources, ranges and opt-in Unix-socket automation.",
    "",
    "## Modes & Syntax",
    "",
    f"{CB}text",
    "burnbag <MODE> [OPTIONS]",
    CB,
    "",
    "### Operational Modes",
    "",
    "| Mode | Description |",
    "|---|---|",
    "| `run` | Inhibit lid-close suspend; maintain currently active power profile. |",
    "| `run-cool` | Inhibit lid-close suspend; switch to `power-saver` profile. |",
    "| `run-balanced` | Inhibit lid-close suspend; switch to `balanced` profile. |",
    "| `run-hot` | Inhibit lid-close suspend; switch to `performance` profile. |",
    "| `suspend` | Immediately trigger a one-shot system suspend. |",
    "| `hibernate` | Request system hibernation after checking platform support and policy. |",
    "| `normal` | Select, verify, and retain the `balanced` profile. Other running processes retain their own inhibitors. |",
    "",
    "Profiles are checked before a requested change. If `performance` is not advertised, `run-hot` fails clearly; use `powerprofilesctl list` to inspect available profiles. Plain `run` can leave profiles untouched when the profile daemon is unavailable. Lid-dependent runs require valid lid telemetry; `--ignore-lid` without a suspend countdown can operate without it. Suspend and hibernate requests check the system-reported capability first.",
    "",
    "### Options",
    "",
    "* `--suspend-after-minutes <MIN>`: Request suspend after `MIN` minutes of continuous lid closure. If the lid is opened before the timer expires, the timer is cancelled.",
    "* `--no-inhibit-auto-suspend`: Allow standard OS background idle timers to suspend the system normally while lid-switch sleep remains blocked.",
    "* `--ignore-lid`: Keep a `run*` mode active when the lid opens and show detected lid transitions on the exit battery graph. Lid opening still cancels an active suspend countdown; a later closure starts a fresh countdown. Without this option, the first observed close/open cycle ends the program.",
    "* `--do-not-touch-backlight`: Leave the screen backlight untouched. Without this opt-out, persistent `run*` modes turn every discovered backlight off three seconds after process startup and restore and verify it as on before handled exit.",
    "* `--log-file <FILE>`: Write the mandatory synchronized running log to an explicit absolute path instead of the XDG state default. The parent must be owned by the effective user and must not be group/world writable.",
    "* `--no-color`: Disable ANSI color in runtime messages, help, usage, and error output. Color remains automatic by default for interactive terminals.",
    "* `--no-plot`: Suppress the 25-row battery depletion chart, lid-event markers, and suspend/hibernate blocks at exit. Battery sampling, synchronized records, battery statistics, lid-transition counts, and suspend detection and summary remain enabled.",
    "* `-h`, `--help`: Display syntax and usage help.",
    "",
    "---",
    "",
    "## Terminal Output",
    "",
    "`burnbag` automatically adds color and visual hierarchy when the relevant standard-output or standard-error stream is an interactive terminal. It emits plain text when a stream is redirected, when `TERM=dumb`, when the `NO_COLOR` environment variable is present, or when `--no-color` is specified. Text labels such as `[INFO]`, `[OK]`, `[WARNING]`, and `[FATAL ERROR]` remain present in every mode, so color is never the only indication of status.",
    "",
    "The battery plot and statistical summary follow the same capability policy. Interactive output uses yellow for the first battery, blue for the second, and green where their plot lines overlap; gauge-rate variability and per-minute statistics use magenta. Plain output uses `1`, `2`, and `X` in the plot and retains statistic labels and units, so every meaning remains available with `--no-color` or redirected output.",
    "",
    "Running `burnbag` without a mode prints a concise quick-start guide to standard error and exits with status 2. `burnbag --help`, the zero-argument guide, and command-line validation run before PyGObject is loaded, so they remain available even when runtime prerequisites are not yet installed.",
    "",
    "---",
    "",
    "## Battery Monitoring, Exit Plot & Statistics",
    "",
    "Burnbag discovers present entries of type `Battery` under `/sys/class/power_supply` in lexical kernel-name order and monitors up to two independently. The collector samples every five seconds; operational runs consume actual available observations through handled teardown. Very short runs may end before the first observation becomes available. Percentage ordering and rate calculations use suspend-inclusive Linux `CLOCK_BOOTTIME`; local wall clock is presentation-only. Systems without an installed battery continue normally and omit battery output. Native `capacity` percentages are preferred; drivers without them use matching `energy_now/energy_full` or `charge_now/charge_full` readings, rounded to whole percentages. The selected source is identified and logged; invalid readings remain gaps.",
    "",
    "Every sampling cycle is recorded in SQLite using the selected batching policy. Operational JSONL records retain immediate durability. A battery discovery or read error is reported as an operational deviation and selects nonzero exit status, but it cannot prevent backlight restoration, inhibitor release, or power-profile restoration. If more than two eligible batteries are exposed, burnbag explicitly identifies the first two selected for monitoring and warns about the unplotted devices.",
    "",
    "At handled exit, burnbag draws exactly 25 data rows across the current standard-output terminal width, with a 20-column minimum and an 80-column fallback when width is unavailable. The Y axis spans only the minimum through maximum battery percentages actually observed. Its top always labels the maximum and its bottom always labels the minimum, even when both percentages are equal; constant data remains vertically centered. Each row has at most one observed percentage label.",
    "",
    "The X axis uses suspend-inclusive elapsed time and covers the whole run from application entry through the final post-recovery, pre-report observation. Startup and recovery remain visible even when battery readings cover less time; unsampled edges stay blank. Both boundaries always show the actual local wall-clock `HH:mm` of the coverage endpoints. Both endpoint labels are reserved before interior callouts, even when the displayed times are equal. If the entire plotted timeline has one elapsed value, its true endpoint labels repeat without inventing a duration and its points remain at the left. Boundary ticks align with the axis edges; interior ticks mark actual elapsed-time positions, and callouts leave at least two blank columns between labels. Missing readings remain gaps instead of being interpolated. `--no-plot` suppresses only this graph.",
    "",
    "With `--ignore-lid`, vertical markers behind the battery curves show detected closes in magenta and opens in yellow. Battery glyphs and series colors remain visible at intersections. A marker header uses `C=close`, `O=open`, and `B=both`; plain vertical lines use `|=close`, `:=open`, and `!=both`. If closes and opens share a column, the `!` marker alternates magenta/yellow in colored output. The chart still has 25 data rows. Shutdown reports separate detected close/open counts, including zero; these totals remain exact even when several events share a column. The initial lid snapshot and duplicate same-state notifications do not count as transitions. `--no-plot` preserves counts and event logging; without valid battery observations there is no graph, but the counts remain available.",
    "",
    "Actual sleep regions appear in every operational mode as full-height blocks: white `S` on red for suspend, green `H` on magenta for verified hibernation. Unverified sleep mode retains `S` with an explicit qualification. Plain output uses `S`/`H`. Each block covers all 25 data rows and takes precedence over battery curves and lid lines; axis labels and the separate lid header remain visible. If different kinds share a screen column, their glyphs and colors alternate down its rows. The shutdown summary reports detected suspended time, mode counts, and approximate boundaries. `--no-plot` keeps detection, summary, and logs; without valid battery observations there is no chart, but the summary remains available. Black `0` on dark gray is reserved for future powered-off regions; current runs do not detect or generate them.",
    "",
    "A read-only observer samples Linux `CLOCK_BOOTTIME` and `CLOCK_MONOTONIC` approximately once per second, independently of the event loop, from application entry through the final snapshot after recovery. Growth in their difference verifies suspended time, including during setup and teardown. Clock detection needs no journal access, extra package, or elevated privileges and never triggers sleep. A one-millisecond detection floor and clock-read uncertainty filter noise while cumulative accounting retains smaller changes. Boundaries are inferred within the bounding observations and qualified by uncertainty; scheduling delays widen that uncertainty, and multiple sleeps between observations can merge into one region. Clock or observer failure is reported as incomplete coverage, never as verified absence of sleep. See [the detection contract and primary clock reference](docs/specifications/power-lifecycle.md#actual-suspend-observation).",
    "",
    "When clock-confirmed sleep intervals exist, an optional read-only journal query can verify suspend or hibernate from an unambiguous successful systemd sleep operation in the same observation window. The query is limited to three seconds, 2 MiB, and 4,096 records. Failed requests, compound-mode labels alone, missing access, and ambiguous evidence leave the mode unverified while preserving measured sleep and clock coverage. Classification never requests sleep or guesses hibernation from intent. A final paired-clock read includes time spent querying; additional sleep remains mode-unverified without repeating the query. See [mode classification](docs/specifications/power-lifecycle.md#sleep-mode-classification).",
    "",
    "Below the graph, or by itself under `--no-plot`, burnbag prints one to three lines per battery. It reports endpoints, net percentage-point change, elapsed span, whole-run least-squares gauge trend, fit and coverage, and—when enough whole-percentage transitions exist—`gauge depletion-rate variability σ` in percentage points per hour. It also shows signed average reported-gauge change per minute and its nonnegative standard deviation in `pp/min`; falling SoC is negative and rising SoC is positive. These per-minute values are conversions of the same duration-weighted transition-rate distribution, not raw five-second derivatives or an independent physical measurement. The variability describes how uneven the reported depletion velocity was; it is not acceleration, watts, instantaneous load, or a claim of zero draw when the integer gauge stays flat. Missing readings, long intervals, and known charge-status changes break local-rate continuity, and short, flat, mixed, or gapped histories are explicitly qualified with `n/a` where necessary.",
    "",
    "`SIGKILL`, sudden power loss, and equivalent unhandled exits cannot take a final reading or render a chart. Samples synchronized before termination remain available in the running log.",
    "",
    "---",
    "",
    "Ctrl-C, SIGTERM, SIGHUP, a completed lid cycle, and handled errors all attempt the same final chart and summary once battery monitoring has begun, including with `--ignore-lid`. A broken stdout falls back to stderr when possible; output failure still selects nonzero status and cannot bypass restoration. Graph and statistics rendering are independent, so failure in one does not suppress the other.",
    "",
    "## Durable Running Log",
    "",
    "Every accepted operational invocation must establish its running log before PyGObject is loaded or host state is changed. The default path is `$XDG_STATE_HOME/burnbag/burnbag.log`, or `$HOME/.local/state/burnbag/burnbag.log` when `XDG_STATE_HOME` is unset. `--log-file /absolute/path` selects another file; there is deliberately no no-log option.",
    "",
    "The log is UTF-8 JSON Lines. Records include UTC and monotonic time, a session UUID, sequence number, process and user IDs, selected mode, stable event code, severity, message, and structured details. Battery discovery and operational summaries are recorded alongside the power lifecycle; periodic samples are stored in SQLite; the final summary includes versioned, unit-bearing derived statistics, signed per-minute average and standard deviation fields, and explicit validity reasons. `session_start` is synchronized before runtime initialization. A handled `session_end` is synchronized after backlight restoration, inhibitor release, power-profile restoration, and final reporting attempts, including observed output failures. If a process or the machine dies before handled teardown, the missing `session_end` remains useful evidence instead of being fabricated later.",
    "",
    "Each actual lid property transition is logged with its local wall-clock observation time, `CLOCK_BOOTTIME` elapsed time, and cumulative close/open counts. Lid events and battery samples share the same process-start elapsed origin. The final state includes `lid_close_count` and `lid_open_count`; individual transition records retain the history without copying an unbounded event array into the final record.",
    "",
    "Suspend observations are finalized after recovery. Separate `suspend_interval` records preserve measured duration, estimated boundaries, boottime/monotonic observation brackets, uncertainty, sleep kind, and classification source; `suspend_monitor_summary` records total suspended time, interval and sleep-kind counts, mode-classification status, coverage, and detector limitations or errors. Final state includes that bounded summary as `suspend_monitor`, without embedding interval history. These records remain enabled with `--no-plot`; an unhandled exit cannot finalize them.",
    "",
    "Each complete record is appended while holding an exclusive advisory lock and is followed by `fsync` before the operation continues. The managed directory is mode `0700` and the log is mode `0600`; symlink targets, non-regular files, multiply linked files, wrong ownership, and unsafe parent permissions are rejected. Failure to open, append, lock, or synchronize the log prevents further host mutation and returns nonzero. If logging fails after state has changed, teardown still takes precedence and runs to completion.",
    "",
    "Burnbag does not rotate, upload, truncate, or delete this file. Retention is operator-owned. An external rename-based rotation leaves an already-running process on its open inode while later sessions use the configured path.",
    "",
    "Inspect recent records without changing them:",
    "",
    f"{CB}bash",
    "tail -n 20 \"${XDG_STATE_HOME:-$HOME/.local/state}/burnbag/burnbag.log\"",
    CB,
    "",
    "---",
    "",
    "## Usage Examples",
    "",
    "**1. Request performance mode with a 20-minute continuous-lid-closure countdown:**",
    f"{CB}bash",
    "burnbag run-hot --suspend-after-minutes 20",
    CB,
    "",
    "**2. Run cool while listening to audiobooks or compiling background tasks with the lid closed:**",
    f"{CB}bash",
    "burnbag run-cool",
    CB,
    "",
    "**3. Keep running with lid closed, but allow standard GNOME background idle timeout to sleep the machine:**",
    f"{CB}bash",
    "burnbag run --no-inhibit-auto-suspend",
    CB,
    "",
    "**4. Select and retain the balanced power profile:**",
    f"{CB}bash",
    "burnbag normal",
    CB,
    "",
    "**5. Stay active across repeated lid close/open cycles until interrupted or a timeout expires:**",
    f"{CB}bash",
    "burnbag run-cool --ignore-lid --suspend-after-minutes 20",
    CB,
    "",
    "**6. Keep the screen backlight under desktop control instead of burnbag control:**",
    f"{CB}bash",
    "burnbag run-cool --do-not-touch-backlight",
    CB,
    "",
    "**7. Put an automation run in a separate synchronized log:**",
    f"{CB}bash",
    "burnbag run-cool --log-file /absolute/path/to/automation.jsonl",
    CB,
    "",
    "**8. Keep battery sampling and log history but omit the exit plot:**",
    f"{CB}bash",
    "burnbag run-cool --no-plot",
    CB,
    "",
    "## Development and verification",
    "",
    "See [the roadmap](ROADMAP.md), [behavior specifications](docs/specifications/README.md), and [automated/manual verification](docs/testing.md). Run `/usr/bin/python3 -B -m unittest discover -s tests` for the native suite. README and manual sources are in `makedocs.py`; `./makedocs.py --check` checks consistency without writing.",
]

readme_lines.extend(['',
 '## Continuous history and services',
 '',
 'The default installer installs, enables, and starts a **system service** running as the non-login '
 '`burnbag:burnbag` account. `./install.sh --install-user-service` selects a user service instead; it '
 'follows login sessions and does not enable lingering. Only one background collector can run per machine. '
 'Upgrades preserve intentionally stopped or disabled service state.',
 '',
 'Plain `./install.sh --mode dev` also installs a root-owned system-daemon copy while the CLI follows this '
 'checkout. `./install.sh --mode dev --install-user-service --dev-command local` makes the user daemon '
 'follow the checkout too. `--check` is read-only; `--destdir` stages files without changing host accounts '
 'or services. `./install.sh --install-user-service --prefix "$HOME/.local"` installs the standard '
 'executable and user service under user-owned paths.',
 '',
 'System telemetry is `/var/lib/burnbag/history.sqlite3`, readable by local accounts. User telemetry is '
 '`$XDG_STATE_HOME/burnbag/history.sqlite3` or `$HOME/.local/state/burnbag/history.sqlite3`, private to that '
 'account. The collector records available battery, charger, CPU, thermal, backlight, lid and profile '
 'information. Hardware capabilities determine which measurements exist. It never wakes the machine to '
 'sample.',
 '',
 'Samples are collected every five seconds and committed after **60 seconds or 64 KiB**, whichever comes '
 'first. Ordinary events commit within five seconds; lifecycle transitions and critical conditions request '
 'immediate commits; the kernel battery capacity level Critical makes its sample urgent. '
 'Abrupt failure can lose approximately the last minute of buffered measurements when '
 'storage is healthy. **`--prudent-writes` commits every update**: `burnbag run --ignore-lid '
 '--prudent-writes` temporarily requests this from the serving collector. Multiple requesting runs cannot '
 "cancel each other's prudent mode.",
 '',
 'The service is optional. Without accessible continuous recording, burnbag prints a prominent warning at '
 'the beginning and end of output, including help and usage errors, and operational runs record locally. An '
 "unhealthy service is diagnosed separately. Another user's private collector does not expose their history; "
 'the current run records locally. Existing JSONL operational diagnostics still synchronize mutation intent, '
 'outcomes, errors and session boundaries.',
 '',
 '| Command | Effect |',
 '| --- | --- |',
 '| `burnbag --status-service` | Report installation, activation and collector health. |',
 '| `burnbag --start-service` / `--stop-service` | Start or stop the selected service now. |',
 '| `burnbag --enable-service` / `--disable-service` | Enable or disable future automatic activation. |',
 '| `burnbag --start-user-service` / `--start-system-service` | Select a scope explicitly; all five actions '
 'support both spellings. |',
 '',
 'Unqualified management selects the active applicable service or sole installed scope. Ambiguous changes '
 'require an explicit scope. Service startup refuses conflicting ownership. Management uses existing systemd '
 "authorization; it does not control another user's service.",
 '',
 '### Historical graphs',
 '',
 '`burnbag --graph --from 2026-09-14T12:00:00-07:00 --to 2026-09-14T15:00:00-07:00` renders the battery '
 'graph, summary, lid markers and verified sleep regions for that interval. `burnbag --graph` selects the '
 'last 24 hours; `--to` defaults to now and omitted `--from` is 24 hours before the selected end. '
 '`--no-plot` retains the historical summary. ISO times accept offsets or Z; local times are accepted only '
 'when unambiguous and existent.',
 '',
 '`burnbag --graph --last 5h` selects the interval from five hours ago to now. Unit names and aliases '
 'are case-insensitive: `5H`, `"5 h"`, `"5 H"`, `"5 hours"`, `"five hours"`, `5:00:00` and `05:00:00` '
 'all select the same duration. **`5:00` means five minutes**: two clock fields are minutes:seconds; '
 'three are hours:minutes:seconds. Quote arguments containing spaces.',
 '',
 'Durations accept decimal quantities (`1.5h`), English integers (`"twenty-one minutes"`) and compounds '
 '(`1h30m` or `"one hour and thirty minutes"`). Supported units extend from seconds through minutes, '
 'hours, days, weeks, months, years, decades, centuries and millennia; `millenia` is also accepted. '
 '`m` always means minutes; use `mo` for months. Months and larger units subtract calendar months, '
 'preserving local time and clamping to the last day when needed: one month before March 31 is '
 'February 28 (29 in a leap year). Their combined quantity must equal whole months; `1.5 years` '
 'is 18 months, while `1.5 months` is invalid. Calendar units are combined and subtracted first, '
 'then smaller units as elapsed time; days are 24 hours and weeks are seven days. '
 '`--last` requires `--graph` and cannot be combined with '
 '`--from` or `--to`. Durations must be positive and contain units or clock fields. Unsupported words, '
 'signed values, invalid clock fields, ambiguous or nonexistent calendar targets at daylight-saving '
 'transitions, and ranges outside years 1 through 9999 fail with a usage error. Use explicit '
 '`--from`/`--to` offsets when a calendar target is ambiguous or nonexistent.',
 '',
 'See the [duration range contract](docs/specifications/duration-ranges.md) for unit aliases and exact '
 'duration semantics.',
 '',
 'Queries read both existing system and current-user databases and merge without changing either. Duplicate '
 'identities or conflicting collection coverage warn and prefer system observations; distinct events at the '
 'same time remain distinct. Missing, damaged or unreadable sources produce explicit partial-history '
 'warnings. Long queries retain representatives spanning the full interval with a resolution warning. '
 'Statistics on reduced queries describe those retained observations. If only lid or sleep events exist, '
 'an event timeline retains them with an unavailable battery scale labeled n/a. '
 'Calendar time forms the historical X axis; unobserved gaps stay blank and do not establish power-off. '
 'Black `0` on dark gray remains reserved. Queries touching the present request a bounded durable flush when '
 'possible.',
 '',
 '### Uninstall',
 '',
 '`./uninstall.sh --system-service` or `./uninstall.sh --user-service` stops and disables that installation '
 'and removes only managed files. Omit the scope only when it is unambiguous. History, configuration and '
 'service accounts are retained by default; **`--purge-data` explicitly removes the selected history**. '
 '`--prefix`, `--destdir`, `--user-home` and `--check` support matching installation locations and read-only '
 'checks. If both standard and dev user installations exist, select `--mode standard` or `--mode dev`. '
 'Finish foreground runs before purging user history. Shared artifacts remain while another installation '
 "references them. Dependencies and other users' files are preserved.",
 '',
 'See the [continuous history contract](docs/specifications/continuous-history.md) and [verification '
 'guide](docs/testing.md) for evidence limits and live service checks.'])

man_lines = [
    '.\\" Man page for burnbag(1)',
    '.\\" Target platform: Ubuntu/Debian and Fedora/RHEL; x86-64 and ARM64',
    '.TH BURNBAG 1 "September 2026" "burnbag 1.0" "User Commands"',
    '.SH NAME',
    'burnbag \\- ephemeral clamshell mode, battery monitoring, power profile, and sleep inhibition for Linux laptops',
    '.SH SYNOPSIS',
    '.B burnbag',
    '\\fIMODE\\fR [\\fIOPTIONS\\fR]',
    '.br',
    '.B burnbag',
    '\\-\\-graph [\\-\\-last \\fIDURATION\\fR | [\\-\\-from \\fITIME\\fR] [\\-\\-to \\fITIME\\fR]] [\\-\\-no\\-plot]',
    '.SH DESCRIPTION',
    '.B burnbag',
    'is a desktop\\-agnostic systems utility for Ubuntu/Debian and Fedora/RHEL family Linux distributions that temporarily inhibits',
    '.B systemd-logind',
    'lid\\-switch and idle\\-suspend events, controls screen backlights, manages',
    '.B power\\-profiles\\-daemon',
    'performance profiles, monitors installed batteries, and monitors hardware lid state via',
    '.BR UPower .',
    '.PP',
    'Unlike static configuration overrides,',
    '.B burnbag',
    'relies on ephemeral D\\-Bus inhibitor file descriptors. Holding these file descriptors open blocks the operating system from suspending when the laptop lid is shut. Upon normal exit, interrupt (\\fBSIGINT\\fR/\\fBSIGTERM\\fR/\\fBSIGHUP\\fR), or process death (\\fBSIGKILL\\fR), the kernel releases the file descriptors, instructing',
    '.B systemd-logind',
    "to drop this process's inhibitor locks. Other inhibitors and OS policy still apply.",
    '.PP',
    'Persistent run modes use the caller\\(aqs',
    '.B org.freedesktop.login1.Session.SetBrightness',
    'interface to turn every discovered kernel screen backlight off three seconds after process startup. On every handled exit, burnbag restores the recorded brightness and verifies that the backlight reports a nonzero value before terminating.',
    '.PP',
    'The control session is resolved from the process session, inherited XDG_SESSION_ID, or the user\\(aqs primary graphical logind session. A candidate must belong to the effective UID, be active, and be local. This supports tmux and user-service launchers whose PIDs are not assigned directly to a logind session.',
    '.PP',
    'Explicit backlight and power\\-profile restoration can run after normal completion, handled SIGINT/SIGTERM/SIGHUP, and caught application errors. It cannot run after SIGKILL, sudden power loss, or equivalent process destruction. Inhibitor file descriptors remain kernel\\-released in those cases.',
    '.PP',
    '.B burnbag',
    'provides narrative console logging on startup and exit, detailing intended system mutations, operational deviations, and the final shutdown state of D\\-Bus locks and power profiles.',
    '.PP',
    'Every accepted operational session also writes an append-only JSON Lines running log. Each complete record is serialized against concurrent burnbag writers and synchronized to the filesystem before execution continues.',
    '.PP',
    'An optional system or user service collects available power measurements every five seconds. Operational runs use its observations or collect into private user SQLite history when the service is unavailable. Shutdown includes quantization-aware per-battery statistics and, unless disabled, a full-width 25-row battery depletion plot.',
    '.SH MODES',
    'The following mutually exclusive operational modes are supported:',
    '.TP',
    '.B run',
    'Inhibit lid\\-close suspend events and maintain the currently active power profile. Persists until the lid is closed and subsequently reopened, a timeout expires, or an interrupt is received.',
    '.TP',
    '.B run\\-cool',
    'Inhibit lid\\-close suspend events and switch the system power profile to',
    '.BR power\\-saver .',
    'Requires the power-saver profile to be advertised by the system daemon; this is not a temperature guarantee.',
    '.TP',
    '.B run\\-balanced',
    'Inhibit lid\\-close suspend events and switch the system power profile to',
    '.BR balanced .',
    '.TP',
    '.B run\\-hot',
    'Inhibit lid\\-close suspend events and switch the system power profile to',
    '.BR performance .',
    '.TP',
    '.B suspend',
    'Immediately trigger a one\\-shot system suspend via D\\-Bus and exit.',
    '.TP',
    '.B hibernate',
    'Verify system hibernation capability via D\\-Bus, then request hibernation. Unsupported platform capabilities, missing prerequisites, or denied policy produce an explicit failure.',
    '.TP',
    '.B normal',
    'Select, verify, and retain the power profile',
    '.BR balanced ,',
    'then exit. Other running processes retain their own inhibitor descriptors; end those processes to release their locks.',
    '.PP',
    'Requested profiles must be advertised by power-profiles-daemon and are verified after changes and restoration. Unavailable profiles fail before inhibitor acquisition. Plain run can operate without the profile daemon. Lid-driven termination and countdowns require valid UPower lid telemetry; --ignore-lid without a countdown can await a signal without a sensor.',
    '.SH OPTIONS',
    '.TP',
    '.BI \\-\\-suspend\\-after\\-minutes " MIN"',
    'Request system suspend after',
    '.I MIN',
    'minutes of continuous lid closure. The countdown does not measure temperature. If the lid is reopened before',
    '.I MIN',
    'elapses, the countdown timer is cancelled.',
    '.TP',
    '.B \\-\\-no\\-inhibit\\-auto\\-suspend',
    'Do not acquire inhibitor locks for background system idle timers. The laptop will stay awake when the lid is closed, but standard OS idle policies (e.g., GNOME inactivity timeouts) remain permitted to trigger sleep.',
    '.TP',
    '.B \\-\\-ignore\\-lid',
    'Keep a run mode active when the lid opens instead of ending after the first observed close/open cycle, and show detected lid transitions on the exit battery graph. Opening the lid still cancels an active suspend countdown; a later closure starts a fresh countdown. Without this option, lid-open termination remains enabled by default.',
    '.TP',
    '.B \\-\\-do\\-not\\-touch\\-backlight',
    'Leave screen backlights untouched. Without this non-default opt-out, persistent run modes snapshot every kernel screen backlight, turn it off three seconds after process startup, verify it is off, and restore and verify a nonzero brightness before handled exit.',
    '.TP',
    '.BI \\-\\-log\\-file " FILE"',
    'Write the mandatory synchronized running log to absolute FILE instead of the XDG state default. The parent must be owned by the effective user and must not be group or world writable.',
    '.TP',
    '.B \\-\\-no\\-color',
    'Disable ANSI color in runtime messages, help, usage, and error output. Color remains automatic by default for interactive terminals.',
    '.TP',
    '.B \\-\\-no\\-plot',
    'Suppress the 25-row battery depletion chart, lid-event markers, and suspend/hibernate blocks at exit. Battery sampling, synchronized records, battery statistics, lid-transition counts, and suspend detection and summary remain enabled.',
    '.TP',
    '.BR \\-h ", " \\-\\-help',
    'Display syntax, mode descriptions, and usage examples, then exit.',
    '.SH TERMINAL OUTPUT',
    'When the relevant standard-output or standard-error stream is an interactive terminal, burnbag automatically adds ANSI color and visual hierarchy. Output remains plain when a stream is redirected, when TERM=dumb, when the NO_COLOR environment variable is present, or when',
    '.B \\-\\-no\\-color',
    'is specified. Text labels such as [INFO], [OK], [WARNING], and [FATAL ERROR] remain present, so color is never the only status indication.',
    '.PP',
    'Invoking burnbag without a mode prints a concise quick-start guide to standard error and exits with status 2. Help, the zero-argument guide, and command-line validation run before PyGObject is loaded.',
    '.SH BATTERY MONITORING, EXIT PLOT, AND STATISTICS',
    'Burnbag discovers present entries of type Battery under /sys/class/power_supply in lexical kernel-name order and monitors up to two independently. The collector samples every five seconds; operational runs consume actual available observations through handled teardown. Very short runs may end before the first observation becomes available. Percentage ordering and rate calculations use suspend-inclusive Linux CLOCK_BOOTTIME; local wall clock is presentation-only. Systems without a battery continue normally and omit battery output. Native capacity percentages are preferred; drivers without them use matching energy_now/energy_full or charge_now/charge_full readings rounded to whole percentages. The selected source is identified and logged; invalid readings remain gaps.',
    '.PP',
    'Every cycle is retained in SQLite under the selected batching policy; operational JSONL diagnostics remain immediately synchronized. Discovery or read failures are reported as operational deviations and select nonzero exit status, but never prevent backlight, inhibitor, or power-profile recovery. More than two eligible devices produce an explicit warning identifying which first two devices were selected.',
    '.PP',
    'The handled-exit chart contains exactly 25 data rows and uses the current standard-output terminal width, with a 20-column minimum and an 80-column fallback. Its Y axis spans only observed percentages. The top always labels the maximum and the bottom always labels the minimum, including equal percentages at both boundaries; constant data remains vertically centered. Each row has at most one observed percentage label.',
    '.PP',
    'The X axis uses suspend-inclusive elapsed time and covers the whole run from application entry through the final post-recovery, pre-report observation. Startup and recovery remain visible even when battery readings cover less time; unsampled edges stay blank. Both boundaries always label the actual local wall-clock HH:mm of the coverage endpoints. Both endpoint callouts are reserved before interior labels, even when their displayed times are equal. If the entire plotted timeline has one elapsed value, its true endpoint labels repeat without inventing a duration and its points remain at the left. Boundary ticks align with the axis edges; interior ticks mark actual elapsed-time positions, and adjacent callouts have at least two blank columns. Missing readings remain gaps.',
    '.PP',
    'With --ignore-lid, vertical markers behind battery curves show detected closes in magenta and opens in yellow. Battery glyphs and series colors remain visible at intersections. A marker header uses C=close, O=open, and B=both; plain vertical lines use |=close, :=open, and !=both. A shared close/open column uses ! with alternating magenta/yellow color. The chart still has 25 data rows. Shutdown reports separate detected close/open counts, including zero, even when several events share a column. The initial snapshot and duplicate same-state notifications do not count. Counts and event logging remain enabled with --no-plot. Without valid battery observations there is no graph, but counts remain available.',
    '.PP',
    'Actual sleep regions appear in every operational mode as full-height blocks: white S on red for suspend, green H on magenta for verified hibernation. Unverified sleep mode retains S with an explicit qualification. Plain output uses S/H. Blocks cover all 25 data rows and take precedence over battery curves and lid lines; axis labels and the separate lid header remain visible. If different kinds share a column, their glyphs and colors alternate down its rows. The shutdown summary reports detected suspended time, mode counts, and approximate boundaries. Detection, summary, and logs remain enabled with --no-plot. Without valid battery observations there is no chart, but the summary remains available. Black 0 on dark gray is reserved for future powered-off regions; current runs do not detect or generate them.',
    '.PP',
    'A read-only background observer samples Linux CLOCK_BOOTTIME and CLOCK_MONOTONIC approximately once per second from application entry through the final post-recovery snapshot, independently of the event loop. Growth in their difference verifies suspended time, including during setup and teardown. Clock detection needs no journal access, extra package, or elevated privileges and never triggers sleep. A one-millisecond floor and clock-read uncertainty filter noise while cumulative accounting retains smaller changes. Boundaries are inferred within bounding observations and qualified by uncertainty. Scheduling delays widen that uncertainty; several sleeps between observations can merge into one region. Clock or observer failure means incomplete coverage, never verified absence of sleep.',
    '.PP',
    'When clock-confirmed sleep intervals exist, an optional read-only journal query can verify suspend or hibernate from an unambiguous successful systemd sleep operation in the same observation window. The query is limited to three seconds, 2 MiB, and 4,096 records. Failed requests, compound-mode labels alone, missing access, and ambiguous evidence leave the mode unverified while preserving measured sleep and clock coverage. Classification never requests sleep or guesses hibernation from intent. A final paired-clock read includes time spent querying; additional sleep remains mode-unverified without repeating the query.',
    '.PP',
    'With ANSI color enabled, the first battery is yellow, the second blue, and overlap green. Plain output uses 1, 2, and X. Use',
    '.B \\-\\-no\\-plot',
    'to suppress only the graph.',
    '.PP',
    'Below the graph, or by itself when the graph is suppressed, burnbag prints one to three summary lines per battery. Endpoints, net percentage-point change, elapsed span, a whole-run least-squares gauge trend, fit, and coverage are shown. When enough reported whole-percentage transitions exist, gauge depletion-rate variability sigma is reported in percentage points per hour as the duration-weighted standard deviation of transition-to-transition gauge rates. The summary also shows signed average reported-gauge change per minute and its nonnegative standard deviation in pp/min; falling state of charge is negative and rising state of charge is positive. These are conversions of the same gated transition-rate distribution, not raw five-second derivatives or an independent physical measurement. They describe uneven reported depletion velocity, not acceleration, watts, instantaneous load, or zero draw when the integer gauge stays flat. Missing readings, long intervals, and known charge-status changes break local-rate continuity; short, flat, mixed, and gapped histories are explicitly qualified with n/a where necessary.',
    '.PP',
    'SIGKILL, sudden power loss, and equivalent unhandled exits cannot render a chart or summary or take a final sample; previously synchronized records remain available.',
    '.PP',
    'Ctrl-C, SIGTERM, SIGHUP, lid-cycle completion, and handled errors attempt the same shutdown chart and summary once battery monitoring starts, including with --ignore-lid. Output failure selects nonzero status but cannot prevent restoration. Broken stdout falls back to stderr when possible; graph and statistics rendering are independent.',
    '.SH RUNNING LOG',
    'Every accepted operational invocation establishes a mandatory append-only running log before PyGObject is loaded or host state is changed. The default path is $XDG_STATE_HOME/burnbag/burnbag.log, falling back to $HOME/.local/state/burnbag/burnbag.log. There is no no-log option.',
    '.PP',
    'The UTF-8 JSON Lines records include UTC and monotonic time, a session UUID, sequence number, PID, effective UID, selected mode, stable event code, severity, message, and structured details. Battery discovery and operational summaries are included; periodic samples are stored in SQLite instead of duplicated in this log; final battery records include versioned, unit-bearing derived statistics, signed per-minute average and standard-deviation fields, and explicit validity reasons. session_start is synchronized before runtime initialization. A handled session_end is synchronized after teardown and final reporting attempts, including observed output failures. Absence of session_end is retained as evidence of an unhandled process or power interruption.',
    '.PP',
    'Actual lid property transitions include local wall-clock observation time, CLOCK_BOOTTIME elapsed time, and cumulative close/open counts. Lid events and battery samples share one process-start elapsed origin. Final state includes lid_close_count and lid_open_count; individual transition records retain the history without copying an unbounded event array into the final record.',
    '.PP',
    'Suspend observations are finalized after recovery. Separate suspend_interval records retain duration, estimated boundaries, boottime/monotonic observation brackets, uncertainty, sleep kind, and classification source. suspend_monitor_summary records total suspended time, interval and sleep-kind counts, mode-classification status, coverage, and detector limitations or errors. Final state includes that bounded summary as suspend_monitor without embedding interval history. These records remain enabled with --no-plot; an unhandled exit cannot finalize them.',
    '.PP',
    'Each record is appended under an exclusive advisory lock and followed by fsync before execution continues. Safety-relevant mutation intent is synchronized before the mutation. Failure to resolve, open, validate, lock, append, or synchronize the log prevents further host mutation and returns nonzero. Logging failure never prevents backlight, inhibitor, or power-profile teardown.',
    '.PP',
    'The managed directory uses mode 0700 and the file mode 0600. Burnbag rejects symlink targets, non-regular or multiply linked files, incorrect ownership, and unsafe parent permissions. Burnbag does not rotate, upload, truncate, or delete logs; retention and external rename-based rotation are operator-owned.',
    '.SH SAFETY & EPHEMERAL INHIBITION',
    'Modifying',
    '.I /etc/systemd/logind.conf',
    'or permanent',
    '.B gsettings',
    'keys to prevent lid\\-close suspend introduces a physical thermal hazard: if forgotten, a running laptop placed inside an unventilated bag may overheat.',
    '.PP',
    '.B burnbag',
    'mitigates this by utilizing D\\-Bus calls to',
    '.BR org.freedesktop.login1.Manager.Inhibit .',
    'The daemon returns a file descriptor handle for each lock. As long as',
    '.B burnbag',
    'holds the handle open, sleep is blocked. When',
    '.B burnbag',
    'terminates, its owned descriptors close. Other processes and system policy may still inhibit sleep.',
    '.SH EXAMPLES',
    'Request performance mode with a 15\\-minute continuous-lid-closure countdown:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-hot \\-\\-suspend\\-after\\-minutes 15',
    '.RE',
    '.PP',
    'Run in power\\-saver mode indefinitely until the lid is opened or Ctrl\\-C is pressed:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-cool',
    '.RE',
    '.PP',
    'Stay active across repeated lid cycles with a 20\\-minute continuous-lid-closure countdown:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-cool \\-\\-ignore\\-lid \\-\\-suspend\\-after\\-minutes 20',
    '.RE',
    '.PP',
    'Run in power\\-saver mode without changing the screen backlight:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-cool \\-\\-do\\-not\\-touch\\-backlight',
    '.RE',
    '.PP',
    'Run with an explicit synchronized log path:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-cool \\-\\-log\\-file /absolute/path/to/automation.jsonl',
    '.RE',
    '.PP',
    'Run with battery monitoring and durable samples but no exit chart:',
    '.PP',
    '.RS 4',
    '.B burnbag run\\-cool \\-\\-no\\-plot',
    '.RE',
    '.PP',
    'Select and retain the balanced power profile:',
    '.PP',
    '.RS 4',
    '.B burnbag normal',
    '.RE',
    '.SH EXIT STATUS',
    '.TP',
    '.B 0',
    'Successful execution, complete lid cycle observed, or clean termination via interrupt (\\fBSIGINT\\fR/\\fBSIGTERM\\fR/\\fBSIGHUP\\fR).',
    '.TP',
    '.B 1',
    'Fatal error or unverified required state encountered (e.g., missing',
    '.B PyGObject',
    'dependencies, D\\-Bus connection failure, running-log durability failure, unsupported hibernation request, battery observation failure, or backlight mutation/restoration failure).',
    '.TP',
    '.B 2',
    'Command-line usage error, including invocation without a required operational mode.',
    '.SH INSTALLATION',
    'From a source checkout, install prerequisites, the executable, and this manual page with:',
    '.PP',
    '.B ./install.sh',
    '.PP',
    'For a repository\\-local development install, use:',
    '.PP',
    '.B ./install.sh \\-\\-mode dev',
    '.PP',
    'Interactive dev mode reports a competing burnbag command and asks whether bare invocations should prefer the checkout. When accepted, it installs a managed launcher under $HOME/.local/bin and verifies effective command lookup. That directory must already precede the installed command on PATH because an installer cannot change its parent shell environment.',
    '.PP',
    'Non\\-interactive callers select checkout resolution explicitly with:',
    '.PP',
    '.B ./install.sh \\-\\-mode dev \\-\\-dev\\-command local',
    '.PP',
    'or set BURNBAG_DEV_LAUNCHER_MODE=local. Use \\-\\-dev\\-command system to remove the managed user launcher and retain the other PATH result. Use \\-\\-user\\-home with an explicit operator home when automation supplies an isolated assistant HOME.',
    '.PP',
    'Use ./install.sh --check for a read-only readiness check. Staged --destdir installation checks prerequisites but does not install host packages, use sudo, or run mandb. Invalid paths and escaping symlinks are rejected. Noninteractive defaults and declined/EOF prompts preserve existing user launchers; explicit --dev-command system removes the managed launcher.',
    '.SH SYSTEM REQUIREMENTS',
    'Requires the distribution /usr/bin/python3 (Python 3.9+),',
    'PyGObject (python3-gi and gir1.2-glib-2.0 on Ubuntu/Debian; python3-gobject on Fedora/RHEL),',
    '.BR systemd\\-logind ,',
    '.BR power\\-profiles\\-daemon ,',
    'and',
    '.BR UPower .',
    '.SH AUTHOR',
    'Matthew C. Heck <mheck@hardproblemsgroup.com>',
    '.SH SEE ALSO',
    '.BR logind.conf (5),',
    '.BR systemd\\-logind.service (8),',
    '.BR upower (1),',
    '.BR powerprofilesctl (1)',
]

man_lines[man_lines.index(".SH EXAMPLES"):man_lines.index(".SH EXAMPLES")] = ['.SH CONTINUOUS HISTORY AND SERVICES',
 'An optional system or user burnbag.service records available power measurements every five seconds. '
 'Exactly one background collector owns the machine. An absent or unhealthy collector causes foreground '
 'operations to record into private user SQLite history. Prominent warnings wrap all CLI output, including '
 'help and rejected commands.',
 '.PP',
 'System history is /var/lib/burnbag/history.sqlite3 and is readable by local users. User history is '
 '$XDG_STATE_HOME/burnbag/history.sqlite3, falling back to $HOME/.local/state/burnbag/history.sqlite3. User '
 'history is private. Operational JSONL diagnostics retain immediate synchronization; routine samples are '
 'not duplicated there.',
 '.TP',
 '.B \\\\-\\\\-prudent\\\\-writes',
 'Commit every telemetry update durably. During an operational run, request this behavior from its collector '
 'until the run ends. Concurrent requests combine; a collector startup setting remains effective. Normally '
 'records commit after 60 seconds or 64 KiB, ordinary events within five seconds, and lifecycle/critical '
 'events immediately. Kernel battery capacity_level=Critical makes a sample urgent; a low percentage alone '
 'does not invent a critical state. Abrupt failure may lose approximately the latest minute while storage is healthy.',
 '.TP',
 '.B \\\\-\\\\-graph',
 'Render merged system and user battery history, summary, lid markers and observed sleep regions. Omitted '
 'bounds select the last 24 hours. --no-plot retains the summary. Existing databases are queried read-only; '
 'they are never created by querying.',
 '.TP',
 '.BI \\\\-\\\\-from " TIME"',
 'Historical start in ISO 8601. Default: 24 hours before the selected end. Local times must be unambiguous '
 'and existent; supply an offset or Z at daylight-saving transitions.',
 '.TP',
 '.BI \\\\-\\\\-to " TIME"',
 'Historical end in ISO 8601; default now. The start must precede the end. Queries including current time '
 'request a bounded collector flush. Reduced-query statistics describe retained observations. '
 'Without battery data, known events still produce a timeline with an n/a battery scale.',
 '.TP',
 '.BI \\-\\-last " DURATION"',
 'Graph a positive duration ending now. Requires --graph; conflicts with --from and --to. Unit spellings '
 'are case-insensitive. 5h, 5H, "5 h", "5 H", "5 hours", "five hours", 5:00:00 and 05:00:00 all mean '
 'five hours. Quote arguments containing spaces. Two clock fields mean minutes:seconds, so 5:00 means '
 'five minutes; three mean hours:minutes:seconds. Fields after the first must be less than 60. The final '
 'seconds field may have a decimal fraction.',
 '.PP',
 'Accepts decimal quantities such as 1.5h, English integers such as "twenty-one minutes", and compounds '
 'such as 1h30m or "one hour and thirty minutes". Units are seconds, minutes, hours, days, weeks, months, '
 'years, decades, centuries and millennia; millenia is accepted too. Singular names and common aliases '
 'are accepted. m means minutes; mo means months.',
 '.PP',
 'Months and larger units use calendar arithmetic: combine them into whole months, subtract once while '
 'preserving local time, and clamp the day to the last day of the target month when necessary. '
 'For example, one month before March 31 is February 28 (29 in a leap year). 1.5 years equals '
 '18 months; 1.5 months is invalid. Then subtract seconds through weeks as elapsed time: one day is '
 '24 hours and one week is seven days. Component order does not change the result.',
 '.PP',
 'Bare quantities, signed or nonpositive durations, unsupported words, malformed clock values, '
 'ambiguous or nonexistent local calendar targets at daylight-saving transitions, and ranges outside '
 'years 1 through 9999 are usage errors. Use explicit --from/--to offsets to resolve a daylight-saving '
 'calendar target.',
 '.TP',
 '.B \\\\-\\\\-enable\\\\-service, \\\\-\\\\-disable\\\\-service',
 'Enable or disable automatic activation without starting or stopping the current process. Use '
 '--enable-user-service, --enable-system-service, --disable-user-service or --disable-system-service for an '
 'explicit scope.',
 '.TP',
 '.B \\\\-\\\\-start\\\\-service, \\\\-\\\\-status\\\\-service, \\\\-\\\\-stop\\\\-service',
 'Start, inspect, or stop the current service. Each action also accepts an explicit user or system scope, '
 'for example --status-user-service and --stop-system-service. Automatic scope selects the active applicable '
 'service or sole installation; ambiguous changes fail with guidance.',
 '.TP',
 '.B \\\\-\\\\-collector',
 'Run the continuous collector under systemd. Requires --service-scope system or --service-scope user. '
 'Supports --prudent-writes as its baseline durability policy.',
 '.PP',
 'Historical queries warn on conflicting coverage or duplicate record identities and prefer system '
 'observations. Underlying records remain unchanged. Distinct equal-time events survive. Unreadable sources '
 'yield partial-result warnings; long queries disclose representative sampling. Calendar time forms the '
 'historical axis. Missing coverage never establishes suspend, hibernate or power-off.',
 '.SH SERVICE INSTALLATION AND REMOVAL',
 'install.sh selects a system service as the non-login burnbag user and group by default. '
 '--install-user-service selects the intended user and does not enable lingering. New installs enable and '
 'start; upgrades preserve intentional stopped/disabled state. Plain --mode dev installs a root-owned '
 'system-daemon copy and a checkout CLI; dev with --install-user-service runs the daemon from the checkout.',
 '.PP',
 'Dev with --install-user-service also installs a regular manual copy at '
 '<user-home>/.local/share/man/man1/burnbag.1. Rerun the installer after documentation changes to refresh '
 'that installed copy. The repository-local .local/share/man/man1/burnbag.1 symlink follows the checkout.',
 '.PP',
 '--check is read-only. --destdir stages files without host service/account changes. uninstall.sh '
 '--system-service or --user-service stops/disables the selected installation and removes managed files. '
 'History and configuration remain unless --purge-data explicitly selects history deletion. Dependencies and '
 'other users are untouched. If both user installation modes exist, select --mode standard or --mode dev. '
 'Finish foreground recording before purging user history. Shared files remain while another installation '
 'references them.']

def main(argv=None):
    """Anchor generated files to this checkout and publish each file atomically."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify generated files without writing")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    outputs = {"README.md": readme_lines, "burnbag.1": man_lines}
    try:
        mismatches = []
        for name, lines in outputs.items():
            target = root / name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise OSError(f"Refusing non-regular generated target: {target}")
            content = ("\n".join(lines) + "\n").encode("utf-8")
            if args.check:
                if not target.exists() or target.read_bytes() != content:
                    mismatches.append(name)
                continue
            # Atomic replacement requires a temporary sibling on the same
            # filesystem, rather than the general .local/tmp test workspace.
            descriptor, temporary = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=root)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    os.fchmod(stream.fileno(), 0o644)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        if mismatches:
            print("[ERROR] Generated documentation is out of date: " + ", ".join(mismatches), file=sys.stderr)
            return 1
    except OSError as exc:
        print(f"[ERROR] Documentation generation failed: {exc}", file=sys.stderr)
        return 1
    print("[OK] Generated documentation matches source." if args.check else
          "[OK] Generated README.md and burnbag.1 from checkout sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
