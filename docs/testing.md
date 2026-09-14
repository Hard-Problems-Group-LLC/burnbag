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

### 2. Physical lid, backlight, and profile

```bash
burnbag_test_original_profile=$(powerprofilesctl get)
powerprofilesctl set balanced
./burnbag.py run-cool
powerprofilesctl get
powerprofilesctl set "$burnbag_test_original_profile"
```

The screen should turn off approximately three seconds after startup. Close
the lid and reopen it. The first complete close/open cycle should end the run,
restore a visible backlight, restore `balanced`, and print the chart and
summary. Starting from `balanced` ensures that this checks a real profile
change and restoration; the last command returns to your pre-test preference.
If needed, Ctrl-C also requests cleanup.

Then repeat with `./burnbag.py run-cool --ignore-lid`: close and reopen the lid
twice, confirm reopening does not end the process, and press Ctrl-C to exit.
Backlight/profile restoration and one final chart/summary are still required.

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
