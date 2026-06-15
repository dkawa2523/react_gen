# DB/Source Provider Audit

Date: 2026-06-15

Branch audited: `update2_db`

## Scope And Invariants

This audit covers the current database, source-provider, preparation, and
external acquisition tooling added around prepare/enrich workflows:

- `src/plasma_reactgen/data_sources/`
- `src/plasma_reactgen/preparation/`
- `external_data_tools/`
- `external_data/`
- `docs/data_sources.md`
- `external_data_tools/README.md`
- `registry/rules/source_profiles/*.yaml`
- related tests under `tests/`

Important invariants observed during the audit:

- `reactgen generate` remains registry-driven and deterministic. Its command
  path uses `FileRegistry`, `ReactionNetworkBuilder`, and local registry files.
- No online API client is called by `reactgen generate`.
- The core package dependencies remain light: `pyyaml` is the only declared
  runtime dependency in `pyproject.toml`.
- External online/API/download tooling is located under `external_data_tools/`,
  not under `src/plasma_reactgen`.
- Prepared, enriched, imported, or candidate data is written outside curated
  `registry/` unless the explicit `reactgen promote --apply` workflow is used.
- One nuance: `src/plasma_reactgen/interface/cli.py` imports several
  preparation/data-source modules at top level so those modules are importable
  when any `reactgen` subcommand starts. This does not make `generate` call
  those providers, but it is a cleanup target because optional/snapshot
  implementation details bleed into CLI import time.

## Component Classification Matrix

