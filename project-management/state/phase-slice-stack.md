# Delivery phase and slice stack

This is the maintained execution state for [the roadmap](../../ROADMAP.md).
Update these tables at phase boundaries, slice transitions, and before long
validation or ACP waits. Record durable evidence in the linked project task
records; this file provides the recovery anchor for the current plan.

## Publication

Delivery: blocked

Notes: Awaiting operator 2000.5000 warning/fallback results. 2000.6000 service sleep and BB-MANUAL-01/02 profile/suspend checks remain. Phase 1000 complete and pushed (754deab); 378 native tests and both compatibility suites passed.

## Phases

| ID | State | Title |
| --- | --- | --- |
| P1 | done | Ubuntu support |
| P2 | blocked | ARM platform support |
| P3 | done | Shutdown graph and summary |
| P4 | done | Error and exception hardening |
| P5 | done | Documentation and installation |
| P6 | done | Durable telemetry |
| P7 | done | Collector services |
| P8 | done | CLI and history graphs |
| P9 | done | Installation and documentation |
| P10 | done | Integration and handoff |
| 1000 | done | Relative history durations |
| 2000 | active | Manual validation and final closure |

## Slices

| ID | Phase | State | Title |
| --- | --- | --- | --- |
| P1.1 | P1 | done | Inventory Ubuntu services and bindings |
| P1.2 | P1 | done | Repair prerequisite portability |
| P1.3 | P1 | done | Verify packages and staged install |
| P1.4 | P1 | done | Confirm desktop and lid hardware |
| P2.1 | P2 | done | Inventory ARM platform capabilities |
| P2.2 | P2 | done | Repair driver compatibility |
| P2.3 | P2 | done | Verify native ARM battery sampling |
| P2.4 | P2 | blocked | Confirm backlight, profiles, and suspend |
| P3.1 | P3 | done | Reproduce missing shutdown report |
| P3.2 | P3 | done | Unify handled finalization |
| P3.3 | P3 | done | Test signals through actual GLib |
| P3.4 | P3 | done | Confirm visible shutdown output |
| P4.1 | P4 | done | Audit runtime and installer errors |
| P4.2 | P4 | done | Harden runtime recovery |
| P4.3 | P4 | done | Harden installer failures |
| P4.4 | P4 | done | Verify injected failures and suite |
| P5.1 | P5 | done | Synchronize behavior contracts |
| P5.2 | P5 | done | Regenerate README and manual |
| P5.3 | P5 | done | Validate delivery and installer handoff |
| P5.4 | P5 | done | Publish evidence and handoff |
| P6.1 | P6 | done | Specify approved behavior |
| P6.2 | P6 | done | Implement SQLite and bounded writer |
| P6.3 | P6 | done | Collect sensors and merge history |
| P6.4 | P6 | done | Verify storage and failure paths |
| P7.1 | P7 | done | Enforce singleton and readiness |
| P7.2 | P7 | done | Collect events and sleep transitions |
| P7.3 | P7 | done | Coordinate fallback and prudent clients |
| P7.4 | P7 | done | Verify concurrent service behavior |
| P8.1 | P8 | done | Add management and warning envelopes |
| P8.2 | P8 | done | Connect foreground telemetry |
| P8.3 | P8 | done | Render arbitrary-time history graphs |
| P8.4 | P8 | done | Verify CLI and reporting |
| P9.1 | P9 | done | Install system and user services |
| P9.2 | P9 | done | Add scoped uninstaller |
| P9.3 | P9 | done | Synchronize contracts and generated docs |
| P9.4 | P9 | done | Verify installation and recovery |
| P10.1 | P10 | done | Run complete automated checks |
| P10.2 | P10 | done | Smoke-test sampling and isolated daemon |
| P10.3 | P10 | done | Publish evidence and manual handoff |
| 1000.1000 | 1000 | done | Set numbering and duration contract |
| 1000.2000 | 1000 | done | Parse durations and calculate ranges |
| 1000.3000 | 1000 | done | Integrate CLI and synchronize docs |
| 1000.4000 | 1000 | done | Verify edge cases and publish |
| 2000.1000 | 2000 | blocked | Await profile and suspend checks |
| 2000.2000 | 2000 | pending | Repair and verify reported defects |
| 2000.3000 | 2000 | pending | Close requests and publish closure |
| 2000.4000 | 2000 | done | Installed collector and history verified |
| 2000.5000 | 2000 | active | Await warning and fallback checks |
| 2000.6000 | 2000 | pending | Verify service sleep coverage |

## Regenerate local tracking

Run from this checkout:

```bash
python3 scripts/update_ubersight.py --dry-run
umask 077
python3 scripts/update_ubersight.py
```

The producer reads only the `Publication`, `Phases`, and `Slices` sections
above. Keep their exact headings and table columns. IDs must be unique;
slice IDs begin with their owning phase ID and a period. New IDs use 1000-step
phase and slice numbering from AGENTS.md, for example 1000.2000; legacy IDs
remain stable. States are `pending`,
`active`, `done`, or `blocked`. Each phase needs at least one slice. Exactly
one phase and one of its slices are active; slices in other phases cannot be
active. A pending phase may contain already completed independent slices.
A done phase must have all its slices done.

Keep phase rows in execution order and final validation 2000 after the delivered
phases. Ubersight shows only two phases before the active row and five after;
appending delivered work after 2000 can hide recent completion. Titles are clipped
to one line, so keep the current action recognizable in a narrow pane. Lead
blocked notes with the operator wait because the phase-stack view does not
show the global blocked label.

`Delivery` is `active`, `blocked`, or `complete`; `Notes` is one concise line.
When manual checks are deferred, mark their slices and phase `blocked`, keep
the deferred scope in [the human requests](../ai-human-requests.md), and
activate the next independent phase and slice. Set delivery to `blocked` only
when all remaining work awaits input; keep the current owning phase and slice
active and describe the wait in notes. Ubersight requires this active row even
while blocked. On final completion, set delivery to `complete`, mark every
slice done, and retain 2000 as the active phase with all other phases done to
satisfy the writer's phase requirement.

The installed `ubersight` console command supplies the atomic status writer;
the producer invokes it with an argument list after validating the entire
stack. It publishes all phases and the active phase's slices under the
explicit `burnbag-main` context, using the project root as working directory.
Writer mode does not run dashboard host inspection or network probes.

The ignored `.local/ubersight/status.json` is a disposable projection using
`ubersight.status.v1`, never the source of delivery history. Regenerate it
after checkout, cache loss, or context recovery. No prompts, transcripts,
credentials, private host details, or runtime identifiers belong in these
tables or status notes. Keep `.local/` private and out of commits.

Republish on work start/resume, slice or phase transitions, long verification
or publication waits, manual deferral, and closeout. A refresh must recheck
the durable records; do not keep an idle dashboard looking active with blind
timestamp updates. The default stale threshold is 900 seconds. Use the
installed writer for atomic replacement; a restrictive umask (`077`) keeps
new status files private. The project-owned `.local/ubersight/` directory is
private to the operator. Environment caches and per-job runtime telemetry
have separate owners and must not be rewritten to manufacture agent progress.

Validated against installed Ubersight 0.1.0, with writer source matching
revision `1ec5d3ccb662f89f7b8c8b8cfd47349894094545`. The protocol and
side-effect boundary are described in
[FieldManual's Ubersight guidance](../../FieldManual/knacks/software-engineering/development-observability/ubersight.knack.md).
