"""Render a generated bundle the way a plasma chemist reads one.

    python tools/visualize.py cases/ar_cf4/candidates

Reads the bundle's YAML and writes SVGs into it. It lives in `tools/` rather
than `src/` because the core has one dependency, PyYAML, and plotting is not
worth adding to that.

What gets drawn follows from what the reader is actually asking.

`energy_landscape` first. Electron-impact chemistry is decided by where a
threshold sits against the electron temperature: a 15 eV channel in a 4 eV
discharge runs on the tail and a 2 eV one runs on the bulk, and no amount of
network topology shows that. Te and 3 Te are marked because that is the band
the chemistry comes from.

`fragmentation` next. The neutral skeleton breaking down - CF4 to CF3 to CF2
to CF to C - is the spine of a fluorocarbon mechanism, and it is legible
because it is sparse. The full reaction graph is not: past forty or so species
a node-link diagram tells a reader nothing, so it degrades to an interaction
matrix, which stays readable at any size.

Each judgement layer gets the distribution of the quantity behind its verdict
rather than a bar chart of the verdict itself - the enthalpy spread for
thermochemistry, the threshold spread against Te for kinetics - because the
question a reviewer has is where the boundary falls, not how many landed on
each side of it.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import yaml
from matplotlib.patches import FancyBboxPatch

ELECTRON = "e"
NEWLINE = chr(10)
READABLE = 45  # species past which a node-link diagram stops being a picture

# Okabe-Ito: the colour-blind-safe set the chemistry and physics journals ask
# for. Saturated on white, distinguishable in greyscale, and eight is enough
# for every categorical axis here.
BLACK = "#000000"
ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
YELLOW = "#F0E442"
BLUE = "#0072B2"
VERMILLION = "#D55E00"
PURPLE = "#CC79A7"
GREY = "#5A5A5A"

INK = BLACK
MUTED = "#3A3A3A"
HAIR = "#9A9A9A"
CHARGE = {0: GREEN, 1: BLUE, -1: ORANGE}
CHARGE_NAME = {"neutral": CHARGE[0], "cation": CHARGE[1], "anion": CHARGE[-1]}
STATUS = {"curated": BLUE, "literature_supported": GREEN, "candidate": ORANGE}
FAMILY = {
    "electron": BLUE,
    "electron_ion": SKY,
    "ion_neutral": VERMILLION,
    "ion_ion": PURPLE,
    "neutral_neutral": GREEN,
    "three_body": ORANGE,
    "unimolecular": GREY,
    "surface": BLACK,
}
# A verdict is either decided, undecided, or never asked; the palette says which.
VERDICT = {
    "conserved": BLUE,
    "conserved, species proposed": ORANGE,
    "exothermic": GREEN,
    "endothermic": VERMILLION,
    "thermoneutral": YELLOW,
    "fast": GREEN,
    "comparable": SKY,
    "slow": ORANGE,
    "negligible": GREY,
    "attested": BLUE,
    "unknown": "#BFBFBF",
    "unattested": "#BFBFBF",
    "not_run": "#E4E4E4",
}
UNDECIDED = frozenset({"unknown", "unattested"})
LACKING = VERMILLION


def read(bundle: Path, name: str, key: str) -> list:
    path = bundle / name
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return document.get(key) or []


def frame(axes, title: str, subtitle: str = "") -> None:
    axes.set_title(title, fontsize=11, color=INK, loc="left", pad=14 if subtitle else 6)
    if subtitle:
        axes.text(0, 1.02, subtitle, transform=axes.transAxes, fontsize=8, color=MUTED, va="bottom")
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(BLACK)
        axes.spines[side].set_linewidth(0.9)
    axes.tick_params(labelsize=8.5, colors=BLACK, length=4, width=0.9, direction="out")


def charge_name(charge: int) -> str:
    return "neutral" if charge == 0 else "cation" if charge > 0 else "anion"


def lacking_count(item: dict) -> int:
    return sum(1 for p in (item.get("properties") or {}).values() if p.get("value") is None)


# --------------------------------------------------------------------------- energy


def energy_landscape(reactions: list[dict], conditions: dict, out: Path, title: str) -> None:
    """Where every channel opens, against the temperature that has to open it."""

    kinds = sorted({r["type"] for r in reactions if r.get("threshold_eV") is not None})
    if not kinds:
        return
    figure, axes = plt.subplots(figsize=(11, max(4.0, 0.42 * len(kinds) + 1.8)))
    rows = {name: index for index, name in enumerate(kinds)}
    rng = np.random.default_rng(7)

    for status, colour in STATUS.items():
        xs, ys = [], []
        for reaction in reactions:
            onset = reaction.get("threshold_eV")
            if onset is None or reaction.get("status") != status:
                continue
            xs.append(onset)
            ys.append(rows[reaction["type"]] + rng.uniform(-0.24, 0.24))
        if xs:
            axes.scatter(
                xs, ys, s=30, c=colour, alpha=0.85, linewidths=0.3, edgecolors="white", label=status
            )

    temperature = (conditions or {}).get("electron_temperature_eV")
    if temperature:
        axes.axvspan(0, temperature, color=YELLOW, alpha=0.22)
        axes.axvline(temperature, color=LACKING, lw=1.2, ls="--")
        axes.axvline(3 * temperature, color=LACKING, lw=0.8, ls=":")
        top = len(kinds) - 0.4
        axes.text(temperature, top, f"  Te = {temperature:g} eV", fontsize=8, color=LACKING)
        axes.text(3 * temperature, top, "  3 Te", fontsize=8, color=LACKING)

    axes.set_yticks(range(len(kinds)))
    axes.set_yticklabels(kinds)
    axes.set_xlabel("threshold [eV]", fontsize=9, color=MUTED)
    axes.set_xlim(left=-0.5)
    axes.grid(axis="x", color=HAIR, lw=0.5)
    axes.set_axisbelow(True)
    axes.legend(fontsize=8, frameon=False, loc="lower right")
    frame(
        axes,
        f"{title}   energy landscape",
        "a channel above 3 Te runs only on the tail of the distribution",
    )
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# --------------------------------------------------------------------------- structure


def _lineage(reactions: list[dict]) -> list[tuple[str, str, dict]]:
    """The edge that first introduced each species: the recursion as walked."""

    seen: set[str] = set()
    out = []
    for reaction in sorted(reactions, key=lambda item: item.get("depth", 0)):
        left = [t["species"] for t in reaction["reactants"] if t["species"] != ELECTRON]
        right = [t["species"] for t in reaction["products"] if t["species"] != ELECTRON]
        fresh = [name for name in right if name not in seen]
        seen.update(right)
        for source in left:
            for target in fresh:
                if source != target:
                    out.append((source, target, reaction))
    return out


def _nodes(graph, layout, axes, index: dict, size: int = 700) -> None:
    """Charge picks the fill; a red rim marks a species still missing data."""

    fills, rims, widths = [], [], []
    for name in graph:
        item = index.get(name, {})
        fills.append(CHARGE.get(item.get("charge", 0), "#8A90A2"))
        rims.append(LACKING if lacking_count(item) else "#FFFFFF")
        widths.append(1.5 if lacking_count(item) else 0.8)
    nx.draw_networkx_nodes(
        graph,
        layout,
        ax=axes,
        node_color=fills,
        edgecolors=rims,
        linewidths=widths,
        node_size=size,
        alpha=0.95,
    )
    nx.draw_networkx_labels(
        graph, layout, ax=axes, font_size=6.5, font_color="white", font_weight="bold"
    )


def fragmentation(species: list[dict], reactions: list[dict], out: Path, title: str) -> None:
    """The skeleton coming apart, laid out by the depth it came apart at."""

    index = {item["id"]: item for item in species}
    graph = nx.DiGraph()
    for item in species:
        if item["id"] != ELECTRON:
            graph.add_node(item["id"])
    for source, target, reaction in _lineage(reactions):
        if graph.has_node(source) and graph.has_node(target):
            graph.add_edge(source, target, family=reaction.get("family", "?"))
    if not graph.number_of_nodes():
        return

    columns: dict[int, list[str]] = defaultdict(list)
    for name in graph:
        columns[index.get(name, {}).get("depth", 0)].append(name)
    tallest = max(len(names) for names in columns.values())
    layout = {}
    for depth, names in columns.items():
        step = tallest / max(len(names), 1)
        for row, name in enumerate(sorted(names)):
            layout[name] = (depth * 2.8, -(row - (len(names) - 1) / 2) * step)

    figure, axes = plt.subplots(
        figsize=(max(8.0, 3.0 * len(columns)), max(5.0, 0.36 * tallest + 2.2))
    )
    families = [d["family"] for _, _, d in graph.edges(data=True)]
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[FAMILY.get(name, "#B9BEC9") for name in families],
        width=1.0,
        alpha=0.55,
        arrowsize=9,
        connectionstyle="arc3,rad=0.06",
        node_size=900,
    )
    _nodes(graph, layout, axes, index, size=900)
    for depth in sorted(columns):
        axes.text(
            depth * 2.8, tallest / 1.6, f"depth {depth}", ha="center", fontsize=9, color=MUTED
        )
    handles = [
        plt.Line2D([], [], color=colour, lw=2, label=name)
        for name, colour in FAMILY.items()
        if name in set(families)
    ]
    axes.legend(handles=handles, fontsize=8, frameon=False, loc="lower left")
    axes.set_title(
        f"{title}   fragmentation — the edge that first made each species",
        fontsize=11,
        color=INK,
        loc="left",
    )
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def _pathway_graph(shown: list[dict], index: dict):
    """Species and reactions as one graph, and which column each belongs in."""

    graph = nx.DiGraph()
    columns: dict[float, list[str]] = defaultdict(list)
    for reaction in shown:
        depth = reaction.get("depth", 0)
        node = reaction["id"]
        graph.add_node(node, kind="reaction", family=reaction.get("family", "?"))
        columns[depth + 0.5].append(node)
        for term, column, forward in (
            *[(t, depth, True) for t in reaction["reactants"]],
            *[(t, depth + 1, False) for t in reaction["products"]],
        ):
            name = term["species"]
            if name not in index:
                continue
            graph.add_node(name, kind="species")
            graph.add_edge(*((name, node) if forward else (node, name)))
            if name not in columns[column]:
                columns[column].append(name)
    return graph, columns


# A layered drawing is boxes you can read, not dots you have to hover. These are
# in axis units: one column is COLUMN wide, one row ROW tall, and a box is sized
# to its own label inside that.
COLUMN = 4.4
ROW = 1.5
CHAR = 0.10  # width of a character at the label size, in axis units


def _box(axes, position, lines: list[str], fill: str, rim: str, width: float = 1.0) -> tuple:
    """One rounded, labelled node. Returns the box's half-extent for routing."""

    x, y = position
    half_w = max(0.42, (max(len(line) for line in lines) * CHAR) / 2 + 0.14)
    half_h = 0.13 + 0.115 * len(lines)
    axes.add_patch(
        FancyBboxPatch(
            (x - half_w, y - half_h),
            2 * half_w,
            2 * half_h,
            boxstyle="round,pad=0.02,rounding_size=0.09",
            facecolor=fill,
            edgecolor=rim,
            linewidth=width,
            zorder=3,
        )
    )
    axes.text(
        x,
        y,
        NEWLINE.join(lines),
        ha="center",
        va="center",
        fontsize=8.5,
        color=INK,
        zorder=4,
        linespacing=1.25,
    )
    return half_w, half_h


