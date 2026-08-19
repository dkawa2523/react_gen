"""Graphviz view of the network.

Writes DOT only. Rendering is left to whatever Graphviz the reader has, so this
package stays dependency-free and the file is diffable.

Species are shaded by the depth they first appear at, edges coloured by family,
and anything only proposed is dashed — so a reader sees at a glance which part
of the picture rests on a source and which does not.
"""

from __future__ import annotations

from pathlib import Path

from reactgen.model import ELECTRON, Network, Reaction

FAMILY_COLOR = {
    "electron": "#1f6f8b",
    "electron_ion": "#4a8fa8",
    "ion_neutral": "#b3651e",
    "ion_ion": "#8a4b9c",
    "neutral_neutral": "#3f7a4b",
    "three_body": "#6a7f2e",
    "unimolecular": "#7a7a7a",
    "surface": "#a8382a",
}
DEPTH_FILL = ["#f0f4f3", "#e3ecea", "#d6e4e1", "#c9dcd8", "#bcd4cf"]
CANDIDATE = "candidate"


def write(path: Path, network: Network, max_edges: int = 400) -> None:
    edges = _edges(network)
    lines = [
        "digraph reactions {",
        '  rankdir=LR; splines=true; overlap=false; bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=8, arrowsize=0.6];',
        *(_node(name, network) for name in sorted(network.species) if name != ELECTRON),
        *(_edge(*edge) for edge in edges[:max_edges]),
    ]
    if len(edges) > max_edges:
        lines.append(f'  label="showing {max_edges} of {len(edges)} edges"; labelloc=b;')
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _edges(network: Network) -> list[tuple[str, str, Reaction]]:
    """One edge per reactant-product pair that actually changes the species."""

    seen: set[tuple[str, str, str]] = set()
    edges = []
    for reaction in network.reactions:
        sources = [t.species for t in reaction.reactants if t.species != ELECTRON]
        targets = [t.species for t in reaction.products if t.species != ELECTRON]
        for source in sources:
            for target in targets:
                key = (source, target, reaction.family)
                if source != target and key not in seen:
                    seen.add(key)
                    edges.append((source, target, reaction))
    return edges


def _node(species_id: str, network: Network) -> str:
    depth = network.depth.get(species_id, 0)
    fill = DEPTH_FILL[min(depth, len(DEPTH_FILL) - 1)]
    species = network.species.get(species_id)
    shape = ', shape=box, style="rounded,filled,dashed"' if _proposed(species) else ""
    return f'  "{species_id}" [fillcolor="{fill}", label="{species_id}\ndepth {depth}"{shape}];'


def _edge(source: str, target: str, reaction: Reaction) -> str:
    color = FAMILY_COLOR.get(reaction.family, "#555555")
    style = ", style=dashed" if reaction.status == CANDIDATE or reaction.surface else ""
    return f'  "{source}" -> "{target}" [color="{color}", tooltip="{reaction.id}"{style}];'


def _proposed(species) -> bool:
    return species is not None and species.status == CANDIDATE
