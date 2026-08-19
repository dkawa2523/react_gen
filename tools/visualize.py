"""Render a generated bundle as pictures.

    python tools/visualize.py cases/ar/outputs

Reads the bundle the way anyone else would - the YAML files, nothing private -
and writes SVGs into it. It lives in `tools/` rather than `src/` because the
core has one dependency, PyYAML, and plotting is not worth adding to that: a
bundle is complete without pictures.

Two network views and a sheet of charts, because they answer different
questions.

`reaction_network` draws every reaction. `species_lineage` draws only the edges
that introduce a species for the first time, which is the view for checking how
the expansion actually recursed - the full graph is too dense to read that
from. Both are laid out in columns by expansion depth, so distance from the
feed gas is a position rather than something to trace.

The charts say how the list divides and how far the evidence for it goes. The
`evidence` panel is the one to read first: it shows each layer of judgement
separately, so a channel that is thermochemically certain and wholly unattested
does not average out into one confidence number.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import yaml

ELECTRON = "e"
# Charge is what a reader sorts a plasma species list by, so it picks the fill.
CHARGE = {0: "#CDE7D0", 1: "#C4DDF5", -1: "#F7E7B8"}
LACKING = "#D62728"
CHARGE_KEY = "charge"
DEPTH_KEY = "depth"
NEWLINE = chr(10)
# Depth reads as distance from the feed gas, so it gets a sequential ramp.
DEPTH = ["#1B3A5C", "#2E6E8E", "#4FA3A5", "#8FC7A8", "#CBE3C3", "#E8EFD9"]
STATUS = {"curated": "#1B3A5C", "literature_supported": "#4FA3A5", "candidate": "#D9A441"}
FAMILY = {
    "electron": "#2E6E8E",
    "ion_neutral": "#B3541E",
    "ion_ion": "#8A3D6B",
    "neutral_neutral": "#4F8A5C",
    "surface": "#7A6A55",
    "three_body": "#9A7BAE",
}
LAYER = {
    "conserved": "#1B3A5C",
    "conserved, species proposed": "#D9A441",
    "exothermic": "#2E7D4F",
    "endothermic": "#B3541E",
    "unknown": "#B9BEC9",
    "not_run": "#DDE1E8",
    "unattested": "#C9A0A0",
}


def read(bundle: Path, name: str, key: str) -> list[dict]:
    path = bundle / name
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return document.get(key) or []


# --------------------------------------------------------------------------- networks


def _edges(reactions: list[dict], lineage_only: bool) -> list[tuple[str, str, dict]]:
    """Species-to-species edges. A reaction is a hyperedge; this projects it.

    ``lineage_only`` keeps just the edge that first introduced each product,
    which is the recursion the expansion actually walked.
    """

    seen: set[str] = set()
    out = []
    for reaction in sorted(reactions, key=lambda item: item.get("depth", 0)):
        left = [t["species"] for t in reaction["reactants"] if t["species"] != ELECTRON]
        right = [t["species"] for t in reaction["products"] if t["species"] != ELECTRON]
        fresh = [name for name in right if name not in seen]
        seen.update(right)
        for source in left:
            for target in fresh if lineage_only else right:
                if source != target:
                    out.append((source, target, reaction))
    return out


def network(
    species: list[dict], reactions: list[dict], out: Path, title: str, lineage: bool
) -> None:
    depth = {item["id"]: item.get("depth", 0) for item in species}
    graph = nx.DiGraph()
    for item in species:
        if item["id"] != ELECTRON:
            graph.add_node(item["id"], depth=item.get("depth", 0))
    for source, target, reaction in _edges(reactions, lineage):
        if graph.has_node(source) and graph.has_node(target):
            graph.add_edge(source, target, family=reaction.get("family", "?"))
    if not graph.number_of_nodes():
        return

    # Columns by depth: distance from the feed gas becomes a position.
    layout = nx.multipartite_layout(graph, subset_key="depth", align="vertical")
    span = max(depth.values(), default=0) + 1
    height = max(6.0, 0.26 * graph.number_of_nodes() ** 0.95)
    figure, axes = plt.subplots(figsize=(max(9.0, 3.2 * span), height))

    families = [d["family"] for _, _, d in graph.edges(data=True)]
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[FAMILY.get(name, "#B9BEC9") for name in families],
        width=0.8,
        alpha=0.5,
        arrowsize=8,
        connectionstyle="arc3,rad=0.10",
    )
    _draw_nodes(graph, layout, axes, species)

    handles = [
        plt.Line2D([], [], marker="s", ls="", color=c, label=n, markersize=9)
        for n, c in (
            ("neutral", CHARGE[0]),
            ("positive ion", CHARGE[1]),
            ("negative ion", CHARGE[-1]),
        )
    ]
    handles += [
        plt.Line2D([], [], color=colour, lw=2, label=name)
        for name, colour in FAMILY.items()
        if name in set(families)
    ]
    axes.legend(handles=handles, loc="upper left", fontsize=7, frameon=False, ncol=2)
    kind = "species lineage - edges that introduce a species" if lineage else "every reaction"
    axes.set_title(f"{title}   {kind}   {graph.number_of_nodes()} species", fontsize=11)
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# --------------------------------------------------------------------------- charts


def bars(axes, counts: Counter, title: str, colours: dict | None = None) -> None:
    if not counts:
        axes.set_title(f"{title} - none", fontsize=10)
        axes.axis("off")
        return
    pairs = counts.most_common(14)
    labels = [str(key) for key, _ in pairs]
    values = [value for _, value in pairs]
    axes.barh(labels, values, color=[(colours or {}).get(name, "#4FA3A5") for name in labels])
    axes.invert_yaxis()
    axes.set_title(title, fontsize=10)
    axes.tick_params(labelsize=8)
    for index, value in enumerate(values):
        axes.text(value, index, f" {value}", va="center", fontsize=7)


def stacked(axes, rows: dict[str, Counter], colours: dict, title: str) -> None:
    names = list(rows)
    if not names:
        axes.set_title(f"{title} - none", fontsize=10)
        axes.axis("off")
        return
    bottom = [0.0] * len(names)
    for key in sorted({k for row in rows.values() for k in row}):
        heights = [rows[name].get(key, 0) for name in names]
        axes.barh(names, heights, left=bottom, color=colours.get(key, "#B9BEC9"), label=str(key))
        bottom = [b + h for b, h in zip(bottom, heights, strict=False)]
    axes.invert_yaxis()
    axes.set_title(title, fontsize=10)
    axes.legend(fontsize=6, frameon=False)
    axes.tick_params(labelsize=8)


def charts(
    bundle: Path,
    species: list[dict],
    reactions: list[dict],
    gaps: list[dict],
    out: Path,
    title: str,
) -> None:
    figure, grid = plt.subplots(3, 3, figsize=(16, 12))
    (a, b, c), (d, e, f), (g, h, i) = grid

    by_family: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        by_family[reaction.get("family", "?")][reaction.get("status", "?")] += 1
    stacked(a, dict(by_family), STATUS, "reactions by family and status")

    bars(b, Counter(r.get("type", "?") for r in reactions), "reaction type")

    by_depth: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        by_depth[str(reaction.get("depth", 0))][reaction.get("family", "?")] += 1
    stacked(c, dict(sorted(by_depth.items())), FAMILY, "expansion depth by family")

    bars(d, Counter(str(s.get("charge", 0)) for s in species), "species charge")
    bars(e, Counter(str(s.get("depth", 0)) for s in species), "species first-seen depth")
    bars(f, Counter(k for s in species for k in (s.get("classes") or [])), "species class")

    layered: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        for layer, verdict in (reaction.get("evidence") or {}).items():
            layered[layer][str(verdict).split(" by ")[0]] += 1
    stacked(g, dict(layered), LAYER, "evidence by layer")

    bars(
        h,
        Counter(f"{gap['severity']}: {gap['kind']}" for gap in gaps),
        "what the list still lacks",
    )

    index = bundle / "datasets" / "dnt" / "index.yaml"
    readiness: Counter = Counter()
    if index.is_file():
        document = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
        for pair in document.get("pairs") or []:
            for tier in pair.get("runnable") or ["blocked"]:
                readiness[tier] += 1
    bars(i, readiness, "DNT+ readiness by tier")

    figure.suptitle(title, fontsize=12)
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# --------------------------------------------------------------------------- per layer


def per_layer(species: list[dict], reactions: list[dict], out: Path, title: str) -> list[str]:
    """One directory per layer of judgement: the same list, seen four ways.

    A layer is a verdict on every reaction rather than a subset of them, so
    each directory holds the whole list with that layer's answer attached, the
    counts, and the network coloured by it. Reading them side by side is how a
    reviewer sees that structure passes everywhere and attestation passes
    almost nowhere, which one merged view flattens.
    """

    names = sorted({layer for r in reactions for layer in (r.get("evidence") or {})})
    for layer in names:
        target = out / layer
        target.mkdir(parents=True, exist_ok=True)
        verdicts = {r["id"]: (r.get("evidence") or {}).get(layer, "not_run") for r in reactions}
        # Grouped by kind, not by value: "exothermic" is the answer, and the
        # electronvolts belong beside each reaction rather than in a tally.
        counts = Counter(v.split(" by ")[0] for v in verdicts.values())

        rows = ["id,equation,family,type,status,verdict"]
        for reaction in reactions:
            fields = [
                reaction["id"],
                reaction["equation"],
                reaction.get("family", ""),
                reaction.get("type", ""),
                reaction.get("status", ""),
                verdicts[reaction["id"]],
            ]
            rows.append(",".join(f'"{f}"' if "," in str(f) else str(f) for f in fields))
        (target / "reactions.csv").write_text(NEWLINE.join(rows) + NEWLINE, encoding="utf-8")

        (target / "summary.yaml").write_text(
            yaml.safe_dump(
                {
                    "layer": layer,
                    "question": QUESTIONS[layer],
                    "reactions": len(reactions),
                    "verdicts": dict(counts.most_common()),
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        _layer_network(species, reactions, verdicts, target / "network.svg", title, layer)
    return names


QUESTIONS = {
    "structure": "can these species exist, and does the equation balance?",
    "thermochemistry": "do the energetics leave the channel open?",
    "kinetics": "does it run fast enough to matter under these conditions?",
    "attestation": "does any source state this reaction?",
}


def _draw_nodes(graph, layout, axes, species: list[dict]) -> None:
    """Charge picks the fill, a red rim marks a species still missing data.

    The label carries what a reviewer checks against — charge and the depth it
    first appeared at — so an arrow can be read without going back to the YAML.
    """

    index = {item["id"]: item for item in species}
    fills, rims, widths = [], [], []
    for name in graph:
        item = index.get(name, {})
        lacking = sum(1 for p in (item.get("properties") or {}).values() if p.get("value") is None)
        fills.append(CHARGE.get(item.get("charge", 0), "#EDEFF2"))
        rims.append(LACKING if lacking else "#7A8090")
        widths.append(1.6 if lacking else 0.6)
    nx.draw_networkx_nodes(
        graph,
        layout,
        ax=axes,
        node_color=fills,
        edgecolors=rims,
        linewidths=widths,
        node_size=1500,
        node_shape="s",
    )
    labels = {}
    for name in graph:
        item = index.get(name, {})
        charge = item.get(CHARGE_KEY, 0)
        labels[name] = NEWLINE.join([name, f"q{charge:+d} d{item.get(DEPTH_KEY, 0)}"])
    nx.draw_networkx_labels(
        graph, layout, labels=labels, ax=axes, font_size=6, font_color="#161A25"
    )


def _layer_network(
    species: list[dict],
    reactions: list[dict],
    verdicts: dict[str, str],
    out: Path,
    title: str,
    layer: str,
) -> None:
    """The network with every edge coloured by what this one layer said."""

    depth = {item["id"]: item.get("depth", 0) for item in species}
    graph = nx.DiGraph()
    for item in species:
        if item["id"] != ELECTRON:
            graph.add_node(item["id"], depth=item.get("depth", 0))
    for source, target, reaction in _edges(reactions, lineage_only=False):
        if graph.has_node(source) and graph.has_node(target):
            graph.add_edge(source, target, verdict=verdicts.get(reaction["id"], "not_run"))
    if not graph.number_of_nodes():
        return

    seen = sorted({d["verdict"].split(" by ")[0] for _, _, d in graph.edges(data=True)})
    palette = {name: LAYER.get(name, _spread(index, len(seen))) for index, name in enumerate(seen)}
    layout = nx.multipartite_layout(graph, subset_key="depth", align="vertical")
    span = max(depth.values(), default=0) + 1
    figure, axes = plt.subplots(
        figsize=(max(9.0, 3.2 * span), max(6.0, 0.26 * graph.number_of_nodes() ** 0.95))
    )
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[palette[d["verdict"].split(" by ")[0]] for _, _, d in graph.edges(data=True)],
        width=0.9,
        alpha=0.6,
        arrowsize=8,
        connectionstyle="arc3,rad=0.10",
    )
    _draw_nodes(graph, layout, axes, species)
    axes.legend(
        handles=[plt.Line2D([], [], color=c, lw=3, label=n) for n, c in palette.items()],
        loc="upper left",
        fontsize=7,
        frameon=False,
    )
    axes.set_title(f"{title}   {layer} — {QUESTIONS[layer]}", fontsize=11)
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def _spread(index: int, total: int) -> str:
    """A readable colour for a verdict the palette does not name."""

    return plt.get_cmap("tab10")(index % 10)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tools/visualize.py <bundle> [<bundle> ...]")
        return 2
    for name in argv:
        bundle = Path(name)
        species = read(bundle, "species.yaml", "species")
        reactions = read(bundle, "reactions.yaml", "reactions")
        gaps = read(bundle, "gaps.yaml", "gaps")
        # Inside the bundle: a case has more than one, and they must not
        # overwrite each other's pictures.
        target = bundle / "visualizations"
        target.mkdir(parents=True, exist_ok=True)
        label = f"{bundle.parent.name} / {bundle.name}"
        network(species, reactions, target / "reaction_network.svg", label, lineage=False)
        network(species, reactions, target / "species_lineage.svg", label, lineage=True)
        charts(bundle, species, reactions, gaps, target / "statistics.svg", label)
        named = per_layer(species, reactions, bundle / "layers", label)
        print(
            f"  {label:26} {len(species):3d} species {len(reactions):5d} reactions"
            f"  -> {target}, layers {named}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