def _arrow(axes, start, end, extent: dict, colour: str, style: str = "-") -> None:
    """An edge that stops at the boxes rather than under them."""

    (x0, y0), (x1, y1) = start[1], end[1]
    left = x0 + extent[start[0]][0]
    right = x1 - extent[end[0]][0]
    if right <= left:
        left, right = x0, x1
    axes.annotate(
        "",
        xy=(right, y1),
        xytext=(left, y0),
        arrowprops={
            "arrowstyle": "-|>",
            "color": colour,
            "linewidth": 0.9,
            "alpha": 0.8,
            "linestyle": style,
            "shrinkA": 0,
            "shrinkB": 0,
            "connectionstyle": "arc3,rad=0.06",
        },
        zorder=2,
    )


def _ordered(columns: dict[float, list[str]], graph, sweeps: int = 6) -> dict[float, list[str]]:
    """Order each column to cut edge crossings, the way a layered drawer does.

    Barycentre sweeps: a node is placed at the mean position of its neighbours
    in the column just drawn, alternating forward and back until it settles.
    Ordering a column alphabetically instead guarantees crossings, which is
    what made the pathway unreadable — the layout was right and the sequence
    inside it was arbitrary.
    """

    order = {key: list(names) for key, names in columns.items()}
    keys = sorted(order)
    for sweep in range(sweeps):
        forward = sweep % 2 == 0
        walk = keys[1:] if forward else keys[-2::-1]
        for key in walk:
            other = keys[keys.index(key) - 1] if forward else keys[keys.index(key) + 1]
            place = {name: position for position, name in enumerate(order[other])}
            linked = graph.predecessors if forward else graph.successors

            def centre(name: str, place=place, linked=linked) -> float:
                seats = [place[n] for n in linked(name) if n in place]
                return sum(seats) / len(seats) if seats else len(place) / 2

            order[key] = sorted(order[key], key=centre)
    return order


