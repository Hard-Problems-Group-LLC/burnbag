# Durable Synchronized Running Log

- ID: `BB-PROP-2026-08-07-01`
- Author: Codex
- Sponsor: Operator
- Date: 2026-08-07
- Status: Approved
- Reviewers: Operator (decision authority)
- Affected projects or audiences: burnbag maintainers and operators
- Related work:
  - Direct operator request on 2026-08-07
  - [Runtime log specification](../../../docs/specifications/runtime-log.md)
  - `BB-2026-08-07-05`

## Problem Statement

Burnbag deliberately changes power profiles, acquires sleep inhibitors, turns
screen backlights off, reacts to lid state, and may request suspend or
hibernate. Its console narrative is useful while a process is attached to a
terminal, but it does not provide durable evidence after a crash, power loss,
terminal closure, or later troubleshooting. A safety-relevant session needs an
append-only record of its start, requested configuration, observed events,
attempted and completed mutations, deviations, teardown, and stop condition.

## Goals

- Create one chronological, machine-readable running log shared by burnbag
  sessions.
- Synchronize every complete record to the filesystem before the logging call
  reports success.
- Record a session start before loading runtime D-Bus dependencies or changing
  host state, and a session end after handled teardown.
- Record every safety-relevant event between those boundaries, including
  mutation intent before the mutation and outcome afterward.
- Serialize concurrent burnbag writers without record interleaving.
- Fail closed before new host mutations when logging cannot be established or
  synchronized, while never allowing a logging failure to prevent teardown.
- Keep records private, bounded in size, stable enough for tools, and useful to
  a human with ordinary JSON Lines utilities.

## Non-Goals

- The log is not a cryptographic audit trail and does not claim tamper
  resistance against the account that owns it or an administrator.
- The first implementation will not upload, transmit, centrally aggregate,
  automatically delete, compress, or rotate logs.
- It will not duplicate arbitrary environment variables, D-Bus payloads, or
  secret-bearing process state.
- It does not replace the interactive startup and shutdown narratives.

## Use Cases

- After an unexpected power event, an operator can see which session started,
  its selected mode, the last synchronized event, and whether a handled
  `session_end` record exists.
- After a backlight or power-profile problem, an operator can distinguish an
  attempted mutation from a verified successful mutation and subsequent
  restoration.
- Concurrent sessions can append to one log without corrupting each other's
  records.
- A test or automation run can select an explicit absolute log path without
  changing the operator's normal history.

## Constraints And Assumptions

Verified constraints:

- Burnbag targets Linux and Python 3.9 or later, so `os.open`, `os.write`,
  `os.fsync`, `fcntl.flock`, and Linux no-follow file-opening flags are
  available without another dependency.
- Help and argument validation must remain available before PyGObject loads.
- Explicit backlight and power-profile teardown must continue even if logging
  fails.

Assumptions:

- The selected filesystem implements successful `fsync` and advisory `flock`
  with local-filesystem semantics. Burnbag can verify syscall success, but it
  cannot prove that storage hardware honored its own persistence guarantees.
- The invoking account's `HOME` or `XDG_STATE_HOME` identifies the intended
  user-state boundary. Burnbag must not silently escape an isolated home by
  consulting another account database.

## Current Context

Runtime status is currently emitted only to standard output and standard
error. Startup and shutdown narratives summarize intended and final state,
but no owned persistent log exists. Python's standard logging defaults do not
provide the required per-record `fsync`, secure file opening, or cross-process
serialization contract.

## Proposed Approach

### Record And Session Model

Use UTF-8 JSON Lines with one object and one trailing newline per record. Every
record contains schema version, UTC timestamp, monotonic elapsed time, session
UUID, per-session sequence number, PID, effective UID, selected mode, event
code, severity, message, and a structured details object. Record size is
bounded at 64 KiB.

The first record is `session_start`. The handled final record is `session_end`
and contains exit status, goal status, shutdown reason, deviations, and final
system-state observations. The absence of `session_end` remains meaningful
evidence of an unhandled process or power interruption; the implementation
must not synthesize an end record for a process that did not execute teardown.

### Event Coverage

Log selected configuration, startup plan, D-Bus readiness, recorded
backlights, power-profile reads and mutations, inhibitor acquisition and
release, lid state and transitions, timer creation/cancellation/expiry,
backlight mutation and verification, suspend/hibernate intent, signals,
warnings, fatal errors, teardown actions, and event-loop entry/exit. A
safety-relevant mutation receives a synchronized intent record before the
call and a result record afterward.

