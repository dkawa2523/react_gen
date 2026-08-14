# Provider Extension Guide

This guide is for developers who want to add a new prepare/enrich data source
without editing `preparer.py`.

## Provider Boundaries

Core providers under `src/plasma_reactgen/data_sources/` must be local-only.
They may read local registry files, internal file exports, reviewed snapshots,
or optional local packages, but they must not download data or call online APIs.

External acquisition code belongs under `external_data_tools/` and should write
local snapshots/assets that core providers can read later.

## Interfaces

Implement the smallest interface that matches the source:

- `SpeciesProvider.find_species(query) -> list[dict]`
- `PropertyProvider.find_properties(species_id, names=None) -> list[dict]`
- `ReactionProvider.find_channels(pair) -> list[dict]`
- `CrossSectionProvider.find_cross_sections(pair) -> list[dict]`

Provider outputs should be YAML-compatible dictionaries. Include provenance with
`source_record` or an equivalent source record in `data.provenance`.

## Registering A Provider In The Factory

Keep each part in its focused module:

- supported public names: `data_sources/provider_catalog.py`
- source-profile and alias interpretation: `data_sources/provider_profile.py`
- lazy adapter construction: `data_sources/provider_builders.py`
- section order and alias-to-builder mapping: `data_sources/provider_factory.py`

Recommended pattern:

1. Add the provider name to the catalog.
2. Add a small lazy builder method and map the name in the factory facade.
3. If required configuration is missing, call the builder warning path and
   return no provider.
4. Import the concrete provider inside the builder method, not at module top
   level.
5. Keep `strict_sources: true` behavior intact by reporting missing configured
   sources through `unavailable_sources`.

Example source profile shape:

```yaml
properties:
  - local_registry
  - my_snapshot
my_snapshot:
  files:
    - external_data/snapshots/my_properties.yaml
```

## Tests

Add focused tests that cover:

- provider returns expected candidates from a temp local fixture
- provider factory builds the provider from a profile
- missing config produces a warning, not a crash
- `strict_sources: true` raises for missing required config
- prepare/enrich writes only to `prepared_registry` or reports
- curated `registry/` is not mutated

Do not add network tests for core providers.

## Rules

- No network access in core providers.
- No curated registry mutation from providers or enrichers.
- No heavy dependencies in the core package.
- Optional package imports must be lazy and failure-tolerant.
- Existing non-null curated values must not be overwritten.
- Units must be explicit and validated before writing candidates.
- Do not invent physical values.
- Use `status: imported` for unreviewed local imports.
- Use `status: literature_supported` only when source/citation review supports
  it.
- Preserve enough provenance for later promotion review.
