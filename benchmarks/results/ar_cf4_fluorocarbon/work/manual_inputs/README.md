# Manual Missing Data Inputs

Generated from `C:\Users\user\Desktop\react_gen-main\benchmarks\results\ar_cf4_fluorocarbon\outputs\missing_data.yaml`.

These files are fill-in templates only. They do not contain guessed physical
values, do not fetch data, and do not mutate curated `registry/`.

Recommended workflow:

1. Fill only values that have been reviewed from internal data, local snapshots,
   transport/DNT fits, or literature.
2. Keep `source_record` provenance with citation/source IDs wherever possible.
3. Convert filled property records into an `internal_file` property snapshot or
   another reviewed local source profile input.
4. Import cross-section tables with `reactgen import-cross-sections`, then copy
   the resulting `assets/cross_sections/<file>.csv` path into
   `cross_section_mapping.yaml`.
5. Keep uncertain or unsupported fields in `manual_review.yaml`.

Do not invent collision radii, reaction energetics, cross sections, or species
composition just to satisfy diagnostics.

## Case-Specific Recommendations: Ar/CF4

- Review/import CF4 and CFx electron cross sections.
- Fill CFx thermochemistry from reviewed local snapshots or internal data.
- Review Ar+ + CF4 ion-neutral energetics before DNT use.

