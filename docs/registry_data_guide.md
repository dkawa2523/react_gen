# Registry data guide

## Purpose

The registry is the local, reproducible data source for `react_gen`.

It stores:

- species data
- reaction-pair data
- reaction-channel data
- physical properties
- DNT-related parameters
- cross-section asset links
- provenance and source information

The generator core should read local registry-compatible files. In normal
curated runs this is `registry/`; in review runs it may be a workspace
`prepared_registry/`.

Normal generation does not require network access. Public DB data must first be
made available as reviewed local snapshots or local assets.

## Directory concept

Recommended structure:

```text
registry/
  species/
    Ar.yaml
    Ar_p.yaml
    CF4.yaml
    CF3.yaml
    CF3_p.yaml

  reactions/
    electron/
      e__CF4.yaml
    ion_neutral/
      Ar_p__CF4.yaml

  rules/
    inference/
      electron_templates.yaml
      ion_neutral_templates.yaml
      species_rules.yaml

  assets/
    cross_sections/
    dnt/
    external_sources/
```

Keep the registry readable.

Avoid deeply nested structures unless needed.

## Prepared registry concept

`prepared_registry/` is a workspace-local registry overlay used by prepare and
enrich workflows. It has the same broad shape as `registry/`, but it is not
curated source of truth:

```text
workspace/
  prepared_registry/
    species/
    reactions/
    assets/
  prepare_report.yaml
  enrichment_report.yaml
  source_cache/
```

Use `prepared_registry/` for imported local data, local snapshot enrichment,
cross-section asset links, and review runs. It can be passed to generation:

```powershell
reactgen generate CASE --registry workspace/prepared_registry --output workspace/outputs
```

Do not treat prepared files as curated until they are reviewed and explicitly
promoted with `reactgen promote --apply`.

## Species YAML

Recommended species format:

```yaml
schema_version: 1
id: CF4
formula: CF4
composition:
  C: 1
  F: 4
charge: 0
classes:
  - neutral
  - molecule

state:
  electronic: ground
  vibrational: ground

metadata:
  status: curated
  aliases:
    - carbon_tetrafluoride
    - tetrafluoromethane
  notes: []

properties:
  mass_amu:
    value: 88.004
    unit: amu
    source: computed_from_composition

  polarizability_A3:
    value: null
    unit: A3
    source: missing

  dipole_moment_D:
    value: 0.0
    unit: D
    source: curated

  collision_radius_A:
    value: null
    unit: A
    source: missing

  ionization_energy_eV:
    value: null
    unit: eV
    source: missing

  electron_affinity_eV:
    value: null
    unit: eV
    source: missing

  enthalpy_formation_eV:
    value: null
    unit: eV
    source: missing
```

## Minimal species fields

Required:

```text
id
composition
charge
classes
```

Recommended:

```text
formula
state
metadata.status
properties.mass_amu
```

DNT-relevant neutral species should include:

```text
properties.polarizability_A3
properties.dipole_moment_D
properties.collision_radius_A
```

Energy-screening and threshold estimation may use:

```text
properties.ionization_energy_eV
properties.electron_affinity_eV
properties.enthalpy_formation_eV
```

Unknown values should be written as `null`.

Do not invent physical values.

## Reaction pair YAML

Recommended reaction-pair format:

```yaml
schema_version: 1

pair:
  family: ion_neutral
  projectile: Ar_p
  target: CF4

metadata:
  status: curated
  source: null
  notes: []

channels:
  - id: ion_Ar_p__CF4__ct_parent
    type: charge_transfer
    dnt_class: charge_transfer
    status: curated

    products:
      - species: Ar
        n: 1.0
      - species: CF4_p
        n: 1.0

    threshold_eV: null
    deltaE_products_minus_reactants_eV: null

    data:
      dnt:
        status: missing_energy
        missing_for_complete_dnt:
          - deltaE_products_minus_reactants_eV

      cross_section:
        status: missing
        path: null

    evidence:
      source_type: registry
      source_id: null
      citation: null

    confidence:
      score: 1.0
      basis:
        - curated_registry_entry

    notes:
      - Add source and energy data before using as final DNT input.
```

