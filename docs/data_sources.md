# Data Sources

Prepare and enrich workflows may read optional local data sources and write
reviewable outputs under a workspace. Normal `reactgen generate` remains
local-registry-only and does not access online services.

## Source Profiles

Source profiles define provider order and simple status policy. Built-in
profiles live under `registry/rules/source_profiles/`:

- `local_only`
- `experimental_first`
- `internal_first`

Profiles can include provider names such as `local_registry`,
`internal_property_db`, `nist_snapshot`, `argonne_atct_snapshot`,
`chemicals_optional`, `ion_reaction_table`, `local_assets`, and
`lxcat_offline`. Some providers also need local configuration blocks, for
example:

```yaml
properties:
  - local_registry
  - nist_snapshot
nist_snapshot:
  root: external_data/nist
```

Unknown or missing profile names fall back to `local_only`.

## Source Governance

External and internal data source governance is recorded in:

```text
external_data/source_catalog.yaml
```

The catalog classifies currently mentioned sources by category, allowed use,
license-review requirement, API-key requirement, redistribution risk, and
default status. Validate it with:

```powershell
python -m external_data_tools.source_catalog_check external_data/source_catalog.yaml
```

Sources with public API access, commercial terms, high redistribution risk, or
unknown redistribution risk must not be treated as bundled production data.

External acquisition setup is configured separately in:

```text
external_data/source_access_profiles.yaml
```

Check it with:

```powershell
python -m external_data_tools.source_setup --config external_data/source_access_profiles.yaml --check
```

This setup layer can install the optional `chemicals` package only with an
explicit flag and can run explicit URL downloads only when policy allows it.
It does not make core generation call online databases.

## Enrich Command

`reactgen enrich` runs prepare plus configured local/offline enrichers into a
workspace:

```powershell
reactgen enrich CASE `
  --registry registry `
  --workspace workspace `
  --source-profile experimental_first
```

The command writes:

```text
workspace/prepared_registry/
workspace/prepare_report.yaml
workspace/enrichment_report.yaml
```

It does not call online services, mutate curated `registry/`, or promote
prepared data. The prepared registry can be passed to `reactgen generate` for a
review run:

```powershell
reactgen generate CASE --registry workspace/prepared_registry --output workspace/outputs
```

## Implemented Core Prepare Providers

### Local Registry

`local_registry` providers expose existing `FileRegistry` species, properties,
reaction channels, and local cross-section asset links. They are read-only and
are the safest default source.

### Internal File Data

`internal_file` providers read local YAML/JSON/CSV files under a configured
directory, for example:

```text
internal_data/
  species/species.yaml
  properties/properties.yaml
  reactions/electron.yaml
  reactions/ion_neutral.yaml
  cross_sections/index.yaml
```

Use this for company/local curated data without SQL, REST, or network access.

### NIST Snapshot Files

`nist_snapshot` reads manually prepared local snapshot YAML. It does not scrape
NIST websites, call NIST services, or download NIST data.

Accepted property units are intentionally narrow: `eV`, `amu`, `D`, and `A3`.
Users are responsible for licensing, citation, and redistribution requirements
for any NIST-derived local snapshots.

### Argonne/ATcT-Style Thermochemistry Snapshots

`argonne_atct_snapshot` reads local thermochemistry snapshots with explicit
values such as `enthalpy_formation_eV`, `ionization_energy_eV`, and
`electron_affinity_eV`. The reaction energetics helper can fill missing
ion-neutral `deltaE_products_minus_reactants_eV` in a prepared registry only
when all required enthalpies are available from explicit sources.

These snapshots require license/citation review before benchmark use.

### Optional Chemicals Provider

`chemicals_optional` / `chemicals_local` can use the optional Python
`chemicals` package for conservative identity and basic property candidates.
The package is imported lazily and is not a core dependency. If unavailable, the
provider returns no candidates and prepare/enrich continues.

This provider should rank below curated local, internal, NIST, and ATcT-style
sources. It does not provide plasma cross sections.

### Chemical Identity Snapshot

`chemical_identity_snapshot` reads local merged identity snapshots and can merge
aliases, identifiers, and ontology tags into prepared species metadata. It does
not overwrite conflicting composition/formula data; conflicts are reported.

### Ion Reaction Tables

`ion_reaction_table` reads local YAML ion-neutral reaction tables. It is useful
for internally reviewed literature tables or converted local snapshots. Reaction
enrichment validates species references, charge balance, and element balance
before writing channels into `prepared_registry`.

## Cross-Section Assets

### Import Local Tables

`reactgen import-cross-sections` imports simple local CSV/TSV files into
workspace assets:

```powershell
reactgen import-cross-sections external_data/lxcat/e_cf4.csv `
  --workspace workspace `
  --source lxcat_offline `
  --reaction-id e_CF4_elastic `
  --target CF4
