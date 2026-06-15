# Release Readiness: update2_db

Date: 2026-06-15

This note summarizes the current `update2_db` baseline for a usable initial
product. It focuses on local, reproducible workflows for low-pressure plasma
reaction-network preparation and generation. No new DB integrations are implied
by this document.

## What Works Now

- `reactgen generate` builds a deterministic reaction network from a local
  registry or prepared registry.
- `reactgen enrich` creates `workspace/prepared_registry/` from the curated
  registry plus configured local/offline providers.
- Local registry, internal file, local snapshot, and local asset workflows are
  separated from curated `registry/`.
- Cross-section CSV/TSV assets can be imported into `prepared_registry/assets/`
  and mapped to prepared electron channels.
- Missing-data planning and manual fill-in templates are available for review
  workflows.
- DNT input export writes solver-free YAML inputs. It does not run DNT or
  Boltzmann solvers.
- `quality_summary.yaml` gives a compact advisory view of mechanism review
  readiness, DNT pair readiness, cross-section coverage, provenance coverage,
  and top missing actions.
- External acquisition tools live under `external_data_tools/`; architecture
  tests prevent the core package from importing them.
- A local Ar/CF4 smoke case and a local benchmark runner are available.

## Commands Verified

The exact `python` command failed in this Windows environment because `python`
resolved to the Microsoft Store alias. The `py` launcher was used for executable
verification.

Test run:

```powershell
python -m pytest
```

Result: failed before tests started because Python was not found through the
`python` alias.

```powershell
py -m pytest
```

Result: `211 passed in 4.98s`.

The `reactgen` console script was not on PATH in this checkout, so smoke commands
were verified through the same CLI module with `PYTHONPATH=src`:

```powershell
$env:PYTHONPATH='src'
py -m plasma_reactgen.interface.cli enrich cases/ar_cf4_db_smoke/input.yaml --registry registry --workspace cases/ar_cf4_db_smoke/work --source-profile cases/ar_cf4_db_smoke/source_profile.yaml
py -m plasma_reactgen.interface.cli generate cases/ar_cf4_db_smoke/input.yaml --registry cases/ar_cf4_db_smoke/work/prepared_registry --output cases/ar_cf4_db_smoke/outputs --export-dnt-inputs
py -m plasma_reactgen.interface.cli plan-missing cases/ar_cf4_db_smoke/outputs --output cases/ar_cf4_db_smoke/work/missing_plan.yaml
py -m external_data_tools.benchmark_runner benchmarks/benchmark_config.yaml --only ar_cf4_db_smoke
```

Verified smoke results:

- Enrich returned 0.
- Generate returned 0.
- Plan missing returned 0.
- Benchmark runner returned 0 and passed `ar_cf4_db_smoke`.
- Generated smoke network: 12 species, 43 reactions, 16 electron reactions,
  27 ion-neutral reactions.
- Coverage: 17 found pairs, 23 missing pairs.
- DNT tasks: 12 total, 10 ready.
- Missing data items: 19.
- Cross-section asset coverage in this smoke run: 0, because the reviewed smoke
  commands did not include `import-cross-sections` and mapping.

## Data Sources Active By Default

For `local_only`:

- Active: `local_registry`, `local_assets`
- Optional: `internal_file`, `nist_snapshot`, `chemicals_optional`
- Disabled: `pubchem_online`, `vamdc`, `openadas`
- External-only: `pubchem_fetch`, `lxcat_raw_import`, `openadas_raw_import`,
  `vamdc_query`

`source-list` was verified with:

```powershell
py -m plasma_reactgen.interface.cli source-list --source-profile local_only --registry registry
```

Provider counts for `local_only`: species=1, properties=1, reactions=1.

## Data Sources External-Only

The following tools are external acquisition or conversion helpers and should be
run explicitly with `python -m external_data_tools...` or `py -m ...`:

- PubChem identity fetcher: external API snapshot creation only.
- LXCat raw import: local/manual file normalization only, no scraping or login.
- OpenADAS raw import: manual raw file cache and mapping skeletons only.
- VAMDC query skeleton: raw query capture only, no XSAMS conversion.
- Astrochem network converter: local KIDA/UMIST-like CSV/TSV conversion into
  review-required ion-neutral candidates.
- NIST and Argonne/ATcT planners/validators: local snapshot planning and
  validation only.

These tools do not run from `reactgen generate`.

## Known Limitations

- `reactgen generate` does not calculate cross sections.
- No DNT or Boltzmann solver is executed.
- Online DB access is not part of the core package.
- PubChem core provider is a disabled placeholder.
- NIST, Argonne/ATcT, chemical identity, LXCat, OpenADAS, VAMDC, and astrochem
  workflows require local files or external-tool outputs and human review.
- Cross-section asset coverage is only as good as imported and mapped local
  assets.
- Some bundled starter registry values are engineering seeds or estimates and
  require review before production modeling.