def _draw_boxes(axes, layout: dict, detail: dict, index: dict) -> dict:
    """A card for every reaction and a chip for every species, sized to its label."""

    extent = {}
    for name, position in layout.items():
        if name in detail:
            reaction = detail[name]
            onset = reaction.get("threshold_eV")
            lines = [reaction["type"]]
            if onset is not None:
                lines.append(f"{onset:.2f} eV")
            extent[name] = _box(
                axes,
                position,
                lines,
                fill="#FFFFFF",
                rim=FAMILY.get(reaction.get("family", "?"), GREY),
                width=1.3,
            )
        else:
            item = index.get(name, {})
            short = lacking_count(item)
            extent[name] = _box(
                axes,
                position,
                [name],
                fill=CHARGE.get(item.get("charge", 0), GREY),
                rim=LACKING if short else "#FFFFFF",
                width=1.6 if short else 0.8,
            )
    return extent


# How much of a mechanism fits on one page. Ar/CF4 opens fifteen channels on the
# feed gas and a hundred and five on their products; by the third generation it
# is two hundred and seventy-five, which is a table, not a diagram.
PRIMARY_DEPTH = 1
CARDS = 40


def pathway(
    species: list[dict],
    reactions: list[dict],
    out: Path,
    title: str,
    max_depth: int = PRIMARY_DEPTH,
    limit: int = CARDS,
) -> None:
    """Reactions as labelled cards, laid out left to right by the depth they open at.

    A species graph collapses a reaction into an arrow and loses which products
    came out together: CF4 to CF3 and CF4 to F are one channel, not two. Here
    each reaction is a card of its own carrying its process and onset, so a
    route reads as a sequence of steps rather than a bundle of arrows.

    Columns are ordered at the barycentre of their neighbours, which is the step
    that makes a layered drawing legible; ordering them by name instead crossed
    three times as many edges.

    Only the primary chemistry is drawn: what the feed gas does and what its
    first products do. Everything past that is where the count explodes, and a
    page of four hundred cards answers nothing a reviewer asked. The curated
    channels come first inside that, because they are the backbone the rest
    hangs off. `reactions.csv` carries the whole list.
    """

    index = {item["id"]: item for item in species if item["id"] != ELECTRON}
    rank = {"curated": 0, "literature_supported": 1, "candidate": 2}
    primary = [r for r in reactions if r.get("depth", 0) <= max_depth]
    shown = sorted(
        primary,
        key=lambda item: (rank.get(item.get("status"), 3), item.get("depth", 0), item["id"]),
    )[:limit]
    if not shown:
        return

    graph, columns = _pathway_graph(shown, index)
    detail = {r["id"]: r for r in shown}

    placed: set[str] = set()
    unique: dict[float, list[str]] = {}
    for column in sorted(columns):
        names = [name for name in columns[column] if name not in placed]
        placed.update(names)
        unique[column] = names
    unique = _ordered(unique, graph)

    tallest = max((len(names) for names in unique.values()), default=1)
    layout = {}
    for column, names in unique.items():
        step = tallest / max(len(names), 1)
        for row, name in enumerate(names):
            layout[name] = (column * COLUMN, -(row - (len(names) - 1) / 2) * step * ROW)
    for name in graph:
        layout.setdefault(name, (0.0, 0.0))

    figure, axes = plt.subplots(
        figsize=(max(12.0, 3.1 * len(unique)), max(6.5, 0.62 * tallest + 2.8))
    )
    extent = _draw_boxes(axes, layout, detail, index)

    for source, target in graph.edges():
        colour = FAMILY.get(detail.get(source, detail.get(target, {})).get("family", "?"), GREY)
        _arrow(axes, (source, layout[source]), (target, layout[target]), extent, colour)

    for column in sorted(unique):
        axes.text(
            column * COLUMN,
            tallest / 1.6 + 0.5,
            f"depth {column:g}" if column == int(column) else "reaction",
            ha="center",
            fontsize=8.5,
            color=MUTED,
        )
    handles = [
        plt.Line2D([], [], marker="s", ls="", color=colour, label=name, markersize=9)
        for name, colour in CHARGE_NAME.items()
    ] + [
        plt.Line2D([], [], color=colour, lw=2, label=name)
        for name, colour in FAMILY.items()
        if name in {r.get("family") for r in shown}
    ]
    axes.legend(handles=handles, fontsize=7.5, frameon=False, loc="lower left", ncol=2)
    axes.set_title(
        f"{title}   primary chemistry — {len(shown)} channels to depth {max_depth}, "
        f"of {len(reactions)}",
        fontsize=11.5,
        color=INK,
        loc="left",
    )
    axes.margins(0.06)
    axes.set_axis_off()
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def interaction_matrix(species: list[dict], reactions: list[dict], out: Path, title: str) -> None:
    """Who turns into what, as a matrix. Readable where a graph is not."""

    heavy = sorted(item["id"] for item in species if item["id"] != ELECTRON)
    if not heavy:
        return
    place = {name: index for index, name in enumerate(heavy)}
    grid = np.zeros((len(heavy), len(heavy)))
    for reaction in reactions:
        left = [t["species"] for t in reaction["reactants"] if t["species"] != ELECTRON]
        right = [t["species"] for t in reaction["products"] if t["species"] != ELECTRON]
        for source in left:
            for target in right:
                if source in place and target in place:
                    grid[place[source], place[target]] += 1
    size = max(7.0, 0.19 * len(heavy) + 3)
    figure, axes = plt.subplots(figsize=(size, size))
    shown = axes.imshow(np.log1p(grid), cmap="cividis", interpolation="nearest")
    axes.set_xticks(range(len(heavy)))
    axes.set_yticks(range(len(heavy)))
    axes.set_xticklabels(heavy, rotation=90, fontsize=5.5)
    axes.set_yticklabels(heavy, fontsize=5.5)
    axes.set_xlabel("product", fontsize=9, color=MUTED)
    axes.set_ylabel("reactant", fontsize=9, color=MUTED)
    figure.colorbar(shown, ax=axes, shrink=0.6, label="log(1 + reactions)")
    axes.set_title(
        f"{title}   who turns into what   {len(heavy)} species", fontsize=11, color=INK, loc="left"
    )
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def reaction_network(species: list[dict], reactions: list[dict], out: Path, title: str) -> None:
    """A node-link view where one is still a picture; a matrix where it is not."""

    heavy = [item for item in species if item["id"] != ELECTRON]
    if len(heavy) > READABLE:
        interaction_matrix(species, reactions, out, title)
        return

    index = {item["id"]: item for item in heavy}
    graph = nx.DiGraph()
    for item in heavy:
        graph.add_node(item["id"])
    for reaction in reactions:
        left = [t["species"] for t in reaction["reactants"] if t["species"] != ELECTRON]
        right = [t["species"] for t in reaction["products"] if t["species"] != ELECTRON]
        for source in left:
            for target in right:
                if source != target and graph.has_node(source) and graph.has_node(target):
                    graph.add_edge(source, target, family=reaction.get("family", "?"))
    if not graph.number_of_nodes():
        return

    layout = nx.kamada_kawai_layout(graph) if graph.number_of_edges() else nx.circular_layout(graph)
    figure, axes = plt.subplots(figsize=(11, 8.5))
    families = [d["family"] for _, _, d in graph.edges(data=True)]
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[FAMILY.get(name, "#B9BEC9") for name in families],
        width=0.8,
        alpha=0.4,
        arrowsize=8,
        connectionstyle="arc3,rad=0.1",
        node_size=700,
    )
    _nodes(graph, layout, axes, index)
    handles = [
        plt.Line2D([], [], color=colour, lw=2, label=name)
        for name, colour in FAMILY.items()
        if name in set(families)
    ]
    handles += [
        plt.Line2D([], [], marker="o", ls="", color=colour, label=name, markersize=8)
        for name, colour in CHARGE_NAME.items()
    ]
    axes.legend(handles=handles, fontsize=7, frameon=False, loc="upper left", ncol=2)
    axes.set_title(f"{title}   every reaction", fontsize=11, color=INK, loc="left")
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# --------------------------------------------------------------------------- sheet


