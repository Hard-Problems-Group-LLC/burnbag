# Verification and manual platform checks

Run commands from the checkout root. Use distribution `/usr/bin/python3` so
native Gio/GLib tests use the same bindings as the installed executable.
Authorization and acceptance criteria are in [the roadmap](../ROADMAP.md).

## Automated verification

```bash
/usr/bin/python3 -B -m unittest discover -s tests
bash -n install.sh uninstall.sh scripts/install_prerequisites.sh
shellcheck install.sh uninstall.sh scripts/install_prerequisites.sh
./scripts/install_prerequisites.sh --check
./install.sh --check
./burnbag.py --help
./burnbag_viewer.py --help
./burnbag_viewerctl.py --help
groff -man -Tutf8 -z -ww burnbag-viewer.1
/usr/bin/python3 -B makedocs.py --check
git diff --check
```

Tests allocate unique disposable fixtures beneath `.local/tmp/`. They use real
files, locks, subprocess signals, native GLib, and staged installer destinations;
external power and backlight mutations use fakes. Native-GLib tests explicitly
skip on interpreters without PyGObject; a skipped suite does not establish
native integration readiness. No automated test suspends or hibernates the host.
The compatibility baseline is Python 3.9 or later; run the same discovery suite
on the oldest supported interpreter and a current release. Real SQLite,
socket ownership, concurrent prudent clients, fallback handoff, history merging,
and staged system/user uninstall are covered without installing host services.
Relative history tests cover the requested duration spellings, calendar
month-end/leap-year adjustment, daylight-saving gaps and ambiguities, and
actual SQLite range selection. Every installation mode and service scope
checks the installed CLI manual against its generated source, including its
`--last` calendar explanation, and installs the viewer manual in every mode.

README and manual sources live in `makedocs.py`. Regenerate with
`/usr/bin/python3 -B makedocs.py`; changes to generated output must be intentional
and `/usr/bin/python3 -B makedocs.py --check` must pass afterward. Render the manual with
`groff -man -Tutf8 -z -ww burnbag.1` to check formatting warnings.

## Physical validation awaiting the operator

The operator selected development installation. Run:

```bash
./install.sh --mode dev --dev-command local
```

This now installs and starts the default system collector as well as selecting
the checkout CLI. The daemon uses its own root-owned installed copy; rerun the
installer after changing collector code. Selecting `--install-user-service`
instead creates a login-session service whose dev daemon follows the checkout.
It does not enable lingering.
Then run `hash -r` and `command -v burnbag`; the result should be the managed
user launcher in `~/.local/bin/burnbag`. The installer reports any PATH ordering
problem. Use `man ./burnbag.1` to view this checkout's updated manual directly.
The system installer copies it to `/usr/local/share/man/man1/burnbag.1` by
default. Dev mode with `--install-user-service` instead copies it to
`~/.local/share/man/man1/burnbag.1`; rerun the installer after documentation
changes to refresh these installed copies.

Use `./burnbag.py` below to select the tested checkout explicitly. An existing
installed `burnbag` may still be an older copy. End any older burnbag session
before these checks so competing inhibitors or profile changes do not obscure
the result. Test on a desk with the laptop ventilated.

### 1. Original Ctrl-C symptom

```bash
./burnbag.py run --ignore-lid --do-not-touch-backlight
```

Wait at least 20 seconds, then press Ctrl-C. Expect one shutdown narrative,
one 25-row battery chart, and a battery summary. This ARM driver should identify
`energy_now/energy_full` as its percentage source. A short or flat run may show
`n/a` for trends and variability; that is expected and must not remove the chart.
The program must return to the shell without a traceback.

### 1a. Lid event counts and graph markers

For the new switch diagnostic, keep backlight control disabled so the output
remains visible while exercising the lid:

```bash
./burnbag.py run --ignore-lid --do-not-touch-backlight
```

Starting with the lid open, wait a few seconds, close and reopen it, wait a few
more seconds, then repeat. Press Ctrl-C after at least 20 seconds overall.
Expect `Lid Events Detected: close=2/open=2` for two observed cycles. The chart
should have magenta close lines and yellow open lines with `C`/`O` above them.
If events share a screen column, `B` and a line alternating magenta/yellow
identify both. Battery points and axis extrema labels must remain readable.
Extra counts are useful evidence for the switch investigation; they should
match the detected transition records rather than being silently discarded.

