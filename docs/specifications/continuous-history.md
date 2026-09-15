# Continuous power history and service lifecycle

Status: implemented, 2026-09-15; live installation/physical acceptance pending.
Authorization: operator's
continuous-monitoring design, six explicit design selections, and instruction
to fully implement. Delivery: roadmap P6–P10.

## Collection and persistence

The optional collector records power observations every five seconds while
awake. It never wakes the machine to sample or blocks sleep indefinitely.
Capture available battery energy, charge, percentage, electrical power,
voltage, temperature and state, charger state, thermal readings, CPU activity
and frequency, backlight, lid and power-profile transitions. Missing sensors
remain absent with provenance/errors; no values are fabricated. Cache static
device information. Preserve individual observation timestamps and boot IDs.

SQLite is the telemetry store. The existing private JSONL operational log
retains immediate durability for mutation intent/outcome, errors and session
boundaries; periodic telemetry is not duplicated there. User history lives at
`$XDG_STATE_HOME/burnbag/history.sqlite3`, falling back to
`$HOME/.local/state/burnbag/history.sqlite3`. The system history is
`/var/lib/burnbag/history.sqlite3`. System history is readable by local users;
only its owner writes it. User history remains private.

One dedicated writer buffers records in bounded RAM and commits at 60 seconds
or 64 KiB, whichever comes first. Ordinary event writes have a five-second
deadline without dropping or debouncing distinct transitions. Lifecycle
boundaries and critical conditions request immediate commits. Sampling must
not stall on storage. Report failed commits, bounded queue exhaustion and
lost coverage. Durability is acknowledged only after SQLite commits
successfully. Abrupt failures can lose approximately one minute of buffered
samples when storage is healthy; blocked or failed storage extends that window.

A battery's explicit kernel `capacity_level=Critical` makes its sample urgent.
Missing critical-state telemetry does not invent a percentage threshold or a
power action; collection remains observational.

`--prudent-writes` commits every update durably. During a foreground run it
requests this policy from the serving collector until the run ends. Multiple
requesting runs combine, and disconnect/crash releases each request. A
collector's startup prudent policy cannot be disabled by a client. SQLite
controls synchronization; neither manually syncing only the database file
nor checkpointing every update implements this contract.

The current storage backend uses SQLite rollback journaling (`DELETE`) with
`synchronous=EXTRA`, allowing ordinary users to read the system database without
write access to its directory. Acknowledged barriers include successful commit;
files and directories retain their scope's ownership and permissions.

## Ownership, fallback and evidence

Exactly one background collector may run on a machine, either the system
`burnbag.service` as non-login `burnbag:burnbag`, or a user's
`burnbag.service`. Atomic ownership protects against concurrent starts across
systemd managers. Readiness includes successful storage initialization and
recording health. Status queries have bounded deadlines and no side effects.

Foreground operations work without a background service and record to their
user database. They detect loss/recovery of the serving collector and hand
off recording. Multiple foreground runs of one user coordinate collection.
A foreign user's collector does not expose that user's private history;
the current foreground operation records locally and explains the limitation.

The outer CLI prints a prominent warning at the beginning and end when
continuous recording is absent or unavailable. This includes help, zero
arguments, invalid arguments and handled exits. Help remains independent of
GI and does not create databases or operational sessions. Footer state is
checked again. Color remains optional; text alone conveys the warning.

Sleep monitoring pairs suspend-inclusive boottime with monotonic clocks.
Pre-sleep/pre-shutdown coordination may briefly delay an orderly transition
only to complete pending writes, with a bounded deadline. Actual sleep
regions retain the existing S/H evidence and color semantics. A collection
gap alone is never evidence of powered-off state; the reserved 0 style remains
reserved until positive evidence is implemented.

## Historical queries

`burnbag --graph --from TIME --to TIME` renders the existing battery graph,
summary and lid/sleep overlays for a requested interval. TIME accepts ISO 8601
with an explicit offset or Z, or a local date/time interpreted in the host
timezone; ambiguous/nonexistent local times require an explicit offset.
`--to` defaults to now and `--from` to 24 hours before the selected end.
`burnbag --graph --last DURATION` instead selects a positive duration ending
at the invocation's captured current time. It conflicts with both explicit
bounds and requires `--graph`. The [duration range contract](duration-ranges.md)
defines accepted spellings, clock notation, unit arithmetic and validation.
Queries require start before end, never create a missing database, and read
both existing system and current-user history. Recent queries request a
bounded flush from the accessible collector before taking their snapshot.

Merge for display without changing either source. Duplicate record identities
and overlapping collection coverage for the same machine, boot and measurement
stream cause an explicit warning; system observations win within conflicting
coverage. Preserve user observations elsewhere and distinct events even when
timestamps coincide. Coverage segments include their first and last actual
observations without extrapolating beyond them; gaps and discontinuities split
segments. Warn about unreadable,
corrupt, incompatible or reduced-resolution history; still report usable data
from the other source. Never interpolate through missing coverage as if it
were observed. Long queries must use bounded memory and preserve interval-wide
coverage and diagnostic events; summaries disclose reduced resolution.

If no battery percentages exist but lid or sleep observations do, render an
event timeline with both battery-scale extrema labeled `n/a`. Retained
representatives determine reduced-resolution statistics; they are not exact
statistics over every stored sample. Continuous coverage metadata preserves
known continuity when queries reduce samples, while actual gaps remain blank.
Historical queries return zero for a complete readable result (including an
empty interval), one for warnings/partial results, and two for invalid bounds.

## Installation and management

The CLI supports `--enable-service`, `--disable-service`, `--start-service`,
`--status-service`, `--stop-service`, and corresponding explicit
`--ACTION-user-service` / `--ACTION-system-service` spellings. Management and
graph commands need no operational mode. Enable/disable controls subsequent
automatic activation; start/stop controls the current service. Inferred scope
uses the active applicable service or an unambiguous installed selection.
Conflicting/ambiguous requests identify explicit remediation, without silently
controlling another user's service.

Normal installation selects the system service by default;
`--install-user-service` selects the intended login user's service. New installs
enable and start the chosen service; updates preserve deliberate disabled or
stopped state. User installations do not enable lingering. Plain dev installs
also deploy a root-owned system-daemon copy while the CLI uses the checkout;
dev plus `--install-user-service` runs the daemon from the checkout.

Staged `--destdir` installs stage all files without host account/service/package
mutations. `--check` is read-only. System code is root-owned; the service
account needs only telemetry reads, its data directory and bounded sleep-delay
coordination. Installation does not relax private home permissions.

The uninstaller stops/disables the selected installation and removes only
managed artifacts. Preserve history, user configuration, unrelated overrides,
dependencies and the service account by default. Explicit `--purge-data`
removes only the selected history. Manifests identify owned paths; staging and
path-confinement rules apply equally to removal.

## Acceptance

Use real SQLite transactions, multiprocess ownership, socket protocol and
subprocess CLI tests. Verify normal/prudent durability, commit failures,
crash recovery, concurrent readers, bounded queues, collection handoff,
overlapping prudent requests, cross-user access, merged history and warnings,
timestamp/DST validation, whole-interval graph coverage, missing data and
unchanged live power-control cleanup. Test staged installs/uninstalls and
failure paths without mutating host service state. Run the full native suite,
shell/static checks, generated-document consistency and compatibility checks.
Live systemd installation and physical suspend remain explicit operator checks.
