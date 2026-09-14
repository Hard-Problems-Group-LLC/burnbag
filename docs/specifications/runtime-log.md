# Runtime Log Specification

- Status: Implemented; ready for operator validation
- Owner: burnbag maintainers
- Last reviewed: 2026-09-14
- Authorization:
  [BB-PROP-2026-08-07-01](../../project-management/proposals/approved/BB-PROP-2026-08-07-01-durable-running-log.md)

## Scope

This specification defines burnbag's mandatory, append-only running log for
operational invocations. It covers log location, record schema, synchronization,
event coverage, security, concurrency, and failure behavior. Help,
zero-argument guidance, and rejected command lines do not create a session or
a log record because no operational lifecycle begins.

## Location And Selection

The default path is:

```text
$XDG_STATE_HOME/burnbag/burnbag.log
```

When `XDG_STATE_HOME` is unset, the default is:

```text
$HOME/.local/state/burnbag/burnbag.log
```

Both base paths must be absolute. Burnbag must use the invoking environment as
the selected user-state boundary and must not silently substitute a passwd
database home. `--log-file FILE` selects another absolute path for that
invocation. There is no no-log option.

## File Safety

Before recording a session, burnbag must:

1. create the dedicated default directory with mode `0700` when needed;
2. reject a symlink or non-directory immediate parent;
3. require the immediate parent to be owned by the effective UID and not
   writable by group or other users;
4. open the file for append with close-on-exec and no-follow behavior;
5. require a regular, singly linked file owned by the effective UID;
6. enforce file mode `0600`; and
7. synchronize the file and containing directory before host mutation.

Any failure is fatal before power, inhibitor, or backlight state changes.

## Record Format

The log is UTF-8 JSON Lines. Every record is one JSON object terminated by one
newline and is at most 65,536 encoded bytes including that newline. Every
record contains:

- `schema_version`: integer `1`;
- `timestamp`: UTC RFC 3339 timestamp with microseconds and `Z` suffix;
- `elapsed_seconds`: non-negative monotonic seconds since process start;
- `session_id`: UUID unique to the burnbag invocation;
- `sequence`: per-session integer beginning at `1` and increasing by one;
- `pid`: process ID;
- `uid`: effective user ID;
- `mode`: selected operational mode;
- `event`: stable snake-case event code;
- `level`: `INFO`, `OK`, `EVENT`, `WARNING`, `ERROR`, or `FATAL`;
- `message`: concise human-readable description; and
- `details`: JSON object containing allowlisted event-specific context.

Records must not contain an indiscriminate environment dump, D-Bus addresses,
credentials, tokens, or unrelated process state. Exceptions may be summarized
as already-visible diagnostic text but must not include captured environment
or memory content.

## Append And Synchronization Contract

For each record, burnbag must:

1. serialize and size-check the complete record before touching the file;
2. acquire an exclusive advisory lock on the log descriptor;
3. append the complete encoded record using direct unbuffered writes;
4. call `fsync` successfully while still holding the lock; and
5. release the lock only after synchronization succeeds.

The method reports success only after step 4. Sequence numbers describe order
within a session; file order describes the serialized order across sessions.
Successful `fsync` is the application-observable durability boundary and is
not a claim about storage firmware or remote-filesystem behavior.

If an earlier unhandled write left bytes without a trailing newline, the next
opener must preserve that forensic fragment, append and synchronize one
newline under the exclusive lock, and set `partial_tail_detected` in its
`session_start` details. It must not concatenate a new JSON record directly to
the interrupted fragment or silently truncate the fragment.

## Session Boundaries

`session_start` must be the invocation's first record. It is synchronized
after command-line validation but before PyGObject loading, D-Bus setup, or any
host mutation. Its details contain selected mode and explicit option values,
not raw arguments or the environment.

`session_end` must be the final handled record and is written after handled
teardown. It contains exit code, goal status, shutdown reason, deviations, and
final observations for inhibitors, backlights, and power profile. An absent
`session_end` is retained as evidence of an unhandled termination; a later
process must not fabricate one for the interrupted process.

## Required Event Coverage

Between session boundaries, synchronized records must cover:

- startup plan and D-Bus/service readiness;
- backlight discovery, control-session resolution, mutation intent, verified
  off state, restoration intent, and verified on state;
- original power profile, mutation intent and result, restoration intent and
  result;
- inhibitor acquisition intent/result and release intent/result;
- initial lid state, lid transitions, timer start/cancel/expiry;
- signal receipt and event-loop entry/exit;
- battery discovery, timer start/stop, each initial, periodic, and final
  battery sample, observation failures, and the final battery summary;
- suspend or hibernate intent before the D-Bus request;
- all console status, warning, error, and fatal messages associated with an
  operational session; and
- teardown deviations and final state.

Every safety-relevant host mutation requires a synchronized intent record
before the mutation and an outcome or deviation record afterward.

Battery sample details use a separate suspend-inclusive `CLOCK_BOOTTIME`
elapsed value for plotting and rate calculations and include per-device
percentage plus optional presence and kernel status. Discovery, each sample,
and the battery summary also include `percentage_sources`, a kernel-name map
whose values are `capacity`, `energy_now/energy_full`, or
`charge_now/charge_full`. Derived-source startup records use the
`battery_percentage_source` event and identify `nearest_integer_half_up`
quantization. Sources are fixed at discovery; read failures remain gaps rather
than silently switching gauge definitions. These are additive event details;
the record schema remains version 1.

The final summary and
`session_end` contain versioned, unit-bearing per-battery derived statistics:
coverage, endpoints, whole-run OLS gauge trend and `R²`, eligible reported
level transitions, duration-weighted gauge-rate standard deviation, robust MAD
scale, signed average reported change and its standard deviation in `pp/min`,
cadence, reversals, segments, excluded gaps, status breaks, and explicit
validity reasons. The per-battery statistics schema is version 2. Unsupported
values are JSON `null`, never NaN or infinity.

## Failure Behavior

Log resolution, opening, validation, append, locking, or synchronization
failure is a mission failure. Before teardown, burnbag must prevent further
host mutations, request event-loop termination when applicable, restore any
state already changed, and return nonzero. Once teardown starts, logging
failure must be reported directly and must never interrupt backlight
restoration, inhibitor release, or power-profile restoration.

If `session_end` itself cannot be synchronized, burnbag returns nonzero and
reports that the durable log is incomplete. The descriptor is closed on every
handled path. Kernel descriptor closure remains the recovery mechanism after
unhandled process death.

## Concurrency, Retention, And Rotation

Multiple burnbag processes may append to the same file. The per-record lock
must prevent cooperating writers from interleaving records.

Burnbag performs no automatic rotation, truncation, upload, or deletion.
Retention is operator-owned. With external rename-based rotation, a running
process continues on its already-open inode while later sessions open the
configured path. Changes to rotation or retention policy require a separate
approved contract.

## Acceptance Criteria

- Real-file tests validate secure creation, mode, ownership, parseable schema,
  increasing sequence, and start/end ordering.
- Concurrent-process tests produce only complete, parseable records.
- Injected write and `fsync` failures produce nonzero mission state and do not
  interrupt teardown.
- Lifecycle tests demonstrate synchronized intent before representative power,
  inhibitor, and backlight mutations.
- Help, README, man page, comments, and startup/shutdown narratives identify
  logging behavior and the selected path.
- Tests pass on Python 3.9, system Python, and Python 3.14.
