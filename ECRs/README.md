# Engineering Change Requests

Use this source-owned tree for durable requests to another project. Each
target gets its own `open/`, `in-progress/`, and `closed/` lifecycle
directory, whether the target is an upstream dependency, peer project,
service, framework, or tool.

- Copy `_target-template/` to `ECRs/<target-project>/` before filing against a
  new target.
- Use the preinstalled `FieldManual/` target when a consuming project needs a
  FieldManual change.
- Never file live requests inside `_target-template/`.
- In an authoritative project checkout, use `ECRs/` only for requests to
  other targets; route ordinary self-maintenance through project management.
- Keep incoming ECR payloads separate from this outgoing tree and map them
  into target-owned project-management records.

Follow the configured FieldManual core standard
`engineering-change-requests.md` for identity, revisions, authority,
transport, deconfliction, and closure evidence.
