# Ar/CF4 public-data starter registry

This registry update replaces the synthetic placeholder data with a public-data-based starter set for Ar/CF4 low-pressure plasma reaction-network generation and DNT+/DNT+DM preprocessing.

## Scope

- Species/state records: Ar, Ar+, CF4, CF4+, CF3, CF3+, CF3-, CF2, CF2+, F, F-, F+.
- Electron-collision channel records: e+Ar, e+CF4, and generated fragment targets e+CF3, e+CF2, e+F.
- Ion-neutral channel records: Ar+ + Ar, Ar+ + CF4, Ar+ + CF3, Ar+ + CF2, Ar+ + F, CF3+ + CF4, CF3+ + CF2, CF3+ + Ar, F- + CF4, F+ + CF4, plus CF4+ surrogate pairs.

## Curation policy

- Numeric electron/ion cross-section curves are **not** bundled. Reaction YAML files store channel identities, products, thresholds or reaction energies, and source labels. `data.cross_section.path` is left `null` until a dedicated LXCat/NIST/literature importer is used.
- DNT+/DNT+DM cross-section calculation is **not** performed here. The generator produces `cases/ar_cf4/outputs/dnt_tasks.yaml`.
- Values marked `estimated` are startup engineering seeds for network expansion or DNT task generation. Replace them with curated values before production simulation.

## Known remaining gaps

- CF2 dipole moment is not curated and is intentionally left missing, so DNT+DM tasks involving neutral CF2 remain `missing_properties`.
- CF4 polarizability is curated from NIST CCCBDB. CF4 collision radius and CF3/CF2 estimated polarizability/collision-radius values are DNT-preprocessing seeds, not final recommended pair potentials.
- Full numerical electron-collision cross-section tables need import from LXCat/Bordage/Phelps/NIST/literature.
