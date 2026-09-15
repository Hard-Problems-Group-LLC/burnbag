# Verification and manual platform checks

Run commands from the checkout root. Use distribution `/usr/bin/python3` so
native Gio/GLib tests use the same bindings as the installed executable.
Authorization and acceptance criteria are in [the roadmap](../ROADMAP.md).

## Automated verification

```bash
/usr/bin/python3 -B -m unittest discover -s tests
bash -n install.sh scripts/install_prerequisites.sh
shellcheck install.sh scripts/install_prerequisites.sh
./scripts/install_prerequisites.sh --check
./install.sh --check
./burnbag.py --help
/usr/bin/python3 -B makedocs.py --check
git diff --check
```

Tests allocate unique disposable fixtures beneath `.local/tmp/`. They use real
files, locks, subprocess signals, native GLib, and staged installer destinations;
external power and backlight mutations use fakes. Native-GLib tests explicitly
skip on interpreters without PyGObject; a skipped suite does not establish
native integration readiness. No automated test suspends or hibernates the host.

README and manual sources live in `makedocs.py`. Regenerate with
`/usr/bin/python3 -B makedocs.py`; changes to generated output must be intentional
and `/usr/bin/python3 -B makedocs.py --check` must pass afterward. Render the manual with
`groff -man -Tutf8 -z -ww burnbag.1` to check formatting warnings.

## Physical validation awaiting the operator

The operator selected development installation. Run `./install.sh --mode dev`
and answer **yes** when it asks whether bare `burnbag` should use this checkout.
Then run `hash -r` and `command -v burnbag`; the result should be the managed
user launcher in `~/.local/bin/burnbag`. The installer reports any PATH ordering
problem. Use `man ./burnbag.1` to view this checkout's updated manual directly.

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
region. The block covers all 25 data rows, including battery/lid intersections;
axis labels and any lid-marker header remain visible. Battery data before and
after the block remains correctly positioned over the whole run. With
`--no-color`, the block uses plain `S`; `--no-plot` retains the suspend summary
and log while omitting the chart.

Report missing regions, an incomplete-observation diagnostic, or an unexpected
duration. Boundary positions are estimates between clock observations; rapid
sleeps can share a region. The earlier countdown test can finish reporting
before the accepted sleep request actually suspends the machine. A suspend
that starts after coverage ends must not create a block for that earlier run.

## Installation validation

`./install.sh --check` checks sources and native prerequisites without installing.
Use `--destdir` under a unique `.local/tmp/` child for staged file checks. Staging
does not elevate privileges, update the host's manual index, or install host
packages. `--skip-prerequisites` deliberately skips only dependency checks.

Standard installation uses `./install.sh` and the default `/usr/local` prefix.
Development setup uses `./install.sh --mode dev`; publishing a user launcher
requires explicit selection or an affirmative interactive answer. To inspect
command selection, run `command -v burnbag` and clear an old shell lookup with
`hash -r`. `--dev-command system` removes only burnbag's managed user launcher.
