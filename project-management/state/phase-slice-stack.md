# Delivery phase and slice stack

This is the maintained execution state for [the roadmap](../../ROADMAP.md).
Update these tables at phase boundaries, slice transitions, and before long
validation or ACP waits. Record durable evidence in the linked project task
records; this file provides the recovery anchor for the current plan.

## Publication

Delivery: blocked

Notes: All-history correction and automated checks pass. Awaiting GNOME title-bar control check in BB-MANUAL-04; phase 9000 retains earlier manual checks.

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
| 3000 | active | GTK 4 history viewer |
| 9000 | blocked | Manual validation and final closure |

## Slices

| ID | Phase | State | Title |
| --- | --- | --- | --- |
| 1000 | P1 | done | Inventory Ubuntu services and bindings |
| 2000 | P1 | done | Repair prerequisite portability |
| 3000 | P1 | done | Verify packages and staged install |
| 4000 | P1 | done | Confirm desktop and lid hardware |
| 1000 | P2 | done | Inventory ARM platform capabilities |
| 2000 | P2 | done | Repair driver compatibility |
| 3000 | P2 | done | Verify native ARM battery sampling |
| 4000 | P2 | blocked | Confirm backlight, profiles, and suspend |
| 1000 | P3 | done | Reproduce missing shutdown report |
| 2000 | P3 | done | Unify handled finalization |
| 3000 | P3 | done | Test signals through actual GLib |
| 4000 | P3 | done | Confirm visible shutdown output |
| 1000 | P4 | done | Audit runtime and installer errors |
| 2000 | P4 | done | Harden runtime recovery |
| 3000 | P4 | done | Harden installer failures |
| 4000 | P4 | done | Verify injected failures and suite |
| 1000 | P5 | done | Synchronize behavior contracts |
| 2000 | P5 | done | Regenerate README and manual |
| 3000 | P5 | done | Validate delivery and installer handoff |
| 4000 | P5 | done | Publish evidence and handoff |
| 1000 | P6 | done | Specify approved behavior |
| 2000 | P6 | done | Implement SQLite and bounded writer |
| 3000 | P6 | done | Collect sensors and merge history |
| 4000 | P6 | done | Verify storage and failure paths |
| 1000 | P7 | done | Enforce singleton and readiness |
| 2000 | P7 | done | Collect events and sleep transitions |
| 3000 | P7 | done | Coordinate fallback and prudent clients |
| 4000 | P7 | done | Verify concurrent service behavior |
| 1000 | P8 | done | Add management and warning envelopes |
| 2000 | P8 | done | Connect foreground telemetry |
| 3000 | P8 | done | Render arbitrary-time history graphs |
| 4000 | P8 | done | Verify CLI and reporting |
| 1000 | P9 | done | Install system and user services |
| 2000 | P9 | done | Add scoped uninstaller |
| 3000 | P9 | done | Synchronize contracts and generated docs |
| 4000 | P9 | done | Verify installation and recovery |
| 1000 | P10 | done | Run complete automated checks |
| 2000 | P10 | done | Smoke-test sampling and isolated daemon |
| 3000 | P10 | done | Publish evidence and manual handoff |
| 1000 | 1000 | done | Set numbering and duration contract |
| 2000 | 1000 | done | Parse durations and calculate ranges |
| 3000 | 1000 | done | Integrate CLI and synchronize docs |
| 4000 | 1000 | done | Verify edge cases and publish |
| 1000 | 9000 | blocked | Await profile and suspend checks |
| 2000 | 9000 | pending | Handle any validation findings |
| 3000 | 9000 | pending | Close requests and publish closure |
| 4000 | 9000 | done | Collector and history verified |
| 5000 | 9000 | blocked | Await warning and fallback checks |
| 6000 | 9000 | pending | Verify service sleep coverage |
| 1000 | 3000 | done | Define viewer data and automation contracts |
| 2000 | 3000 | done | Build GTK shell and native window behavior |
| 3000 | 3000 | done | Show complete history by default |
| 4000 | 3000 | done | Add socket automation and controller |
| 5000 | 3000 | done | Integrate install and documentation |
| 6000 | 3000 | active | Verify and hand off GNOME checks |

## Regenerate local tracking

Run from this checkout:

```bash
python3 scripts/update_ubersight.py --dry-run
umask 077
python3 scripts/update_ubersight.py
```

The producer reads only the `Publication`, `Phases`, and `Slices` sections
above. Keep their exact headings and table columns. Phase IDs are unique;
slice IDs are unique only within their owning Phase column. Local slice IDs
restart at 1000 in every phase and never include a phase prefix. A phase and
a slice can share the same ID. The producer identifies a slice by the pair
of owning phase and local ID, then publishes just the local ID for the current
phase. All live slices use AGENTS.md's spaced numbering; historical references
such as P2.4 map to phase P2, slice 4000. States are `pending`,
`active`, `done`, or `blocked`. Each phase needs at least one slice. Exactly
one phase and one of its slices are active; slices in other phases cannot be
active. A pending phase may contain already completed independent slices.
A done phase must have all its slices done.

Keep phase rows in execution order and deferred validation phase 9000 after the active delivery phases. Ubersight shows only two phases before the active row and five after;
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
slice done, and retain the final deferred-validation phase as the active phase with all other phases done to
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