```

Supported v1 columns:

```text
energy_eV,cross_section_m2
```

The command writes:

```text
workspace/prepared_registry/assets/cross_sections/<safe_name>.csv
workspace/prepared_registry/assets/cross_sections/<safe_name>.metadata.yaml
```

If `--reaction-id` matches a channel in the prepared registry, only that
prepared channel is linked. Curated `registry/` files are never modified.

### Apply Reviewed Mappings

`reactgen apply-cross-section-mapping` applies reviewed YAML mappings to
prepared electron channels:

```yaml
schema_version: 1
mappings:
  - reaction_id: e_CF4_dissociation_CF3_F
    asset_path: assets/cross_sections/e_CF4_dissociation_CF3_F_lxcat.csv
    source: lxcat_offline
    mapping_status: reviewed
    process_label_original: DISSOCIATION
```

```powershell
reactgen apply-cross-section-mapping mapping.yaml --workspace workspace
```

There is no fuzzy matching and no curated registry mutation.

### LXCat Offline Index

`lxcat_offline` reads a local index YAML and returns candidates pointing to
local files. It does not log in to LXCat, scrape LXCat, download data, compute
cross sections, or run a Boltzmann solver.

## Property And Reaction Enrichment

Property enrichment fills missing or null prepared species properties from
configured providers. Existing non-null values are not overwritten. Conflicting
candidate values are reported as `property_conflict` for manual review.

Reaction enrichment imports configured local reaction candidates into
`prepared_registry/reactions/`. Existing channel IDs are not overwritten, and
invalid species references, charge imbalance, or element imbalance are skipped
and reported.

When a provider reaction references product species that are not yet registered,
prepare/enrich can seed those product species conservatively. It first uses an
explicit `species_candidate` embedded in the channel, then tries configured
species identity providers by exact species id. A species is seeded only when
composition and charge are present from an explicit local source. Alias-only
matches, formula-only records, and incomplete candidates are reported for manual
review instead of being guessed.

This means users normally provide initial gases and a source profile; they do
not need to list every expected fragment up front. Cross sections, DNT
properties, collision radii, and reaction energetics are still not invented.
They remain in `missing_data.yaml` until reviewed data is imported or provided.

## Source Cache Manifest

Local source files may be copied into a workspace cache:

```text
workspace/source_cache/
  manifest.yaml
  <source_name>/<safe_file_name>_<sha12>.ext
```

Cache records include original path, cached path, SHA-256, source name, and
import timestamp. The cache is local YAML plus copied files; it is not a
database server and does not mutate curated registry files.

## Missing-Data Plans

`reactgen plan-missing` converts an existing `missing_data.yaml` into a small
action plan:

```powershell
reactgen plan-missing cases/ar_cf4/outputs --output missing_plan.yaml
```

The output groups missing items into actions such as `seed_species`,
`enrich_properties`, `import_cross_sections`,
`review_reaction_energetics`, and `manual_review`. It does not fetch data.

## Promotion Workflow

`reactgen promote` copies only explicitly reviewed prepared or candidate records
into curated `registry/`. The default mode is dry-run; `--apply` is required for
mutation.

Existing curated species and channels are not overwritten. Provenance fields
are preserved by copying reviewed payloads rather than rebuilding them.

## External Data Tools

`external_data_tools/` is outside the core package. It contains optional tools
for explicit URL downloads, raw file caching, snapshot planning/validation, and
local conversion workflows. These tools are not imported by `reactgen generate`.

Implemented external tools include:

- PubChem identity snapshot fetch/normalize
- NIST snapshot plan/validate
- LXCat/manual raw cross-section import
- OpenADAS raw file registration
- VAMDC raw query capture
- KIDA/UMIST-like local network conversion
- Argonne/ATcT-style thermochemistry plan/validate
- chemical identity fetch/normalize skeletons

External outputs must be reviewed before use in prepare/enrich workflows.

## Potential Future Adapters

These are not production-ready core adapters:

- Core `PubChemProvider`: disabled placeholder that returns empty candidate
  lists and performs no network calls.
- ChemSpider online fetch: skeleton only; requires explicit credentials before
  any future implementation.
- OPSIN and NCI/Cactus online resolvers: disabled external skeletons.
- VAMDC conversion into registry-ready chemistry: raw query capture exists, but
  full XSAMS parsing/conversion is future work.
- Full OpenADAS parsing: raw file registration and mapping skeletons exist, but
  broad ADF parsing is future work.
- Automatic LXCat login/download/scraping: intentionally not implemented.

Do not treat these placeholders as validated production data sources.
