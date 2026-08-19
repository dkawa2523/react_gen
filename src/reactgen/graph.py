"""Graphviz views of the network.

Writes DOT only. Rendering is left to whatever Graphviz the reader has, so this
package stays dependency-free and the file is diffable.

Two views, because they answer different questions. The reaction network draws
every reaction; the lineage keeps only the edge that first introduced each
species, which is the recursion the expansion actually walked and is
unreadable in the full graph.

A node carries what a reviewer checks it against — charge, the depth it first
appeared at, its classes, and how many properties it still lacks — and an edge
carries the process and the reaction id, with the whole equation in the
tooltip. Reading a species graph without those means going back to the YAML for
every arrow.
"""

from __future__ import annotations

from pathlib import Path

from reactgen.model import ELECTRON, Network, Reaction, Species

FAMILY = {
    "electron": ("#2F6DB3", "dashed"),
    "electron_ion": ("#4A8FA8", "dashed"),
    "ion_neutral": ("#B23B3B", "solid"),
    "ion_ion": ("#8A4B9C", "solid"),
    "neutral_neutral": ("#3F7A4B", "solid"),
    "three_body": ("#6A7F2E", "solid"),
    "unimolecular": ("#7A7A7A", "solid"),
    "surface": ("#A8382A", "bold"),
}
# Charge is what a reader sorts a plasma species list by, so it picks the fill.
CHARGE_FILL = {0: "#E8F5E9", 1: "#E3F2FD", -1: "#FFF8E1"}
PROPOSED_FILL = "#F7F7F7"
LACKING = "#D62728"
CANDIDATE = "candidate"
BREAK = "\\n"  # a line break inside a DOT label, not in the file


def write(path: Path, network: Network, max_edges: int = 400, lineage: bool = False) -> None:
    edges = _edges(network, lineage)
    title = "species lineage" if lineage else "reaction network"
    header = (
        f'  graph [rankdir=LR, splines=true, overlap=false, label="{title}", '
        'labelloc=t, fontsize=18, fontname="Helvetica", bgcolor="transparent"];'
    )
    nodes = (
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
        "fontsize=10, margin=0.08];"
    )
    lines = [
        "digraph reactions {",
        header,
        nodes,
        '  edge [fontname="Helvetica", fontsize=8, arrowsize=0.7];',
        *_legend(),
        *(_node(name, network) for name in sorted(network.species) if name != ELECTRON),
        *(_edge(*edge) for edge in edges[:max_edges]),
    ]
    if len(edges) > max_edges:
        lines.append(f'  labelloc=b; label="showing {max_edges} of {len(edges)} edges";')
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _legend() -> list[str]:
    return [
        "  subgraph cluster_legend {",
        '    label="legend"; fontsize=11; color="#DDDDDD";',
        '    l_n [label="neutral", fillcolor="#E8F5E9"];',
        '    l_p [label="positive ion", fillcolor="#E3F2FD"];',
        '    l_m [label="negative ion", fillcolor="#FFF8E1"];',
        '    l_c [label="proposed", fillcolor="#F7F7F7", style="rounded,filled,dashed"];',
        f'    l_x [label="missing property", fillcolor="#F7F7F7", '
        f'color="{LACKING}", penwidth=2.0];',
        "  }",
    ]


def _edges(network: Network, lineage: bool) -> list[tuple[str, str, Reaction]]:
    """One edge per reactant-product pair that changes the species.

    ``lineage`` keeps only the pair that first introduced a product, which is
    what makes the recursive expansion legible.
    """

    seen: set[tuple[str, str, str]] = set()
    introduced: set[str] = set()
    edges = []
    for reaction in sorted(network.reactions, key=lambda item: item.depth):
        sources = [t.species for t in reaction.reactants if t.species != ELECTRON]
        products = [t.species for t in reaction.products if t.species != ELECTRON]
        fresh = [name for name in products if name not in introduced]
        introduced.update(products)
        for source in sources:
            for target in fresh if lineage else products:
                key = (source, target, reaction.family)
                if source != target and key not in seen:
                    seen.add(key)
                    edges.append((source, target, reaction))
    return edges


def _node(species_id: str, network: Network) -> str:
    species = network.species.get(species_id)
    depth = network.depth.get(species_id, 0)
    charge = species.charge if species else 0
    proposed = species is not None and species.status == CANDIDATE
    lacking = _lacking(species)

    parts = [species_id, f"q={charge:+d} | depth={depth}"]
    if species is not None and species.classes:
        parts.append(",".join(sorted(species.classes)[:3]))
    if lacking:
        parts.append(f"missing={len(lacking)}")

    fill = PROPOSED_FILL if proposed else CHARGE_FILL.get(charge, "#F7F7F7")
    style = "rounded,filled,dashed" if proposed else "rounded,filled"
    border = LACKING if lacking else "#666666"
    width = 2.0 if lacking else 1.0
    tip = f"{species_id} | missing={','.join(lacking)}" if lacking else species_id
    return (
        f'  "{species_id}" [label="{BREAK.join(parts)}", fillcolor="{fill}", '
        f'style="{style}", color="{border}", penwidth={width}, tooltip="{tip}"];'
    )


def _lacking(species: Species | None) -> list[str]:
    if species is None:
        return []
    return sorted(name for name, item in species.properties.items() if item.value is None)


def _edge(source: str, target: str, reaction: Reaction) -> str:
    colour, style = FAMILY.get(reaction.family, ("#555555", "solid"))
    if reaction.status == CANDIDATE:
        style = "dotted"
    label = f"{reaction.type}{BREAK}d{reaction.depth} | {reaction.id}"
    return (
        f'  "{source}" -> "{target}" [label="{label}", color="{colour}", '
        f'fontcolor="{colour}", style="{style}", tooltip="{reaction.equation}"];'
    )
