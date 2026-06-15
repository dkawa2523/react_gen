# DB Cleanup Workflow

Use this workflow when you want to disable or remove source-provider/database
integrations without breaking the current local-only workflow.

The cleanup tool never guesses what to remove. It reads an audit report and, if
provided, an explicit decision YAML. The default mode is dry-run.

## Commands

Create a target inventory report:

```powershell
python -m external_data_tools.db_cleanup_plan docs/db_provider_audit.md `
  --output db_cleanup_plan.yaml
```

Dry-run decisions:

```powershell
python -m external_data_tools.db_cleanup_plan docs/db_provider_audit.md `
  --decision cleanup_decisions.yaml `
  --dry-run
```

Apply explicit decisions:

```powershell
python -m external_data_tools.db_cleanup_plan docs/db_provider_audit.md `
  --decision cleanup_decisions.yaml `
  --apply
```

## Decision File

```yaml
schema_version: 1
decisions:
  - target: pubchem_external_tools
    action: disable
    reason: not needed for initial product
  - target: vamdc_external_tools
    action: remove
    reason: not needed
    remove_tests: true
  - target: chemicals_optional
    action: keep
    reason: useful offline fallback
```

Supported actions:

- `keep`: record the decision; no file changes.
- `disable`: remove provider names from built-in source profiles and append a
  cleanup note. Source code and tests remain.
- `remove`: remove source files only when no active imports remain. Tests are
  removed only with `remove_tests: true`; docs are removed only with
  `remove_docs: true`.
- `move_to_future_notes`: append a cleanup note that the target should be
  treated as future/advisory. Code remains.

## Safety Rules

- Dry-run does not mutate the repository.
- `remove` is blocked when active imports remain.
- Tests are not removed unless the decision explicitly sets `remove_tests:
  true`.
- Docs are not removed unless the decision explicitly sets `remove_docs: true`.
- Curated `registry/` data is not modified by this workflow.
- Local-only generation should remain available even if optional DB targets are
  disabled.

## Recommended Review Steps

1. Run the inventory report.
2. Write a small decision file with only the targets you want to change.
3. Run dry-run and inspect `files_to_modify`, `files_to_remove`,
   `active_imports`, `tests_referencing_removed_modules`, and `docs_to_review`.
4. Update the decision file if the dry-run report shows an unsafe removal.
5. Apply only after the dry-run is clean.
6. Run `python -m pytest` or the project Python launcher equivalent.
