# Visualization design

The visualization layer is a post-processing module. It consumes generated output files under a case output directory and writes plots under a separate visualization directory. It does not depend on the network-generation application layer, so plotting changes do not affect the physics/network builder.

## Module layout

```text
src/plasma_reactgen/visualization/
|-- loader.py                  # Reads generated outputs into VisualizationDataset
|-- models.py                  # Small data container for visualization inputs
|-- svg_chart_scale.py         # Tick spacing and scale calculation
|-- svg_chart_layout.py        # Input normalization and chart geometry
|-- svg_chart_primitives.py    # Shared SVG text, colors, and presentation
|-- svg_horizontal_bar.py      # Horizontal-bar SVG renderer
|-- svg_grouped_bar.py         # Grouped-bar SVG renderer
|-- svg_charts.py              # Stable statistical-chart facade
|-- stats.py                   # Statistical chart definitions and registry
|-- graphviz_options.py        # Graphviz rendering options
|-- graphviz_dot.py            # Shared DOT escaping and node projection
|-- graphviz_edges.py          # Shared reaction-edge selection
|-- reaction_network_dot.py    # Full reaction-network DOT builder
|-- species_lineage_dot.py     # Species-lineage DOT builder
|-- network.py                 # Public facade and optional dot execution
|-- reaction_pathway_layout.py # Reaction-card geometry by expansion depth
|-- reaction_pathway.py        # Reaction-equation SVG presentation and writing
`-- writer.py                  # Orchestrates outputs and manifest.json
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

`svg_charts.py` is intentionally limited to the two public chart entry points.
Geometry is computed before rendering, common SVG presentation is shared once,
and each chart type owns only its own elements. This keeps layout changes from
expanding the public facade or duplicating scale and escaping rules.

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

## Reaction-equation pathway

`reaction_equation_network.svg` complements the species graphs with one card
per reaction. Cards are grouped by expansion depth and show the reaction id,
full equation, family, and type. Directed edges are built from
`precursor_reaction_ids`, so the graph exposes which earlier reactions enabled
each later reaction. It is generated without Graphviz and is therefore always
available with the statistical SVG charts.

`reaction_pathway_layout.py` owns sorting, depth grouping, canvas size, and card
positions. `reaction_pathway.py` only renders headers, edges, cards, legends,
and the final file. Geometry changes therefore do not require editing the
reaction presentation rules.

The pathway graph describes registered reachability, not reaction flux or
kinetic importance. Use the species graphs for topology and the equation graph
for reviewing the chemical meaning of a multistep path.

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
