# Visualization design

The visualization layer is a post-processing module. It consumes generated output files under a case output directory and writes plots under a separate visualization directory. It does not depend on the network-generation application layer, so plotting changes do not affect the physics/network builder.

## Module layout

```text
src/plasma_reactgen/visualization/
|-- loader.py        # Reads generated YAML/JSON outputs into VisualizationDataset
|-- models.py        # Small data container for visualization inputs
|-- svg_charts.py    # Dependency-free SVG chart primitives
|-- stats.py         # Statistical chart definitions and chart registry
|-- network.py       # Graphviz DOT generation and optional dot rendering
`-- writer.py        # Orchestrates all visualization outputs and manifest.json
```

## Statistical charts

Default charts are registered in `default_chart_specs()` in `stats.py`.

Current charts:

1. `reaction_family_counts.svg`: electron vs ion-neutral reaction count
2. `reaction_type_counts.svg`: reaction type distribution
3. `reaction_depth_by_family.svg`: expansion-depth distribution by family
4. `species_charge_counts.svg`: state list charge distribution
5. `species_class_counts.svg`: state class distribution
6. `species_depth_counts.svg`: first-seen depth distribution
7. `coverage_status_counts.svg`: found/missing candidate-pair coverage
8. `dnt_readiness_counts.svg`: DNT+/DNT+DM task readiness
9. `missing_data_counts.svg`: missing-data severity and subject distribution

To add a chart, implement a small builder function that receives `VisualizationDataset` and output directory, then append a `ChartSpec` to `default_chart_specs()`.

## Graphviz network

Two Graphviz views are generated:

- `reaction_network.*`: all state-changing reaction edges.
- `species_lineage.*`: compact graph showing only edges that introduce new species. This is usually easier for checking recursive expansion paths.

Both Graphviz outputs use species/state nodes and reaction edges.

Node labels include:

- species id
- charge
- first-seen depth
- compact class list
- missing-property count, if any

Edge labels include:

- collision family: `e` or `ion`
- reaction type
- expansion depth
- reaction id

Edge styles:

- electron reactions: dashed blue
- ion-neutral reactions: solid red

The network is intentionally a species graph rather than a strict hypergraph. For readability, electron reactions are drawn from the electron target to products. Ion-neutral reactions use simple composition-based mapping, e.g.

```text
Ar+ + CF4 -> Ar + CF3+ + F
```

becomes approximately:

```text
Ar+ -> Ar
CF4 -> CF3+
CF4 -> F
```

This keeps paths readable while preserving the original full reaction equation in edge tooltips.

## CLI

```bash
PYTHONPATH=src python -m plasma_reactgen.interface.cli visualize cases/ar_cf4/outputs \
  --output cases/ar_cf4/visualizations \
  --formats svg,png
```

Useful options:

- `--include-self-loops`: include self-loop edges such as elastic channels
- `--include-non-expanding`: include non-expanding channels such as elastic/effective/excitation
- `--max-reactions -1`: draw all reactions
- `--formats svg,png,pdf`: Graphviz render formats

Graphviz DOT is always written. SVG/PNG/PDF rendering requires the system `dot` executable.