def bars(axes, counts: Counter, title: str, colours: dict | None = None) -> None:
    if not counts:
        frame(axes, f"{title} — none")
        axes.axis("off")
        return
    pairs = counts.most_common(12)
    labels = [str(key) for key, _ in pairs]
    values = [value for _, value in pairs]
    axes.barh(labels, values, color=[(colours or {}).get(n, "#4FA3A5") for n in labels], height=0.7)
    axes.invert_yaxis()
    for row, value in enumerate(values):
        axes.text(value, row, f" {value}", va="center", fontsize=7, color=MUTED)
    frame(axes, title)


def stacked(axes, rows: dict[str, Counter], colours: dict, title: str) -> None:
    if not rows:
        frame(axes, f"{title} — none")
        axes.axis("off")
        return
    names = list(rows)
    bottom = [0.0] * len(names)
    for key in sorted({k for row in rows.values() for k in row}):
        heights = [rows[name].get(key, 0) for name in names]
        axes.barh(
            names,
            heights,
            left=bottom,
            color=colours.get(key, "#B9BEC9"),
            label=str(key),
            height=0.7,
        )
        bottom = [b + h for b, h in zip(bottom, heights, strict=False)]
    axes.invert_yaxis()
    axes.legend(fontsize=6, frameon=False)
    frame(axes, title)


