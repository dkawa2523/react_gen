# Ar/CF4 public-data starter Registry

This directory is a read-only evidence source for Ar/CF4 low-pressure plasma
candidate assessment. Candidate generation does not depend on these records.

## Scope

- Species/state records: Ar, Ar+, CF4, CF4+, CF3, CF3+, CF3-, CF2, CF2+, F, F-, F+.
- Electron-collision channel records: e+Ar, e+CF4, and generated fragment targets e+CF3, e+CF2, e+F.
- Ion-neutral channel records: Ar+ + Ar, Ar+ + CF4, Ar+ + CF3, Ar+ + CF2, Ar+ + F, CF3+ + CF4, CF3+ + CF2, CF3+ + Ar, F- + CF4, F+ + CF4, plus CF4+ surrogate pairs.

## Curation policy

- Numeric electron/ion cross-section curves are **not** bundled. Reaction YAML
  files store channel identities, products, thresholds or reaction energies,
  and source labels. Import numerical data through `acquire` and `rgen ingest`.
- DNT+/DNT+DM cross-section calculation and DNT input generation are outside
  this repository. Ion-neutral species and channel records remain useful as
  evidence for mechanically generated candidates.
- Values marked `estimated` may support `exploratory_simulation` only. Replace
  them with reviewed data before strict simulation.

## Known remaining gaps

- CF2 dipole moment is not curated and remains unknown.
- CF4 polarizability is curated from NIST CCCBDB. Estimated collision-radius
  and fragment transport properties are not final recommended pair potentials.
- Full numerical electron-collision cross-section tables need import from LXCat/Bordage/Phelps/NIST/literature.
