# Changelog

## 1.0.0 - 2026-11-08

- Generate bounded electron, ion, and neutral gas-phase collision candidates,
  including elastic scattering. Report conservation, transformation, endpoint
  energetics, and evidence as separate conclusions.
- Preserve the declared collision roles, qualified records, and alternative
  calculations. Query all-reactants reachability and inspect the saved evidence
  behind each branch.
- Write result schema 5 with helper view format 10. See the
  [result reference](docs/output_reference.md) for older results and migration.
- Export ion–neutral candidates and recorded properties for DNT preprocessing.
  Publish [the process report and benchmark](docs/reaction_judgment_matrix.md)
  with the Registry inventory and reproducible example inputs.
- Keep acquisition, candidate matching, scientific review, and Registry writes
  separate. Publish snapshots with content-addressed originals and tables.
- Include the Registry, attribution notices, case inputs, source catalog, and
  current guides in the source distribution. The wheel contains the runtime
  and result schema.
- Run development checks through [the quality commands](docs/quality.md).
