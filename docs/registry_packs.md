# Registry packs and data administration

Normal users continue to run only:

```powershell
reactgen generate case.yaml --output outputs
```

When `--registry` is omitted, reactgen reads `registry_packs/index.yaml` and
selects the most specific, newest pack whose `seed_gases` contain every input
gas. The selected pack is overlaid read-only on the base `registry/`. Pack
species and channels take precedence without modifying either source. The pack
ID and version are recorded in `summary.json.registry`.

If no pack matches, generation continues with the base registry and adds a
`registry_pack.coverage` warning to `missing_data.yaml`. Supplying
`--registry PATH` keeps the existing explicit-registry behavior and disables
automatic pack selection.

Selection has a separate validation boundary in
`infrastructure/registry_pack_selection.py`: malformed index entries and
missing manifests are ignored, manifest paths must remain inside
`registry_packs/`, and otherwise equivalent packs are ranked deterministically.
`infrastructure/registry_pack.py` only resolves and overlays the selected pack.

## Pack structure

```text
registry_packs/
  index.yaml
  <pack_id>/
    <version>/
      pack.yaml
      species/
      reactions/
      assets/
        cross_sections/
        rate_coefficients/
```

The resolver continues to read the original `<pack_id>/pack.yaml` layout for
backward compatibility. New builds always use a version directory so multiple
published versions cannot point at the same files.

`pack.yaml` records the ID, version, seed gases, supported species,
recommended depth, source manifest, coverage summary, redistribution status,
validation report, and any excluded numeric assets.

Redistribution values are `permitted`, `internal`, and `site-local`. An asset
is copied only when both the pack and its source explicitly say `permitted`.
The default is `site-local`; LXCat numeric assets are never assumed to be
redistributable.

## Maintainer commands

Administrative commands remain outside the normal `reactgen` CLI:

```powershell
python -m external_data_tools.data_admin plan_registry_pack `
  --seed-gases Ar CF4 --max-depth 2 --registry registry

python -m external_data_tools.data_admin import_lxcat_raw export.txt `
  --registry workspaces/ar_cf4/prepared_registry

python -m external_data_tools.data_admin import_property_snapshot properties.yaml `
  --registry workspaces/ar_cf4/prepared_registry

python -m external_data_tools.data_admin import_rate_snapshot rates.yaml `
  --registry workspaces/ar_cf4/prepared_registry

python -m external_data_tools.data_admin build_registry_pack `
  --id ar_cf4 --version 1.0.0 --seed-gases Ar CF4 --max-depth 2 `
  --registry workspaces/ar_cf4/prepared_registry
```

Importers use local files, retain SHA-256 and source metadata, and apply data
only when a reaction ID or normalized equation has exactly one match.
Unmatched and ambiguous records are review items. Reusing the same source hash
is idempotent.

Supported P2 forms are LXCat normalized CSV/TSV and minimal two-column text
blocks, property YAML/CSV, and rate YAML/CSV using `constant`, `arrhenius`, or
`table`. Table data may be inline or a local referenced file.

Full LXCat XML, database-specific multi-column exports, automatic unit
inference, pressure-dependent/falloff rates, uncertainty covariance matrices,
and non-Arrhenius analytic rate laws remain review-only.