def _lacking_properties(species: list[dict]) -> Counter:
    counts: Counter = Counter()
    for item in species:
        for name, prop in (item.get("properties") or {}).items():
            if prop.get("value") is None:
                counts[name] += 1
    return counts


def _reactivity(reactions: list[dict]) -> Counter:
    """How often each heavy species is struck. Hubs carry the mechanism."""

    counts: Counter = Counter()
    for reaction in reactions:
        for term in reaction["reactants"]:
            if term["species"] != ELECTRON:
                counts[term["species"]] += 1
    return counts


def _readiness(bundle: Path) -> Counter:
    counts: Counter = Counter()
    for pair in read(bundle / "datasets" / "dnt", "index.yaml", "pairs"):
        for tier in pair.get("runnable") or ["blocked"]:
            counts[tier] += 1
    return counts


def single(out: Path, title: str, draw) -> None:
    """One chart, one file. The sheet is for scanning; a file is for citing."""

    figure, axes = plt.subplots(figsize=(6.4, 4.2))
    draw(axes)
    figure.suptitle(title, fontsize=10, color=INK, x=0.01, ha="left")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def charts(
    bundle: Path,
    species: list[dict],
    reactions: list[dict],
    gaps: list[dict],
    out: Path,
    title: str,
) -> None:
    """The nine panels again, each as its own file.

    The sheet answers "how does this list divide" at a glance; a separate file
    is what goes into a report or a review comment, which is why both exist.
    """

    out.mkdir(parents=True, exist_ok=True)
    heavy = [item for item in species if item["id"] != ELECTRON]

    by_family: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        by_family[reaction.get("family", "?")][reaction.get("status", "?")] += 1
    by_depth: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        by_depth[f"depth {reaction.get('depth', 0)}"][reaction.get("family", "?")] += 1
    layered: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        for layer, verdict in (reaction.get("evidence") or {}).items():
            layered[layer][str(verdict).split(" by ")[0]] += 1

    panels = {
        "reaction_family_counts": lambda ax: stacked(
            ax, dict(by_family), STATUS, "reactions by family and status"
        ),
        "reaction_type_counts": lambda ax: bars(
            ax, Counter(r.get("type", "?") for r in reactions), "process"
        ),
        "reaction_depth_by_family": lambda ax: stacked(
            ax, dict(sorted(by_depth.items())), FAMILY, "where the chemistry appears"
        ),
        "species_charge_counts": lambda ax: bars(
            ax,
            Counter(charge_name(item.get("charge", 0)) for item in heavy),
            "species by charge",
            CHARGE_NAME,
        ),
        "missing_property_counts": lambda ax: bars(
            ax, _lacking_properties(species), "properties nobody has yet"
        ),
        "evidence_by_layer": lambda ax: stacked(ax, dict(layered), VERDICT, "evidence by layer"),
        "species_reactivity": lambda ax: bars(
            ax, _reactivity(reactions), "species that react the most"
        ),
        "missing_data_counts": lambda ax: bars(
            ax,
            Counter(f"{gap['severity']}: {gap['kind']}" for gap in gaps),
            "what the list still lacks",
        ),
        "dnt_readiness_counts": lambda ax: bars(ax, _readiness(bundle), "DNT+ readiness by tier"),
    }
    for name, draw in panels.items():
        single(out / f"{name}.svg", title, draw)