| component | file_path | categories | purpose | imported_by_core_runtime | can_access_network | optional_dependency | can_mutate_curated_registry | outputs_written | current_tests | recommendation |
|---|---|---|---|---|---|---|---|---|---|---|
| `base` | `src/plasma_reactgen/data_sources/base.py` | `keep_core_prepare_provider` | Small provider interface classes. | Yes, by data-source providers. | No. | No. | No. | None. | `tests/test_data_sources.py` indirectly. | Keep. Consider converting method names to one consistent protocol in a later cleanup. |
| `models` | `src/plasma_reactgen/data_sources/models.py` | `keep_core_prepare_provider`, `needs_doc_update` | Dataclass helpers for candidate/source records. | Yes, by provider interfaces and registry placeholders. | No. | No. | No. | None. | `tests/test_data_sources.py` indirectly. | Keep, but align dict/dataclass usage; many providers now return plain dicts instead. |
| `source_profile` | `src/plasma_reactgen/data_sources/source_profile.py` | `keep_core_prepare_provider` | Loads built-in or YAML source profiles. | Yes, by prepare/enrich. | No. | No. | No. | None. | `tests/test_data_sources.py`. | Keep. Add schema-focused docs if profiles continue growing. |
| `registry` | `src/plasma_reactgen/data_sources/registry.py` | `keep_core_prepare_provider`, `needs_doc_update` | Global provider registry and provider registration helpers. | Yes, by tests and some workflows; placeholders register at import time. | No. | Chemicals is optional through registered providers. | No. | None. | `tests/test_data_sources.py`, `tests/test_internal_file_sources.py`, `tests/test_nist_snapshot.py`, `tests/test_argonne_atct_workflow.py`, `tests/test_cross_section_importer.py`, `tests/test_ion_reaction_table.py`. | Keep, but split placeholder registration from concrete provider imports to reduce import-time complexity. |
| `selection` | `src/plasma_reactgen/data_sources/selection.py` | `keep_core_prepare_provider` | Simple source/status ranking. | Yes, by property enrichment. | No. | No. | No. | None. | `tests/test_selection.py`. | Keep. This is a good low-complexity selection boundary. |
| `cache` | `src/plasma_reactgen/data_sources/cache.py` | `keep_core_prepare_provider` | Workspace source-file cache manifest helper. | Yes, by prepare and cross-section import. | No. | No. | No. | `workspace/source_cache/manifest.yaml` and copied cached files. | `tests/test_source_cache.py`. | Keep. Could share a YAML helper with external cache tooling. |
| `local_registry` | `src/plasma_reactgen/data_sources/local_registry.py` | `keep_core_prepare_provider` | Read-only providers over existing `FileRegistry`. | Yes, through provider registry and tests. | No. | No. | No. | Candidate dicts only. | `tests/test_data_sources.py`. | Keep. It is the safest default provider family. |
| `internal_file` | `src/plasma_reactgen/data_sources/internal_file.py` | `keep_core_prepare_provider` | Reads local YAML/JSON/CSV internal species, properties, reactions, and cross-section indexes. | Yes, by `prepare_case`. | No. | No. | No. | Candidate dicts only; prepare writes derived prepared files. | `tests/test_internal_file_sources.py`, `tests/test_enrich_cli.py`. | Keep. This is practical for company/local curated data. |
| `ion_reaction_table` | `src/plasma_reactgen/data_sources/ion_reaction_table.py` | `keep_core_prepare_provider` | Reads generic local ion-neutral reaction table snapshots. | Yes, by `prepare_case` when configured. | No. | No. | No. | Candidate dicts only. | `tests/test_ion_reaction_table.py`, `tests/test_reaction_enrichment.py`. | Keep. Important bridge for reviewed literature/internal ion-neutral data. |
| `nist_snapshot` | `src/plasma_reactgen/data_sources/nist_snapshot.py` | `keep_core_prepare_provider`, `needs_license_review` | Reads local NIST-derived property snapshots. | Yes, by `prepare_case` when configured. | No. | No. | No. | Candidate dicts only. | `tests/test_nist_snapshot.py`. | Keep, with explicit license/citation review before real benchmark data use. |
| `argonne_atct_snapshot` | `src/plasma_reactgen/data_sources/argonne_atct_snapshot.py` | `keep_core_prepare_provider`, `needs_license_review` | Reads local ATcT/Argonne-style thermochemistry snapshots. | Not used by `prepare_case` directly; provider is available through registration/tests and reaction energetics workflows. | No. | No. | No. | Candidate dicts only. | `tests/test_argonne_atct_workflow.py`. | Keep for reaction energetics, but document how it is wired into enrich/prepare profiles. |
| `chemical_identity_snapshot` | `src/plasma_reactgen/data_sources/chemical_identity_snapshot.py` | `keep_core_prepare_provider`, `needs_license_review`, `needs_doc_update` | Reads local merged identity snapshots and can enrich prepared species metadata. | Yes, by `enricher.py` when profile includes `chemical_identity_snapshot`. | No. | No. | No. | Updates `prepared_registry/species/*.yaml` metadata only. | `tests/test_chemical_identity_workflow.py`. | Keep, but clarify formula-conflict policy in docs. |
| `chemicals_provider` | `src/plasma_reactgen/data_sources/chemicals_provider.py` | `keep_core_prepare_provider`, `candidate_for_future_plugin` | Optional lazy provider using the Python `chemicals` package for identity/basic properties. | Yes, imported by `prepare_case` and `data_sources/__init__`; actual package import is lazy. | No direct network call. | Optional `chemicals`, not a core dependency. | No. | Candidate dicts only; prepare may write selected candidates to `prepared_registry`. | `tests/test_chemicals_provider.py`. | Keep for now, but it is large/package-specific and a strong future plugin candidate. |
| `pubchem_provider` | `src/plasma_reactgen/data_sources/pubchem_provider.py` | `keep_documented_placeholder`, `candidate_for_removal` | Disabled core extension point for future PubChem support. | Yes, registered as disabled placeholder at data-source registry import time. | No; methods return empty lists. | No. | No. | None. | `tests/test_pubchem_provider.py`. | Keep only as documented placeholder unless PubChem remains in roadmap; conditionally remove if identity enrichment is fully externalized. |
| `lxcat_offline` | `src/plasma_reactgen/data_sources/lxcat_offline.py` | `keep_core_prepare_provider`, `needs_license_review` | Reads local LXCat-style cross-section index YAML. | Available through provider registry; not used by `generate`. | No. | No. | No. | Candidate dicts only. | `tests/test_cross_section_importer.py`. | Keep. It supports prepared local asset links without parsing online data. |
| `cross_section_table` | `src/plasma_reactgen/data_sources/cross_section_table.py` | `keep_core_prepare_provider`, `needs_license_review` | Imports local CSV/TSV cross-section tables into prepared assets and optionally links prepared channels. | Yes, top-level import in CLI for `import-cross-sections`. | No. | No. | No. | `workspace/prepared_registry/assets/cross_sections/*.csv`, metadata YAML, optional prepared channel update. | `tests/test_cross_section_importer.py`, `tests/test_source_cache.py`. | Keep. Consider moving import command helpers under preparation/imports later. |
| `data_sources.__init__` | `src/plasma_reactgen/data_sources/__init__.py` | `needs_doc_update` | Broad re-export of providers, importers, and registry helpers. | Yes when users import the package namespace. | No direct network call. | Imports optional-provider wrappers but not optional package eagerly. | No. | None. | Covered indirectly by many tests. | Reduce broad imports/re-exports to lower import-time coupling. |
| `preparer` | `src/plasma_reactgen/preparation/preparer.py` | `keep_core_prepare_provider`, `needs_doc_update` | Prepares workspace registry overlays and runs local property/reaction enrichment. | Yes, by `enricher.py` and CLI `enrich`. | No. | Chemicals optional provider object may be constructed. | No. | `prepared_registry/`, `prepare_report.yaml`, source cache entries. | `tests/test_enrich_cli.py`, `tests/test_internal_file_sources.py`, `tests/test_chemicals_provider.py`. | Keep but refactor; it mixes provider discovery, caching, seeding, property enrichment, and reaction enrichment. |
| `enricher` | `src/plasma_reactgen/preparation/enricher.py` | `keep_core_prepare_provider` | End-to-end local/offline enrich orchestration. | Yes, by CLI `enrich`. | No. | No direct optional dependency. | No. | `workspace/prepared_registry/`, `workspace/prepare_report.yaml`, `workspace/enrichment_report.yaml`. | `tests/test_enrich_cli.py`, `tests/test_chemical_identity_workflow.py`. | Keep. Good user-facing workflow boundary. |
| `property_enrichment` | `src/plasma_reactgen/preparation/property_enrichment.py` | `keep_core_prepare_provider` | Fills missing prepared species properties and reports conflicts/unresolved items. | Yes, by `prepare_case`. | No. | Provider-dependent only. | No. | Updates `prepared_registry/species/*.yaml`; reports returned to prepare report. | `tests/test_property_enrichment.py`, `tests/test_chemicals_provider.py`. | Keep. Centralize provenance shape before adding more property sources. |
| `reaction_enrichment` | `src/plasma_reactgen/preparation/reaction_enrichment.py` | `keep_core_prepare_provider` | Imports provider channels into prepared registry after validation. | Yes, by `prepare_case`. | No. | No. | No. | Updates `prepared_registry/species/*.yaml` seeds and `prepared_registry/reactions/*/*.yaml`. | `tests/test_reaction_enrichment.py`, `tests/test_ion_reaction_table.py`. | Keep. Consider shared validation/report helpers with energetics and promotion. |
| `reaction_energetics` | `src/plasma_reactgen/preparation/reaction_energetics.py` | `keep_core_prepare_provider`, `needs_doc_update` | Computes missing ion-neutral deltaE from explicit enthalpy providers. | Not wired into `prepare_case` in the audited code path. | No. | Provider-dependent only. | No. | Updates prepared ion-neutral reaction YAML only. | `tests/test_argonne_atct_workflow.py`. | Keep, but document invocation/integration status before relying on it in benchmark workflows. |
| `cross_section_mapping` | `src/plasma_reactgen/preparation/cross_section_mapping.py` | `keep_core_prepare_provider` | Applies reviewed mapping YAML to prepared electron channels. | Yes, by CLI `apply-cross-section-mapping`. | No. | No. | No. | Updates `prepared_registry/reactions/electron/*.yaml`. | `tests/test_cross_section_mapping.py`. | Keep. Small and reviewable. |
| `missing_plan` | `src/plasma_reactgen/preparation/missing_plan.py` | `keep_core_prepare_provider` | Converts `missing_data.yaml` into action-oriented local plan. | Yes, by CLI `plan-missing`. | No. | No. | No. | `missing_plan.yaml`. | `tests/test_missing_plan.py`. | Keep. Useful planning command without data fetching. |
| `promote` | `src/plasma_reactgen/preparation/promote.py` | `keep_core_prepare_provider`, `needs_doc_update` | Explicit reviewed promotion from prepared/candidate registry to curated registry. | Yes, by CLI `promote`. | No. | No. | Yes, only with `--apply`. | `promote_report.yaml`; curated `registry/` mutations only for accepted decisions. | `tests/test_promote.py`. | Keep. Refactor later because it is long and security-critical. |
| `external_data_tools.config` | `external_data_tools/config.py` | `keep_external_tool` | External-tool environment config. | No. | No. | No. | No. | None. | `tests/test_external_data_tools.py`. | Keep. |
| `external_data_tools.cache` | `external_data_tools/cache.py` | `keep_external_tool` | External file copy/SHA helper. | No. | No. | No. | No. | External cache copies. | `tests/test_external_data_tools.py`. | Keep; consider sharing concepts with core cache without importing external tools into core. |
| `external_data_tools.manifest` | `external_data_tools/manifest.py` | `keep_external_tool` | External YAML manifest append/load helper. | No. | No. | No. | No. | External manifest YAML. | `tests/test_external_data_tools.py`, `tests/test_external_http_client.py`. | Keep. |
| `external_data_tools.http_client` | `external_data_tools/http_client.py` | `keep_external_tool`, `needs_license_review` | Stdlib explicit URL download helper with dry-run and SHA records. | No. | Yes, when invoked outside tests/dry-run. | No. | No. | Downloaded raw files and records. | `tests/test_external_http_client.py`. | Keep external only. Never import from core runtime. |
| `external_data_tools.download_manifest` | `external_data_tools/download_manifest.py` | `keep_external_tool`, `needs_license_review` | CLI for explicit user-provided download manifests. | No. | Yes, when invoked without dry-run. | No. | No. | Raw downloads, download report, external manifest records. | `tests/test_external_http_client.py`. | Keep external only. |
| `external_data_tools.pubchem_fetch` | `external_data_tools/pubchem_fetch.py` | `keep_external_tool`, `needs_license_review` | External PubChem identity snapshot fetcher. | No. | Yes, when invoked without dry-run. | No. | No. | Raw PubChem JSON and snapshot YAML. | `tests/test_external_pubchem_fetch.py`. | Keep external only. Review PubChem terms/citation before using snapshots. |
| `external_data_tools.pubchem_normalize` | `external_data_tools/pubchem_normalize.py` | `keep_external_tool`, `needs_license_review` | Normalizes conservative PubChem identity fields. | No. | No. | No. | No. | Snapshot records returned to fetcher. | `tests/test_external_pubchem_fetch.py`. | Keep. |
| `external_data_tools.chemical_identity_fetch` | `external_data_tools/chemical_identity_fetch.py` | `keep_external_tool`, `candidate_for_future_plugin`, `needs_license_review` | External identity fetch skeleton for ChEBI, ChemSpider, OPSIN, NCI/Cactus. | No. | Disabled by default; can access network only when explicitly enabled/configured. | ChemSpider API key optional via env. | No. | Raw identity files and snapshot YAML when enabled. | `tests/test_chemical_identity_workflow.py`. | Keep as external skeleton; consider plugin if these providers become active. |
| `external_data_tools.chemical_identity_normalize` | `external_data_tools/chemical_identity_normalize.py` | `keep_external_tool`, `needs_license_review` | Normalizes local chemical identity records. | No. | No. | No. | No. | Snapshot records returned to fetcher. | `tests/test_chemical_identity_workflow.py`. | Keep. |
| `external_data_tools.nist_snapshot_plan` | `external_data_tools/nist_snapshot_plan.py` | `keep_external_tool`, `needs_license_review` | Plans manually prepared NIST property snapshots from missing reports. | No. | No. | No. | No. | Required-property request YAML. | `tests/test_external_nist_snapshot_tools.py`. | Keep. Strong fit for local snapshot workflow. |
| `external_data_tools.nist_snapshot_validate` | `external_data_tools/nist_snapshot_validate.py` | `keep_external_tool`, `needs_license_review` | Validates manually prepared NIST snapshot YAML. | No. | No. | No. | No. | Validation report to stdout/return value. | `tests/test_external_nist_snapshot_tools.py`. | Keep. |
| `external_data_tools.argonne_atct_snapshot_plan` | `external_data_tools/argonne_atct_snapshot_plan.py` | `keep_external_tool`, `needs_license_review` | Plans thermochemistry snapshot needs from missing/network outputs. | No. | No. | No. | No. | Required-thermochemistry request YAML. | `tests/test_argonne_atct_workflow.py`. | Keep. Strong fit before DNT energetics benchmarks. |
| `external_data_tools.argonne_atct_snapshot_validate` | `external_data_tools/argonne_atct_snapshot_validate.py` | `keep_external_tool`, `needs_license_review` | Validates local ATcT/Argonne-style thermochemistry snapshots. | No. | No. | No. | No. | Validation report to stdout/return value. | `tests/test_argonne_atct_workflow.py`. | Keep. |
| `external_data_tools.lxcat_raw_import` | `external_data_tools/lxcat_raw_import.py` | `keep_external_tool`, `needs_license_review` | Imports user-provided LXCat/BOLSIG-like raw files into prepared cross-section assets. | No. | No. | No. | No. | Prepared cross-section assets, metadata, mapping updates, import report. | `tests/test_external_lxcat_raw_import.py`. | Keep but refactor; it is the largest module in the audit. |
| `external_data_tools.lxcat_manifest` | `external_data_tools/lxcat_manifest.py` | `keep_external_tool`, `needs_license_review` | Mapping-manifest support for LXCat imports. | No. | No. | No. | No. | Mapping-derived metadata returned to importer. | `tests/test_external_lxcat_raw_import.py`. | Keep. |
| `external_data_tools.openadas_raw_import` | `external_data_tools/openadas_raw_import.py` | `keep_external_tool`, `candidate_for_future_plugin`, `needs_license_review` | Registers manually downloaded OpenADAS raw files and optional ion-reaction skeletons. | No. | No. | No. | No. | Workspace source cache, import report, optional snapshot table. | `tests/test_external_openadas_raw_import.py`. | Keep external; future plugin candidate because applicability is specialized. |
| `external_data_tools.vamdc_query` | `external_data_tools/vamdc_query.py` | `keep_external_tool`, `candidate_for_future_plugin`, `needs_license_review` | Stores raw VAMDC TAP/XSAMS query results for review. | No. | Yes, when invoked without dry-run. | No. | No. | Raw XML/results and external manifest. | `tests/test_external_vamdc_query.py`. | Keep external skeleton; plugin candidate due federation-specific behavior. |
| `external_data_tools.astrochem_network_convert` | `external_data_tools/astrochem_network_convert.py` | `keep_external_tool`, `candidate_for_future_plugin`, `needs_license_review` | Converts local KIDA/UMIST-like CSV/TSV networks into generic ion-neutral candidates. | No. | No. | No. | No. | Converted ion reaction table and conversion report. | `tests/test_external_astrochem_network_convert.py`. | Keep external but label as candidate discovery only; plugin candidate if not used for semiconductor benchmarks. |
| `external_data/` docs | `external_data/**/*.md` | `keep_external_tool`, `needs_license_review` | Documents raw/snapshot areas for external data families. | No. | No. | No. | No. | None; directories hold ignored raw/snapshot files. | Covered indirectly by workflow tests. | Keep docs, but add a concise index linking which sources are practical for semiconductor plasma. |
| source profiles | `registry/rules/source_profiles/*.yaml` | `keep_core_prepare_provider`, `needs_doc_update` | Provider ordering and source policy. | Yes, by `load_source_profile`. | No. | Chemicals optional only when configured. | No. | None. | `tests/test_data_sources.py`, `tests/test_enrich_cli.py`. | Keep. Add examples for configuring NIST/ATcT/internal file roots. |
| `docs/data_sources.md` | `docs/data_sources.md` | `needs_doc_update` | User-facing source and prepare/enrich documentation. | No. | No. | No. | No. | None. | Not directly tested. | Keep and update after cleanup decisions; it is currently broad but useful. |
| `external_data_tools/README.md` | `external_data_tools/README.md` | `keep_external_tool`, `needs_doc_update` | External tooling policy and explicit download docs. | No. | No. | No. | No. | None. | Not directly tested. | Keep; add a map of tool maturity levels. |

