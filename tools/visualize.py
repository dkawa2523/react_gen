"""Render a generated bundle as pictures.

    python tools/visualize.py cases/ar/outputs

Reads the bundle the way anyone else would — `species.yaml` and
`reactions.yaml`, nothing private — and writes SVGs beside them. It lives in
`tools/` rather than `src/` because the core has one dependency, PyYAML, and
plotting is not worth adding to that: a bundle is complete without pictures.

Two views, because they answer different questions. The network says what turns
into what; the profile says how much of the list rests on data nobody has yet.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import yaml

# Depth reads as distance from the feed gas, so it gets a sequential ramp.
DEPTH_COLOURS = ["#1B3A5C", "#2E6E8E", "#4FA3A5", "#8FC7A8", "#CBE3C3"]
STATUS_COLOURS = {
    "curated": "#1B3A5C",
    "literature_supported": "#4FA3A5",
    "candidate": "#D9A441",
}
SEVERITY_COLOURS = {"blocking": "#A93226", "data": "#4A3FBF", "info": "#8A90A2"}


def load(bundle: Path) -> tuple[list[dict], list[dict], list[dict]]:
    def read(name: str, key: str) -> list[dict]:
        document = yaml.safe_load((bundle / name).read_text(encoding="utf-8")) or {}
        return document.get(key) or []

    return (
        read("species.yaml", "species"),
        read("reactions.yaml", "reactions"),
        read("gaps.yaml", "gaps"),
    )


def network(species: list[dict], reactions: list[dict], out: Path, title: str) -> None:
    """Species as nodes, one edge per reaction that turns one into another."""

    depth = {item["id"]: item.get("depth", 0) for item in species}
    graph = nx.DiGraph()
    for item in species:
        if item["id"] != "e":
            graph.add_node(item["id"])
    for reaction in reactions:
        left = [t["species"] for t in reaction["reactants"] if t["species"] != "e"]
        right = [t["species"] for t in reaction["products"] if t["species"] != "e"]
        for source in left:
            for target in right:
                if source != target and graph.has_node(source) and graph.has_node(target):
                    graph.add_edge(source, target, status=reaction.get("status", "candidate"))
    if not graph:
        return

    size = max(7.0, min(20.0, 0.55 * graph.number_of_nodes() ** 0.75))
    figure, axes = plt.subplots(figsize=(size * 1.4, size))
    layout = nx.spring_layout(graph, seed=7, k=1.9 / max(1, graph.number_of_nodes()) ** 0.4)

    colours = [DEPTH_COLOURS[min(depth.get(n, 0), len(DEPTH_COLOURS) - 1)] for n in graph]
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[
            STATUS_COLOURS.get(d["status"], "#B9BEC9") for _, _, d in graph.edges(data=True)
        ],
        width=0.7,
        alpha=0.55,
        arrowsize=7,
        connectionstyle="arc3,rad=0.08",
    )
    nx.draw_networkx_nodes(graph, layout, ax=axes, node_color=colours, node_size=560, linewidths=0)
    nx.draw_networkx_labels(graph, layout, ax=axes, font_size=7, font_color="white")

    legend = [
        plt.Line2D([], [], color=c, lw=2, label=f"depth {i}")
        for i, c in enumerate(DEPTH_COLOURS[: max(depth.values(), default=0) + 1])
    ]
    legend += [plt.Line2D([], [], color=c, lw=2, label=k) for k, c in STATUS_COLOURS.items()]
    axes.legend(handles=legend, loc="upper left", fontsize=7, frameon=False, ncol=2)
    axes.set_title(
        f"{title} — {graph.number_of_nodes()} species, {len(reactions)} reactions", fontsize=11
    )
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def profile(reactions: list[dict], gaps: list[dict], out: Path, title: str) -> None:
    """How the list divides by family and status, and what it still lacks."""

    figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.4))

    families = Counter(r.get("family", "?") for r in reactions)
    statuses = Counter(r.get("status", "?") for r in reactions)
    names = [n for n, _ in families.most_common()]
    bottom = [0.0] * len(names)
    for status, colour in STATUS_COLOURS.items():
        heights = [
            sum(1 for r in reactions if r.get("family") == n and r.get("status") == status)
            for n in names
        ]
        left.barh(names, heights, left=bottom, color=colour, label=f"{status} ({statuses[status]})")
        bottom = [b + h for b, h in zip(bottom, heights, strict=False)]
    left.set_title("reactions by family and status", fontsize=10)
    left.legend(fontsize=7, frameon=False)
    left.invert_yaxis()
    left.tick_params(labelsize=8)

    kinds = Counter((g["severity"], g["kind"]) for g in gaps)
    if kinds:
        labels = [f"{k}" for _, k in sorted(kinds, key=lambda x: -kinds[x])]
        values = [kinds[s] for s in sorted(kinds, key=lambda x: -kinds[x])]
        colours = [
            SEVERITY_COLOURS.get(s, "#8A90A2") for s, _ in sorted(kinds, key=lambda x: -kinds[x])
        ]
        right.barh(labels, values, color=colours)
        right.invert_yaxis()
    right.set_title("what the list still lacks", fontsize=10)
    right.tick_params(labelsize=8)

    figure.suptitle(title, fontsize=11)
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tools/visualize.py <bundle> [<bundle> ...]")
        return 2
    for name in argv:
        bundle = Path(name)
        species, reactions, gaps = load(bundle)
        # Inside the bundle, not beside it: a case has more than one bundle
        # (curated, and the same case with candidates) and they must not
        # overwrite each other's pictures.
        target = bundle / "visualizations"
        target.mkdir(parents=True, exist_ok=True)
        label = f"{bundle.parent.name} / {bundle.name}"
        network(species, reactions, target / "network.svg", label)
        profile(reactions, gaps, target / "profile.svg", label)
        print(f"  {label:12} {len(species):3d} species  {len(reactions):4d} reactions -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