For plain output, add `--no-color`: close lines use `|`, open lines use `:`, and
shared columns use `!`. Counts remain present with `--no-plot` or no battery
observations. The startup state itself is not counted as a transition.

### 2. Physical lid, backlight, and profile

The following helper saves your original preference, starts each test from
`balanced`, checks the post-run profile, and restores your preference on exit.
Setup failures stop the test before burnbag runs. Define it and run the first
check from the checkout root:

```bash
burnbag_check_profile() (
    burnbag_test_original_profile=$(powerprofilesctl get) || exit
    trap 'powerprofilesctl set "$burnbag_test_original_profile" || exit 1' EXIT
    powerprofilesctl set balanced || exit
    ./burnbag.py "$@"
    burnbag_test_status=$?
    burnbag_test_restored_profile=$(powerprofilesctl get) || exit
    printf 'Run exit: %s; restored profile: %s (expected balanced)\n' \
        "$burnbag_test_status" "$burnbag_test_restored_profile"
    [ "$burnbag_test_status" -eq 0 ] && [ "$burnbag_test_restored_profile" = balanced ]
)
burnbag_check_profile run-cool
```

The startup output should verify a switch to `power-saver`. The screen should
turn off approximately three seconds after startup. Close the lid and reopen
it. The first complete close/open cycle should end the run, restore a visible
backlight, restore `balanced`, and print the chart and summary. If needed,
Ctrl-C also requests cleanup. The helper then restores your pre-test preference.

Repeat with the same helper, which establishes a fresh `balanced` baseline:

```bash
burnbag_check_profile run-cool --ignore-lid
```

Close and reopen the lid twice, then press Ctrl-C. With `--ignore-lid`, reopening
does not end the process or restore the screen: it stays dark until Ctrl-C.
Afterward, confirm the output records both close/open cycles, continuation after
opening, verified backlight/profile restoration, and one final chart/summary.

Report each result as pass/fail, with the exact visible error and whether the
screen and profile recovered. Relevant warnings and a concise error are enough.

### 3. Supervised suspend/resume

This is a separate physical platform check. Save other work and run it only
when interruption of the desktop is acceptable:

```bash
./burnbag.py run-cool --ignore-lid --suspend-after-minutes 1
```

Close the lid, allow the countdown to expire, then wake the laptop using its
normal controls. Confirm the command ends with its report and the screen and
original profile recover. If this platform fails to resume, record that as a
platform observation; the automated tests do not establish hardware suspend
reliability. Hibernation is currently reported unsupported by this host, so
there is no requested live hibernation test.

To verify the new suspend regions while burnbag remains active, use a separate
run with backlight control disabled:

```bash
./burnbag.py run --ignore-lid --do-not-touch-backlight
```

Wait at least 15 seconds, select **Suspend** from the desktop's power controls,
leave the system asleep for at least 20 seconds, then wake it normally. Wait
another 15 seconds and press Ctrl-C. If desired, repeat the supervised sleep
cycle before Ctrl-C to check separate regions. Expect the suspend summary to
report detected time and approximate boundaries, and a full-height block of
white capital `S` characters on a red background for each separately observed
region. A readable matching successful journal operation identifies suspend;
otherwise the report explicitly says its mode is unverified while preserving
the clock-confirmed region. The block covers all 25 data rows, including
battery/lid intersections; axis labels and any lid-marker header remain visible.
Battery data before and
after the block remains correctly positioned over the whole run. With
`--no-color`, the block uses plain `S`; `--no-plot` retains the suspend summary
and log while omitting the chart.

Report missing regions, an incomplete-observation diagnostic, or an unexpected
duration. Boundary positions are estimates between clock observations; rapid
sleeps can share a region. The earlier countdown test can finish reporting
before the accepted sleep request actually suspends the machine. A suspend
that starts after coverage ends must not create a block for that earlier run.

Hibernate classification and green `H` on magenta blocks are covered by
automated journal fixtures and graph checks. No live hibernation test is
requested on this host, which does not advertise that capability. On a future
supported platform, a completed hibernate/wake cycle during a continued run
can verify the `H` display when matching successful journal evidence is
readable. Without that evidence, expect clock-confirmed `S` with mode unverified;
the program must not guess hibernation from a request. Black `0` on dark gray is
reserved for future powered-off regions; current tests must not expect a
power-off detector or generated `0` blocks.

