# Optional Chemicals Package Provider

`chemicals` is an optional local Python package provider for prepare/enrich
workflows. It is not required by the core project and is not used by
`reactgen generate`.

The provider is intended as a conservative offline fallback for species
identity and a few basic properties. It should be ordered after curated local
registry data, internal files, NIST snapshots, and Argonne/ATcT-style
thermochemistry snapshots.

Supported conservative mappings:

- molecular weight in g/mol is reported as `mass_amu`; numerically this is the
  molecular mass in amu for neutral molecules.
- formation enthalpy in J/mol or kJ/mol is converted explicitly to eV per
  molecule.
- dipole moments are used only when the package exposes a clear Debye value.
- collision radius is used only when an explicit molecular diameter or
  Lennard-Jones sigma source is exposed.

The provider does not output plasma cross sections and does not invent missing
values. Conflicts with existing curated or prepared values should be reported
for manual review rather than overwritten.
