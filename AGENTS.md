<!-- FIELDMANUAL_MANAGED_HEADER_START -->
# FieldManual Project Instructions

This project uses FieldManual for shared development, testing, documentation,
review, and project-management practices.

Before substantial work:

1. Read `FieldManual-config.toml` and, when it exists,
   `.local/FieldManual-localconfig.toml`.
2. Confirm the configured `FieldManual_ProjectRoot` and
   `FieldManual_FrameworkRoot` identify the project being changed and the
   FieldManual checkout being used.
3. Read `FieldManual/README.md` and
   `FieldManual/standards-and-practices/core/README.md`.
4. Load only the language, technology, technique, and knack documents that
   apply to the work.
5. Read the project-specific instructions between this header and the managed
   footer.

---

Put project-specific `AGENTS.md` content below this line and above the managed
FieldManual footer.
<!-- FIELDMANUAL_MANAGED_HEADER_END -->

## Phase and slice numbering

- Allocate new roadmap phases as `1000`, `2000`, `3000`, and so on. Within
  each phase, allocate local slice IDs `1000`, `2000`, `3000`, and so on.
  Slice IDs restart in each phase and never include the phase ID. The phase
  section or owning Phase column supplies that context; outside it, write
  "phase 2000, slice 5000" to disambiguate.
- Reserve intervening numbers for later insertions (for example phase `1500`
  or local slice `1500`). Keep assigned IDs stable when inserting work.
- Apply these IDs consistently in `ROADMAP.md`, project-management records,
  and the phase/slice stack that generates Ubersight. Update those records as
  work advances, including completed and manually deferred slices.
- The new series starts with phase `1000` for historical graph `--last`
  durations. At the operator's direction on 2026-09-15, manual validation
  phase `V` was renamed `2000`, then renumbered to phase `9000` when phase
  `3000` was assigned to the GTK 4 history viewer. Its six local slices remain
  numbered `1000` through `6000` in order. All slice names are local; use local
  IDs throughout the live stack and dashboard. Legacy slice references such as
  `P2.4` correspond to phase `P2`, local slice `4000`; historical task and
  request identifiers remain unchanged. Existing published `P1`–`P10` IDs
  remain legacy references. Phase `4000` covers persistent viewer field
  selection. Phase `5000` covers standard installer recovery under sudo.
  Phase `6000` covers shared-rectangle viewer traces and unit-based axes.
  Phase `7000` covers graph range selection, cursor/table synchronization and
  selection-aware zoom. Phase `8000` covers duplicate-checkout reconciliation
  and retirement. Allocate the next new phase as `10000`; `9000` remains
  reserved for the existing manual validation work.

## Ubersight maintenance

- Treat `project-management/state/phase-slice-stack.md` as the canonical
  execution/recovery state for `ROADMAP.md`; Ubersight is its derived display.
  Keep the roadmap, task/bug records, and stack synchronized at phase and slice
  transitions, before long validation or publication waits, and at handoff.
- Use the phase and local slice numbering above in both the stack and display.
  Start each new phase's slices at `1000`; never prefix a slice ID with its
  phase ID or renumber existing IDs to insert work.
- Keep exactly one active phase and one of its slices active while work is
  incomplete. Mark deferred manual checks blocked and continue independent
  work. If everything remaining awaits input, mark Delivery blocked, retain
  the owning active phase/slice, and describe the wait in Notes. Keep deferred
  validation phase `9000` after delivery phases so recent work remains visible.
- After updating the stack, run `python3 -B scripts/update_ubersight.py --dry-run`
  from this project root, then publish with
  `umask 077; python3 -B scripts/update_ubersight.py`. Use the installed
  Ubersight writer through this script, with its explicit `burnbag-main`
  context; do not hand-edit status JSON or invoke network/display probes just
  to publish progress.
- Keep `.local/ubersight/` ignored and private. On recovery, verify tracked
  records and regenerate status; an old dashboard is not authoritative.
  Never mark manual checks passed without evidence or commit runtime status.

<!-- FIELDMANUAL_MANAGED_FOOTER_START -->
---

## Field Manual Managed Guidance

- Treat the configured project root as the boundary for project-owned files,
  local state, and project-management records.
- Treat the configured framework root as read-only guidance when it is a
  submodule. Do not write project state into the FieldManual subtree.
- Use `project-management/` for the backlog, active and completed work, bugs,
  proposals, reviews, decisions, open questions, and bounded human requests.
- Keep durable behavior and interface contracts in `docs/specifications/`.
- Keep checkout-local state and policy inputs under `.local/`, and keep the
  entire `.local/` tree ignored by version control.
- Put disposable test workspaces and temporary project artifacts in uniquely
  named children of the project root's `.local/tmp/` by default. Clean up
  only paths created or explicitly acquired by the current operation.
- Put cross-project change requests under `ECRs/<target-project>/`. Use the
  ready `ECRs/FieldManual/` tree for FieldManual requests and copy
  `ECRs/_target-template/` for another target.
- FieldManual supplies prose standards, not language-specific verification
  programs. Use the consuming project's declared build, test, lint, security,
  and release commands.
- Project-specific instructions may specialize FieldManual defaults. Record
  intentional exceptions explicitly instead of allowing silent drift.
<!-- FIELDMANUAL_MANAGED_FOOTER_END -->