## Component Notes

### Core Runtime And Generate Boundary

`reactgen generate` still uses local case input plus local registry data. The
generate subcommand does not call provider registries, online fetchers, snapshot
planners, optional `chemicals`, or external tools. Existing sample smoke tests
exercise the Ar/CF4 case through `ReactionNetworkBuilder`.

The main boundary issue is import shape rather than behavior: `cli.py` imports
`import_cross_section_table`, `enrich_case`, `promote_reviewed_registry`, and
other preparation modules at top level. That means a `reactgen generate` process
imports some prepare/import code before dispatching to the generate command.
This is currently safe because those imports do not perform network calls or
mutate files, but it makes the deterministic runtime boundary less obvious.

### Source Profiles

The three built-in profiles are present:

- `local_only`: local registry species/properties/reactions and local assets.
- `experimental_first`: local, internal, chemical identity snapshot, NIST,
  ATcT/Argonne, optional chemicals, LXCat offline.
- `internal_first`: internal sources before local registry where applicable.

They preserve the intended policy ordering and keep PubChem disabled by default.
The profiles do not themselves configure roots for NIST, ATcT/Argonne, chemical
identity, or ion reaction tables; those require explicit profile additions by
the caller.

### Practical Semiconductor Plasma Path

The most practical low-pressure semiconductor plasma workflow is:

