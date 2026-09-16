# Development Roadmap

Use this record for durable phase and workstream planning. It complements the
ordered backlog and the active-task record; it does not replace either.

## Maintenance Rules

- Add only approved or explicitly directed scope.
- Link phases and workstreams to proposals, specifications, and decisions.
- Update status when the source records change.
- Do not put credentials, host identifiers, or other local state here.

## Status Terms

- `planned`
- `active`
- `blocked`
- `complete`
- `deferred`

## Phases

The operator requested a root [ROADMAP.md](../ROADMAP.md) on 2026-09-14.
It is the canonical phase design for Ubuntu support, ARM support, shutdown
reporting, exception hardening, documentation/installer consistency, continuous
history and services, phase 1000 relative graph durations, and phase 3000 GTK 4
history viewer. Phase 3100's viewer delivery/rendering fixes and initial/locked
time ranges are complete, including follow-up slice 5000's authoritative
command/service installation modes and FieldManual ECR-003. On 2026-09-16,
phase 3100, slice 5000 was reactivated for the system dev service bind-path
quoting defect (BB-BUG-2026-09-16-01). The repair passes all 57 affected installer
tests, including a real parser regression that fails before the fix. After
integration with delivered phases 5000–7000, all 65 installer tests pass;
operator reinstallation and restart verification are pending in
BB-MANUAL-06. Agents do not run sudo commands.
Phase 4000 is complete: persistent graph/table field selection through a modal
Fields dialog, automation, real GTK verification and synchronized documentation.
Phase 5000 is complete: standard sudo installation no longer assumes root's
PATH matches the caller's shell, and managed launcher cleanup selects the
validated caller home. Operator deployment and all three normal-shell command
paths passed on 2026-09-15, closing BB-MANUAL-05.
Phase 3000 awaits visible GNOME controls;
phase 6000 is complete for shared-rectangle traces, grouped unit scales,
alternating axis strips, readable ticks and a lower-center translucent color
key. Native regression tests and nine isolated-binding GTK frame tests pass;
the pre-existing native-binding capture limitation is tracked as a separate bug.
Warning/fallback and physical observations remain under phase 9000.
Phase 7000 is complete locally: graph range highlighting, independent cursor
identity, selection-filtered table paging, Fit and synchronized 2x zoom. Native,
isolated GTK and affected compatibility tests pass. Its six local slices and
acceptance contract are in the root roadmap and viewer specification. The
operator approved ACP on 2026-09-16; installation remains separate.
New phases and slices follow AGENTS.md's 1000-step numbering
rule. Slice numbers are local to their owning phase; refer to both separately
when needed, for example phase 9000, slice 5000.
See [current phase and slice state](state/phase-slice-stack.md) for progress.
