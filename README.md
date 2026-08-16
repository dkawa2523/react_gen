# plasma-reactgen

`react_gen` / `plasma-reactgen` is a local-registry-driven reaction-network
generator for low-pressure plasma mechanism work. It is aimed at reviewable
semiconductor plasma workflows where species, reaction channels, physical
properties, and cross-section asset links are kept as readable YAML and local
files.

The normal generation path is deterministic: `reactgen generate` follows
primary, secondary, and later products from the input gases until the registered
reaction frontier closes, then writes a lineage-aware reaction list.
`network.reactions.yaml` / `.csv` are the primary products. Reaction equations
do not require DNT, a solver result, or a numerical cross section/rate.

## User Commands

| command | purpose | mutates curated `registry/`? |
|---|---|---|
| `generate` | Build a reaction network from a case YAML and local registry. | No |
| `visualize` | Create statistics plots and Graphviz reaction-network views from generated outputs. | No |
| `export-dnt` | Write solver-free pair-wise DNT+/DNT+DM input YAML from a case and registry. | No |
| `dev-check` | Validate registry structure, uniqueness, references, and local asset links. Returns non-zero on errors. | No |

## Core Workflows

### Generate

```powershell
reactgen generate cases/ar_cf4/input.yaml --output cases/ar_cf4/outputs
```

The normal user supplies only the gases in the case YAML and runs `generate`;
source profiles, workspaces, mappings, and property files are not required.
Species and reusable reaction records come from the shared `registry/`; a gas
mixture is never required as prebuilt data. When `--registry` is omitted, an
optional versioned release pack may overlay the shared registry. No matching
pack is not a data gap. Explicit `--registry` remains supported.
Reaction discovery is driven entirely by files under `registry/reactions/*/*.yaml`:
both reactants must already be active and at least one must be in the current
frontier. Consequently, registered families such as `electron`, `ion_neutral`,
`neutral_neutral`, `ion_ion`, and `electron_ion` need no CaseConfig switches,
and unregistered species combinations are not invented. Binary families use two
active reactants; `unimolecular` records use one physical reactant.
Main outputs include:

- `network.reactions.yaml` / `.csv` (primary reaction list)
- `mechanism_coverage.yaml` (bounded primary-source table coverage)
- `network.states.yaml` / `.csv`
- `dnt_tasks.yaml`
- `coverage_report.yaml`
- `missing_data.yaml` / `.csv`
- `summary.json`
- `quality_summary.yaml`

`generate` does not calculate electron cross sections, run DNT or Boltzmann
solvers, download public data, scrape websites, or call online APIs.

See [Reaction output contract](docs/reaction_output_contract.md) for lineage,
dataset, and missing-data field definitions. `dnt_tasks.yaml` only inventories
ion-neutral properties and existing datasets; no DNT runner or result importer
is included.
See [Shared registry coverage](docs/shared_registry_coverage.md) for the completed
CF4/O2 and SF6/O2 bounded gas-phase mechanisms and prioritized scientific gaps.
Pack creation and local snapshot imports are maintainer workflows documented in
[Registry packs and data administration](docs/registry_packs.md).

Configured limits are never silent. `summary.json` contains
`generation_complete` and a machine-readable `truncations` list; the reaction,
coverage, and quality YAML outputs repeat the relevant completeness data. Limit
events identify the applied limit and record retained/omitted counts and
context. A truncated run is not marked mechanism-ready for review in
`quality_summary.yaml`.
The default has no depth limit and propagates excited states; it follows the
registered chemistry until the frontier closes. Set `expansion.max_depth` or
disable `propagate_excited_states` only for a deliberately partial diagnostic
network.

## Data Maintainer Workflows

Normal generation does not require enrichment, a workspace, mappings, or
manual property input. Those operations are optional registry-maintenance
workflows and are intentionally documented separately:

- [Registry packs and data administration](docs/registry_packs.md) covers
  versioned packs and exact-match local snapshot imports.
- [Manual data input](docs/manual_data_input_guide.md) covers exceptional gaps
  that cannot be filled from reviewed snapshots.
- [Semiconductor maintainer workflow](docs/quickstart_semiconductor.md) covers
  preparation, review, and explicit promotion.

The compatibility commands `enrich`, `import-cross-sections`,
`apply-cross-section-mapping`, `plan-missing`, and `promote` remain available,
but they are not part of the normal user path.