1. Start with curated local registry data.
2. Prepare a workspace with `local_registry` and `internal_file`.
3. Fill conservative properties from reviewed NIST/ATcT local snapshots.
4. Import local LXCat/manual cross-section assets into prepared registry.
5. Add reviewed ion-neutral reaction tables for DNT-relevant channels.
6. Run `reactgen generate` against the prepared registry for review.
7. Promote only explicit reviewed decisions with `reactgen promote --apply`.

The external VAMDC, OpenADAS, astrochem, ChemSpider, OPSIN, and NCI/Cactus
tooling is useful as experimental acquisition/conversion scaffolding, but it is
less central to the immediate semiconductor workflow and should not be allowed
to drive benchmark results without review.

### Licensing And Review Risks

The following source families need explicit license/citation review before real
benchmark use or redistribution:

- NIST-derived snapshots.
- Argonne/ATcT or internal thermochemistry snapshots.
- PubChem API snapshots.
- ChEBI/ChemSpider/OPSIN/NCI/Cactus identity snapshots.
- LXCat exports and BOLSIG/LXCat-like cross-section files.
- OpenADAS raw files and derived mappings.
- VAMDC raw query outputs.
- KIDA/UMIST-like astrochemical converted networks.

The code generally records provenance and license notes, but no code can
validate that the user has redistribution rights. This should remain a human
review gate.

