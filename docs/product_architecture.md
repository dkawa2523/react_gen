# plasma-reactgen Product Architecture

`plasma-reactgen` is organized around a deterministic local generation core,
plus reviewable preparation, enrichment, external data, and promotion layers.
The layers are intentionally separated so public data acquisition and optional
source tooling do not become runtime requirements for `reactgen generate`.

## Core Generation Layer

The core generation layer reads a case YAML and a local registry, then writes
reaction-network outputs. It owns:

- case loading
- local `FileRegistry` access
- collision-pair selection
- registered and optionally inferred channel providers
- `ReactionNetworkBuilder`
- species reference, charge-balance, and element-balance checks
- state lists, DNT task summaries, coverage reports, and missing-data reports
- explicit generation completeness and machine-readable truncation records
- YAML/CSV output writing

User commands in this layer:

- `reactgen generate`
- `reactgen visualize`
- `reactgen export-dnt`
- `reactgen infer-candidates`
- `reactgen dev-check`

The core generation layer does not download public data, call online APIs,
calculate cross sections, run Boltzmann solvers, or run DNT/DNT+DM solvers.
`dnt_tasks.yaml` reports pair-property readiness separately from complete-input
readiness: a pair can have all transport properties while still lacking channel
thresholds or energetics.

`summary.json` is the primary completeness view. Its `generation_complete`
field is false whenever a configured limit omits data, and `truncations` records
the limit name, scope, value, depth, observed/retained/omitted counts, and
limit-specific details. The reaction, coverage, and quality YAML outputs expose
the same status where relevant; truncated generation is never marked
mechanism-ready for review.

## Preparation And Enrichment Layer

The preparation/enrichment layer creates a review workspace and writes local
prepared registry files. It owns:

- `workspace/prepared_registry/`
- `prepare_report.yaml`
- `enrichment_report.yaml`
- curated registry copied as the prepared-registry baseline
- internal file providers
- local snapshot providers such as NIST and Argonne/ATcT-style thermochemistry
- optional local `chemicals` package providers
- property enrichment and conflict reporting
- reaction enrichment from configured local providers
- cross-section asset imports and mapping updates
- missing-data planning

User commands in this layer:

- `reactgen enrich`
- `reactgen import-cross-sections`
- `reactgen apply-cross-section-mapping`
- `reactgen plan-missing`

This layer may write `prepared_registry/` and workspace reports. It must not
mutate curated `registry/` files. `reactgen enrich --fresh` removes only
enrich-owned workspace artifacts before rebuilding the prepared registry;
omitting it preserves local overlays for incremental review. Cross-section
mapping accepts only existing files contained by `prepared_registry/` and
reports every rejected mapping.

## External Data Tools Layer

`external_data_tools/` is outside `src/plasma_reactgen`. It owns optional public
DB/API experiments, explicit URL downloads, raw local file caching, snapshot
planning, and snapshot validation.

Implemented external tools include:

- explicit download manifests using stdlib `urllib`
- PubChem identity snapshot fetching and normalization
- NIST snapshot planning and validation
- LXCat/manual raw cross-section import
- OpenADAS raw file registration
- VAMDC raw query capture
- KIDA/UMIST-like local network conversion
- Argonne/ATcT-style thermochemistry snapshot planning and validation
- chemical identity snapshot/fetch skeletons for ChEBI, ChemSpider, OPSIN, and
  NCI/Cactus

These tools may access online resources only when explicitly invoked by a user.
They are not imported by the core runtime and do not make `generate` depend on
network access.

## Registry Promotion And Review Layer

The review layer is the only supported path from prepared/candidate data into
curated `registry/`.

User command:

- `reactgen promote`

Promotion is dry-run by default. `--apply` is required to mutate curated
registry files. Existing curated species and reaction channels are not
overwritten, and conflicts are reported in `promote_report.yaml`.

## Benchmark Layer

The repository contains a local three-case semiconductor benchmark workflow.
Each run rebuilds its enrichment workspace in fresh mode, validates expected
network content, collects coverage/readiness metrics, and writes per-case YAML
reports plus a generated Markdown report. Its enrichment quality gate fails on
unavailable configured sources, invalid property candidates, unresolved product
species or reactions, and invalid/skipped reaction channels. Ordinary missing
physical properties remain visible data gaps rather than structural failures.

Generated `benchmark_report.yaml`, `benchmark_metrics.yaml`, and `summary.yaml`
are the source of truth for a run. Checked-in Markdown result narratives are
review snapshots and can become stale when code, fixtures, or policies change.

Before a real benchmark, record:

- the case input
- the source profile
- the registry or prepared registry used by `generate`
- local snapshot and asset provenance
- missing-data and enrichment reports
- any promotion decisions

## Design Boundaries

- Keep `ReactionNetworkBuilder` focused on network generation from available
  local data.
- Treat `ReactionNetwork` as the diagnostic source of truth; output builders
  must not independently rediscover reaction gaps.
- Build pair-wise DNT exports from `dnt_tasks`, which is the canonical DNT
  classification and readiness representation.
- Define source profiles in registry YAML only, and apply providers in their
  declared order. The local registry is a baseline, not an enrichment source.
- Keep inference default-disabled and clearly marked as `status: inferred`.
- Keep imported data marked as `imported` or `literature_supported` until
  reviewed.
- Keep public DB/API/download logic out of `src/plasma_reactgen`.
- Keep source acquisition, preparation, and promotion separate from generation.
- Make every configured generation limit visible in output completeness data.
- Never register a cross-section path that escapes the prepared registry or
  does not resolve to a local file.