### Durability And Concurrency

Open the log with append, close-on-exec, and no-follow semantics. For every
record, acquire an exclusive advisory file lock, issue direct `os.write` calls
until the complete encoded record is appended, call `os.fsync`, then release
the lock. Synchronize the containing directory when establishing the file.
Do not use buffered text-file writes as the durability boundary.

If an interrupted prior write left a non-newline tail, preserve the fragment,
append and synchronize a separating newline under the lock, and identify the
condition in the new `session_start`. Do not silently truncate forensic bytes
or concatenate the new session's JSON onto an incomplete fragment.

### Location And Permissions

The default is `$XDG_STATE_HOME/burnbag/burnbag.log`, falling back to
`$HOME/.local/state/burnbag/burnbag.log`. `--log-file FILE` selects an explicit
absolute path. The immediate parent must be a real directory owned by the
effective UID and not writable by group or other users. The managed default
directory is mode `0700`; the log is a regular, singly linked file owned by the
effective UID and forced to mode `0600`. Symlink log targets are rejected.

### Failure And Recovery

Failure to resolve, open, validate, lock, append, or synchronize the running
log before host mutation is fatal and prevents the mutation. A mid-session
logging failure marks the mission incomplete, requests event-loop shutdown,
and returns nonzero. Once teardown begins, further logging failures are
reported directly but cannot interrupt backlight restoration, inhibitor
release, or power-profile restoration.

No in-process rotation occurs. An external rename-based rotation may move the
active inode; an already running process continues safely on its open file
descriptor, and later sessions open the new configured path. Retention and
rotation policy remain operator-owned.

## Alternatives Considered

- **systemd journal only:** useful as an additional destination, but retention
  and persistent storage vary by host configuration and do not satisfy the
  owned-file contract.
- **Python `logging.FileHandler`:** convenient formatting, but buffered writes
  and no default per-record `fsync` or cross-process serialization make its
  default contract insufficient.
- **One file per session:** simplifies concurrency but makes one chronological
  running history and external review less convenient.
- **SQLite:** offers transactions but adds format, recovery, locking, and
  operational complexity disproportionate to append-only events.
- **Human-only text:** readable, but less reliably validated and queried than
  a stable JSON Lines schema.

## Risks And Mitigations

- **Disk-full or I/O latency:** each `fsync` can delay operation. This is an
  intentional safety tradeoff; failures stop new mutations and force handled
  teardown.
- **Sensitive diagnostic data:** allowlisted fields exclude environment dumps,
  D-Bus addresses, and unrelated process state; permissions are restrictive.
- **Corruption by concurrent writers:** one lock spans the complete append and
  `fsync`; tests use real concurrent processes.
- **Log growth:** size is not silently capped or deleted. Documentation tells
  operators that retention is their responsibility; future rotation policy
  requires a separate approved change.
- **False persistence confidence:** documentation states that successful
  `fsync` is the program's verifiable boundary, not proof about storage
  firmware or remote filesystems.

## Validation

- Real-file tests validate permissions, schema, ordering, session boundaries,
  and parseable JSON Lines under the project-local temporary tree.
- Multi-process tests validate non-interleaved concurrent appends.
- Failure injection covers open, write, and `fsync` failure, including the
  invariant that teardown continues after a log failure.
- Lifecycle tests confirm intent records precede owned mutations and that the
  final record follows teardown.
- The suite runs on Python 3.9, system Python 3.12, and Python 3.14.
- Help, README, man page, and the durable specification agree on location,
  permissions, failure behavior, and `--log-file`.

## Open Questions

None for this revision. Rotation, retention limits, cryptographic integrity,
and journal mirroring require separate decisions if later requested.

## Milestones

1. **Contract** — Codex; exit when this approved proposal and linked
   specification agree.
2. **Implementation** — Codex; exit when logging covers the complete handled
   lifecycle and failure semantics.
3. **Validation and documentation** — Codex; exit when cross-version tests and
   generated user documentation pass.

## Adoption And Rollout

There is no existing file format to migrate. The first operational invocation
after installation creates the default state directory and log. Rollback is a
code rollback; retained JSON Lines remain ordinary operator-owned state and
are not deleted automatically. Operators must be told the default path and
the explicit override before rollout.

## Decision Log

- 2026-08-07 — Operator requested a synchronized running-log specification and
  subsequently directed implementation once the proposal was complete. This
  is recorded as approval of the scope and safety tradeoffs above.