## Registry-driven pair discovery

Every YAML file below `registry/reactions/<family>/` contributes its `pair` to
the generate-time index. The same pair is indexed by both reactant species, but
is returned only once. It becomes eligible when both species are active and at
least one was newly introduced at the current frontier depth. There is no
CaseConfig family allow-list and no enumeration of unregistered combinations.

The `family` value may describe any registered two-body family. The curated
catalog currently documents `electron`, `ion_neutral`, `neutral_neutral`,
`ion_ion`, and `electron_ion` reaction types.

## Electron reaction pair example

```yaml
schema_version: 1

pair:
  family: electron
  projectile: e
  target: CF4

metadata:
  status: curated
  source: null
  notes: []

channels:
  - id: e__CF4__ionization_parent
    type: ionization
    status: curated

    products:
      - species: e
        n: 2.0
      - species: CF4_p
        n: 1.0

    threshold_eV: null

    data:
      cross_section:
        status: missing
        path: null

    evidence:
      source_type: registry
      source_id: null
      citation: null
```

## Status values

Recommended status values:

```text
curated
literature_supported
imported
estimated
inferred
draft
deprecated
```

Meaning:

### `curated`

Manually reviewed and accepted.

### `literature_supported`

Based on a cited literature source.

### `imported`

Imported from an external database or file.

### `estimated`

Estimated from known physical properties or related data.

### `inferred`

Generated by rule/template inference.

### `draft`

Work in progress.

### `deprecated`

Kept for traceability but not recommended for use.

Guidance:

- Use `curated` only for data accepted into curated `registry/` after review.
- Use `literature_supported` for reviewed literature or database-snapshot data
  with citation/provenance.
- Use `imported` for mechanically imported local files or snapshots before
  full domain review.
- Use `inferred` only for rule/template candidates; never present inferred data
  as literature or curated data.
- Use `estimated` only when the value is explicitly calculated or approximated
  from documented assumptions.

## Provenance

Every nontrivial data entry should keep source information when available.

Recommended format:

```yaml
evidence:
  source_type: literature
  source_id: null
  citation: null
  url: null
  accessed_date: null
```

Many prepare/enrich providers use `source_record`, especially for property
sources and imported local snapshots:

```yaml
source_record:
  source_type: public_database_snapshot
  database: NIST Chemistry WebBook SRD 69
  source_id: nist_webbook:CF4:ionization_energy
  citation: NIST Chemistry WebBook SRD 69
  accessed_date: 2026-06-15
```

For species property enrichment, keep detailed provenance under metadata:

```yaml
metadata:
  property_sources:
    ionization_energy_eV:
      source_type: public_database_snapshot
      database: NIST Chemistry WebBook SRD 69
      source_id: nist_webbook:CF4:ionization_energy
```

For imported local files, record the original file and hash in
`workspace/source_cache/manifest.yaml` where practical.

## Cross-section assets

Cross-section tables should be stored as local assets.

Example:

```yaml
data:
  cross_section:
    status: local_file_registered
    path: assets/cross_sections/e_CF4_ionization.csv
    source: LxCat
    format: csv
    columns:
      - energy_eV
      - cross_section_m2
```

The registry entry should link to the asset.

The reaction generator should not need to parse all possible public DB formats directly.

### Multiple reaction datasets

Channels may retain multiple cross-section, rate, mobility, branching,
threshold, or reaction-energy candidates without overwriting one another:

```yaml
data:
  datasets:
    - id: ds_e_CF4_xs_lxcat
      kind: cross_section
      representation: table
      independent_variable: energy
      dependent_variable: cross_section
      unit: m2
      asset:
        path: assets/cross_sections/e_CF4.csv
        format: csv
      validity:
        minimum: 0.0
        maximum: 100.0
        unit: eV
      source:
        source_type: local_snapshot
        source_id: lxcat:e_CF4
      status: imported
      preferred: true
    - id: ds_e_CF4_rate_literature
      kind: rate_coefficient
      representation: arrhenius
      unit: m3/s
      parameters:
        A: 1.0e-15
        n: 0.5
      source:
        source_type: literature
        source_id: doi:example
      status: literature_supported
```