## External Data Tools

`external_data_tools/` is separate from the core package. It contains optional
local/external tooling for explicit URL downloads, raw file caching, snapshot
planning/validation, PubChem identity snapshots, LXCat raw imports, OpenADAS raw
file registration, VAMDC raw query capture, astrochemical network conversion,
thermochemistry snapshot planning, a reviewed semiconductor-chemistry inventory,
and a licensed QDB raw-response fetcher.

These tools may access online resources only when explicitly invoked outside the
core runtime. Their outputs are local files under `external_data/`,
`workspaces/`, or `benchmarks/`. Generated snapshots and imported assets require
human review before use and are never auto-promoted into curated `registry/`.
For CF2, CF3, CF4, O2, SF3, SF4, SF5, and SF6,
`python -m external_data_tools.data_admin import_nist_beb` imports NIST SRD 107
total-ionization tables into an explicit prepared registry; it does not treat
them as product-resolved channel cross sections.

For O2 process rates, `python -m external_data_tools.data_admin
import_oxygen_cross_sections` downloads the official evaluated workbook once,
converts its seven reviewed tables to SI CSV assets, and maps them to exact
reaction IDs in a prepared registry. The CC BY-NC source data are not bundled
in the shared registry. Install the isolated importer dependency with
`python -m pip install -e ".[external-data]"`; the core generator still depends
only on PyYAML.
Source/license governance is tracked in `external_data/source_catalog.yaml`; see
[docs/source_license_policy.md](docs/source_license_policy.md). External source
setup for NIST/ATcT/Chemicals/PubChem/LXCat workflows is described in
[docs/external_source_setup.md](docs/external_source_setup.md).

To turn arbitrary input gases into an actionable, DB-specific collection
backlog without creating mixture packs, run:

```powershell
python -m external_data_tools.data_admin plan_data_acquisition `
  --seed-gases Ar O2 CF4 SF6 `
  --registry registry `
  --output-dir external_data/acquisition_work
```

The generated manifests keep confirmed gaps, numerical dataset gaps, and
unverified reaction-pair candidates separate. Downloads and registry promotion
remain explicit follow-up operations.

The QDB manifest is derived from the 29 chemistry sets in the cited QDB Table 7.
Fetches require `QDB_API_KEY` from the environment, redact it from records, keep
responses site-local, and never auto-promote reactions.

The plan can download the official UMIST Rate22 file with
`python -m external_data_tools.umist_rate22` and then match its native `.rates`
records to exact registry pair targets. A zero-match result is recorded rather
than being treated as coverage.

Benchmark outputs under `benchmarks/results/` are reproducible artifacts and
are intentionally not versioned. Benchmark fixtures remain under
`benchmarks/fixtures/`.
Case `outputs/` and `work/` directories are likewise reproducible local
artifacts and are not versioned; case inputs and reviewed fixtures remain in
the repository.

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

Install the pinned quality toolchain and run the same gates as CI:

```powershell
python -m pip install -e ".[quality]"
python -m nox -s quality-fast
python -m nox -s quality-pr
```

Scheduled mutation and end-to-end checks use
`python -m nox -s quality-nightly`. The existing-issue baseline is updated only
through the explicit `python -m nox -s quality-baseline` command; normal checks
and CI never rewrite it. See [Quality gates](docs/quality.md).

Validate a registry before generation or promotion:

```powershell
reactgen dev-check --registry registry --strict
```

`dev-check` returns exit code `1` for a missing registry or any validation
error, so it can be used directly as a CI gate. In non-strict mode, unresolved
product references and missing cross-section files remain warnings; `--strict`
promotes them to errors.

## Documentation

- [物理・シミュレーション技術レポート](docs/plasma_reactgen_technical_report.md)
- [Product architecture](docs/product_architecture.md)
- [Data sources](docs/data_sources.md)
- [Semiconductor quickstart](docs/quickstart_semiconductor.md)
- [Source and license policy](docs/source_license_policy.md)
- [External source setup](docs/external_source_setup.md)
- [Provider extension guide](docs/provider_extension_guide.md)
- [Registry data guide](docs/registry_data_guide.md)
- [Inference design](docs/inference_design.md)
- [DNT input export](docs/dnt_input_export.md)
- [Visualization design](docs/visualization_design.md)
