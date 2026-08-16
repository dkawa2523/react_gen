from __future__ import annotations

from pathlib import Path

from plasma_reactgen.visualization.network import GraphvizOptions
from plasma_reactgen.visualization.writer import write_visualizations


def run_visualize(
    outputs: Path,
    output: Path | None,
    include_self_loops: bool,
    include_non_expanding: bool,
    max_reactions: int,
    formats: str,
) -> int:
    manifest = write_visualizations(
        outputs,
        output,
        graphviz_options=GraphvizOptions(
            include_self_loops=include_self_loops,
            include_non_expanding=include_non_expanding,
            max_reactions=None if max_reactions < 0 else max_reactions,
            render_formats=tuple(item.strip() for item in formats.split(",") if item.strip()),
        ),
    )
    print(f"Generated visualizations: {manifest['visualization_dir']}")
    print(f"  statistical_charts: {len(manifest['statistics'])}")
    print(f"  graphviz_network_dot: {manifest['network']['dot']}")
    if "lineage" in manifest:
        print(f"  graphviz_lineage_dot: {manifest['lineage']['dot']}")
    rendered = [
        *manifest["network"].get("rendered", []),
        *manifest.get("lineage", {}).get("rendered", []),
    ]
    if rendered:
        print("  graphviz_rendered: " + ", ".join(rendered))
    else:
        print("  graphviz_rendered: not available; install Graphviz 'dot' to render")
    return 0
