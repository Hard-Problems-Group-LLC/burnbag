# AI Human Requests

Bounded operator checks for the Ubuntu/ARM delivery. Exact commands and expected
results are in [the testing guide](../docs/testing.md).

## Pending Requests

No additional queued requests.

## Active Requests

- `BB-MANUAL-01` — Revised-build graph, lid, backlight, and profile confirmation.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Covers roadmap P2.4 and P3.4; all prerequisite automated work is complete.
  - Operator selected self-installation with `./install.sh --mode dev` after
    readiness. Accept checkout command selection at its prompt and run
    `hash -r`. No agent installation into `/usr/local` is requested.
  - Run [checks 1 and 2](../docs/testing.md#physical-validation-awaiting-the-operator):
    first an untimed `--ignore-lid --do-not-touch-backlight` run for at least
    20 seconds ending with Ctrl-C; then ordinary and repeated-ignore-lid cycles
    with backlight control and a real balanced-to-power-saver transition.
  - Acceptance: one graph and summary, valid derived battery readings, clean
    shell return, visible screen restoration, correct profile restoration,
    and expected lid termination/continuation. Report pass/fail and errors.
  - Baseline evidence: the operator's older installed run already confirmed
    lid events, delayed screen-off, verified screen restoration, and inhibitor
    release. It closed P1.4, but did not validate the revised battery reader,
    changed-and-restored profile, or physical suspend/resume.

- `BB-MANUAL-02` — Supervised ARM suspend/resume.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Covers P2.4. Perform [check 3](../docs/testing.md#3-supervised-suspendresume)
    when desktop interruption is acceptable, after saving other work.
  - Acceptance: the one-minute continuous-lid-closure countdown requests sleep;
    after normal wake, burnbag exits with its report and the screen and profile
    recover. Report failures or unexpected wake behavior.
  - Hibernation is reported unsupported on this host; no hibernation test is
    requested. Automated tests establish request/failure handling, not physical
    suspend reliability.

## Completed Requests

No revised-build manual requests have completed yet.