## Installation validation

`./install.sh --check` checks sources and native prerequisites without installing.
Use `--destdir` under a unique `.local/tmp/` child for staged file checks. Staging
does not elevate privileges, create host accounts, activate services, update
the host's manual index, or install host packages. `--skip-prerequisites`
deliberately skips only dependency checks.

Standard installation uses `./install.sh` and the default `/usr/local` prefix.
Development setup uses `./install.sh --mode dev`; publishing a user launcher
requires explicit selection or an affirmative interactive answer. To inspect
command selection, run `command -v burnbag` and clear an old shell lookup with
`hash -r`. `--dev-command system` removes only burnbag's managed user launcher.

## Continuous service acceptance

After installing the verified build, start with a desk check that does not
change power profiles or backlight state:

```bash
hash -r
burnbag --status-service
burnbag --help
burnbag --graph
```

Expect the selected system service to be active and recording health to be
ready. Help should have no absent-service warning. Allow at least 15 seconds
after installation; the graph query requests a bounded flush and should find
new system observations, retaining any nonconflicting earlier user history.
Use explicit `--from` and `--to` ISO timestamps to inspect an earlier interval.
For a range ending now, use `burnbag --graph --last 5m` or
`burnbag --graph --last 'five hours'`. `--last 5:00` means five minutes.
`--last 'one month'` preserves the earlier month's local date/time and adjusts
for month-end, as described in the installed manual.
If history overlaps, the warning and system preference are intentional.

To verify fallback and prudent writes, finish other burnbag runs, then:

```bash
burnbag --stop-service
burnbag --help
burnbag run --ignore-lid --do-not-touch-backlight --prudent-writes
```

Expect the service warning above and below help. Leave the run open for at
least 15 seconds, then press Ctrl-C. Expect its chart/summary, clean teardown,
and the same warning at both ends. It records private user history while the
background service is stopped. Inspect `burnbag --graph`, then restore service
recording with `burnbag --start-service` and verify `burnbag --status-service`.
Start/stop acts now; enable/disable changes automatic activation without
implicitly starting or stopping anything.

For continuous sleep coverage, leave the service running, save other work,
use the desktop's Suspend command, and wake normally after 20 seconds. Query
the interval with `burnbag --graph`. Expect a clock-confirmed sleep region;
missing journal permission can leave its mode explicitly unverified. No
foreground burnbag process is needed for this check. Do not request live
hibernation on this unsupported host.

Report service status, whether warning placement and fallback passed, and
whether the historical graph contains observations and the supervised sleep
region. Include any exact error. Live installation, reboot activation, and
physical sleep remain operator checks; staging and simulated clocks establish
neither real systemd activation nor hardware resume reliability.


## GTK history viewer manual verification

After `./install.sh --mode dev --dev-command local` and `hash -r`, open
`burnbag-viewer`. Check that the GNOME titlebar exposes working minimize,
restore, maximize, and close controls. F11 must enter and leave fullscreen; on
the graph tab the graph should fill the screen without the toolbar, status, or
tab strip.

Check both tabs. Search a value visible in telemetry (for example a battery
name), scroll through additional table pages, select a row range and choose
View selection, then double-click a row and a graph point. Each navigation must
switch tabs and preserve a useful graph range or matching table selection.
Try wheel zoom, drag/arrow pan, and choose another numeric measurement.

For the opt-in controller, use a private per-user runtime path:

```bash
socket="$XDG_RUNTIME_DIR/burnbag-viewer-check.sock"
burnbag-viewer --automation "$socket"
```

In another terminal, run `burnbag-viewerctl --socket "$socket" status`, toggle
F11 with `key F11`, switch tabs, select rows, and retrieve a PNG with
`capture --output "$XDG_RUNTIME_DIR/burnbag-viewer-check.png"`. Confirm the PNG
shows the entire viewer client area; GNOME's window decorations are supplied by
the window manager and are not part of the application frame. Close the viewer
and confirm its socket is removed. Normal launches must not create a socket.
