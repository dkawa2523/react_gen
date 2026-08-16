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
- `reactgen infer-candidates`

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
- VAMDC raw query capture and XSAMS review inventory
- KIDA/UMIST local network conversion with native Rate22 parsing, pair-target
  filtering, and rate-candidate projection
- arbitrary-gas data-acquisition planning and DB-specific manifests
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
  local data. `application/network_expansion.py` owns pair/channel traversal,
  `application/network_expansion_state.py` owns limits and accumulated state,
  and `application/network_species_expansion.py` owns introduced-species
  handling. Initialization/finalization remains in `application/network_state.py`.
- Keep DNT artifact assembly in `application/dnt_task_builder.py`. Pair
  inference, required physical properties, and mass fallback live in
  `dnt_properties.py`; pair/channel completeness decisions live in
  `dnt_readiness.py`.
- Keep `application/reaction_factory.py` as the generated-reaction projection.
  Legacy and normalized numerical-data availability is classified only in
  `reaction_data_status.py`.
- Keep lineage mutation in `application/reaction_lineage.py`; input-species
  filtering, precursor lookup, and producer indexing live in
  `reaction_lineage_index.py`.
- Keep manual-input generation as a three-step flow: report normalization in
  `preparation/input_report_reader.py`, record classification in
  `preparation/input_template_records.py`, and file output in
  `preparation/input_templates.py`.
- Keep reaction enrichment traversal in `preparation/reaction_enrichment.py`.
  Provider channel normalization/persistence, product-species resolution, and
  report bookkeeping live in `reaction_enrichment_channels.py`,
  `reaction_enrichment_species.py`, and `reaction_enrichment_report.py`.
- Keep `preparation/preparer.py` as the public workspace workflow. Provider and
  source resolution lives in `preparation_context.py`, species projection and
  overlay cleanup in `prepared_species.py`, and report aggregation in
  `preparation_report.py`.
- Keep `preparation/promote.py` focused on explicit decision orchestration.
  Species/channel execution, report bookkeeping, registry lookup/YAML
  persistence, and pure payload transformations live in `promotion_items.py`,
  `promotion_report.py`, `promotion_repository.py`, and
  `promotion_payloads.py`, respectively.
- Keep benchmark artifact loading, metric evaluation, and Markdown rendering in
  `benchmark_report_data.py`, `benchmark_evaluation.py`, and
  `benchmark_markdown.py`, respectively. `benchmark_report.py` is only the
  public API and CLI.
- Keep benchmark execution separate from report presentation:
  `benchmark_workflow.py` owns one-case execution, `benchmark_commands.py`
  adapts the reactgen CLI, `benchmark_io.py` owns safe generated paths and YAML
  I/O, and `benchmark_quality_gate.py` classifies enrichment defects. Optional
  pip installation reuses the explicit command runner in
  `source_setup_actions.py`; benchmark setup must not maintain a second process
  execution path.
- Keep the stable benchmark metric artifact assembled in `benchmark_metrics.py`.
  DNT readiness aggregation and reaction/asset aggregation live in
  `benchmark_dnt_metrics.py` and `benchmark_reaction_metrics.py`.
- Keep inference providers behind `inference/provider.py` as the stable import
  facade. Registry delegation, inferred channel/species generation, and
  curated-plus-inferred composition live in `registered_provider.py`,
  `inferred_provider.py`/`inferred_species.py`, and `composite_provider.py`.
- Keep `inference/candidate_writer.py` focused on candidate-registry assembly
  and file output. Reaction traversal, inferred-channel de-duplication, and
  candidate payload construction live in `reaction_candidate_builder.py`.
- Keep Graphviz file execution in `visualization/network.py`. Reaction-network
  and species-lineage edge selection live in separate DOT builders, while
  `graphviz_edges.py` and `graphviz_dot.py` contain their shared projection and
  presentation rules.
- Keep `visualization/svg_charts.py` as the public statistical-chart facade.
  Input normalization and geometry live in `svg_chart_layout.py`, tick scaling
  in `svg_chart_scale.py`, shared presentation primitives in
  `svg_chart_primitives.py`, and chart-specific rendering in
  `svg_horizontal_bar.py` and `svg_grouped_bar.py`.
