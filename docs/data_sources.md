# Data Sources

Prepare and enrich workflows may read optional local data sources and write
reviewable outputs under `prepared_registry/` or report files. Normal
`reactgen generate` remains local-registry-only and does not access online
services.

## Enrich Command

`reactgen enrich` runs the prepare workflow and configured local/offline
enrichers into a workspace:

```powershell
reactgen enrich CASE `
  --registry registry `
  --workspace workspace `
  --source-profile experimental_first
```

The command creates a local working registry at `workspace/prepared_registry/`,
then writes `workspace/prepare_report.yaml` and
`workspace/enrichment_report.yaml`. It does not call online services, mutate the
curated `registry/`, or promote prepared data back into curated files.

Configured local providers are used only when their source profile entries and
local configuration are available. Supported local/offline inputs include local
registry data, internal file snapshots, NIST snapshots, optional local
`chemicals` package data, ion reaction tables, and already imported/local
cross-section assets. The resulting `prepared_registry/` is intended to be
usable as the registry input to `reactgen generate` for review runs.

## Source Cache Manifest

Imported local files can be recorded under a workspace cache directory:

```text
workspace/source_cache/
  manifest.yaml
  <source_name>/<safe_file_name>_<sha12>.ext
```

The helper `record_source_file(cache_root, source_name, original_path)` computes
the source file SHA-256, copies the original file into the cache, and appends a
record to `manifest.yaml`:

```yaml
schema_version: 1
source_files:
  - source_type: local_file_cache
    source_name: lxcat_offline
    original_path: external_data/lxcat/e_cf4.csv
    cached_path: lxcat_offline/e_cf4_0123456789ab.csv
    sha256: ...
    imported_at: ...
```

Repeated imports are allowed. If a file with the same SHA-256 is already in the
manifest, a note is added to the new manifest entry instead of trying to resolve
or deduplicate the records. The source cache is local YAML plus copied files; it
does not require a database server and never mutates curated `registry/` files.

`reactgen import-cross-sections` records its input file in this cache and also
writes the cache record into the cross-section metadata sidecar. Prepare-time
local file inputs such as internal file DB snapshots and ion reaction tables are
recorded in the prepare report when practical. Future import commands, such as a
literature-candidate importer, should use the same helper.

## NIST Snapshot Files

The NIST snapshot adapter is a local file reader. It does not scrape NIST
websites, call NIST online services, or download public database content. Users
prepare snapshot YAML files themselves under a directory such as:

```text
external_data/nist/
  species_properties.yaml
  atomic_properties.yaml
  README.md
```

Enable the snapshot in a source profile:

```yaml
properties:
  - local_registry
  - internal_property_db
  - nist_snapshot
  - chemicals_optional
nist_snapshot:
  root: external_data/nist
```

The adapter accepts only clearly documented local units: `eV`, `amu`, `D`, and
`A3`. Records with other units are skipped and reported as unresolved by the
provider. Users are responsible for licensing, citation, and redistribution
requirements for any NIST-derived local snapshots they prepare.

## PubChem Provider Skeleton

`PubChemProvider` is currently a disabled extension point for future identity
and property enrichment. It does not import `requests` or `httpx`, does not make
HTTP calls, and returns empty candidate lists by default.

Configuration placeholder:

```yaml
species_identity:
  - local_registry
  - pubchem_offline
properties:
  - local_registry
  - pubchem_online
pubchem:
  enabled: false
  mode: online
  cache_dir: external_data/pubchem/cache
```

Future PubChem support should be limited to explicit `prepare` or `enrich`
workflows, never `reactgen generate`. Any online adapter should write and reuse
a local cache under `cache_dir` so repeated enrichment remains reviewable and
reproducible. Normal workflows must continue to work when PubChem is unavailable
or disabled.

## Offline Cross-Section Tables

`reactgen import-cross-sections` imports simple local CSV or TSV files into a
workspace `prepared_registry` asset directory. It does not log in to LXCat,
download data, scrape websites, call APIs, or compute cross sections.

Supported v1 columns are:

```text
energy_eV,cross_section_m2
```

Optional columns such as `process`, `target`, `reaction_id`, `source`, and
`comment` may be present, but only `energy_eV` and `cross_section_m2` are written
to the normalized table. The importer validates numeric energies, non-negative
cross sections, sortable energy grids, and at least two rows.

Example:

```powershell
reactgen import-cross-sections external_data/lxcat/e_cf4.csv `
  --workspace workspace `
  --source lxcat_offline `
  --reaction-id e_CF4_elastic `
  --target CF4
```

The command writes:

```text
workspace/prepared_registry/assets/cross_sections/<safe_name>.csv
workspace/prepared_registry/assets/cross_sections/<safe_name>.metadata.yaml
```

If `--reaction-id` matches a channel under
`workspace/prepared_registry/reactions/`, only that prepared registry channel is
linked to the imported asset. Curated `registry/` files are never modified.

## Cross-Section Mapping Files

For reviewed manual mappings, use `reactgen apply-cross-section-mapping` with a
simple YAML file:

```yaml
schema_version: 1
mappings:
  - reaction_id: e_CF4_dissociation_CF3_F
    asset_path: assets/cross_sections/e_CF4_dissociation_CF3_F_lxcat.csv
    source: lxcat_offline
    mapping_status: reviewed
    process_label_original: DISSOCIATION
    notes:
      - Mapped manually from local LXCat export.