def statistics(
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
    bars(b, Counter(r.get("type", "?") for r in reactions), "process")

    by_depth: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        by_depth[f"depth {reaction.get('depth', 0)}"][reaction.get("family", "?")] += 1
    stacked(c, dict(sorted(by_depth.items())), FAMILY, "where the chemistry appears")

    bars(
        d,
        Counter(charge_name(item.get("charge", 0)) for item in species if item["id"] != ELECTRON),
        "species by charge",
        CHARGE_NAME,
    )

    bars(e, _lacking_properties(species), "properties nobody has yet")

    layered: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        for layer, verdict in (reaction.get("evidence") or {}).items():
            layered[layer][str(verdict).split(" by ")[0]] += 1
    stacked(f, dict(layered), {}, "evidence by layer")

    bars(g, _reactivity(reactions), "species that react the most")
    bars(h, Counter(f"{gap['severity']}: {gap['kind']}" for gap in gaps), "what the list lacks")

    bars(i, _readiness(bundle), "DNT+ readiness by tier")

    figure.suptitle(title, fontsize=12, color=INK, x=0.01, ha="left")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# --------------------------------------------------------------------------- per layer


QUESTIONS = {
    "structure": "can these species exist, and does the equation balance?",
    "thermochemistry": "do the energetics leave the channel open?",
    "kinetics": "does it run fast enough to matter under these conditions?",
    "attestation": "does any source state this reaction?",
}


def _enthalpy(axes, reactions: list[dict]) -> None:
    values = [r["delta_e_eV"] for r in reactions if r.get("delta_e_eV") is not None]
    if not values:
        frame(axes, "reaction enthalpy — none computed")
        axes.axis("off")
        return
    axes.hist(values, bins=32, color="#4FA3A5", edgecolor="white", linewidth=0.4)
    axes.axvline(0, color=LACKING, lw=1.2)
    axes.text(0, axes.get_ylim()[1] * 0.95, "  thermoneutral", fontsize=8, color=LACKING, va="top")
    axes.set_xlabel("ΔH [eV]   negative is downhill", fontsize=9, color=MUTED)
    frame(axes, "reaction enthalpy", f"{len(values)} of {len(reactions)} could be computed")


def _accessibility(axes, reactions: list[dict], conditions: dict) -> None:
    values = [r["threshold_eV"] for r in reactions if r.get("threshold_eV") is not None]
    if not values:
        frame(axes, "threshold — none recorded")
        axes.axis("off")
        return
    axes.hist(values, bins=32, color="#2E6E8E", edgecolor="white", linewidth=0.4)
    temperature = (conditions or {}).get("electron_temperature_eV")
    if temperature:
        top = axes.get_ylim()[1]
        axes.axvline(temperature, color=LACKING, lw=1.2, ls="--")
        axes.axvline(3 * temperature, color=LACKING, lw=0.8, ls=":")
        axes.text(temperature, top * 0.95, "  Te", fontsize=8, color=LACKING, va="top")
        axes.text(3 * temperature, top * 0.80, "  3 Te", fontsize=8, color=LACKING, va="top")
    axes.set_xlabel("threshold [eV]", fontsize=9, color=MUTED)
    frame(axes, "what the electrons can reach", f"{len(values)} of {len(reactions)} have an onset")


def _proposed_by_depth(axes, species: list[dict]) -> None:
    rows: dict[str, Counter] = defaultdict(Counter)
    for item in species:
        if item["id"] != ELECTRON:
            rows[f"depth {item.get('depth', 0)}"][charge_name(item.get("charge", 0))] += 1
    stacked(
        axes, dict(sorted(rows.items())), CHARGE_NAME, "species introduced, by depth and charge"
    )


def _attested_by_family(axes, reactions: list[dict]) -> None:
    rows: dict[str, Counter] = defaultdict(Counter)
    for reaction in reactions:
        verdict = str((reaction.get("evidence") or {}).get("attestation", "not_run"))
        key = verdict if verdict in {"unattested", "not_run"} else "attested"
        rows[reaction.get("family", "?")][key] += 1
    stacked(
        axes,
        dict(rows),
        {"attested": "#1B3A5C", "unattested": "#C9A0A0", "not_run": "#DDE1E8"},
        "who is stated by a source, by family",
    )


def layer_figure(
    layer: str,
    reactions: list[dict],
    species: list[dict],
    conditions: dict,
    out: Path,
    title: str,
    tally: dict | None = None,
) -> None:
    """The verdict, and the quantity the verdict was made on.

    A count of verdicts says how many fell each side of a line. What a reviewer
    asks is where the line falls and how much sits near it, which is a
    distribution, so each layer draws the quantity behind its own answer.
    """

    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 4.8))
    verdicts = Counter(
        str((r.get("evidence") or {}).get(layer, "not_run")).split(" by ")[0] for r in reactions
    )
    counted = tally or {}
    head = (
        f"judged {counted.get('judged', 0)} / undecided {counted.get('undecided', 0)}"
        f" / not run {counted.get('not_run', 0)}   of {len(reactions)}"
    )
    bars(left, verdicts, "verdict", VERDICT)
    left.text(0, 1.02, head, transform=left.transAxes, fontsize=8, color=MUTED, va="bottom")

    if layer == "thermochemistry":
        _enthalpy(right, reactions)
    elif layer == "kinetics":
        _accessibility(right, reactions, conditions)
    elif layer == "structure":
        _proposed_by_depth(right, species)
    else:
        _attested_by_family(right, reactions)

    figure.suptitle(
        f"{title}   {layer} — {QUESTIONS[layer]}", fontsize=11, color=INK, x=0.01, ha="left"
    )
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def _layer_network(
    species: list[dict],
    reactions: list[dict],
    verdicts: dict[str, str],
    out: Path,
    title: str,
    layer: str,
) -> None:
    """The network with every edge coloured by what this one layer said.

    Undecided edges are drawn thin and grey so the decided ones carry the eye:
    what a layer answers is which part of the mechanism it settled, and a
    uniformly drawn graph cannot show that.
    """

    index = {item["id"]: item for item in species if item["id"] != ELECTRON}
    graph = nx.DiGraph()
    for name in index:
        graph.add_node(name)
    for reaction in reactions:
        verdict = verdicts.get(reaction["id"], "not_run").split(" by ")[0]
        left = [t["species"] for t in reaction["reactants"] if t["species"] != ELECTRON]
        right = [t["species"] for t in reaction["products"] if t["species"] != ELECTRON]
        for source in left:
            for target in right:
                if source != target and graph.has_node(source) and graph.has_node(target):
                    graph.add_edge(source, target, verdict=verdict)
    if not graph.number_of_edges():
        return
    if len(index) > READABLE:
        _verdict_matrix(index, graph, out, title, layer)
        return

    layout = nx.kamada_kawai_layout(graph)
    figure, axes = plt.subplots(figsize=(11, 8.5))
    seen = [d["verdict"] for _, _, d in graph.edges(data=True)]
    faint = UNDECIDED | {"not_run"}
    nx.draw_networkx_edges(
        graph,
        layout,
        ax=axes,
        edge_color=[VERDICT.get(name, GREY) for name in seen],
        width=[0.6 if name in faint else 1.5 for name in seen],
        alpha=0.8,
        arrowsize=9,
        connectionstyle="arc3,rad=0.1",
        node_size=700,
    )
    _nodes(graph, layout, axes, index)
    axes.legend(
        handles=[
            plt.Line2D([], [], color=VERDICT.get(name, GREY), lw=2.5, label=name)
            for name in sorted(set(seen))
        ],
        fontsize=8,
        frameon=False,
        loc="upper left",
    )
    axes.set_title(f"{title}   {layer} across the network", fontsize=11, color=INK, loc="left")
    axes.axis("off")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


