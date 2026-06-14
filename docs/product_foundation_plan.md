# Product foundation plan

This document records the implementation direction for extending `plasma-reactgen` into a product foundation for low-pressure plasma reaction-list generation.

> Status: historical roadmap/reference. For the current product entry point, use
> `README.md` and `docs/product_architecture.md`. Some items in this document
> are now implemented; treat it as planning context rather than the active
> feature specification.

## Goals

- Preserve current registry-driven network generation behavior.
- Keep `generate`, `visualize`, `dev-check`, `dev-index`, and `template` backward compatible.
- Keep `ReactionNetworkBuilder` focused on registered data expansion and basic validation.
- Add inferred reaction candidates through a separate inference layer.
- Export DNT+/DNT+DM inputs as pair-wise files that remain compatible with the current `dnt_tasks.yaml` structure.
- Treat external databases as future adapters, not core runtime dependencies.

## Current responsibilities

`application/network_builder.py` reads case config, selected collision pairs, registered channels, and species records to build a `ReactionNetwork`. It already rejects malformed registered channels when species references, charge balance, or element balance fail.

`application/dnt_task_builder.py` groups generated ion-neutral reactions into the existing `dnt_tasks.yaml` view. This remains the stable compatibility output.

`application/dnt_input_builder.py` adds a downstream export view. It does not change the network. It writes normalized pair-wise DNT input payloads with species properties, missing DNT fields, DNT-relevant channels, and provenance.

`inference/` is the only place for candidate generation. Inference remains disabled by default, and optional inferred-channel integration is used by `generate` only when explicitly enabled.

## Layering rules

- Registry data and inferred candidates must stay separate.
- Inferred candidate records must carry `status: inferred`, `confidence`, `inference`, `provenance`, and `missing_for_complete_dnt`.
- DNT export may consume generated network data, but it must not add reactions back into the network.
- External DB access belongs in adapter modules added later. Core generation must work offline.
- Avoid large schemas or abstract contract classes until multiple concrete adapters require them.

## Minimum physical checks

The product foundation should keep these checks visible in generated or exported data:

- species reference status
- charge balance
- element balance
- generation depth
- product count per channel
- confidence for inferred candidates
- provenance for registered or inferred data
- missing inputs needed for complete DNT+/DNT+DM calculation

## CLI boundary

User-facing workflows:

- `generate`: build standard network outputs from case input and registry.
- `visualize`: render charts and Graphviz views from generated outputs.
- `export-dnt`: write pair-wise DNT input files for downstream tools.

Developer workflows:

- `dev-check`: validate registry readability and references.
- `dev-index`: rebuild registry index files.
- `template`: print registration templates for new species or reaction pairs.

Candidate review is a developer workflow (`infer-candidates`) rather than a silent change to `generate`.

## Near-term roadmap

1. Keep `dnt_tasks.yaml` stable and add pair-wise DNT input export.
2. Add a disabled inference skeleton with the required audit fields.
3. Add candidate generation rules in `inference/` only after the exported validation fields are stable.
4. Add optional adapters for external sources behind explicit commands or configuration.
5. Add focused tests around new exporters and candidate audit fields, without converting the project into a large schema-first framework.