The legacy `data.cross_section` mapping remains valid and is normalized to one
dataset at read time. Loading it never rewrites the registry file. Channel-level
`evidence`, `provenance`, `source_record`, and `confidence` are preserved in
generated reaction records.

Prepared cross-section imports also write a metadata sidecar next to the
normalized CSV:

```text
workspace/prepared_registry/assets/cross_sections/<safe_name>.csv
workspace/prepared_registry/assets/cross_sections/<safe_name>.metadata.yaml
```

Recommended sidecar fields include:

```yaml
source_type: public_database_snapshot
database: LXCat
original_file: external_data/lxcat/e_cf4.csv
imported_at: 2026-06-15T00:00:00+00:00
columns:
  - energy_eV
  - cross_section_m2
units:
  energy: eV
  cross_section: m2
row_count: 120
energy_min_eV: 0.0
energy_max_eV: 100.0
sha256: ...
license_note: user must follow source citation and redistribution requirements
```

## DNT-related data

Ion-neutral channels may include DNT metadata.

Example:

```yaml
data:
  dnt:
    status: ready_with_warnings
    model_variant_hint: dnt_plus
    missing_for_complete_dnt:
      - deltaE_products_minus_reactants_eV
```

Pair-level DNT readiness and existing dataset availability are reported in
`dnt_tasks.yaml`. This is data inventory only; core generation does not
execute DNT+ or import DNT results.

## Inferred candidate data

Inferred candidates should be clearly marked.

Example:

```yaml
status: inferred
confidence:
  score: 0.55
  basis:
    - charge_and_element_balanced
    - generated_by_template
    - energy_unknown
inference:
  rule: charge_transfer
  generated_from:
    - Ar_p
    - CF4
```

Do not automatically write inferred candidates into curated registry files.

Use a separate candidate output directory first.

## External data and importer policy

External DB importers should:

- run outside the normal generation path
- produce local snapshots, prepared registry YAML, or local asset files
- preserve source and provenance
- avoid overwriting curated files automatically
- make imported status explicit
- allow developer review before promotion

External DB importers should not:

- make `reactgen generate` require internet access
- hide the source of imported data
- silently change existing curated reaction mechanisms
- mix inferred and curated entries without status labels

Implemented local import/preparation commands include:

- `reactgen enrich`
- `reactgen import-cross-sections`
- `reactgen apply-cross-section-mapping`
- `reactgen plan-missing`
- `reactgen promote`

External acquisition and conversion tools live under `external_data_tools/`.
They are separate from the core package and may write local files under
`external_data/`, `workspaces/`, or `benchmarks/`. If an external tool fetches
public data, it must be invoked explicitly by the user and its outputs require
review before prepare/enrich or promotion.

## User input reduction strategy

The long-term goal is to reduce manual user input.

Preferred approach:

```text
public DB / downloaded data / developer-provided files
  -> importer
  -> local registry YAML/assets
  -> normal generation
```

This allows future automation while keeping the core generator reproducible and inspectable.

## Developer workflow

Recommended workflow for adding data:

```text
1. Add or import species data.
2. Add or import reaction-pair data.
3. Add local cross-section or DNT assets if available.
4. Run developer checks.
5. Generate a sample case.
6. Inspect coverage and missing-data reports.
7. Add missing properties or reactions iteratively.
```

## Keep the registry simple

Avoid:

- deeply nested schemas
- multiple competing formats for the same data
- hidden defaults for physical values
- automatic promotion of inferred data
- mandatory external-service calls
- large generated files committed without need

Prefer:

- readable YAML
- explicit `null` for unknown values
- clear status fields
- local asset links
- small reviewable files
