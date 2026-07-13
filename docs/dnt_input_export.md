# DNT+/DNT+DM input export

## Purpose

The project generates a DNT task summary from ion-neutral reactions.

The DNT input exporter additionally writes pair-wise DNT+/DNT+DM input files that can be passed to, or converted for, a separate DNT solver.

This document defines the normalized output format for those pair-wise files.

The exporter does not run a DNT solver, calculate cross sections, or estimate missing reaction energies.

## Output files

When DNT input export is enabled, the output directory contains:

```text
outputs/
  dnt_tasks.yaml
  dnt_manifest.yaml
  dnt_inputs/
    <pair_id>.yaml
```

### `dnt_tasks.yaml`

A compact summary for humans. This remains the existing human-readable DNT output.

It continues to show:

- ion-neutral pair
- model variant
- pair-property readiness (`pair_property_readiness`)
- complete pair-and-channel readiness (`complete_readiness`)
- missing required properties
- associated reactions

The legacy `readiness` field remains an alias for pair-property readiness. It
must not be read as a claim that every channel has complete solver input.

### `dnt_manifest.yaml`

A machine-readable index of all pair-wise DNT input files.

Example:

```yaml
schema_version: 1
pairs:
  - pair_id: Ar_p__CF4
    file: dnt_inputs/Ar_p__CF4.yaml
    model_variant: dnt_plus
    status: missing_required_data
    missing_required_properties:
      - target.polarizability_A3
      - target.collision_radius_A

summary:
  total_pairs: 1
  property_ready_pairs: 0
  complete_ready_pairs: 0
  complete_ready_with_warnings_pairs: 0
  ready: 0
  ready_with_warnings: 0
  missing_required_data: 1
  no_dnt_channels: 0
```

### `dnt_inputs/<pair_id>.yaml`

A pair-wise DNT input file.

The file describes one ion-neutral collision pair and all DNT-relevant channels for that pair.

## Minimal pair-wise schema

Example:

```yaml
schema_version: 1
pair_id: Ar_p__CF4
model_variant: dnt_plus
status: missing_required_data

pair_property_readiness:
  status: missing_properties
  scope: pair_properties
  missing:
    - target.polarizability_A3
    - target.collision_radius_A

complete_readiness:
  status: missing_required_data
  scope: pair_properties_and_channels
  missing_required_properties:
    - target.polarizability_A3
    - target.collision_radius_A
  channel_warnings:
    - reaction_id: ion_Ar_p__CF4__ct_parent
      fields:
        - deltaE_products_minus_reactants_eV

projectile:
  id: Ar_p
  charge: 1
  mass_amu: 39.948
  composition:
    Ar: 1
  properties:
    mass_amu:
      value: 39.948
      unit: amu
      source: curated

target:
  id: CF4
  charge: 0
  mass_amu: 88.004
  composition:
    C: 1
    F: 4
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

pair_properties:
  reduced_mass_amu: 27.5
  long_range_model: ion_induced_dipole
  missing_required_properties:
    - target.polarizability_A3
    - target.collision_radius_A

channels:
  - reaction_id: ion_Ar_p__CF4__ct_parent
    type: charge_transfer
    dnt_class: charge_transfer
    products:
      - species: Ar
        n: 1.0
      - species: CF4_p
        n: 1.0
    threshold_eV: null
    deltaE_products_minus_reactants_eV: null
    status: curated
    missing_for_complete_dnt:
      - deltaE_products_minus_reactants_eV
    provenance:
      source_type: registry
      source_id: null

run_config:
  energy_grid_eV:
    min: 0.01
    max: 100.0
    n: 200
  output_cross_section_unit: cm2

provenance:
  generated_by: plasma-reactgen
  source_network: network.reactions.yaml
```

## Two Readiness Scopes

`pair_property_readiness.status` is either `ready` or `missing_properties` and
only answers whether the required ion/neutral properties are available.

`complete_readiness.status`, the top-level pair-file `status`, and the manifest
status use the statuses below. They combine pair properties with DNT channel
classification, thresholds, and energetics.

## Complete Readiness Status

Use only a small set of statuses.

### `ready`

All required pair properties and required channel-level DNT values are available.

### `ready_with_warnings`

The required pair properties are present, but one or more channel-level values
are missing.

Typical examples:

- missing reaction energy
- missing threshold for a non-elastic channel

### `missing_required_data`

One or more required pair-level properties are missing.

Typical examples:

- missing ion mass
- missing neutral mass
- missing neutral polarizability
- missing neutral dipole moment
- missing neutral collision radius

### `no_dnt_channels`

The ion-neutral pair exists, but no channel is classified as DNT-relevant.

## Required pair properties

### Projectile ion

Required:

```text
id
charge
mass_amu
composition
```

### Target neutral

Required:

```text
id
charge
mass_amu
composition
polarizability_A3
dipole_moment_D
collision_radius_A
```

## Channel fields

Each DNT-relevant channel should include:

```text
reaction_id
type
dnt_class
products
threshold_eV
deltaE_products_minus_reactants_eV
status
missing_for_complete_dnt
provenance
```

Unknown values should be written as `null`.

Unknown values should not cause export failure unless the pair itself cannot be identified.

They do, however, keep complete readiness at `ready_with_warnings` when the
missing field is required for a complete DNT channel.

## Model variant

Use a simple model selection rule at this layer.

```text
dipole_moment_D is zero or missing -> dnt_plus
dipole_moment_D is nonzero        -> dnt_plus_dm
```

This is a practical export classification.

Solver-specific decisions can be handled later by the numerical DNT solver or a solver-specific adapter.

## Implementation

The implementation lives in:

```text
src/plasma_reactgen/application/dnt_input_builder.py
src/plasma_reactgen/infrastructure/dnt_writer.py
```

Main functions:

```python
build_dnt_inputs(network) -> dict
write_dnt_inputs(output_dir, dnt_inputs) -> None
```

Keep implementation simple.

Preferred style:

- plain dictionaries for output objects
- small helper functions
- minimal unit conversion
- no large DNT class hierarchy
- no solver-specific numerical logic

## Configuration

Pair-wise DNT input export is optional in normal generation:

```yaml
outputs:
  dnt_inputs: false
```

If `outputs.dnt_inputs` is missing, the default is `false` to preserve existing `generate` outputs.

Use `outputs.dnt_inputs: true` during generation, or `reactgen export-dnt` for
an explicit export destination.

## Missing data policy

The exporter should write missing fields explicitly.

Do this:

```yaml
missing_required_properties:
  - target.polarizability_A3
```

Do not hide missing values.

Do not replace unknown physical values with arbitrary numbers.

## Testing guidance

Add small behavior tests only.

Recommended tests:

- DNT input export creates `dnt_manifest.yaml`.
- DNT input export creates at least one file under `dnt_inputs/` for a case with ion-neutral reactions.
- Missing required data are written to YAML instead of raising an exception.
- Existing `dnt_tasks.yaml` behavior remains available.

Avoid large golden-file tests.
