# Manual Data Input Guide

This is an exceptional maintainer workflow, not a prerequisite for
`reactgen generate`. Missing properties and datasets never stop the registered
reaction list from being written.

`reactgen template-missing` creates fill-in templates from `missing_data.yaml`
when local providers and snapshots cannot supply everything needed for a case.
It does not fetch data, guess values, mutate curated `registry/`, or promote
anything.

```powershell
reactgen template-missing outputs --output-dir manual_inputs
reactgen template-missing outputs/missing_data.yaml --output-dir manual_inputs
```

The command writes:

- `species_properties.yaml` for missing species properties.
- `reaction_channels.yaml` for missing species/reaction registration review.
- `cross_section_mapping.yaml` for reviewed links from imported assets to
  electron channels.
- `reaction_energetics.yaml` for missing
  `deltaE_products_minus_reactants_eV` and missing `threshold_eV`.
- `manual_review.yaml` for fields without a specific template.
- `README.md` with local guidance.

## What To Fill

Use reviewed local or internal sources first. For semiconductor low-pressure
plasma work, practical sources usually include internal transport/DNT fits,
reviewed literature tables, local NIST/ATcT-style thermochemistry snapshots,
licensed local cross-section files, and curated internal chemistry databases.

Recommended source priority:

1. Existing curated local registry values.
2. Reviewed internal data or company-approved snapshots.
3. Reviewed local public-database snapshots with license/citation approval.
4. Literature-supported manual entries.
5. Explicit estimates only when a domain expert has reviewed the method.

## Converting Filled Templates

Filled `species_properties.yaml` records can be copied into an
`internal_data/properties/properties.yaml` fixture or another local snapshot used
by a source profile. Keep `source_record` fields so enrichment reports can trace
where each value came from.

For cross sections, first import the local CSV/TSV file:

```powershell
reactgen import-cross-sections INPUT.csv --workspace WORKSPACE --reaction-id REACTION_ID --target TARGET
```

Then copy the generated `assets/cross_sections/<file>.csv` path into
`cross_section_mapping.yaml` and apply it:

```powershell
reactgen apply-cross-section-mapping manual_inputs/cross_section_mapping.yaml --workspace WORKSPACE
```

For reaction energetics, fill `deltaE_products_minus_reactants_eV` only from
reviewed reaction energetics or from an external calculation based entirely on
reviewed species thermochemistry. Check the sign convention before DNT use.

For missing reaction pair coverage, `reaction_channels.yaml` contains
placeholder channel records keyed by `family`, `projectile`, and `target`. Fill
these only after reviewing species references, charge balance, element balance,
reaction energetics, and provenance. Convert reviewed entries into
`internal_data/reactions/electron.yaml`, `internal_data/reactions/ion_neutral.yaml`,
or another local snapshot source.

## Semiconductor Benchmark Case Hints

For `ar_o2_simple`, prioritize O2 cross sections, O2 DNT properties, and
Ar+ + O2 energetics.

For `ar_cf4_fluorocarbon`, prioritize CF4/CFx cross sections, CFx
thermochemistry, and Ar+ + CF4 energetics.

For `sf6_o2_electronegative`, prioritize SF6 attachment/dissociation cross
sections, negative ion channels, and SFx thermochemistry/DNT properties.

These are workflow hints, not permission to invent values.

## What Not To Invent

Do not invent collision radii, cross sections, reaction energetics, species
composition, charge, or reaction products just to make diagnostics pass. Leave
uncertain items in `manual_review.yaml` until a source or domain expert review is
available.
