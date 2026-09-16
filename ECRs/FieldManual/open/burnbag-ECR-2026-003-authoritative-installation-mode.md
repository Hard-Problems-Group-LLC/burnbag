# Engineering Change Request: Make installation mode authoritative for commands and services

- ECR ID: `burnbag-ECR-2026-003`
- Request revision: 1
- Source project or origin namespace: burnbag
- Target project: FieldManual
- Target canonical locator: `Hard-Problems-Group-LLC/FieldManual`
- Target component, version, or revision: Installer/runtime guidance at `95702da77b342e95c6b52c5bb0e9f867c61a7662`
- Request owner: burnbag maintainers
- Drafted: 2026-09-15
- Submitted: Not yet submitted
- Submitted-content digest: Not yet recorded
- Source lifecycle: Open
- Target handling status as reported: Not submitted
- Target intake ID or authoritative reference: None
- Sensitivity and reuse classification: Non-sensitive; reusable framework guidance
- Related, duplicate, or superseded ECR IDs: Refines `burnbag-ECR-2026-001`; supersedes its optional command-activation policy only
- Origin and provenance: Direct operator clarification during burnbag development-installation repair, roadmap phase 3100, slice 5000.

## Submitted Request

### Problem And Source Impact

Selecting development installation did not consistently select development
code. A separate command-selection option or confirmation was required, some
helpers retained old installed copies, and the system service deliberately
used a copied daemon even in development mode. The operator could therefore
test stale code while believing that a successful dev installation selected
the checkout. Returning to standard installation could leave dev launchers
ahead of installed executables on PATH.

In burnbag this concealed working history fixes: the bare graphical viewer
still launched a build displaying only the first 500 records. A healthy
collector continued recording, but the viewer appeared to lose most of the day.
File-presence tests alone did not establish which implementation actually ran.

### Requested Outcome

Provide strong, implementation-neutral normative guidance:

1. **The selected installation mode MUST determine the code source for the
   entire application.** Development mode MUST make user-run commands and all
   application services installed/configured by that operation execute the
   selected checkout. This includes helpers, GUI applications, controllers,
   imported support code, and system/user service scopes. Symlinks, wrappers,
   service configuration, or equivalent mechanisms are acceptable.
2. **Standard mode MUST install complete, independent artifacts and make those
   installed artifacts win.** Omitting the development option selects standard
   mode when that is the project's declared default. A successful standard
   installation MUST NOT depend on the checkout still existing or on a dev
   launcher being removed later by hand.
3. **Selecting the mode is sufficient intent.** Installers MUST NOT require a
   redundant command-selection flag or another confirmation merely to make the
   selected mode effective. Interactive and unattended runs MUST have the same
   mode semantics. Legacy flags/environment settings MUST NOT silently create
   a mixture of development and installed execution.
4. **Verify effective execution, not just published files.** Installers MUST
   check user command precedence and configured service execution targets.
   Mode transitions MUST retire or replace obsolete managed indirection and
   update/reload affected units. Active services should be restarted when
   needed; deliberately stopped/disabled state must be preserved.
5. **Fail honestly when precedence or access cannot be established.** Preserve
   unrelated/unmanaged files. Report an actionable conflict instead of success
   when PATH, user identity, service permissions, or sandbox restrictions would
   select the wrong code or prevent it from executing. Do not silently fall
   back to an installed daemon in dev mode.

The guidance should distinguish code source (development/standard) from service
scope (system/user). A system service does not inherently require a copied
release executable: a development service may run checkout code under its
normal restricted account, with narrowly scoped filesystem access. Do not
unnecessarily run it as root or weaken unrelated home-directory permissions.

### Acceptance Criteria

- FieldManual documents the authoritative mode contract with MUST/SHOULD-level
  direction and cross-links runtime, installation, verification and change
  safety guidance. Examples do not introduce an independent selection policy.
- A consuming-project verification matrix includes dev and standard modes,
  interactive and unattended use, all installed command entry points, both
  supported service scopes, and both directions of mode transition.
- Dev verification proves commands and service entry points resolve the
  checkout and observe a code change on their next invocation/restart without
  recopying application code.
- Standard verification proves commands and service support modules run after
  the source checkout is moved out of the way, and that managed dev launchers
  cannot override them.
- Verification covers stale launchers, conflicting PATH entries, explicit
  operator identity, service sandbox/private-home access, partial failures,
  and non-mutating check/staging modes.
- The parent-shell boundary is explicit: installers cannot rewrite a running
  shell's aliases or command cache. They verify ordinary lookup and report any
  required cache refresh without treating a dormant link as activation.

### Non-Goals

- A universal installer, language, package manager, filesystem layout or init
  system; projects own their implementation and verification tools.
- Enabling both mutually exclusive collector scopes, changing unrelated users'
  installations, or automatically changing service account privileges.
- Modifying running-process code in place. A new invocation or service restart
  is sufficient to consume changed development code.
- Turning read-only checks or destination staging into host activation.

### Constraints And Risks

Development services intentionally execute mutable checkout code. Preserve the
service's declared account and isolation, document the checkout dependency, and
validate access rather than substituting a stale copy. Mode changes must retain
history/configuration and respect ownership of shared artifacts. Authorization
for installation remains separate from merely editing or testing an installer.

### Evidence At Submission

- burnbag's installation specification and installer separated dev setup from
  command activation; `burnbag-ECR-2026-001` requested a similar optional policy.
- Its system dev service used an installed copy while its user dev service used
  the checkout, despite sharing the same development-mode option.
- Source-owned investigation and repairs are recorded in ROADMAP phase 3100
  and `project-management/bugs/closed/BB-BUG-2026-09-15-01-viewer-history-visibility.md`.

## Source Tracking

### Local Mitigation

- 2026-09-15 — Implementing the clarified mode contract in burnbag, including
  command precedence, system/user service code source and transition tests.
- 2026-09-15 — Local repair verified by 80 affected tests on each of three
  supported interpreters, real command/source-removal transition fixtures and
  systemd unit validation. Target guidance remains a request; no FieldManual
  implementation or acknowledgement is claimed.

### Transport And Receipt Log

- 2026-09-15 — Drafted locally at operator direction; not yet submitted. The
  FieldManual submodule remains unchanged.

### Discussion And Amendments

- This request supersedes only the command-activation portions of ECR-001
  that permit dev mode to leave installed commands authoritative by default.
  ECR-001's prerequisite/runtime and other installation guidance remains useful.

### Target Disposition

Not yet reported.

### Source Closure

Open.
