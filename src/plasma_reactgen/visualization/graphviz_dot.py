from __future__ import annotations

from typing import Any, TypeAlias

GraphEdge: TypeAlias = tuple[str, str, dict[str, str]]


def render_species_graph(
    *,
    graph_name: str,
    title: str,
    states_by_id: dict[str, dict[str, Any]],
    node_ids: set[str],
    edges: list[GraphEdge],
    concentrate: bool | None = None,
    arrow_size: str = "0.8",
) -> str:
    lines = [f"digraph {graph_name} {{", "  graph ["]
    lines.extend(_graph_attributes(title, concentrate))
    lines.extend(
        [
            "  ];",
            (
                '  node [shape=box, style="rounded,filled", fontname="Arial", '
                "fontsize=11, margin=0.08];"
            ),
            f'  edge [fontname="Arial", fontsize=9, arrowsize={arrow_size}];',
            "",
            *_legend_lines(),
            "",
        ]
    )
    for species_id in sorted(node_ids, key=_node_sort_key):
        state = states_by_id.get(species_id, {"id": species_id})
        lines.append(f"  {_node_name(species_id)} [{_attrs(_node_attrs(state))}];")
    lines.append("")
    lines.extend(
        f"  {_node_name(source)} -> {_node_name(target)} [{_attrs(attributes)}];"
        for source, target, attributes in edges
    )
    lines.append("}")
    return "\n".join(lines) + "\n"


def reaction_edge_attributes(
    reaction: dict[str, Any],
    *,
    penwidth: str | None = None,
) -> dict[str, str]:
    family = str(reaction.get("family", "unknown"))
    color = _edge_color(family)
    attributes = {
        "label": _edge_label(reaction),
        "color": color,
        "fontcolor": color,
        "style": _edge_style(family),
        "tooltip": str(reaction.get("equation") or reaction.get("id") or ""),
    }
    if penwidth is not None:
        attributes["penwidth"] = penwidth
    return attributes


def _graph_attributes(title: str, concentrate: bool | None) -> list[str]:
    lines = [
        "    rankdir=LR,",
        "    overlap=false,",
        "    splines=true,",
    ]
    if concentrate is not None:
        lines.append(f"    concentrate={str(concentrate).lower()},")
    lines.extend(
        [
            f"    label={_quote(title)},",
            "    labelloc=t,",
            "    fontsize=22,",
            '    fontname="Arial"',
        ]
    )
    return lines


def _edge_label(reaction: dict[str, Any]) -> str:
    family = str(reaction.get("family", "unknown"))
    prefix = {"electron": "e", "ion_neutral": "ion"}.get(family, family)
    reaction_type = str(reaction.get("type", "unknown"))
    depth = reaction.get("depth", "?")
    reaction_id = str(reaction.get("id", ""))
    return f"{prefix}: {reaction_type}\nD{depth} | {reaction_id}"


def _edge_color(family: str) -> str:
    return {"electron": "#2F6DB3", "ion_neutral": "#B23B3B"}.get(
        family,
        "#555555",
    )


def _edge_style(family: str) -> str:
    return {"electron": "dashed", "ion_neutral": "solid"}.get(family, "solid")


def _legend_lines() -> list[str]:
    return [
        "  subgraph cluster_legend {",
        '    label="Legend";',
        "    fontsize=12;",
        '    color="#DDDDDD";',
        ('    legend_neutral [label="neutral / input gas", fillcolor="#E8F5E9", color="#666666"];'),
        ('    legend_positive [label="positive ion", fillcolor="#E3F2FD", color="#666666"];'),
        ('    legend_negative [label="negative ion", fillcolor="#FFF8E1", color="#666666"];'),
        (
            '    legend_missing [label="missing property", '
            'fillcolor="#F7F7F7", color="#D62728", penwidth="2.0"];'
        ),
        '    legend_e_a [label="electron reaction", shape=plain];',
        '    legend_e_b [label="dashed blue edge", shape=plain];',
        '    legend_i_a [label="ion-neutral reaction", shape=plain];',
        '    legend_i_b [label="solid red edge", shape=plain];',
        ('    legend_e_a -> legend_e_b [color="#2F6DB3", style="dashed"];'),
        ('    legend_i_a -> legend_i_b [color="#B23B3B", style="solid"];'),
        "  }",
    ]


def _node_attrs(state: dict[str, Any]) -> dict[str, str]:
    species_id = str(state.get("id", "unknown"))
    charge = state.get("charge", "?")
    depth = state.get("depth_first_seen", "?")
    classes = ",".join(str(item) for item in state.get("classes", [])[:3])
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
    if "input_gas" in {str(role) for role in roles}:
        return "#E8F5E9"
    try:
        value = int(charge)
    except (TypeError, ValueError):
        return "#F5F5F5"
    if value > 0:
        return "#E3F2FD"
    if value < 0:
        return "#FFF8E1"
    return "#F7F7F7"


def _node_tooltip(state: dict[str, Any]) -> str:
    parts = [str(state.get("id", "unknown"))]
    roles = state.get("roles", []) or []
    missing = state.get("missing_properties", []) or []
    if roles:
        parts.append("roles=" + ",".join(str(item) for item in roles))
    if missing:
        parts.append("missing=" + ",".join(str(item) for item in missing))
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
    return _quote("node:" + species_id)


def _attrs(attributes: dict[str, str]) -> str:
    return ", ".join(f"{key}={_quote(value)}" for key, value in attributes.items())


def _quote(value: Any) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'


__all__ = ["GraphEdge", "reaction_edge_attributes", "render_species_graph"]
