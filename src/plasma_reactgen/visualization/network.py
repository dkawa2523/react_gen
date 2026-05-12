from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any

from plasma_reactgen.visualization.models import VisualizationDataset


@dataclass(frozen=True)
class GraphvizOptions:
    """Options for Graphviz reaction-network rendering."""

    include_self_loops: bool = False
    include_non_expanding: bool = False
    max_reactions: int | None = 250
    render_formats: tuple[str, ...] = ("svg", "png")


def write_reaction_network_graphviz(
    dataset: VisualizationDataset,
    output_dir: str | Path,
    *,
    options: GraphvizOptions | None = None,
) -> dict[str, str | bool | list[str]]:
    """Write a state-node reaction network as Graphviz DOT and rendered files.

    Nodes are chemical/electronic states. Edges are reaction transitions labeled
    by collision family, reaction type, depth and reaction id. For multi-product
    reactions, a labeled edge is emitted from each non-electron reactant to each
    non-electron product. This is intentionally a readable overview rather than
    a strict hypergraph representation.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    options = options or GraphvizOptions()

    dot_path = output_dir / "reaction_network.dot"
    dot = build_reaction_network_dot(dataset, options=options)
    dot_path.write_text(dot, encoding="utf-8")

    rendered: list[str] = []
    dot_available = shutil.which("dot") is not None
    if dot_available:
        for fmt in options.render_formats:
            out = output_dir / f"reaction_network.{fmt}"
            subprocess.run(
                ["dot", f"-T{fmt}", str(dot_path), "-o", str(out)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rendered.append(str(out))

    return {
        "dot": str(dot_path),
        "rendered": rendered,
        "graphviz_dot_available": dot_available,
    }




def write_species_lineage_graphviz(
    dataset: VisualizationDataset,
    output_dir: str | Path,
    *,
    options: GraphvizOptions | None = None,
) -> dict[str, str | bool | list[str]]:
    """Write a compact Graphviz graph focused on species introduction paths.

    Unlike the full network, this graph only draws edges into species listed in
    ``introduced_species`` for each reaction. It is usually easier to read when
    the user wants to understand how the generated state list expanded from the
    input gases.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    options = options or GraphvizOptions()

    dot_path = output_dir / "species_lineage.dot"
    dot = build_species_lineage_dot(dataset, options=options)
    dot_path.write_text(dot, encoding="utf-8")

    rendered: list[str] = []
    dot_available = shutil.which("dot") is not None
    if dot_available:
        for fmt in options.render_formats:
            out = output_dir / f"species_lineage.{fmt}"
            subprocess.run(
                ["dot", f"-T{fmt}", str(dot_path), "-o", str(out)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rendered.append(str(out))

    return {
        "dot": str(dot_path),
        "rendered": rendered,
        "graphviz_dot_available": dot_available,
    }


def build_species_lineage_dot(dataset: VisualizationDataset, *, options: GraphvizOptions) -> str:
    states_by_id = {str(s.get("id")): s for s in dataset.states}
    node_ids = set(states_by_id)
    edges: list[tuple[str, str, dict[str, str]]] = []

    considered = 0
    for reaction in dataset.reactions:
        if options.max_reactions is not None and considered >= options.max_reactions:
            break

        introduced = {str(x) for x in reaction.get("introduced_species", []) if str(x) != "e"}
        if not introduced:
            continue

        reactants = _non_electron_amounts(reaction.get("reactants", []))
        products = _non_electron_amounts(reaction.get("products", []))
        mapped = _mapped_species_edges(
            reaction=reaction,
            reactants=reactants,
            products=products,
            states_by_id=states_by_id,
        )

        label = _edge_label(reaction)
        attrs = {
            "label": label,
            "color": _edge_color(str(reaction.get("family", "unknown"))),
            "fontcolor": _edge_color(str(reaction.get("family", "unknown"))),
            "style": _edge_style(str(reaction.get("family", "unknown"))),
            "tooltip": str(reaction.get("equation") or reaction.get("id") or ""),
            "penwidth": "1.8",
        }

        added = 0
        for src, dst in mapped:
            if dst not in introduced:
                continue
            if src == dst and not options.include_self_loops:
                continue
            node_ids.add(src)
            node_ids.add(dst)
            edges.append((src, dst, attrs))
            added += 1

        if added:
            considered += 1

    case_name = str(dataset.case.get("name", "case"))
    lines: list[str] = []
    lines.append("digraph species_lineage {")
    lines.append("  graph [")
    lines.append("    rankdir=LR,")
    lines.append("    overlap=false,")
    lines.append("    splines=true,")
    lines.append(f"    label={_q('Species lineage: ' + case_name)},")
    lines.append("    labelloc=t,")
    lines.append("    fontsize=22,")
    lines.append("    fontname=\"Arial\"")
    lines.append("  ];")
    lines.append("  node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", fontsize=11, margin=0.08];")
    lines.append("  edge [fontname=\"Arial\", fontsize=9, arrowsize=0.8];")
    lines.append("")
    lines.extend(_legend_lines())
    lines.append("")
    for species_id in sorted(node_ids, key=_node_sort_key):
        state = states_by_id.get(species_id, {"id": species_id})
        lines.append(f"  {_node_name(species_id)} [{_attrs(_node_attrs(state))}];")
    lines.append("")
    for src, dst, attrs in edges:
        lines.append(f"  {_node_name(src)} -> {_node_name(dst)} [{_attrs(attrs)}];")
    lines.append("}")
    return "\n".join(lines) + "\n"

def build_reaction_network_dot(dataset: VisualizationDataset, *, options: GraphvizOptions) -> str:
    states_by_id = {str(s.get("id")): s for s in dataset.states}
    node_ids = set(states_by_id)

    edges: list[tuple[str, str, dict[str, str]]] = []
    considered = 0
    for reaction in dataset.reactions:
        if options.max_reactions is not None and considered >= options.max_reactions:
            break

        reactants = _non_electron_amounts(reaction.get("reactants", []))
        products = _non_electron_amounts(reaction.get("products", []))
        if not reactants or not products:
            continue

        if not options.include_non_expanding and not _reaction_changes_species(reactants, products):
            continue

        label = _edge_label(reaction)
        color = _edge_color(str(reaction.get("family", "unknown")))
        style = _edge_style(str(reaction.get("family", "unknown")))
        tooltip = str(reaction.get("equation") or reaction.get("id") or "")

        reaction_edges = 0
        for src, dst in _mapped_species_edges(
            reaction=reaction,
            reactants=reactants,
            products=products,
            states_by_id=states_by_id,
        ):
            if src == dst and not options.include_self_loops:
                continue
            node_ids.add(src)
            node_ids.add(dst)
            edges.append(
                (
                    src,
                    dst,
                    {
                        "label": label,
                        "color": color,
                        "fontcolor": color,
                        "style": style,
                        "tooltip": tooltip,
                    },
                )
            )
            reaction_edges += 1

        if reaction_edges:
            considered += 1

    case_name = str(dataset.case.get("name", "case"))
    lines: list[str] = []
    lines.append("digraph reaction_network {")
    lines.append("  graph [")
    lines.append("    rankdir=LR,")
    lines.append("    overlap=false,")
    lines.append("    splines=true,")
    lines.append("    concentrate=false,")
    lines.append(f"    label={_q('Reaction network: ' + case_name)},")
    lines.append("    labelloc=t,")
    lines.append("    fontsize=22,")
    lines.append("    fontname=\"Arial\"")
    lines.append("  ];")
    lines.append("  node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", fontsize=11, margin=0.08];")
    lines.append("  edge [fontname=\"Arial\", fontsize=9, arrowsize=0.7];")
    lines.append("")
    lines.extend(_legend_lines())
    lines.append("")

    for species_id in sorted(node_ids, key=_node_sort_key):
        state = states_by_id.get(species_id, {"id": species_id})
        attrs = _node_attrs(state)
        lines.append(f"  {_node_name(species_id)} [{_attrs(attrs)}];")

    lines.append("")
    for src, dst, attrs in edges:
        lines.append(f"  {_node_name(src)} -> {_node_name(dst)} [{_attrs(attrs)}];")

    lines.append("}")
    return "\n".join(lines) + "\n"


def _non_electron_amounts(amounts: list[dict[str, Any]]) -> list[str]:
    species: list[str] = []
    for amount in amounts or []:
        sid = str(amount.get("species", ""))
        if sid and sid != "e":
            species.append(sid)
    return species


def _reaction_changes_species(reactants: list[str], products: list[str]) -> bool:
    return sorted(reactants) != sorted(products)




def _mapped_species_edges(
    *,
    reaction: dict[str, Any],
    reactants: list[str],
    products: list[str],
    states_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    """Map a multi-reactant/multi-product reaction to readable species edges.

    The generated network is a species graph, not a hypergraph. To keep the
    result interpretable, electron reactions are drawn from the electron target
    to products. Ion-neutral reactions are mapped using simple composition
    matching so, for example, ``Ar+ + CF4 -> Ar + CF3+ + F`` becomes
    ``Ar+ -> Ar`` and ``CF4 -> CF3+ / F`` rather than a full Cartesian product.
    """

    family = str(reaction.get("family", "unknown"))

    if family == "electron":
        source = reactants[-1] if reactants else None
        return [(source, product) for product in products if source and product != source]

    if family == "ion_neutral" and len(reactants) >= 2:
        projectile, target = reactants[0], reactants[1]
        mapped: list[tuple[str, str]] = []
        for product in products:
            source = _best_source_for_product(projectile, target, product, states_by_id)
            mapped.append((source, product))
        return mapped

    return [(src, dst) for src in reactants for dst in products]


def _best_source_for_product(
    projectile: str,
    target: str,
    product: str,
    states_by_id: dict[str, dict[str, Any]],
) -> str:
    product_comp = _composition(product, states_by_id)
    projectile_comp = _composition(projectile, states_by_id)
    target_comp = _composition(target, states_by_id)

    if product_comp and projectile_comp == product_comp and product == _neutral_or_same(projectile):
        return projectile

    if product_comp and _contains_composition(target_comp, product_comp):
        return target

    if product_comp and _contains_composition(projectile_comp, product_comp):
        return projectile

    return target


def _neutral_or_same(species_id: str) -> str:
    if species_id.endswith("+") or species_id.endswith("-"):
        return species_id[:-1]
    return species_id


def _composition(species_id: str, states_by_id: dict[str, dict[str, Any]]) -> dict[str, float]:
    comp = states_by_id.get(species_id, {}).get("composition", {}) or {}
    return {str(k): float(v) for k, v in comp.items()}


def _contains_composition(source: dict[str, float], product: dict[str, float]) -> bool:
    if not source or not product:
        return False
    for elem, count in product.items():
        if source.get(elem, 0.0) + 1e-12 < count:
            return False
    return True

def _edge_label(reaction: dict[str, Any]) -> str:
    family = str(reaction.get("family", "unknown"))
    prefix = "e" if family == "electron" else "ion" if family == "ion_neutral" else family
    rtype = str(reaction.get("type", "unknown"))
    depth = reaction.get("depth", "?")
    rid = str(reaction.get("id", ""))
    return f"{prefix}: {rtype}\nD{depth} | {rid}"


def _edge_color(family: str) -> str:
    return {
        "electron": "#2F6DB3",
        "ion_neutral": "#B23B3B",
    }.get(family, "#555555")


def _edge_style(family: str) -> str:
    return {
        "electron": "dashed",
        "ion_neutral": "solid",
    }.get(family, "solid")




def _legend_lines() -> list[str]:
    return [
        "  subgraph cluster_legend {",
        "    label=\"Legend\";",
        "    fontsize=12;",
        "    color=\"#DDDDDD\";",
        "    legend_neutral [label=\"neutral / input gas\", fillcolor=\"#E8F5E9\", color=\"#666666\"];",
        "    legend_positive [label=\"positive ion\", fillcolor=\"#E3F2FD\", color=\"#666666\"];",
        "    legend_negative [label=\"negative ion\", fillcolor=\"#FFF8E1\", color=\"#666666\"];",
        "    legend_missing [label=\"missing property\", fillcolor=\"#F7F7F7\", color=\"#D62728\", penwidth=\"2.0\"];",
        "    legend_e_a [label=\"electron reaction\", shape=plain];",
        "    legend_e_b [label=\"dashed blue edge\", shape=plain];",
        "    legend_i_a [label=\"ion-neutral reaction\", shape=plain];",
        "    legend_i_b [label=\"solid red edge\", shape=plain];",
        "    legend_e_a -> legend_e_b [color=\"#2F6DB3\", style=\"dashed\"];",
        "    legend_i_a -> legend_i_b [color=\"#B23B3B\", style=\"solid\"];",
        "  }",
    ]

def _node_attrs(state: dict[str, Any]) -> dict[str, str]:
    species_id = str(state.get("id", "unknown"))
    charge = state.get("charge", "?")
    depth = state.get("depth_first_seen", "?")
    classes = ",".join(str(x) for x in state.get("classes", [])[:3])
    missing = state.get("missing_properties", []) or []
    roles = state.get("roles", []) or []

    label_parts = [species_id, f"q={charge} | depth={depth}"]
    if classes:
        label_parts.append(classes)
    if missing:
        label_parts.append(f"missing={len(missing)}")

    return {
        "label": "\n".join(label_parts),
        "fillcolor": _node_fillcolor(charge, roles),
        "color": "#D62728" if missing else "#666666",
        "penwidth": "2.0" if missing else "1.0",
        "tooltip": _node_tooltip(state),
    }


def _node_fillcolor(charge: Any, roles: list[Any]) -> str:
    role_set = {str(r) for r in roles}
    if "input_gas" in role_set:
        return "#E8F5E9"
    try:
        q = int(charge)
    except (TypeError, ValueError):
        return "#F5F5F5"
    if q > 0:
        return "#E3F2FD"
    if q < 0:
        return "#FFF8E1"
    return "#F7F7F7"


def _node_tooltip(state: dict[str, Any]) -> str:
    parts = [str(state.get("id", "unknown"))]
    roles = state.get("roles", []) or []
    missing = state.get("missing_properties", []) or []
    if roles:
        parts.append("roles=" + ",".join(str(x) for x in roles))
    if missing:
        parts.append("missing=" + ",".join(str(x) for x in missing))
    return " | ".join(parts)


def _node_sort_key(species_id: str) -> tuple[int, str]:
    if species_id == "e":
        return (-1, species_id)
    if species_id.endswith("+"):
        return (1, species_id)
    if species_id.endswith("-"):
        return (2, species_id)
    return (0, species_id)


def _node_name(species_id: str) -> str:
    # DOT node identifiers are safer as quoted strings because species ids may
    # contain +, -, parentheses or state labels.
    return _q("node:" + species_id)


def _attrs(attrs: dict[str, str]) -> str:
    return ", ".join(f"{key}={_q(value)}" for key, value in attrs.items())


def _q(value: Any) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'
