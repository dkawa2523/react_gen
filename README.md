# plasma-reactgen

`react_gen` / `plasma-reactgen` is a local-registry-driven reaction-network
generator for low-pressure plasma mechanism work. It is aimed at reviewable
semiconductor plasma workflows where species, reaction channels, physical
properties, and cross-section asset links are kept as readable YAML and local
files.

The normal generation path is deterministic: `reactgen generate` reads a case
YAML plus a local registry and writes network, state, DNT-readiness, coverage,
and missing-data outputs. It does not access online databases.

## What The Main Commands Do

| command | purpose | mutates curated `registry/`? |
|---|---|---|
| `generate` | Build a reaction network from a case YAML and local registry. | No |
| `enrich` | Prepare a workspace registry and run configured local/offline enrichers. | No |
| `import-cross-sections` | Normalize a local CSV/TSV cross-section table into `workspace/prepared_registry/assets/`. | No |
| `apply-cross-section-mapping` | Apply reviewed cross-section asset mappings to prepared electron channels. | No |
| `plan-missing` | Convert `missing_data.yaml` into a simple action plan. | No |
| `promote` | Promote explicitly reviewed prepared/candidate data into curated registry. Dry-run by default. | Only with `--apply` |
| `visualize` | Create statistics plots and Graphviz reaction-network views from generated outputs. | No |
| `export-dnt` | Write solver-free pair-wise DNT+/DNT+DM input YAML from a case and registry. | No |
| `infer-candidates` | Write inferred species/reaction candidates into `candidate_registry/` for review. | No |
| `dev-check` | Check registry readability and basic references. | No |

## Core Workflows

### Generate

```powershell
reactgen generate cases/ar_cf4/input.yaml --registry registry --output cases/ar_cf4/outputs
```

Main outputs include:

- `network.reactions.yaml` / `.csv`
- `network.states.yaml` / `.csv`
- `dnt_tasks.yaml`
- `coverage_report.yaml`
- `missing_data.yaml` / `.csv`
- `summary.json`

`generate` does not calculate electron cross sections, run DNT or Boltzmann
solvers, download public data, scrape websites, or call online APIs.

### Enrich

```powershell
reactgen enrich cases/ar_cf4/input.yaml `
  --registry registry `
  --workspace workspaces/ar_cf4 `
  --source-profile experimental_first
```

`enrich` creates `workspaces/ar_cf4/prepared_registry/`, writes
`prepare_report.yaml` and `enrichment_report.yaml`, and uses only configured
local/offline providers. Curated `registry/` files are not changed.

### Import And Map Cross Sections

```powershell
reactgen import-cross-sections external_data/lxcat/e_cf4.csv `
  --workspace workspaces/ar_cf4 `
  --source lxcat_offline `
  --reaction-id e_CF4_elastic `
  --target CF4

reactgen apply-cross-section-mapping external_data/lxcat/mappings.yaml `
  --workspace workspaces/ar_cf4
```

The importer accepts simple CSV/TSV files with `energy_eV` and
`cross_section_m2`, writes normalized local assets plus metadata sidecars under
`prepared_registry`, and can link only prepared registry channels.

### Plan Missing Data

```powershell
reactgen plan-missing cases/ar_cf4/outputs --output workspaces/ar_cf4/missing_plan.yaml
```

This reads existing `missing_data.yaml` and writes suggested actions such as
`enrich_properties`, `import_cross_sections`, and
`review_reaction_energetics`. It is reporting only and fetches no data.

### Promote Reviewed Data

```powershell
reactgen promote workspaces/ar_cf4/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml

reactgen promote workspaces/ar_cf4/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml `
  --apply
```

Promotion is explicit and dry-run by default. Existing curated species or
channels are not overwritten; conflicts are reported for manual review.

## Minimal Ar/CF4 Workflow

```powershell
reactgen enrich cases/ar_cf4/input.yaml --registry registry --workspace workspaces/ar_cf4 --source-profile local_only
reactgen generate cases/ar_cf4/input.yaml --registry workspaces/ar_cf4/prepared_registry --output workspaces/ar_cf4/outputs
reactgen plan-missing workspaces/ar_cf4/outputs --output workspaces/ar_cf4/missing_plan.yaml
reactgen visualize workspaces/ar_cf4/outputs --output workspaces/ar_cf4/visualizations
```

For a cross-section update, import a reviewed local table, apply a reviewed
mapping if needed, then rerun `generate` with the prepared registry.

See [docs/quickstart_semiconductor.md](docs/quickstart_semiconductor.md) for a
more complete minimal semiconductor workflow.

## External Data Tools

`external_data_tools/` is separate from the core package. It contains optional
local/external tooling for explicit URL downloads, raw file caching, snapshot
planning/validation, PubChem identity snapshots, LXCat raw imports, OpenADAS raw
file registration, VAMDC raw query capture, astrochemical network conversion,
and thermochemistry snapshot planning.

These tools may access online resources only when explicitly invoked outside the
core runtime. Their outputs are local files under `external_data/`,
`workspaces/`, or `benchmarks/`. Generated snapshots and imported assets require
human review before use and are never auto-promoted into curated `registry/`.
Source/license governance is tracked in `external_data/source_catalog.yaml`; see
[docs/source_license_policy.md](docs/source_license_policy.md). External source
setup for NIST/ATcT/Chemicals/PubChem/LXCat workflows is described in
[docs/external_source_setup.md](docs/external_source_setup.md).

## What It Does Not Do

- `generate` does not access online databases or public APIs.
- `generate` does not calculate cross sections or rate coefficients.
- `generate` does not run DNT, DNT+DM, or Boltzmann solvers.
- `enrich` does not mutate curated `registry/`; it writes to
  `workspace/prepared_registry`.
- Imported, inferred, or externally fetched data is not promoted automatically.
- Public DB data must be supplied as reviewed local snapshots/assets or fetched
  with external tools before prepare/enrich workflows use it.
- Placeholder providers, such as the core PubChem provider, are not production
  online adapters.

## Install And Test

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pytest
```

If `python` points to the Windows Store alias, use the active environment
interpreter or the Python launcher:

```powershell
py -m pytest
```

## Documentation

- [Product architecture](docs/product_architecture.md)
- [Data sources](docs/data_sources.md)
- [Semiconductor quickstart](docs/quickstart_semiconductor.md)
- [Source and license policy](docs/source_license_policy.md)
- [External source setup](docs/external_source_setup.md)
- [DB cleanup workflow](docs/db_cleanup_workflow.md)
- [Provider extension guide](docs/provider_extension_guide.md)
- [Registry data guide](docs/registry_data_guide.md)
- [Inference design](docs/inference_design.md)
- [DNT input export](docs/dnt_input_export.md)
- [Visualization design](docs/visualization_design.md)
