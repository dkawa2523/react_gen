from __future__ import annotations

from pathlib import Path
import json

from plasma_reactgen.visualization.loader import load_visualization_dataset
from plasma_reactgen.visualization.network import GraphvizOptions, write_reaction_network_graphviz, write_species_lineage_graphviz
from plasma_reactgen.visualization.reaction_pathway import write_reaction_pathway_svg
from plasma_reactgen.visualization.stats import write_statistical_charts


def write_visualizations(
    case_output_dir: str | Path,
    visualization_dir: str | Path | None = None,
    *,
    graphviz_options: GraphvizOptions | None = None,
) -> dict:
    """Create statistical charts and reaction-network Graphviz outputs.

    Parameters
    ----------
    case_output_dir:
        Directory containing generated outputs such as ``network.reactions.yaml``.
    visualization_dir:
        Destination directory. Defaults to ``case_output_dir / 'visualizations'``.
    graphviz_options:
        Network rendering options.
    """

    case_output_dir = Path(case_output_dir)
    if visualization_dir is None:
        visualization_dir = case_output_dir / "visualizations"
    visualization_dir = Path(visualization_dir)
    visualization_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_visualization_dataset(case_output_dir)

    stats_dir = visualization_dir / "statistics"
    network_dir = visualization_dir / "network"

    charts = write_statistical_charts(dataset, stats_dir)
    options = graphviz_options or GraphvizOptions()
    network = write_reaction_network_graphviz(
        dataset,
        network_dir,
        options=options,
    )
    lineage = write_species_lineage_graphviz(
        dataset,
        network_dir,
        options=options,
    )
    reaction_pathway = write_reaction_pathway_svg(dataset, network_dir)

    manifest = {
        "schema_version": 1,
        "case": dataset.case,
        "source_dir": str(case_output_dir),
        "visualization_dir": str(visualization_dir),
        "statistics": charts,
        "network": network,
        "lineage": lineage,
        "reaction_pathway": reaction_pathway,
        "notes": [
            "Statistical charts are dependency-free SVG files.",
            "The reaction pathway SVG shows equations and precursor-reaction links without Graphviz.",
            "Graphviz DOT is always written; SVG/PNG rendering requires the 'dot' executable.",
        ],
    }
    (visualization_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
