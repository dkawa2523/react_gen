# Changelog

## 0.1.0 - 2026-07-14

- Generate deterministic, registry-driven multistep reaction lists with depth
  and precursor lineage.
- Associate multiple cross-section, rate-coefficient, and mobility datasets
  with registered reaction channels while reading the legacy cross-section form.
- Report DNT-relevant ion-neutral properties and existing datasets without
  executing DNT.
- Resolve versioned registry packs from input gases and retain explicit
  `--registry` behavior.
- Separate normal generation from registry-maintenance commands and keep
  generated workspaces out of source control.