- `reactgen` command availability depends on installing the package or exposing
  the console script on PATH.

## Required Domain Expert Review

Before using outputs for modeling decisions, review:

- Collision radii and transport/DNT parameters.
- Electron cross-section mappings and asset provenance.
- Ion-neutral DNT classes and reaction energetics sign convention.
- Imported internal or literature reaction channels.
- Thermochemistry values used to derive reaction energetics.
- Any estimated, inferred, imported, or literature-supported entries before
  promotion to curated `registry/`.

## License-Sensitive Sources

License-sensitive or redistribution-sensitive sources are handled as local files,
local snapshots, external tool outputs, or optional package providers. They are
not bundled as production-ready data by default.

- NIST-derived snapshots: local snapshot only; users handle citation and license
  review.
- Argonne/ATcT-style thermochemistry: local/internal snapshot only; users handle
  redistribution permissions.
- LXCat files: user-provided local files; no scraping, login, or redistribution.
- OpenADAS and VAMDC: external raw capture or manual import only.
- Chemicals package: optional local Python package, lazy import, not a core
  dependency.
- PubChem: external identity snapshot fetcher only; no core online access.

See `external_data/source_catalog.yaml` and `docs/source_license_policy.md`.

## Adding A New DB Provider

Use `docs/provider_extension_guide.md` as the main checklist.

Minimum expectations:

- Keep online/download logic outside `src/plasma_reactgen`.
- Core providers must read local files or local package data only.
- Do not mutate curated `registry/`.
- Return YAML-compatible dictionaries.
- Include `source_record` or provenance.
- Validate units conservatively.
- Add provider-factory support only when the provider is useful for prepare/enrich.
- Add tests for missing configuration, no network access, and no curated-registry
  mutation.
- Add source catalog governance metadata if licensing or redistribution matters.

## Running The Ar/CF4 Smoke Case

From an installed environment:

```powershell
reactgen enrich cases/ar_cf4_db_smoke/input.yaml --registry registry --workspace cases/ar_cf4_db_smoke/work --source-profile cases/ar_cf4_db_smoke/source_profile.yaml
reactgen generate cases/ar_cf4_db_smoke/input.yaml --registry cases/ar_cf4_db_smoke/work/prepared_registry --output cases/ar_cf4_db_smoke/outputs --export-dnt-inputs
reactgen plan-missing cases/ar_cf4_db_smoke/outputs --output cases/ar_cf4_db_smoke/work/missing_plan.yaml
```

To include the synthetic cross-section fixture:

```powershell
reactgen import-cross-sections cases/ar_cf4_db_smoke/cross_sections/e_CF4_elastic.csv --workspace cases/ar_cf4_db_smoke/work --source local_file --reaction-id e_CF4_elastic --target CF4 --license-note "synthetic test fixture"
reactgen apply-cross-section-mapping cases/ar_cf4_db_smoke/cross_section_mapping.yaml --workspace cases/ar_cf4_db_smoke/work
```

Then rerun `generate`.

## Interpreting Outputs

`network.reactions.yaml`

- Generated reaction channels included in the mechanism.
- Contains reaction family, type, equation, depth, reactants, products,
  validation status, data status, and source data.
- Check electron reactions for cross-section asset paths.
- Check ion-neutral reactions for DNT class and reaction energetics.

`network.states.yaml`

- Species states introduced by input gases and reactions.
- Shows depth first seen, roles, composition, charge, classes, properties, and
  missing properties.

`dnt_tasks.yaml`

- Solver-free DNT task summary by ion-neutral pair.
- Shows readiness and missing ion/neutral properties.
- Ready tasks still require solver-side review before physical use.

`dnt_inputs/`

- Per-pair YAML inputs for DNT/DNT+DM style workflows.
- These files are inputs only; no solver is run.

`missing_data.yaml`

- Machine-readable diagnostics for missing species, properties, cross-section
  paths, reaction energetics, and DNT readiness gaps.

`missing_plan.yaml`

- Action-oriented grouping of missing data into a small number of actions:
  seed species, enrich properties, import cross sections, review energetics, or
  manual review.

`quality_summary.yaml`

- Advisory readiness report.
- In the current Ar/CF4 smoke run, mechanism review readiness is true, but
  cross-section coverage is low and DNT required properties remain missing for
  some pairs.

## Promotion Criteria

Promote prepared data into curated `registry/` only when:

- A decision YAML explicitly marks the item for promotion.
- `reactgen promote --apply` is used.
- Existing curated species or channels are not overwritten.
- Provenance, citation, source IDs, and review notes are present.
- License review is complete for imported/public/commercial/user-provided data.
- Domain experts have reviewed physical values, reaction balance, DNT class,
  reaction energetics, and cross-section mapping.
- Smoke generation still passes after promotion.

Default promotion mode is dry-run. Use conflicts as review blockers, not as
automatic merge prompts.
