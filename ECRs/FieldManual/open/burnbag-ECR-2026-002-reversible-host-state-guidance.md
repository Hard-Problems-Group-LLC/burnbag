# Engineering Change Request: Reversible Host-State Lifecycle Guidance

- ECR ID: `burnbag-ECR-2026-002`
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
- Origin and provenance: Drafted while specifying burnbag's temporary hardware-backlight mutation lifecycle.

## Submitted Request

Freeze this section after first transport. Preserve a prior revision when a
material change must be resubmitted.

### Problem And Source Impact

FieldManual advises projects to expose side effects, validate changes, test
failure behavior, and plan rollback, but its language-invariant core does not
currently define the lifecycle for a process that temporarily mutates host or
hardware state and promises to restore it before exit.

For burnbag, turning a laptop backlight off during a persistent run requires a
saved starting state, post-mutation verification, restoration on every handled
exit path, post-restoration verification, explicit partial-failure behavior,
and honest documentation of unhandleable termination such as `SIGKILL`.
Without shared guidance, projects can easily advertise restoration while
leaving fatal-error or partial-mutation paths uncovered.

### Requested Outcome

Add concise, language- and technology-independent guidance for temporary
external-state mutation. It should cover:

- discovery and validation before mutation;
- snapshotting the authoritative starting state;
- least-privilege mutation through a supported system boundary;
- verification after both mutation and restoration;
- one idempotent teardown path for normal, error, and handled-signal exits;
- compensation after partial application;
- a nonzero or otherwise explicit failure outcome when the requested final
  state cannot be verified; and
- documentation of cleanup limits when the process cannot execute teardown.

### Acceptance Criteria

- The guidance applies to temporary host, device, service, session, and other
  external-state changes without prescribing one operating system or language.
- It distinguishes process-owned automatic cleanup from explicit restorative
  action and does not promise cleanup after unhandleable process destruction.
- It requires projects to define authoritative observation, success criteria,
  partial-application behavior, and the final failure signal.
- It cross-links pragmatic change safety, documentation, test development,
  privilege boundaries, and project-owned specifications rather than
  duplicating them.

### Non-Goals

- Defining Linux backlight APIs, POSIX signal mechanics, or a universal
  transaction abstraction.
- Requiring restoration where the approved operation is intentionally
  permanent or irreversible.
- Claiming that all external mutations can be made atomic.

### Constraints And Risks

The guidance must not imply that cleanup can run after `SIGKILL`, sudden power
loss, kernel failure, or equivalent process destruction. It should encourage
native leases and automatically released resources where available while
still requiring explicit restoration for state that outlives process death.

### Evidence At Submission

- FieldManual core guidance mentions validation, rollback, and cleanup in
  several contexts but does not state a general reversible-mutation lifecycle.
- burnbag's inhibitor file descriptors are kernel-released on process death,
  while backlight brightness and power-profile mutations require explicit
  restoration and therefore have materially different failure boundaries.

## Source Tracking

After first transport, maintain this section as an append-only history.

### Local Mitigation

- 2026-08-07 — burnbag added a project-owned backlight lifecycle specification
  requiring snapshot, apply verification, compensating restoration, final
  verification, and explicit unhandleable-termination limits.

### Transport And Receipt Log

- 2026-08-07 — Drafted locally; not yet submitted.

### Discussion And Amendments

None.

### Target Disposition

Not yet reported.

### Source Closure

Open.