def _verdict_matrix(index: dict, graph, out: Path, title: str, layer: str) -> None:
    """Which pairs this layer decided, where a node-link view is unreadable."""

    names = sorted(index)
    place = {name: position for position, name in enumerate(names)}
    order = [key for key in VERDICT if key != "not_run"]
    grid = np.full((len(names), len(names)), np.nan)
    for source, target, data in graph.edges(data=True):
        verdict = data["verdict"]
        if verdict in order:
            grid[place[source], place[target]] = order.index(verdict)
    size = max(7.0, 0.19 * len(names) + 3)
    figure, axes = plt.subplots(figsize=(size, size))
    shown = axes.imshow(grid, cmap="cividis", interpolation="nearest", vmin=0, vmax=len(order) - 1)
    axes.set_xticks(range(len(names)))
    axes.set_yticks(range(len(names)))
    axes.set_xticklabels(names, rotation=90, fontsize=5.5)
    axes.set_yticklabels(names, fontsize=5.5)
    axes.set_xlabel("product", fontsize=9, color=INK)
    axes.set_ylabel("reactant", fontsize=9, color=INK)
    bar = figure.colorbar(shown, ax=axes, shrink=0.6, ticks=range(len(order)))
    bar.ax.set_yticklabels(order, fontsize=7)
    axes.set_title(f"{title}   {layer} per pair", fontsize=11, color=INK, loc="left")
    figure.tight_layout()
    figure.savefig(out, format="svg", bbox_inches="tight")
    plt.close(figure)


# What each layer needs of a species before it can decide anything about it.
NEEDS = {
    "structure": ("mass_amu",),
    "thermochemistry": ("enthalpy_formation_eV", "ionization_energy_eV"),
    "kinetics": ("mass_amu", "polarizability_A3"),
    "attestation": (),
}


def _species_rows(layer: str, species: list[dict], reactions: list[dict]) -> list[str]:
    """The state list, with what this layer can say about each species.

    A layer is not only a verdict on reactions. Thermochemistry cannot decide a
    channel whose species carry no formation enthalpy, so the state list says
    which of them do — that is where a reviewer looks to see what unblocks the
    layer next.
    """

    touched: Counter = Counter()
    for reaction in reactions:
        for term in reaction["reactants"] + reaction["products"]:
            touched[term["species"]] += 1

    rows = ["id,charge,depth,status,reactions,ready,missing"]
    for item in sorted(species, key=lambda entry: entry["id"]):
        properties = item.get("properties") or {}
        missing = [
            name
            for name in NEEDS.get(layer, ())
            if (properties.get(name) or {}).get("value") is None
        ]
        rows.append(
            ",".join(
                str(field)
                for field in (
                    item["id"],
                    item.get("charge", 0),
                    item.get("depth", 0),
                    item.get("status", ""),
                    touched.get(item["id"], 0),
                    "no" if missing else "yes",
                    "|".join(missing),
                )
            )
        )
    return rows


