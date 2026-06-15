# Optional Chemicals Provider

`plasma_reactgen.data_sources.chemicals_provider` can use the Python
`chemicals` package as a local/offline prepare-time fallback. It is not used by
`reactgen generate` and is not a core dependency.

Install it explicitly in an environment that will run prepare/enrich tooling:

```powershell
python -m pip install chemicals
```

Source profiles opt in with `chemicals_optional`, typically after curated local
or internal sources:

```yaml
properties:
  - local_registry
  - internal_property_db
  - nist_snapshot
  - chemicals_optional
```

The adapter returns empty candidate lists when `chemicals` is not installed, so
prepare workflows should continue without failing. It currently maps only
conservative properties with clear units: molecular weight to `mass_amu`, dipole
moment to `dipole_moment_D` when available, and gas-phase formation enthalpy to
`enthalpy_formation_eV` when the package returns J/mol. It does not emit
polarizability candidates and skips collision radius unless a future adapter
chooses a specific documented diameter source.
