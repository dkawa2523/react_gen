# Quickstart: Semiconductor Plasma Review Workflow

This quickstart shows a minimal local workflow for a semiconductor-style
low-pressure plasma case. It uses Ar/CF4 as the sample case and keeps all
prepared/imported data outside curated `registry/` until explicit review.

## 1. Prepare And Enrich A Workspace

Start with the local-only profile:

```powershell
reactgen enrich cases/ar_cf4/input.yaml `
  --registry registry `
  --workspace workspaces/ar_cf4 `
  --source-profile local_only
```

This writes:

```text
workspaces/ar_cf4/prepared_registry/
workspaces/ar_cf4/prepare_report.yaml
workspaces/ar_cf4/enrichment_report.yaml
```

Curated `registry/` is not changed.

You usually do not need to list every expected fragment species in the case
input. During enrich, local/internal reaction providers may introduce product
species into `prepared_registry` when a configured species provider has an exact
id match with explicit composition and charge. Incomplete product species remain
reported for manual review.

## 2. Generate From The Prepared Registry

```powershell
reactgen generate cases/ar_cf4/input.yaml `
  --registry workspaces/ar_cf4/prepared_registry `
  --output workspaces/ar_cf4/outputs `
  --export-dnt-inputs
```

Inspect:

```text
workspaces/ar_cf4/outputs/network.reactions.yaml
workspaces/ar_cf4/outputs/network.states.yaml
workspaces/ar_cf4/outputs/missing_data.yaml
workspaces/ar_cf4/outputs/dnt_tasks.yaml
```

## 3. Plan Missing Data Work

```powershell
reactgen plan-missing workspaces/ar_cf4/outputs `
  --output workspaces/ar_cf4/missing_plan.yaml
```

Use the plan to decide whether the next action is property enrichment,
cross-section import, reaction energetics review, or manual registry review.
The command does not fetch data or modify any registry.

## 4. Import A Reviewed Cross-Section CSV

Prepare a local CSV or TSV with:

```text
energy_eV,cross_section_m2
0.1,1.0e-22
1.0,2.0e-21
```

Import it into the workspace:

```powershell
reactgen import-cross-sections external_data/lxcat/e_cf4_dissociation.csv `
  --workspace workspaces/ar_cf4 `
  --source lxcat_offline `
  --reaction-id e_CF4_dissociation_CF3_F `
  --target CF4 `
  --license-note "Review LXCat citation and redistribution requirements before sharing."
```

Replace `e_CF4_dissociation_CF3_F` with the reviewed channel ID from your
prepared registry or generated `network.reactions.yaml`.

The importer writes normalized assets under:

```text
workspaces/ar_cf4/prepared_registry/assets/cross_sections/
```

It also writes a metadata sidecar and, when the reaction ID exists in the
prepared registry, links only that prepared channel.

## 5. Apply A Reviewed Mapping If Needed

If the asset was imported without a direct reaction link, create a reviewed
mapping file:

```yaml
schema_version: 1
mappings:
  - reaction_id: e_CF4_dissociation_CF3_F
    asset_path: assets/cross_sections/e_CF4_dissociation_CF3_F_lxcat.csv
    source: lxcat_offline
    mapping_status: reviewed
    process_label_original: DISSOCIATION
    notes:
      - Mapped manually from a local LXCat export.
```

Apply it:

```powershell
reactgen apply-cross-section-mapping external_data/lxcat/mappings.yaml `
  --workspace workspaces/ar_cf4
```

Only `workspaces/ar_cf4/prepared_registry/reactions/electron/*.yaml` is
updated. Curated `registry/` is not changed.

## 6. Rerun Generate

```powershell
reactgen generate cases/ar_cf4/input.yaml `
  --registry workspaces/ar_cf4/prepared_registry `
  --output workspaces/ar_cf4/outputs_after_xsec `
  --export-dnt-inputs
```

Compare `missing_data.yaml`, `dnt_tasks.yaml`, and DNT input files before using
the prepared data downstream.

## 7. Optional Promotion

After domain review, write a decision file:

```yaml
schema_version: 1
decisions:
  - kind: reaction_channel
    id: e_CF4_dissociation_CF3_F
    pair:
      family: electron
      projectile: e
      target: CF4
    action: promote
    target_status: literature_supported
```

Dry-run first:

```powershell
reactgen promote workspaces/ar_cf4/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml
```

Apply only after the report looks right:

```powershell
reactgen promote workspaces/ar_cf4/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml `
  --apply
```

Promotion never overwrites existing curated species or channels automatically.

## Notes

- `reactgen generate` does not access online databases.
- Cross-section CSV files must come from reviewed local sources.
- External data tools can help create snapshots or raw caches, but their outputs
  still require review before use.
- Missing DNT properties such as `collision_radius_A` are not invented by this
  workflow.
- Reaction-driven species seeding is conservative: it uses explicit local
  source records only and writes only to `prepared_registry`.