```

Apply it to a workspace:

```powershell
reactgen apply-cross-section-mapping mapping.yaml --workspace workspace
```

Only `workspace/prepared_registry/reactions/electron/*.yaml` is scanned. There
is no fuzzy matching, no online access, and no updates to curated `registry/`
files. Missing reaction ids or missing asset paths are reported as unresolved.

## Property Enrichment

Prepare workflows can fill missing species properties in `prepared_registry`
from configured local providers. Enrichment is intentionally simple: provider
order follows the source profile, the first non-null candidate with the expected
unit is used, and existing non-null curated values are never overwritten.

When a provider offers a different value for an already populated property, the
value is left untouched and a `property_conflict` item is written to the prepare
report for manual review. Unsupported units are skipped. `collision_radius_A` is
not estimated automatically; it is filled only when an explicit provider returns
a value in angstroms, otherwise it remains unresolved for DNT readiness.

## Reaction Enrichment

Prepare workflows may import reviewed reaction channels from configured local
providers into `prepared_registry/reactions/`. The enrichment step reuses the
existing collision pair selection logic from the case config, asks providers in
source-profile order, and writes only channels whose species references, charge
balance, and element balance validate.

Existing prepared channels with the same id are not overwritten. If a product
species is missing, the channel may include a simple `species_candidate` payload
with composition, charge, classes, and optional properties; that species is
written as a prepared seed before the channel is accepted. Channels with missing
unresolvable products or failed validation are reported for review instead of
being written. Curated `registry/` files and `reactgen generate` behavior are not
changed.

## Ion Reaction Tables

`IonReactionTableProvider` reads simple local YAML snapshots for ion-neutral
reaction candidates. The format is intentionally generic so that internal DB
exports, KIDA/UMIST-like gas-phase network conversions, OpenADAS-like
charge-exchange table conversions, or manually reviewed literature tables can be
mapped into the same local structure. The adapter does not access KIDA, UMIST,
OpenADAS, VAMDC, or any online service.

Example:

```yaml
schema_version: 1
source:
  source_type: local_snapshot
  database: internal_ion_reaction_db
  version: 2026-06
reactions:
  - id: Arp_CF4_dct_CF3p
    projectile: Ar+
    target: CF4
    family: ion_neutral
    type: dissociative_charge_transfer
    dnt_class: short_range_charge_exchange
    products:
      - species: Ar
        n: 1
      - species: CF3+
        n: 1
      - species: F
        n: 1
    deltaE_products_minus_reactants_eV: -1.0891
    status: literature_supported
    evidence_type: experimental_or_literature
    citation: local literature table
```

Configure it in a source profile:

```yaml
ion_neutral_reactions:
  - local_registry
  - ion_reaction_table
ion_reaction_table:
  files:
    - external_data/ion_reactions/internal.yaml
    - external_data/ion_reactions/kida_converted.yaml
```

Only `family: ion_neutral` records are used. Records without explicit
`curated` or `literature_supported` status are treated as `imported`
candidates. Reaction enrichment validates species references, charge balance,
and element balance before writing any channel into `prepared_registry`; invalid
or unresolved records are reported instead of being written.

## Missing-Data Plans

`reactgen plan-missing` converts an existing `missing_data.yaml` report into a
small action plan. It is a reporting command only: it does not fetch data, call
online services, change diagnostics, or mutate any registry files.

Example:

```powershell
reactgen plan-missing cases/ar_cf4/outputs --output missing_plan.yaml
```

The input may be either `missing_data.yaml` itself or an output directory that
contains it. The resulting `missing_plan.yaml` groups items into a few reviewed
actions: `seed_species`, `enrich_properties`, `import_cross_sections`,
`review_reaction_energetics`, and `manual_review`. Command hints are deliberately
lightweight; they point to the relevant prepare, enrich, import, or review step
without performing it automatically.

## Promotion Workflow

`reactgen promote` copies only explicitly reviewed prepared or candidate records
into curated `registry/`. The default mode is dry-run, so registry files are not
mutated unless `--apply` is provided.

Example decision file:

```yaml
schema_version: 1
decisions:
  - kind: species
    id: CF3
    action: promote
    target_status: literature_supported
    notes:
      - reviewed by domain expert
  - kind: reaction_channel
    id: e_CF4_dissociation_CF3_F
    pair:
      family: electron
      projectile: e
      target: CF4
    action: promote
    target_status: literature_supported
  - kind: species
    id: speculative_fragment
    action: reject
```

Dry-run:

```powershell
reactgen promote workspace/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml
```

Apply:

```powershell
reactgen promote workspace/prepared_registry `
  --registry registry `
  --decision review_decisions.yaml `
  --apply
```

Species are copied only when the curated registry does not already contain that
species. Reaction channels are appended only when the corresponding curated pair
file does not already contain the channel id. Existing curated files and channels
are never overwritten, and conflicts are reported in
`workspace/promote_report.yaml` for manual review. Provenance fields such as
`data.provenance`, `data.evidence`, `data.source_record`, `confidence`, and
`inference` are preserved by copying the reviewed payload rather than rebuilding
it.