- Keep reaction-card geometry in `visualization/reaction_pathway_layout.py`.
  `reaction_pathway.py` owns only SVG presentation and file writing; it must not
  rediscover reaction lineage or expansion depth.
- Keep `lxcat_raw_import.py` as the CLI and compatibility facade. Format parsing,
  normalized asset writing, and prepared-registry mapping live in
  `lxcat_parser.py`, `lxcat_assets.py`, and `lxcat_import_workflow.py`.
- Keep `chemical_identity_fetch.py` as the identity-fetch workflow and
  module-execution facade.
  `chemical_identity_cli.py` owns argument parsing and terminal summaries.
  Provider availability, ChEBI matching, and raw-source caching live in
  `chemical_identity_sources.py`; snapshot and manifest persistence lives in
  `chemical_identity_artifacts.py`; record merging remains in
  `chemical_identity_normalize.py`.
- Keep `source_setup.py` as the setup workflow and module-execution facade.
  Argument parsing and terminal output live in `source_setup_cli.py`; report
  construction, status calculation, and summary formatting live in
  `source_setup_report.py`. Access-profile
  validation, explicit installation/download actions, and YAML/path projection
  live in `source_setup_validation.py`, `source_setup_actions.py`, and
  `source_setup_io.py`; validation remains free of network and install side
  effects.
- Keep registry administration entry points in `registry_admin.py`.
  `registry_snapshot_import.py` is only the stable snapshot facade; property
  mutation, rate-dataset mutation, and shared snapshot parsing/provenance live
  in `registry_property_snapshot.py`, `registry_rate_snapshot.py`, and
  `registry_snapshot_records.py`. LXCat import and pack lifecycle operations
  remain in their separately named modules.
- Keep `infrastructure/file_registry.py` as the repository adapter for species,
  reactions, rules, and assets. Registry YAML loading, duplicate-ID checks, and
  species-to-pair index construction live in `infrastructure/registry_index.py`.
- Keep `infrastructure/registry_pack.py` focused on read-only registry overlay
  and path resolution. Index filtering, manifest validation, safe pack-root
  containment, and deterministic pack ranking live in
  `infrastructure/registry_pack_selection.py`.
- Keep `external_data_tools/data_admin.py` as the CLI adapter. Its parser owns
  command-line defaults, while command execution delegates to the stable
  `registry_admin.py` API; import argument definitions are shared once.
- Keep NIST and Argonne/ATcT snapshot validators separated into record-shape,
  property-value, and source-record checks. These checks validate local
  snapshots only and do not acquire or promote data.
- Treat `ReactionNetwork` as the diagnostic source of truth; output builders
  must not independently rediscover reaction gaps.
- Keep `application/diagnostics.py` as the public missing-data assembler.
  State, reaction, and DNT gap classification lives in
  `application/missing_data_collectors.py`; serializers must not add diagnostic
  rules of their own.
- Keep readiness, quality, and action-summary decisions in
  `application/output_summary.py`; infrastructure writers only serialize the
  resulting contracts.
- Build the DNT task catalog once per generated network and reuse it for
  diagnostics, YAML output, and optional solver-free input export.
- Define source profiles in registry YAML only, and apply providers in their
  declared order. The local registry is a baseline, not an enrichment source.
- Keep `data_sources/provider_factory.py` as the stable ordered-construction
  facade. Supported names live in `provider_catalog.py`, profile and alias
  interpretation in `provider_profile.py`, and lazy local-adapter construction
  in `provider_builders.py`. Aliases for one physical source must not construct
  duplicate providers, and `disabled_sources` is applied before construction.
- Keep candidate ranking in `data_sources/selection.py`; translate provenance
  record shapes into profile names only in `data_sources/source_identity.py`.
- Keep state-list projection in `application/state_builder.py`; derive
  reaction-family roles without mutating the network in `state_roles.py`.
- Keep source-list orchestration in `data_sources/source_listing.py`.
  Configuration detection, source-catalog/license evaluation, and text
  presentation live in `source_configuration.py`, `source_catalog.py`, and
  `source_listing_format.py`, respectively.
