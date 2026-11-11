"""Render target-centred projections of the saved candidate pathway graph."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from reactgen.model import ELECTRON, THIRD_BODY, Term
from reactgen.pathway import (
    Pathway,
    ProducerPathway,
    Reachability,
    net_stoichiometry,
    pathway_participant_claims,
    pathway_participants,
    saved_pathway,
    saved_reachability,
)
from reactgen.presentation import diagram_terms
from reactgen.reaction_tables import energy_values

FAMILY_COLORS = {
    "electron": "#2F6B9A",
    "ion": "#C56A2D",
    "neutral": "#71884A",
    "surface": "#B05A7A",
}
INK = "#1F2933"
MUTED = "#64717D"
STATE_WIDTH = 194
REACTION_WIDTH = 214
COLUMN_GAP = 284
NodeKey = tuple[str, ...]


@dataclass(frozen=True)
class _Node:
    subject: str
    role: str
    level: int


@dataclass(frozen=True)
class _Edge:
    source: NodeKey
    target: NodeKey
    count: float


def pathway_png(
    *,
    case_name: str,
    view_label: str,
    states: list[dict],
    state_names: dict[str, str],
    reactions: list[dict],
    pathways: dict,
    exploration_status: str = "",
    exploration_complete: bool | None = None,
    target: str | None = None,
    mode: str = "conditioned",
    selected: ProducerPathway | None = None,
    skipped_requested_expansions: dict[str, dict] | None = None,
) -> bytes:
    """Render one readable example; the HTML remains the target-selectable view."""

    analysis = pathways
    scope = saved_reachability(analysis, mode)
    reachability = selected.reachability if selected else scope
    pathway = (
        selected.pathway
        if selected
        else saved_pathway(reactions, analysis, target=target, mode=mode)
    )
    state_by_id = {state["id"]: state for state in states}
    reaction_by_id = {reaction["id"]: reaction for reaction in reactions}
    path_reactions = [reaction_by_id[reaction_id] for reaction_id in pathway.reaction_ids]
    unresolved = analysis[mode]["unresolved"]
    open_reaction_checks = {
        reaction_id
        for reaction_id in pathway.reaction_ids
        if any("state" not in note for note in unresolved.get(reaction_id, ()))
    }
    participants = pathway_participants(pathway.state_ids, path_reactions)
    state_claims = pathway_participant_claims(states, participants)
    unconfirmed = {
        state_id: analysis["unconfirmed_states"][state_id]
        for state_id in sorted(participants & analysis["unconfirmed_states"].keys())
    }
    skipped = {
        reaction_id: skipped_requested_expansions[reaction_id]
        for reaction_id in pathway.reaction_ids
        if skipped_requested_expansions and reaction_id in skipped_requested_expansions
    }
    blocked = _blocked_direct_producers(
        reactions, state_by_id, target or pathway.target, scope, analysis[mode]["excluded"]
    )
    query_notes = {
        "unconfirmed_states": unconfirmed,
        "state_claims": state_claims,
        "skipped_requested_expansions": skipped,
        "blocked_direct_producers": blocked,
    }
    image = _render_pathway(
        pathway,
        path_reactions,
        reachability,
        state_by_id,
        state_names,
        conditions=analysis["conditions"],
        requested_target=target,
        case_name=case_name,
        scope=view_label,
        partial=exploration_complete is False,
        open_checks=open_reaction_checks,
    )
    return _save_png(
        image,
        case_name,
        view_label,
        pathway,
        reachability,
        analysis,
        mode,
        target,
        exploration_status,
        query_notes,
        selected=selected,
    )


_TOPOLOGY_NOTE = (
    "Directed stoichiometric sides. Links between reactions are selected supports; "
    "local supply and terminal product nodes do not track individual particles. "
    "Electron occurrences share a node within a reaction stage and side. "
    "Depth denotes AND reachability."
)


def _blocked_direct_producers(
    reactions: list[dict],
    state_by_id: dict[str, dict],
    target: str | None,
    reachability: Reachability,
    excluded: dict,
) -> dict[str, dict]:
    """Expose reasons for saved direct producers that cannot support the target."""
    blocked: dict[str, dict] = {}
    if target is None:
        return blocked
    for reaction in reactions:
        reaction_id = reaction["id"]
        if reaction_id in reachability.reaction_layers or net_stoichiometry(reaction, target) <= 0:
            continue
        if reaction_id in excluded:
            blocked[reaction_id] = {
                "excluded": [
                    _saved_exclusion_details(reaction, state_by_id, reference)
                    for reference in excluded[reaction_id]
                ]
            }
        else:
            blocked[reaction_id] = {
                "unreachable_reactants": sorted(
                    {
                        term["species"]
                        for term in reaction["reactants"]
                        if term["species"] not in reachability.state_layers
                    }
                )
            }
    return blocked


def _saved_exclusion_details(reaction: dict, state_by_id: dict[str, dict], reference: dict) -> dict:
    owner = state_by_id[reference["state"]] if "state" in reference else reaction
    claim = owner.get("assessments", {}).get(reference.get("assessment"), {})
    return reference | {name: claim[name] for name in ("verdict", "message") if name in claim}


def _pathway_layout(
    pathway: Pathway, reactions: list[dict], reachability: Reachability
) -> tuple[dict[NodeKey, _Node], list[_Edge]]:
    """Expand each selected event while sharing only the saved support links."""
    nodes: dict[NodeKey, _Node] = {
        ("state", state): _Node(
            state,
            "target" if state == pathway.target else "intermediate",
            3 * reachability.state_layers[state] - 1,
        )
        for state in pathway.supported_by
    }
    if pathway.target is not None and pathway.target in reachability.seeds:
        nodes[("state", pathway.target)] = _Node(pathway.target, "supplied_target", 0)
    edges: list[_Edge] = []
    for reaction in reactions:
        identifier = reaction["id"]
        reaction_key = ("reaction", identifier)
        level = 3 * reachability.reaction_layers[identifier] - 2
        nodes[reaction_key] = _Node(identifier, "reaction", level)
        for term in diagram_terms(reaction, "reactants"):
            key: NodeKey = ("state", term.species)
            if key not in nodes:
                key = _local_participant_key("input", identifier, level, term.species)
                role = "third_body" if term.species == THIRD_BODY else "supply"
                nodes[key] = _Node(term.species, role, level - 1)
            edges.append(_Edge(key, reaction_key, term.n))
        for term in diagram_terms(reaction, "products"):
            key = ("state", term.species)
            if pathway.supported_by.get(term.species) != identifier:
                key = _local_participant_key("output", identifier, level, term.species)
                role = "third_body" if term.species == THIRD_BODY else "product"
                nodes[key] = _Node(term.species, role, level + 1)
            edges.append(_Edge(reaction_key, key, term.n))
    return nodes, edges


def _local_participant_key(side: str, reaction: str, level: int, species: str) -> NodeKey:
    return (side, str(level) if species == ELECTRON else reaction, species)


def _render_pathway(
    pathway: Pathway,
    reactions: list[dict],
    reachability: Reachability,
    states: dict[str, dict],
    names: dict[str, str],
    *,
    conditions: dict,
    requested_target: str | None,
    case_name: str,
    scope: str,
    partial: bool,
    open_checks: set[str],
) -> Image.Image:
    nodes, edges = _pathway_layout(pathway, reactions, reachability)
    target = pathway.target or requested_target
    if not nodes and target:
        nodes[("state", target)] = _Node(target, "unreachable", 0)
    fonts = _Fonts()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    by_id = {reaction["id"]: reaction for reaction in reactions}
    labels = {
        key: _node_labels(node, by_id, names, conditions, measure, fonts)
        for key, node in nodes.items()
    }
    node_height = _node_height(labels, edges)
    positions, lanes = _node_positions(nodes, edges, node_height)
    width = max(760, 96 + max((x for x, _ in positions.values()), default=0) + REACTION_WIDTH)
    height = max(215, 36 + max((y for _, y in positions.values()), default=150) + node_height)
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    _draw_heading(draw, fonts, case_name, scope, target is not None, partial)
    _draw_legend(draw, fonts, {reaction["family"] for reaction in reactions}, bool(open_checks))
    _draw_connections(draw, fonts, nodes, edges, positions, lanes, node_height, by_id)
    for key, node in nodes.items():
        _draw_node(
            draw, fonts, node, positions[key], node_height, labels[key], states, by_id, open_checks
        )
    return image


def _node_labels(
    node: _Node,
    reactions: dict[str, dict],
    names: dict[str, str],
    conditions: dict,
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
) -> tuple[list[str], list[str]]:
    primary = names.get(node.subject, node.subject)
    detail = {
        "supply": "Supply",
        "target": "Target",
        "supplied_target": "Target · supplied",
        "unreachable": "Unreachable",
        "third_body": "Third body",
    }.get(node.role, "")
    if node.role == "reaction":
        reaction = reactions[node.subject]
        primary = reaction["reaction_type"].capitalize()
        energy = energy_values({"input": {"conditions": conditions}}, reaction)
        value, frame = energy["relative_collision_energy_eV"], "COM"
        if value is None:
            value = energy["incident_energy_eV"]
            frame = (energy["incident_energy_frame"] or "").upper()
        incident = f"{value:g} eV {frame}".strip() if value is not None else ""
        detail = " · ".join(
            filter(None, (reaction.get("stabilization"), reaction.get("surface"), incident))
        )
    width = _node_width(node) - 30
    return _wrap_label(draw, primary, fonts.node_bold, width), _wrap_label(
        draw, detail, fonts.node_small, width
    )


def _wrap_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: int,
) -> list[str]:
    lines = []
    label = " ".join(label.split())
    while draw.textlength(label, font=font) > width:
        stop = 1
        while draw.textlength(label[: stop + 1], font=font) <= width:
            stop += 1
        separator = label.rfind(" ", 0, stop + 1)
        if separator >= stop // 2:
            stop = separator
        lines.append(label[:stop].rstrip())
        label = label[stop:].lstrip()
    return [*lines, label] if label else lines


def _node_width(node: _Node) -> int:
    return REACTION_WIDTH if node.role == "reaction" else STATE_WIDTH


def _node_height(labels: dict[NodeKey, tuple[list[str], list[str]]], edges: list[_Edge]) -> int:
    incoming: dict[NodeKey, int] = defaultdict(int)
    outgoing: dict[NodeKey, int] = defaultdict(int)
    for edge in edges:
        incoming[edge.target] += 1
        outgoing[edge.source] += 1
    line_count = max((len(primary) + len(detail) for primary, detail in labels.values()), default=1)
    return max(56, 18 + 17 * line_count, 12 + 16 * max([0, *incoming.values(), *outgoing.values()]))


def _node_positions(
    nodes: dict[NodeKey, _Node],
    edges: list[_Edge],
    node_height: int,
) -> tuple[dict[NodeKey, tuple[int, int]], list[list[NodeKey]]]:
    """Reserve a lane in every crossed column before ordering adjacent columns."""
    columns_in_use = sorted({node.level for node in nodes.values()})
    column_for_level = {level: index for index, level in enumerate(columns_in_use)}
    levels = {key: column_for_level[node.level] for key, node in nodes.items()}
    lanes = []
    for index, edge in enumerate(edges):
        route = [edge.source]
        for level in range(levels[edge.source] + 1, levels[edge.target]):
            lane = ("lane", str(index), str(level))
            levels[lane] = level
            route.append(lane)
        lanes.append([*route, edge.target])
    columns: dict[int, list[NodeKey]] = defaultdict(list)
    predecessors: dict[NodeKey, list[NodeKey]] = defaultdict(list)
    successors: dict[NodeKey, list[NodeKey]] = defaultdict(list)
    for key, level in levels.items():
        columns[level].append(key)
    for route in lanes:
        for source, target in pairwise(route):
            predecessors[target].append(source)
            successors[source].append(target)
    for column in columns.values():
        column.sort()
    order = {key: index for column in columns.values() for index, key in enumerate(column)}
    for level in sorted(columns):
        column = columns[level]
        column.sort(key=lambda key: (_barycentre(predecessors[key] or successors[key], order), key))
        order.update((key, index) for index, key in enumerate(column))
    rows = max(map(len, columns.values()), default=0)
    row_gap = node_height + 32
    return {
        key: (48 + level * COLUMN_GAP, 127 + (rows - len(column)) * row_gap // 2 + index * row_gap)
        for level, column in columns.items()
        for index, key in enumerate(column)
    }, lanes


def _barycentre(neighbors: list[NodeKey], order: dict[NodeKey, int]) -> float:
    return sum(order[key] for key in neighbors) / len(neighbors) if neighbors else len(order)


def _ports(
    lanes: list[list[NodeKey]],
    positions: dict[NodeKey, tuple[int, int]],
    height: int,
    *,
    output: bool,
) -> dict[int, float]:
    groups: dict[NodeKey, list[tuple[int, int]]] = defaultdict(list)
    for index, route in enumerate(lanes):
        node, adjacent = (route[0], route[1]) if output else (route[-1], route[-2])
        groups[node].append((positions[adjacent][1], index))
    return {
        index: positions[node][1] + (rank + 1) * height / (len(group) + 1)
        for node, group in groups.items()
        for rank, (_, index) in enumerate(sorted(group))
    }


def _draw_connections(
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
    nodes: dict[NodeKey, _Node],
    edges: list[_Edge],
    positions: dict[NodeKey, tuple[int, int]],
    lanes: list[list[NodeKey]],
    height: int,
    reactions: dict[str, dict],
) -> None:
    exits = _ports(lanes, positions, height, output=True)
    entries = _ports(lanes, positions, height, output=False)
    labels = []
    for index, (edge, route) in enumerate(zip(edges, lanes, strict=True)):
        source, target = nodes[edge.source], nodes[edge.target]
        x1 = positions[edge.source][0] + _node_width(source)
        x2 = positions[edge.target][0]
        y1, y2 = exits[index], entries[index]
        identifier = source.subject if source.role == "reaction" else target.subject
        color = FAMILY_COLORS.get(reactions[identifier]["family"], MUTED)
        points = [(x1, y1), (x1 + 14, y1)]
        points.extend(
            (positions[key][0] + STATE_WIDTH // 2, positions[key][1] + height / 2)
            for key in route[1:-1]
        )
        points.extend(((x2 - 14, y2), (x2, y2)))
        draw.line(points, fill="#FFFFFF", width=6, joint="curve")
        draw.line(points, fill=color, width=2, joint="curve")
        draw.polygon([(x2, y2), (x2 - 10, y2 - 4), (x2 - 10, y2 + 4)], fill=color)
        if edge.count != 1:
            label = str(Term("", edge.count)).strip()
            labels.append(
                (x2 - 18, y2, label) if source.role == "reaction" else (x1 + 18, y1, label)
            )
    for x, y, label in labels:
        draw.text(
            (x, y - 3),
            label,
            INK,
            fonts.node_small,
            anchor="ms",
            stroke_width=3,
            stroke_fill="white",
        )


def _draw_heading(
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
    case_name: str,
    scope: str,
    has_target: bool,
    partial: bool,
) -> None:
    title = "Reaction pathway" if has_target else "No reachable product"
    draw.text((48, 23), title, INK, fonts.title)
    context = " · ".join(filter(None, (case_name, scope, "Partial exploration" if partial else "")))
    draw.text((48, 64), context, MUTED, fonts.label)


def _draw_legend(
    draw: ImageDraw.ImageDraw, fonts: _Fonts, families: set[str], open_checks: bool
) -> None:
    cursor = 48
    for family in sorted(families):
        color = FAMILY_COLORS.get(family, MUTED)
        draw.line((cursor, 100, cursor + 20, 100), fill=color, width=3)
        draw.text((cursor + 27, 100), family.capitalize(), INK, fonts.node_small, anchor="lm")
        cursor += int(draw.textlength(family.capitalize(), font=fonts.node_small)) + 48
    if open_checks:
        draw.text(
            (cursor, 100), "?  Open reaction checks", "#886319", fonts.node_small, anchor="lm"
        )


def _draw_node(
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
    node: _Node,
    position: tuple[int, int],
    height: int,
    labels: tuple[list[str], list[str]],
    states: dict[str, dict],
    reactions: dict[str, dict],
    open_checks: set[str],
) -> None:
    x, y = position
    width = _node_width(node)
    if node.role == "reaction":
        color = FAMILY_COLORS.get(reactions[node.subject]["family"], MUTED)
        fill, border = "#FFFFFF", 3
    else:
        state = states.get(node.subject)
        fill = _state_fill(state) if state is not None else "#F2F4F5"
        color, border = MUTED, 1
        if node.role in {"target", "supplied_target", "unreachable"}:
            color, border = INK, 3
        elif node.role == "supply":
            fill = "#E9F3F8"
    draw.rounded_rectangle(
        (x, y, x + width, y + height), radius=8, fill=fill, outline=color, width=border
    )
    primary, detail = labels
    text_y = y + (height - 17 * (len(primary) + len(detail))) / 2 + 8
    for lines, font, ink in ((primary, fonts.node_bold, INK), (detail, fonts.node_small, MUTED)):
        for line in lines:
            draw.text((x + width / 2, text_y), line, ink, font, anchor="mm")
            text_y += 17
    if node.role == "reaction" and node.subject in open_checks:
        badge_x, badge_y = x + width - 10, y + 10
        draw.ellipse(
            (badge_x - 8, badge_y - 8, badge_x + 8, badge_y + 8), fill="#FFF7E0", outline="#886319"
        )
        draw.text((badge_x, badge_y), "?", "#886319", fonts.node_bold, anchor="mm")


def _state_fill(state: dict) -> str:
    if state["id"] == "e":
        return "#F2F4F5"
    if int(state["charge"]) > 0:
        return "#E8F0F6"
    if int(state["charge"]) < 0:
        return "#F7EAE2"
    if state["state"]["kind"] != "ground":
        return "#FFF7E0"
    return "#FFFFFF"


def _save_png(
    image: Image.Image,
    case_name: str,
    view_label: str,
    pathway: Pathway,
    reachability: Reachability,
    analysis: dict,
    mode: str,
    requested_target: str | None,
    exploration_status: str,
    query_notes: dict,
    *,
    selected: ProducerPathway | None = None,
) -> bytes:
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("reactgen.case", case_name)
    metadata.add_text("reactgen.view", view_label)
    if exploration_status:
        metadata.add_text("reactgen.exploration_status", exploration_status)
    metadata.add_text("reactgen.scope", "target_centered_canonical_hyperpath")
    metadata.add_text("reactgen.target", pathway.target or "")
    metadata.add_text("reactgen.requested_target", requested_target or pathway.target or "")
    metadata.add_text("reactgen.path_state_count", str(len(pathway.state_ids)))
    metadata.add_text("reactgen.path_reaction_count", str(len(pathway.reaction_ids)))
    metadata.add_text("reactgen.related_reaction_count", str(len(pathway.related_reactions)))
    metadata.add_text(
        "reactgen.path_reaction_ids_sha256",
        sha256("\n".join(pathway.reaction_ids).encode()).hexdigest(),
    )
    metadata.add_text("reactgen.seed_states", ",".join(reachability.seeds))
    metadata.add_text("reactgen.topology_assumptions", _TOPOLOGY_NOTE)
    metadata.add_text(
        "reactgen.pathway_query",
        json.dumps(
            {
                "seeds": analysis["seeds"],
                "effective_seeds": reachability.seeds,
                "conditions": analysis["conditions"],
                "mode": mode,
                "target": requested_target or pathway.target,
                **(
                    {
                        "via": selected.producer,
                        "equation_and_energy_checks_pass": selected.equation_and_energy_checks_pass,
                    }
                    if selected
                    else {}
                ),
                "reaction_ids": pathway.reaction_ids,
                "related_reactions": pathway.related_reactions,
                "unresolved": {
                    key: analysis[mode]["unresolved"][key]
                    for key in pathway.reaction_ids
                    if key in analysis[mode]["unresolved"]
                },
                **query_notes,
                **(
                    {"excluded_seeds": analysis[mode]["excluded_seeds"]}
                    if "excluded_seeds" in analysis[mode]
                    else {}
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
    )
    image.save(output, format="PNG", optimize=True, pnginfo=metadata)
    return output.getvalue()


class _Fonts:
    def __init__(self) -> None:
        self.title = _font(31, bold=True)
        self.label = _font(15)
        self.node_bold = _font(14, bold=True)
        self.node_small = _font(13)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ("arialbd.ttf", "arial.ttf"),
        ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"),
        ("LiberationSans-Bold.ttf", "LiberationSans-Regular.ttf"),
    )
    filename = names[0][0 if bold else 1]
    candidates: Iterable[Path | str] = (
        Path("C:/Windows/Fonts") / filename,
        Path("/usr/share/fonts/truetype/dejavu") / names[1][0 if bold else 1],
        Path("/usr/share/fonts/truetype/liberation2") / names[2][0 if bold else 1],
        Path("/System/Library/Fonts/Supplemental") / filename,
        names[1][0 if bold else 1],
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)
