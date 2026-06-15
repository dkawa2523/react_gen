# Ar/CF4 DB Smoke Workflow

This smoke case exercises the local data-source and enrichment workflow without
downloading public data, requiring optional dependencies, or mutating the curated
`registry/` directory. The fixture data are intentionally tiny and synthetic
where noted; they prove the plumbing, not physical completeness.

## Files

- `cases/ar_cf4_db_smoke/input.yaml` defines an Ar/CF4 low-pressure plasma case.
- `cases/ar_cf4_db_smoke/source_profile.yaml` enables local registry and local
  internal-file providers.
- `cases/ar_cf4_db_smoke/internal_data/` contains a small property snapshot and
  one ion-neutral reaction candidate.
- `cases/ar_cf4_db_smoke/cross_sections/e_CF4_elastic.csv` is a synthetic
  three-row cross-section table.
- `cases/ar_cf4_db_smoke/cross_section_mapping.yaml` shows the reviewed mapping
  format used to link a prepared cross-section asset to `e_CF4_elastic`.

## Workflow

Run from the repository root:

```powershell
reactgen enrich cases/ar_cf4_db_smoke/input.yaml --registry registry --workspace cases/ar_cf4_db_smoke/work --source-profile cases/ar_cf4_db_smoke/source_profile.yaml
reactgen import-cross-sections cases/ar_cf4_db_smoke/cross_sections/e_CF4_elastic.csv --workspace cases/ar_cf4_db_smoke/work --source local_file --reaction-id e_CF4_elastic --target CF4 --license-note "synthetic test fixture"
```

The included mapping already points at the SHA-qualified fixture asset path
created by the import command. When replacing the CSV with real data, update
that mapping path to the new imported asset name before applying it.

```powershell
reactgen apply-cross-section-mapping cases/ar_cf4_db_smoke/cross_section_mapping.yaml --workspace cases/ar_cf4_db_smoke/work
reactgen generate cases/ar_cf4_db_smoke/input.yaml --registry cases/ar_cf4_db_smoke/work/prepared_registry --output cases/ar_cf4_db_smoke/outputs --export-dnt-inputs
reactgen plan-missing cases/ar_cf4_db_smoke/outputs --output cases/ar_cf4_db_smoke/work/missing_plan.yaml
reactgen visualize cases/ar_cf4_db_smoke/outputs --output cases/ar_cf4_db_smoke/visualizations
```

Graphviz DOT files are always written by `visualize`. SVG/PNG rendering is
created only when the `dot` executable is installed.

## Replacing The Fixtures

For real studies, replace `internal_data/` with reviewed internal or literature
snapshots and replace the synthetic cross-section CSV with licensed local assets.
Keep imported data in `work/prepared_registry/` until reviewed. Use
`reactgen promote --apply` only with an explicit review decision file.