- Keep optional `chemicals` imports and API compatibility handling in
  `data_sources/chemicals_adapter.py`, source-record projection and unit
  conversion in `chemicals_records.py`, and stable provider entry points in
  `chemicals_provider.py`.
- Keep chemical-identity snapshot loading and species lookup in
  `data_sources/chemical_identity_snapshot.py`. Non-destructive metadata merge,
  formula comparison, and manual-review conflict construction live in
  `chemical_identity_merge.py`.
- Keep public dataset value types and object construction in
  `domain/datasets.py`; explicit and legacy channel mappings are normalized
  only in `dataset_mapping.py`.
- Keep property-enrichment workspace traversal and YAML persistence in
  `preparation/property_enrichment.py`. Provider collection, supported-unit
  filtering, profile-based selection, and conflict detection live in
  `property_candidates.py`.
- Keep cross-section mapping orchestration and report assembly in
  `preparation/cross_section_mapping.py`. Entry and asset validation lives in
  `cross_section_mapping_rules.py`; prepared electron-reaction mutation lives
  in `prepared_cross_sections.py`.
- Keep reaction-energetics traversal and reporting in
  `preparation/reaction_energetics.py`. Local/provider enthalpy resolution lives
  in `enthalpy_lookup.py`; stoichiometric calculation and evidence projection
  live in `reaction_energy_calculation.py`.
- Keep legacy preparation pair selection separated by collision family, and
  keep generation admission policy separated into status, pair-data readiness,
  and local-asset checks in `application/channel_policy.py`.
- Keep inference default-disabled and clearly marked as `status: inferred`.
- Keep imported data marked as `imported` or `literature_supported` until
  reviewed.
- Keep public DB/API/download logic out of `src/plasma_reactgen`.
- Keep source acquisition, preparation, and promotion separate from generation.
- Make every configured generation limit visible in output completeness data.
- Never register a cross-section path that escapes the prepared registry or
  does not resolve to a local file.
- Keep `interface/cli.py` focused on command dispatch. Normal argument
  definitions live in `cli_parser.py`; generation, DNT export, and
  visualization execution live in `generate_command.py`, `dnt_command.py`, and
  `visualize_command.py`. Shared provider composition for network-producing
  commands lives in `network_dependencies.py`. Historic
  preparation/review argument definitions live in `maintenance_parser.py`, and
  their execution adapters live in `maintenance_commands.py` until the commands
  can move to data-admin completely.
- Keep registration-template YAML construction in `registration_templates.py`.
  Species, electron-pair, and ion-pair defaults have separate builders and share
  only arity validation and the common pair document envelope.
- Construct the public reaction record explicitly in
  `application/reaction_catalog.py`; adding an internal dataclass field must not
  silently extend the YAML contract.
- Keep optional public-data workflows thin: VAMDC per-query validation and
  capture lives in `vamdc_query_records.py`, while XSAMS review projection
  lives in `vamdc_xsams_inventory.py`; astrochemical notation and record
  projection live in `astrochem_reaction.py`; PubChem URL construction and
  per-species acquisition live in `pubchem_urls.py` and
  `pubchem_species_fetch.py`.
- Keep acquisition planning split into target extraction
  (`acquisition_targets.py`), source routing (`acquisition_manifests.py`), and
  orchestration/persistence (`data_acquisition_plan.py`). A planning run scopes
  arbitrary gas input; it must not create a mixture-specific data pack.
- Keep the UMIST release format and fetch metadata in `umist_rate22.py`;
  `astrochem_reaction.py` owns notation/family conversion, while
  `astrochem_network_convert.py` only orchestrates filtering and artifacts.

## Compatibility boundary

Pair discovery is registry-driven. The old `collisions.electron` and
`collisions.ion_neutral` selectors are parsed only for case-file and Python API
compatibility and live in `application/legacy_config.py`; they do not select
normal generated families. New code must not depend on them.

The family-specific selector implementation lives under
`preparation/pair_selection.py`.

`max_missing_pairs_per_depth` and the strict data-policy switches are also
legacy expert controls. Registered reactions remain visible under the default
policy even when numerical datasets or DNT properties are missing.
