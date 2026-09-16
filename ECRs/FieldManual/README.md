# FieldManual Change Requests

This is the ready target tree for source-owned requests to FieldManual.
Consuming projects use it when their FieldManual checkout is read-only or is
not the authoritative maintenance checkout.

- `open/`: drafted or submitted, but not actively acknowledged by FieldManual
- `in-progress/`: acknowledged or actively handled, with a FieldManual
  reference recorded
- `closed/`: settled with a dated disposition and FieldManual evidence when
  the closure claims a FieldManual outcome

Current clarification: [burnbag-ECR-2026-003](open/burnbag-ECR-2026-003-authoritative-installation-mode.md)
requests authoritative dev/standard execution across commands and services,
superseding ECR-001's optional command-activation policy.

Keep the source ECR and its filename when transmitting a copy. Freeze its
submitted-request sections after first transport and append later receipts,
discussion, mitigations, and disposition evidence.

When maintaining FieldManual itself, use FieldManual's project-management
workflow for ordinary self-directed work. This self-target directory normally
remains empty in the authoritative FieldManual checkout.