### Tests

Current data-source and external-tool tests are broad and useful:

- Core provider foundations: `tests/test_data_sources.py`,
  `tests/test_selection.py`, `tests/test_source_cache.py`.
- Local/internal/snapshot providers: `tests/test_internal_file_sources.py`,
  `tests/test_nist_snapshot.py`, `tests/test_argonne_atct_workflow.py`,
  `tests/test_chemical_identity_workflow.py`, `tests/test_chemicals_provider.py`.
- Reaction/property enrichment: `tests/test_property_enrichment.py`,
  `tests/test_reaction_enrichment.py`, `tests/test_enrich_cli.py`.
- Cross sections and mappings: `tests/test_cross_section_importer.py`,
  `tests/test_cross_section_mapping.py`, `tests/test_external_lxcat_raw_import.py`.
- External acquisition/conversion tools:
  `tests/test_external_data_tools.py`, `tests/test_external_http_client.py`,
  `tests/test_external_pubchem_fetch.py`,
  `tests/test_external_nist_snapshot_tools.py`,
  `tests/test_external_openadas_raw_import.py`,
  `tests/test_external_vamdc_query.py`,
  `tests/test_external_astrochem_network_convert.py`.
- Safety placeholders: `tests/test_pubchem_provider.py`,
  `tests/test_importer_placeholders.py`.

