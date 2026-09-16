# Engineering Change Request: Language-Invariant Installer And Prerequisite Guidance

- ECR ID: `burnbag-ECR-2026-001`
- Request revision: 1
- Source project or origin namespace: burnbag
- Target project: FieldManual
- Target canonical locator: `Hard-Problems-Group-LLC/FieldManual`
- Target component, version, or revision: Core standards at `95702da77b342e95c6b52c5bb0e9f867c61a7662`
- Request owner: burnbag maintainers
- Drafted: 2026-08-07
- Submitted: Not yet submitted
- Submitted-content digest: Not yet recorded
- Source lifecycle: Open
- Target handling status as reported: Not submitted
- Target intake ID or authoritative reference: None
- Sensitivity and reuse classification: Non-sensitive; reusable framework guidance
- Related, duplicate, or superseded ECR IDs: None
- Origin and provenance: Drafted from burnbag prerequisite remediation and recurring installer conventions inherited from TheKnowledge projects.

## Submitted Request

Freeze this section after first transport. Preserve a prior revision when a
material change must be resubmitted.

### Problem And Source Impact

FieldManual defines runtime precedence, package ownership, environment safety,
and validation outcomes, but it does not currently describe the
language-invariant contract for a project's prerequisite and installation
entry points. Projects can consequently expose setup commands that select a
different runtime than the system package manager, block non-runtime commands
such as help, require unnecessary privilege, or use inconsistent meanings for
development installation. They can also report a successful development
install without establishing or verifying which executable a subsequent bare
command will run.

In burnbag, an environment-selected Python could not import a native binding
that the operating-system package manager had correctly installed for the
distribution Python. The original error reduced this scope mismatch to a
misleading missing-package instruction.

### Requested Outcome

Add outcome-based FieldManual guidance for project-owned prerequisite,
bootstrap, and installation workflows. The guidance should remain independent
of language, package manager, filename, and implementation technology while
covering:

- a discoverable canonical installation or bootstrap entry point;
- explicit standard, development, system, user, and repository-local scope
  semantics when those modes exist;
- a non-mutating prerequisite or readiness check;
- deterministic runtime and package-manager ownership;
- explicit command-resolution outcomes when development and installed copies
  can coexist, including the boundary that an installer cannot modify its
  parent shell's current environment;
- interactive conflict selection and explicit non-interactive policy where a
  workflow optionally publishes a user-facing development launcher;
- visible privilege, network, and external-state transitions;
- safe repeated execution, staging, and partial-failure behavior; and
- documentation that distinguishes similarly named but unrelated packages.

### Acceptance Criteria

- FieldManual identifies the observable contract a consuming project's
  installer and prerequisite workflow should satisfy.
- The guidance does not require Bash, Python, `install.sh`, `dnf`, a virtual
  environment, or any other particular implementation.
- Development mode is described as project-declared local setup and is kept
  distinct from a user or system deployment.
- An installer that offers to change command resolution protects unmanaged
  targets, reports competing commands, verifies the resulting lookup, and
  does not claim that a non-activated directory controls the parent shell.
- Non-interactive automation leaves command resolution unchanged by default
  or selects the intended behavior through an explicit project-owned option.
- Readiness checks are non-mutating and report the selected runtime, package
  source, scope, and actionable mismatch where those facts matter.
- The guidance cross-links runtime/package environments, local operator state,
  pragmatic change safety, documentation, and validation evidence rather than
  duplicating their rules.

### Non-Goals

- Supplying a universal executable installer or package-manager wrapper.
- Requiring every project to support every installation scope or mode.
- Requiring a global development shim, shell-profile mutation, environment
  activation tool, or one universal command-resolution strategy.
- Replacing language-specific packaging or platform deployment standards.
- Standardizing TheKnowledge's heavier environment bootstrap as a FieldManual
  requirement.

### Constraints And Risks

The guidance must not imply that an installer may silently obtain privilege,
access the network, change a user profile, modify an adjacent project, or
replace an operator-owned environment. Examples must not turn one ecosystem's
conventions into universal requirements.

### Evidence At Submission

- FieldManual's runtime standard already treats unexpected interpreter and
  package resolution as an interrupt condition.
- A burnbag checkout selected a pyenv interpreter while the required native
  module was installed for the distribution interpreter.
- Existing TheKnowledge-derived projects use explicit standard and
  repository-local development modes, demonstrating reusable semantics but
  also showing why FieldManual guidance should be lighter and
  implementation-neutral.
- A burnbag development install created a valid link beneath the checkout but
  left an existing system installation first in effective command lookup,
  while still reporting the development launcher as successfully installed.

## Source Tracking

After first transport, maintain this section as an append-only history.

### Local Mitigation

- 2026-08-07 — burnbag began adding a canonical prerequisite check and
  installer with explicit standard and repository-local development modes.
- 2026-08-07 — burnbag began repairing development launcher selection after
  observing that a checkout-local link alone did not affect command lookup.

### Transport And Receipt Log

- 2026-08-07 — Drafted locally; not yet submitted.

### Discussion And Amendments

- 2026-09-15 — Direct operator clarification is captured in
  `burnbag-ECR-2026-003`. It supersedes this request's optional command-selection
  policy: development mode must select checkout execution for commands and
  services; standard mode must select installed artifacts. Other requested
  prerequisite and runtime guidance remains unchanged. Neither draft has
  been submitted or acknowledged by FieldManual.

- 2026-08-07 — Expanded the unsubmitted revision 1 draft to cover observable
  command-resolution outcomes, safe launcher conflicts, and explicit
  interactive versus automation behavior. No submitted text was changed
  because the ECR has not yet been transported.

### Target Disposition

Not yet reported.

### Source Closure

Open.
