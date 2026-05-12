"""Visualization utilities for generated plasma reaction-network outputs.

The visualization package is intentionally independent from the network generation
core. It consumes files under a case output directory and writes human-readable
SVG/Graphviz artifacts. This keeps plots easy to add/remove without touching the
physics/network builder code.
"""

from plasma_reactgen.visualization.writer import write_visualizations

__all__ = ["write_visualizations"]