Potential stale area: documentation still describes some workflows more
smoothly than they are wired today. In particular, ATcT reaction energetics and
chemical identity snapshot enrichment should have clearer command-level docs if
they are part of the benchmark path.

## Complexity Hotspots

### Modules Over 250 Lines

| file | lines observed | concern | cleanup direction |
|---|---:|---|---|
| `external_data_tools/lxcat_raw_import.py` | 376 | Parsing, normalization, metadata, mapping, report writing, and CLI behavior live together. | Split parser/normalizer/report/linking helpers once behavior stabilizes. |
| `src/plasma_reactgen/preparation/preparer.py` | 348 | Provider discovery, source cache recording, species seeding, property enrichment, reaction enrichment, and overlay cleanup are coupled. | Extract provider-chain construction and source-cache recording into helpers/modules. |
| `src/plasma_reactgen/preparation/promote.py` | 296 | Promotion is safety-critical and handles species/channel mutation/reporting in one file. | Keep behavior, but separate decision parsing, dry-run planning, and apply operations. |
| `src/plasma_reactgen/data_sources/chemicals_provider.py` | 291 | Optional package adapter contains API probing, identity mapping, property mapping, and unit conversions. | Keep lazy behavior; consider moving to future plugin if optional providers expand. |

### Broad Direct Imports

