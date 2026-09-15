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
  each phase, allocate slices in the same increments, using the qualified
  form `1000.1000`, `1000.2000`, `1000.3000`, and so on.
- Reserve intervening numbers for later insertions (for example phase `1500`
  or slice `1000.1500`). Keep assigned IDs stable when inserting work.
- Apply these IDs consistently in `ROADMAP.md`, project-management records,
  and the phase/slice stack that generates Ubersight. Update those records as
  work advances, including completed and manually deferred slices.
- The new series starts with phase `1000` for historical graph `--last`
  durations. Existing published `P1`–`P10` and `V` IDs remain legacy references;
  new phases and slices use the spaced numbering scheme above.

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
