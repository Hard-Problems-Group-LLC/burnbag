# TARGET_PROJECT Change Requests

## Scaffold Activation

Remove this section after activation. While the parent directory is named
`_target-template`, this tree is non-live scaffolding.

1. Copy `_target-template/` to `ECRs/<target-project>/`.
2. Rename the target directory with a stable, portable project slug.
3. Replace every `TARGET_PROJECT` placeholder in the copied files.
4. Remove this scaffold-activation section from the copied README.
5. Keep one target project in the directory.

## Lifecycle

Use this directory for source-owned ECRs aimed at `TARGET_PROJECT`. For each
new request, copy `request-template.md` to a stable filename under `open/`;
leave the root template clean.

- `open/`: draft or submitted without active target acknowledgement
- `in-progress/`: acknowledged or actively handled with target evidence
- `closed/`: settled with a dated disposition and target evidence when
  applicable

Preserve each ECR ID, revision, filename, and submitted request across
lifecycle moves. Transport a copy to the target; retain the source record.