- `src/plasma_reactgen/preparation/preparer.py` imports concrete provider
  classes directly. This makes adding/removing providers require changes in the
  orchestration module.
- `src/plasma_reactgen/data_sources/__init__.py` re-exports nearly every
  provider and helper. This makes importing `plasma_reactgen.data_sources`
  heavier than necessary.
- `src/plasma_reactgen/data_sources/registry.py` imports concrete provider
  classes inside registration helpers and also registers chemicals/PubChem
  placeholders at import time.
- `src/plasma_reactgen/interface/cli.py` imports prepare/import/promote modules
  at top level even when the selected command is `generate`.

### Repeated Helpers And Shapes

- YAML load/write helpers are repeated across preparation modules and external
  tools.
- `source_record`, `source_records`, `data.provenance`, and
  `metadata.property_sources` are all used, with slightly different shapes.
- Snapshot validation logic is repeated for NIST, Argonne/ATcT, chemical
  identity, OpenADAS, and LXCat import metadata.
- Registry mutation protections are spread across prepare, import, mapping, and
  promote workflows. They are tested, but the policy would be easier to audit if
  shared helper names made intent explicit.

## Recommended Next Cleanup Steps

### Must Do Before Real Benchmark

- Write a benchmark source policy document that identifies which local source
  families are approved for semiconductor low-pressure plasma results.
- Confirm license/citation handling for NIST, ATcT/Argonne/internal
  thermochemistry, PubChem identity snapshots, LXCat exports, and any converted
  external reaction networks.
- Add a short test or assertion that `reactgen generate` does not call provider
  registry functions, external tools, or online-capable helpers.
- Document the exact source profile and local snapshot paths used for benchmark
  reproduction.
- Decide whether ATcT reaction energetics should be wired into `reactgen enrich`
  or kept as an explicit manual function.

### Should Do Before Adding New DB

- Reduce top-level CLI imports by moving prepare/import/promote imports inside
  command handlers. This keeps `generate` import-time boundaries cleaner.
- Split `prepare_case` provider-chain construction from enrichment execution.
- Reduce `data_sources.__init__` re-exports; prefer importing concrete providers
  from their modules.
- Create a small shared provenance helper for source records and property source
  metadata.
- Create shared YAML helpers for safe load/write/report patterns.
- Add docs for source profile configuration blocks for `internal_file`,
  `nist_snapshot`, `argonne_atct_snapshot`, `chemical_identity_snapshot`, and
  `ion_reaction_table`.

### Optional Cleanup

- Split `external_data_tools/lxcat_raw_import.py` into parser, writer, and
  mapping-link modules.
- Split `promote.py` into dry-run planning and apply submodules.
- Move optional package/provider-specific adapters such as `chemicals_provider`
  toward a plugin-style boundary if more optional scientific packages are added.
- Add maturity labels to `external_data_tools/README.md`: stable local workflow,
  experimental external fetcher, placeholder/skeleton.

### Safe Removals If User Decides A DB Is Unnecessary

No immediate deletion is recommended in this audit. Conditional safe-removal
candidates are:

- `pubchem_provider` in core if PubChem identity support is fully externalized
  through snapshots.
- VAMDC external query skeleton if VAMDC is not part of the project roadmap.
- OpenADAS external raw import if charge-exchange/ADAS coefficient workflows
  are out of scope.
- Astrochem KIDA/UMIST converter if astrochemical candidate discovery is not
  useful for semiconductor plasmas.
- ChemSpider/OPSIN/NCI/Cactus identity skeletons if PubChem plus internal
  identity snapshots are sufficient.

Any removal should be a separate cleanup task with tests updated at the same
time.

## Test Result Summary

Requested command:

```powershell
python -m pytest
```

Result in this Windows environment:

```text
Python was not found; run without arguments to install from the Microsoft Store,
or disable this shortcut from Settings > Apps > Advanced app settings >
App execution aliases.
```

Fallback command:

```powershell
py -m pytest
```

Result:

```text
179 passed in 2.30s
```

No production code was changed for this audit. The only intended repository
change is this report file.
