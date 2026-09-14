# Specifications

Keep durable, project-specific behavior and interface contracts here.

Specifications should identify:

- the problem and scope;
- required behavior and explicit non-goals;
- interfaces, data, invariants, and failure behavior;
- compatibility and migration constraints;
- security and operational considerations; and
- acceptance criteria and validation evidence.

Link specifications to the proposal, backlog item, bug, or direct operator
request that authorized them. Update specifications when behavior changes;
do not use them as retrospective decoration.

## Burnbag contracts

- [Linux platform support](platform-support.md): distribution prerequisites,
  architecture support, and native integration.
- [Installation](installation.md): standard, staged, and development targets.
- [Power lifecycle](power-lifecycle.md): profiles, lid capabilities, sleep
  requests, inhibitor ownership, and recovery.
- [Backlight lifecycle](backlight-lifecycle.md): delayed screen-off and verified
  restoration.
- [Shutdown lifecycle](shutdown-lifecycle.md): handled signals, independent
  cleanup, and final reporting.
- [Battery monitoring](battery-monitoring.md): telemetry sources, sampling,
  chart geometry, statistics, and evidence limits.
- [Runtime log](runtime-log.md): durable records, ordering, and failure behavior.
- [Terminal output](terminal-output.md): stream capabilities and plain output.

Use [the testing guide](../testing.md) for automated commands and outstanding
physical platform checks; delivery state belongs to [the roadmap](../../ROADMAP.md).