def _passed(rows: list[str]) -> list[str]:
    """The header, and the rows whose flag says the layer settled it.

    Parsed as CSV rather than split on commas: a verdict like "conserved,
    species proposed" is one quoted field, and counting columns by comma put
    four hundred and forty-six settled reactions at thirty-one.
    """

    header = next(csv.reader([rows[0]]))
    flag = "decided" if "decided" in header else "ready"
    position = header.index(flag)
    kept = [row for row in rows[1:] if next(csv.reader([row]))[position] == "yes"]
    return [rows[0], *kept]


def _tally(verdicts: dict[str, str]) -> dict:
    """Decided, undecided, never asked. A count of verdicts hides the middle."""

    kinds = Counter(value.split(" by ")[0] for value in verdicts.values())
    return {
        "judged": sum(n for k, n in kinds.items() if k not in UNDECIDED and k != "not_run"),
        "undecided": sum(kinds[k] for k in UNDECIDED if k in kinds),
        "not_run": kinds.get("not_run", 0),
        "by_verdict": dict(kinds.most_common()),
    }


def per_layer(
    species: list[dict], reactions: list[dict], conditions: dict, out: Path, title: str
) -> list[str]:
    """One directory per layer: the whole list with that layer's answer attached."""

    names = sorted({layer for r in reactions for layer in (r.get("evidence") or {})})
    heavy = [item for item in species if item["id"] != ELECTRON]
    for layer in names:
        target = out / layer
        target.mkdir(parents=True, exist_ok=True)
        verdicts = {
            r["id"]: str((r.get("evidence") or {}).get(layer, "not_run")) for r in reactions
        }
        tally = _tally(verdicts)

        rows = ["id,equation,family,type,depth,status,verdict,decided"]
        for reaction in reactions:
            verdict = verdicts[reaction["id"]]
            kind = verdict.split(" by ")[0]
            fields = [
                reaction["id"],
                reaction["equation"],
                reaction.get("family", ""),
                reaction.get("type", ""),
                reaction.get("depth", 0),
                reaction.get("status", ""),
                verdict,
                "no" if kind in UNDECIDED or kind == "not_run" else "yes",
            ]
            rows.append(",".join(f'"{f}"' if "," in str(f) else str(f) for f in fields))
        (target / "reactions.csv").write_text(NEWLINE.join(rows) + NEWLINE, encoding="utf-8")
        # The subset the layer actually settled, so it can be handed on without
        # anyone re-deriving which rows those were.
        (target / "reactions_passed.csv").write_text(
            NEWLINE.join(_passed(rows)) + NEWLINE, encoding="utf-8"
        )
        state = _species_rows(layer, heavy, reactions)
        (target / "species.csv").write_text(NEWLINE.join(state) + NEWLINE, encoding="utf-8")
        (target / "species_passed.csv").write_text(
            NEWLINE.join(_passed(state)) + NEWLINE, encoding="utf-8"
        )

        blocked = [
            item["id"]
            for item in heavy
            if any(
                (item.get("properties") or {}).get(name, {}).get("value") is None
                for name in NEEDS.get(layer, ())
            )
        ]
        (target / "summary.yaml").write_text(
            yaml.safe_dump(
                {
                    "layer": layer,
                    "question": QUESTIONS[layer],
                    "reactions": {"total": len(reactions), **tally},
                    "species": {
                        "total": len(heavy),
                        "needs": list(NEEDS.get(layer, ())),
                        "blocked_by_missing_property": len(blocked),
                    },
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        layer_figure(layer, reactions, heavy, conditions, target / "verdict.svg", title, tally)
        _layer_network(species, reactions, verdicts, target / "network.svg", title, layer)

        # The same pathway view, restricted to what this layer settled: the
        # part of the mechanism it can stand behind, followed left to right.
        settled = [
            reaction
            for reaction in reactions
            if verdicts[reaction["id"]].split(" by ")[0] not in UNDECIDED | {"not_run"}
        ]
        if settled:
            taking_part = {
                term["species"]
                for reaction in settled
                for term in reaction["reactants"] + reaction["products"]
            }
            pathway(
                [item for item in heavy if item["id"] in taking_part],
                settled,
                target / "pathway.svg",
                f"{title}   {layer} — settled only",
            )
    return names


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tools/visualize.py <bundle> [<bundle> ...]")
        return 2
    for name in argv:
        bundle = Path(name)
        species = read(bundle, "species.yaml", "species")
        reactions = read(bundle, "reactions.yaml", "reactions")
        gaps = read(bundle, "gaps.yaml", "gaps")
        summary = yaml.safe_load((bundle / "summary.yaml").read_text(encoding="utf-8")) or {}
        conditions = summary.get("conditions") or {}

        target = bundle / "visualizations"
        target.mkdir(parents=True, exist_ok=True)
        label = f"{bundle.parent.name} / {bundle.name}"
        energy_landscape(reactions, conditions, target / "energy_landscape.svg", label)
        fragmentation(species, reactions, target / "fragmentation.svg", label)
        pathway(species, reactions, target / "pathway.svg", label)
        reaction_network(species, reactions, target / "reaction_network.svg", label)
        statistics(bundle, species, reactions, gaps, target / "statistics.svg", label)
        charts(bundle, species, reactions, gaps, target / "charts", label)
        named = per_layer(species, reactions, conditions, bundle / "layers", label)
        print(f"  {label:26} {len(species):3d} species {len(reactions):5d} reactions  {named}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
