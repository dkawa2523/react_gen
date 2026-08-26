"""Target-centred, topology-only reaction pathway views."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from io import BytesIO
from math import ceil
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from reactgen.pathway import Pathway, Reachability, reaction_reachability, select_pathway

FAMILY_COLORS = {
    "electron": "#2F6B9A",
    "ion": "#C56A2D",
    "neutral": "#71884A",
    "surface": "#B05A7A",
}
INK = "#1F2933"
MUTED = "#64717D"
GRID = "#D7DDE2"
STATE_WIDTH = 180
REACTION_WIDTH = 110
NODE_HEIGHT = 64
COLUMN_GAP = 215
ROW_GAP = 90


def pathway_png(
    *,
    case_name: str,
    view_label: str,
    states: list[dict],
    state_names: dict[str, str],
    reactions: list[dict],
) -> bytes:
    """Render one readable example; the HTML remains the target-selectable view."""

    reachability = reaction_reachability(states, reactions)
    pathway = select_pathway(states, reactions, reachability=reachability)
    state_by_id = {state["id"]: state for state in states}
    reaction_by_id = {reaction["id"]: reaction for reaction in reactions}
    fonts = _Fonts()

    if pathway.target is None:
        image = Image.new("RGB", (1500, 440), "#FFFFFF")
        draw = ImageDraw.Draw(image)
        draw.text((45, 35), f"{case_name} - hierarchical reaction pathway", INK, fonts.title)
        draw.text((45, 92), view_label, MUTED, fonts.subtitle)
        draw.text(
            (45, 190),
            "No non-feed target is reachable from all required reactants in this view.",
            INK,
            fonts.label_bold,
        )
        return _save_png(image, case_name, view_label, pathway, reachability)

    path_states = [state_by_id[state_id] for state_id in pathway.state_ids]
    path_reactions = [reaction_by_id[reaction_id] for reaction_id in pathway.reaction_ids]
    levels, edges = _pathway_layout(pathway, path_states, path_reactions, reachability)
    max_level = max(levels.values(), default=0)
    level_counts: dict[int, int] = {}
    for level in levels.values():
        level_counts[level] = level_counts.get(level, 0) + 1
    max_rows = max(level_counts.values(), default=1)
    top = 185
    width = max(1300, 100 + max_level * COLUMN_GAP + 230)
    key_rows = ceil(len(path_reactions) / 2)
    network_bottom = top + (max_rows - 1) * ROW_GAP + NODE_HEIGHT
    key_y = network_bottom + 55
    height = max(560, key_y + 45 + key_rows * 28 + 65)
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    target_name = state_names.get(pathway.target, pathway.target)
    minimum_steps = reachability.state_layers[pathway.target]
    draw.text((45, 28), f"{case_name} - hierarchical reaction pathway", INK, fonts.title)
    draw.text(
        (45, 77),
        (
            f"{target_name}  |  {minimum_steps} steps  |  "
            f"{len(path_states)} states  |  {len(path_reactions)} reactions"
        ),
        INK,
        fonts.subtitle,
    )
    draw.text(
        (45, 108),
        f"{view_label}  |  topology only",
        MUTED,
        fonts.node_small,
    )
    _draw_legend(draw, fonts, 45, 132)
    _draw_stage_labels(draw, fonts, max_level, top)

    positions = _node_positions(levels, edges, top, ROW_GAP, COLUMN_GAP)
    for source, target, family in edges:
        _draw_edge(draw, source, target, positions, family)
    reaction_labels = {
        reaction_id: f"R{index}"
        for index, reaction_id in enumerate(
            sorted(
                pathway.reaction_ids,
                key=lambda reaction_id: (
                    reachability.reaction_layers[reaction_id],
                    reaction_id,
                ),
            ),
            start=1,
        )
    }
    for node_id, position in positions.items():
        if node_id.startswith("state:"):
            state_id = node_id.removeprefix("state:")
            _draw_state(
                draw,
                position,
                state_by_id[state_id],
                state_names.get(state_id, state_id),
                fonts,
                is_target=state_id == pathway.target,
                is_seed=state_id in reachability.seeds,
            )
        else:
            reaction_id = node_id.removeprefix("reaction:")
            _draw_reaction(
                draw,
                position,
                reaction_by_id[reaction_id],
                reaction_labels[reaction_id],
                fonts,
            )

    _draw_reaction_key(draw, fonts, key_y, width, path_reactions, reaction_labels)
    draw.text(
        (45, height - 42),
        (
            f"Reachability overview only. {len(pathway.related_reaction_ids)} related reactions "
            "and all exact equations remain in network.html."
        ),
        MUTED,
        fonts.node_small,
    )
    return _save_png(image, case_name, view_label, pathway, reachability)


def _pathway_layout(
    pathway: Pathway,
    states: list[dict],
    reactions: list[dict],
    reachability: Reachability,
) -> tuple[dict[str, int], list[tuple[str, str, str]]]:
    levels = {
        f"state:{state['id']}": 2 * reachability.state_layers[state["id"]] for state in states
    }
    reaction_by_id = {reaction["id"]: reaction for reaction in reactions}
    edges: list[tuple[str, str, str]] = []
    for reaction_id in pathway.reaction_ids:
        reaction = reaction_by_id[reaction_id]
        reaction_node = f"reaction:{reaction_id}"
        levels[reaction_node] = 2 * reachability.reaction_layers[reaction_id] - 1
        for term in reaction["reactants"]:
            state_node = f"state:{term['species']}"
            if state_node in levels:
                edges.append((state_node, reaction_node, reaction["family"]))
    for state_id, reaction_id in pathway.supported_by.items():
        edges.append(
            (
                f"reaction:{reaction_id}",
                f"state:{state_id}",
                reaction_by_id[reaction_id]["family"],
            )
        )
    return levels, edges


def _node_positions(
    levels: dict[str, int],
    edges: list[tuple[str, str, str]],
    top: int,
    row_gap: int,
    column_gap: int,
) -> dict[str, tuple[int, int]]:
    by_level: dict[int, list[str]] = {}
    for node_id, level in levels.items():
        by_level.setdefault(level, []).append(node_id)
    predecessors: dict[str, list[str]] = {node_id: [] for node_id in levels}
    successors: dict[str, list[str]] = {node_id: [] for node_id in levels}
    for source, target, _ in edges:
        predecessors[target].append(source)
        successors[source].append(target)
    for nodes in by_level.values():
        nodes.sort()
    for _ in range(5):
        order = {
            node_id: index for nodes in by_level.values() for index, node_id in enumerate(nodes)
        }
        for level in sorted(by_level):
            by_level[level].sort(
                key=lambda node_id: (
                    _barycentre(predecessors[node_id], order),
                    node_id,
                )
            )
        order = {
            node_id: index for nodes in by_level.values() for index, node_id in enumerate(nodes)
        }
        for level in sorted(by_level, reverse=True):
            by_level[level].sort(
                key=lambda node_id: (
                    _barycentre(successors[node_id], order),
                    node_id,
                )
            )
    max_rows = max((len(nodes) for nodes in by_level.values()), default=1)
    positions = {}
    for level, nodes in by_level.items():
        offset = (max_rows - len(nodes)) * row_gap // 2
        for index, node_id in enumerate(nodes):
            positions[node_id] = (60 + level * column_gap, top + offset + index * row_gap)
    return positions


def _barycentre(neighbours: list[str], order: dict[str, int]) -> float:
    if not neighbours:
        return 1.0e9
    return sum(order.get(node, 0) for node in neighbours) / len(neighbours)


def _draw_edge(
    draw: ImageDraw.ImageDraw,
    source_id: str,
    target_id: str,
    positions: dict[str, tuple[int, int]],
    family: str,
) -> None:
    source = positions[source_id]
    target = positions[target_id]
    x1, y1 = source
    x2, y2 = target
    x1 += STATE_WIDTH if source_id.startswith("state:") else REACTION_WIDTH
    y1 += NODE_HEIGHT // 2
    y2 += NODE_HEIGHT // 2
    middle = (x1 + x2) // 2
    points = [(x1, y1), (middle, y1), (middle, y2), (x2, y2)]
    color = FAMILY_COLORS.get(family, MUTED)
    draw.line(points, fill="#FFFFFF", width=8, joint="curve")
    draw.line(points, fill=color, width=3, joint="curve")
    draw.polygon([(x2, y2), (x2 - 11, y2 - 6), (x2 - 11, y2 + 6)], fill=color)


def _draw_state(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    state: dict,
    name: str,
    fonts: _Fonts,
    *,
    is_target: bool,
    is_seed: bool,
) -> None:
    x, y = position
    fill = _state_fill(state)
    outline = FAMILY_COLORS["neutral"] if is_target else INK
    width = 4 if is_target else 2
    draw.rounded_rectangle(
        (x, y, x + STATE_WIDTH, y + NODE_HEIGHT),
        radius=9,
        fill=fill,
        outline=outline,
        width=width,
    )
    name_width = draw.textlength(name, font=fonts.node_bold)
    draw.text((x + (STATE_WIDTH - name_width) / 2, y + 12), name, INK, fonts.node_bold)
    role = "TARGET" if is_target else "INPUT" if is_seed else "INTERMEDIATE"
    role_width = draw.textlength(role, font=fonts.node_small)
    draw.text((x + (STATE_WIDTH - role_width) / 2, y + 40), role, MUTED, fonts.node_small)


def _draw_reaction(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    reaction: dict,
    label: str,
    fonts: _Fonts,
) -> None:
    x, y = position
    color = FAMILY_COLORS.get(reaction["family"], MUTED)
    draw.rounded_rectangle(
        (x, y, x + REACTION_WIDTH, y + NODE_HEIGHT),
        radius=7,
        fill="#FFFFFF",
        outline=color,
        width=3,
    )
    label_width = draw.textlength(label, font=fonts.reaction_id)
    draw.text(
        (x + (REACTION_WIDTH - label_width) / 2, y + 7),
        label,
        color,
        fonts.reaction_id,
    )
    lines = wrap(
        _compact_reaction_type(reaction),
        width=14,
        break_long_words=False,
        break_on_hyphens=False,
    )[:2]
    for index, line in enumerate(lines):
        line_width = draw.textlength(line, font=fonts.reaction_small)
        draw.text(
            (x + (REACTION_WIDTH - line_width) / 2, y + 35 + index * 13),
            line,
            INK,
            fonts.reaction_small,
        )


def _draw_legend(draw: ImageDraw.ImageDraw, fonts: _Fonts, x: int, y: int) -> None:
    draw.text((x, y), "Reaction family", INK, fonts.label_bold)
    cursor = x + 165
    for family, color in FAMILY_COLORS.items():
        draw.line((cursor, y + 11, cursor + 28, y + 11), fill=color, width=3)
        draw.text((cursor + 38, y + 1), family, INK, fonts.label)
        cursor += 145
    draw.text((cursor + 10, y + 1), "All lines have equal width", MUTED, fonts.label)


def _draw_stage_labels(draw: ImageDraw.ImageDraw, fonts: _Fonts, max_level: int, top: int) -> None:
    for level in range(0, max_level + 1, 2):
        if level == 0:
            label = "INPUT"
        elif level == max_level:
            label = "TARGET"
        else:
            label = f"STAGE {level // 2}"
        x = 60 + level * COLUMN_GAP + STATE_WIDTH / 2
        label_width = draw.textlength(label, font=fonts.node_small)
        draw.text((x - label_width / 2, top - 28), label, MUTED, fonts.node_small)


def _draw_reaction_key(
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
    y: int,
    width: int,
    reactions: list[dict],
    labels: dict[str, str],
) -> None:
    draw.line((45, y, width - 45, y), fill=GRID, width=2)
    draw.text((45, y + 14), "Reaction key", INK, fonts.label_bold)
    ordered = sorted(reactions, key=lambda reaction: int(labels[reaction["id"]][1:]))
    column_width = (width - 90) // 2
    for index, reaction in enumerate(ordered):
        column = index % 2
        row = index // 2
        x = 45 + column * column_width
        row_y = y + 43 + row * 28
        color = FAMILY_COLORS.get(reaction["family"], MUTED)
        draw.rounded_rectangle(
            (x, row_y, x + 37, row_y + 21), radius=4, fill="#FFFFFF", outline=color, width=2
        )
        draw.text((x + 7, row_y + 2), labels[reaction["id"]], color, fonts.reaction_small)
        draw.text(
            (x + 48, row_y + 2),
            f"{_compact_reaction_type(reaction)}  ·  {reaction['family']}",
            INK,
            fonts.node_small,
        )


def _compact_reaction_type(reaction: dict) -> str:
    written = str(reaction["reaction_type"])
    for prefix in (
        "Electron-impact ",
        "Electron ",
        "Ion-neutral ",
        "Neutral ",
        "Excited-state ",
        "Surface ",
    ):
        if written.startswith(prefix):
            written = written.removeprefix(prefix)
            break
    return written.replace(" (superelastic)", "").capitalize()


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
) -> bytes:
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("reactgen.case", case_name)
    metadata.add_text("reactgen.view", view_label)
    metadata.add_text("reactgen.scope", "target_centered_canonical_hyperpath")
    metadata.add_text("reactgen.target", pathway.target or "")
    metadata.add_text("reactgen.path_state_count", str(len(pathway.state_ids)))
    metadata.add_text("reactgen.path_reaction_count", str(len(pathway.reaction_ids)))
    metadata.add_text("reactgen.related_reaction_count", str(len(pathway.related_reaction_ids)))
    metadata.add_text(
        "reactgen.path_reaction_ids_sha256",
        sha256("\n".join(pathway.reaction_ids).encode()).hexdigest(),
    )
    metadata.add_text("reactgen.seed_states", ",".join(reachability.seeds))
    image.save(output, format="PNG", optimize=True, pnginfo=metadata)
    return output.getvalue()


class _Fonts:
    def __init__(self) -> None:
        self.title = _font(31, bold=True)
        self.subtitle = _font(18)
        self.label_bold = _font(16, bold=True)
        self.label = _font(15)
        self.node_bold = _font(14, bold=True)
        self.node_small = _font(11)
        self.reaction_id = _font(17, bold=True)
        self.reaction_small = _font(9)
        self.footer = _font(16)


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
