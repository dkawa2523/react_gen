# plasma-reactgen product architecture

`plasma-reactgen` is a registry-driven reaction-network generator for low-pressure plasma modeling.

## Core responsibility

The core responsibility is to generate reproducible reaction lists, state lists, DNT preparation tasks, coverage reports, missing-data reports, and visualizations from local registry data.

The core does not numerically calculate electron-collision cross sections, rate coefficients, or DNT+/DNT+DM cross sections. Numerical solvers and public-database importers should remain separate adapters.

## Design goals

- Keep the user workflow simple: provide gas species and receive reaction, state, and DNT-related outputs.
- Keep the developer workflow explicit: add or review species, reaction channels, rules, and assets in the registry.
- Preserve physical sanity with basic hard checks: species reference, charge balance, and element balance.
- Allow incomplete data during early mechanism construction; report missing cross sections and missing properties instead of failing.
- Support future public database importers without making external services mandatory at runtime.
- Keep inferred candidates clearly separated from curated or literature-supported data.

## Current core flow

1. Load case input YAML.
2. Load registry species and reaction channels from local files.
3. Expand a reaction network by frontier depth.
4. Select electron and ion-neutral collision pairs.
5. Read registered channels for each pair.
6. Validate species references, charge balance, and element balance.
7. Register newly introduced product species for the next depth when allowed by configuration.
8. Build state list.
9. Build DNT task summary.
10. Build coverage and missing-data reports.
11. Write YAML/CSV outputs.
12. Optionally write visualization files.

## Extension layers

Extension layers live beside the current core. They should not turn `ReactionNetworkBuilder` into a chemistry inference engine, numerical DNT solver, or public database client.

### DNT input export layer

Status: implemented as a solver-free exporter.

Purpose:

- Convert generated ion-neutral network data into pair-wise DNT+/DNT+DM input YAML files.
- Keep `dnt_tasks.yaml` as a human-readable summary.
- Write normalized calculation-oriented files under `dnt_inputs/`.
- Do not calculate cross sections or reaction energies.

Output:

- `dnt_manifest.yaml`
- `dnt_inputs/<pair_id>.yaml`

### Inference layer

Status: implemented as default-disabled candidate tooling and minimal optional generation integration.

Purpose:

- Generate physically plausible species and reaction candidates when local registry data are missing.
- Keep inference disabled by default.
- Mark every inferred item with `status: inferred`, `confidence`, `inference.rule`, and missing-data fields.
- Never silently promote inferred data to curated registry data.

Implemented modules:

- `src/plasma_reactgen/inference/provider.py`
- `src/plasma_reactgen/inference/candidates.py`
- `src/plasma_reactgen/inference/species_candidates.py`
- `src/plasma_reactgen/inference/reaction_templates.py`
- `src/plasma_reactgen/inference/screening.py`
- `src/plasma_reactgen/inference/scoring.py`
- `src/plasma_reactgen/inference/candidate_writer.py`

### External data adapter layer

Status: placeholder tooling only. Real public database parsers/downloaders are planned adapters, not core runtime behavior.

Purpose:

- Import or link public data sources such as LxCat or species-property databases.
- Produce local registry YAML and asset files.
- Avoid network access in core generation.

Location:

- `tools/importers/`

## What not to do

- Do not put all chemistry inference inside `ReactionNetworkBuilder`.
- Do not make public DB access required for `reactgen generate`.
- Do not implement DNT+/DNT+DM numerical solvers inside the generator core.
- Do not add excessive schema frameworks or heavy validation layers.
- Do not merge inferred candidates into curated registry files automatically.
- Do not duplicate long explanations in README and docs.
