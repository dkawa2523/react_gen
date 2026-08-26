"""Render a complete reaction-state incidence matrix as one PNG."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

FAMILY_COLORS = {
    "electron": "#2F6B9A",
    "ion": "#C56A2D",
    "neutral": "#71884A",
    "surface": "#B05A7A",
}
VERDICT_COLORS = {
    "pass": "#2F6B9A",
    "fail": "#A34D52",
    "unknown": "#D7B45A",
    "not_applicable": "#C9CFD4",
}
REACTANT = "#C56A2D"
PRODUCT = "#2F6B9A"
UNCHANGED = "#6E7881"
INK = "#1F2933"
MUTED = "#64717D"
GRID = "#D7DDE2"
ASSESSMENTS = ("consistency", "state", "thermochemistry", "reaction_evidence", "kinetics")


def network_matrix_png(
    *,
    case_name: str,
    states: list[dict],
    state_names: dict[str, str],
    reactions: list[dict],
) -> bytes:
    """Return a high-resolution PNG containing every reaction exactly once."""

    ordered_states = sorted(states, key=lambda state: _state_key(state, state_names))
    ordered_reactions = sorted(reactions, key=_reaction_key)
    reaction_count = len(ordered_reactions)
    state_count = len(ordered_states)
    label_width = 390
    matrix_width = max(1400, min(8000, reaction_count * 3))
    row_height = 24
    header_height = 245
    verdict_height = 24
    footer_height = 105
    width = label_width + matrix_width + 55
    height = (
        header_height + state_count * row_height + len(ASSESSMENTS) * verdict_height + footer_height
    )
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    fonts = _Fonts()

    draw.text((38, 30), f"{case_name} - reaction-state stoichiometric matrix", INK, fonts.title)
    incidences = sum(_reaction_incidence_count(reaction) for reaction in ordered_reactions)
    draw.text(
        (38, 74),
        (
            f"All candidates: {state_count:,} states | {reaction_count:,} reactions | "
            f"{incidences:,} directed state-reaction incidences"
        ),
        MUTED,
        fonts.subtitle,
    )
    _draw_legend(draw, fonts, 38, 113)

    matrix_x = label_width
    matrix_y = header_height
    draw.text((38, matrix_y - 29), "State (one row each)", INK, fonts.label_bold)
    draw.text(
        (matrix_x, matrix_y - 29),
        "Reaction columns (one column each)",
        INK,
        fonts.label_bold,
    )
    _draw_family_band(draw, fonts, ordered_reactions, matrix_x, matrix_y - 62, matrix_width)

    previous_group = ""
    for row, state in enumerate(ordered_states):
        y = matrix_y + row * row_height
        group = _state_group(state)
        if group != previous_group:
            draw.line((35, y, matrix_x + matrix_width, y), fill=INK, width=2)
            previous_group = group
        fill = "#F7F9FA" if row % 2 else "#FFFFFF"
        draw.rectangle((35, y, matrix_x + matrix_width, y + row_height), fill=fill)
        group_color = _state_group_color(group)
        draw.rectangle((35, y + 3, 43, y + row_height - 3), fill=group_color)
        name = state_names.get(state["id"], state["id"])
        detail = f"{group} | q={int(state['charge']):+d} | {state['state']['kind']}"
        draw.text((53, y + 3), name, INK, fonts.row)
        draw.text((205, y + 5), detail, MUTED, fonts.row_small)

        reactants = _stoichiometry(state["id"], ordered_reactions, "reactants")
        products = _stoichiometry(state["id"], ordered_reactions, "products")
        for column, (reactant_n, product_n) in enumerate(zip(reactants, products, strict=True)):
            if not reactant_n and not product_n:
                continue
            x0, x1 = _column_bounds(column, reaction_count, matrix_x, matrix_width)
            _draw_participation(
                draw,
                (x0, y + 2, x1, y + row_height - 2),
                reactant_n,
                product_n,
                fonts,
            )

    matrix_bottom = matrix_y + state_count * row_height
    draw.line((35, matrix_bottom, matrix_x + matrix_width, matrix_bottom), fill=INK, width=2)
    for index, assessment in enumerate(ASSESSMENTS):
        y = matrix_bottom + index * verdict_height
        label = assessment.replace("_", " ")
        draw.text((53, y + 4), label, INK, fonts.row)
        draw.rectangle((35, y, 43, y + verdict_height), fill="#27313A")
        for column, reaction in enumerate(ordered_reactions):
            verdict = reaction["assessments"][assessment]["verdict"]
            x0, x1 = _column_bounds(column, reaction_count, matrix_x, matrix_width)
            draw.rectangle((x0, y + 3, x1, y + verdict_height - 3), fill=VERDICT_COLORS[verdict])
    verdict_bottom = matrix_bottom + len(ASSESSMENTS) * verdict_height
    draw.line((35, verdict_bottom, matrix_x + matrix_width, verdict_bottom), fill=INK, width=2)

    draw.text(
        (38, verdict_bottom + 25),
        (
            "Each reaction occupies exactly one column; no reaction is sampled, merged, "
            "or projected into species-species edges."
        ),
        INK,
        fonts.footer,
    )
    draw.text(
        (38, verdict_bottom + 56),
        (
            "Use network.html to zoom, filter assessment views, inspect exact equations, "
            "and follow local reaction hyperedges."
        ),
        MUTED,
        fonts.footer,
    )
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("reactgen.case", case_name)
    metadata.add_text("reactgen.state_count", str(state_count))
    metadata.add_text("reactgen.reaction_count", str(reaction_count))
    metadata.add_text(
        "reactgen.reaction_ids_sha256",
        sha256("\n".join(reaction["id"] for reaction in ordered_reactions).encode()).hexdigest(),
    )
    metadata.add_text("reactgen.scope", "all_candidates_no_sampling")
    image.save(output, format="PNG", optimize=True, pnginfo=metadata)
    return output.getvalue()


def _draw_legend(draw: ImageDraw.ImageDraw, fonts: _Fonts, x: int, y: int) -> None:
    draw.text((x, y), "Participation", INK, fonts.label_bold)
    cursor = x + 120
    for label, color, marker in (
        ("reactant", REACTANT, "triangle-left"),
        ("product", PRODUCT, "triangle-right"),
        ("zero-net participant", UNCHANGED, "diamond"),
    ):
        _draw_marker(draw, cursor, y + 4, color, marker)
        draw.text((cursor + 24, y), label, INK, fonts.label)
        cursor += 190 if label != "zero-net participant" else 260
    draw.text((x, y + 37), "Assessment", INK, fonts.label_bold)
    cursor = x + 120
    for verdict in ("pass", "fail", "unknown", "not_applicable"):
        draw.rectangle((cursor, y + 41, cursor + 15, y + 55), fill=VERDICT_COLORS[verdict])
        draw.text((cursor + 23, y + 35), verdict.replace("_", " "), INK, fonts.label)
        cursor += 175


def _draw_marker(draw: ImageDraw.ImageDraw, x: int, y: int, color: str, marker: str) -> None:
    if marker == "triangle-left":
        draw.polygon(((x, y + 8), (x + 17, y), (x + 17, y + 16)), fill=color)
    elif marker == "triangle-right":
        draw.polygon(((x, y), (x + 17, y + 8), (x, y + 16)), fill=color)
    else:
        draw.polygon(((x + 8, y), (x + 17, y + 8), (x + 8, y + 16), (x, y + 8)), fill=color)


def _draw_family_band(
    draw: ImageDraw.ImageDraw,
    fonts: _Fonts,
    reactions: list[dict],
    x: int,
    y: int,
    width: int,
) -> None:
    count = len(reactions)
    if not count:
        draw.rectangle((x, y, x + width, y + 22), fill="#F2F4F5", outline=GRID)
        draw.text((x + 8, y + 3), "no reactions", MUTED, fonts.row_small)
        return
    start = 0
    while start < count:
        family = reactions[start]["family"]
        end = start + 1
        while end < count and reactions[end]["family"] == family:
            end += 1
        x0, _ = _column_bounds(start, count, x, width)
        _, x1 = _column_bounds(end - 1, count, x, width)
        draw.rectangle((x0, y, x1, y + 22), fill=FAMILY_COLORS.get(family, MUTED))
        if x1 - x0 >= 65:
            label_width = draw.textlength(family, font=fonts.row_small)
            draw.text((x0 + (x1 - x0 - label_width) / 2, y + 4), family, "#FFFFFF", fonts.row_small)
        start = end
    draw.rectangle((x, y, x + width, y + 22), outline=INK, width=1)


def _draw_participation(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    reactant_n: float,
    product_n: float,
    fonts: _Fonts,
) -> None:
    x0, y0, x1, y1 = box
    if reactant_n and product_n and reactant_n == product_n:
        draw.rectangle(box, fill=UNCHANGED)
        return
    if reactant_n and product_n:
        middle = (y0 + y1) // 2
        draw.rectangle((x0, y0, x1, middle), fill=REACTANT)
        draw.rectangle((x0, middle + 1, x1, y1), fill=PRODUCT)
    else:
        draw.rectangle(box, fill=REACTANT if reactant_n else PRODUCT)
    if x1 - x0 >= 12:
        coefficient = max(reactant_n, product_n)
        if coefficient > 1:
            written = int(coefficient) if coefficient == int(coefficient) else coefficient
            draw.text((x0 + 2, y0 + 1), str(written), "#FFFFFF", fonts.coefficient)


def _stoichiometry(state_id: str, reactions: list[dict], side: str) -> list[float]:
    return [
        sum(float(term["n"]) for term in reaction[side] if term["species"] == state_id)
        for reaction in reactions
    ]


def _reaction_incidence_count(reaction: dict) -> int:
    return len({term["species"] for term in reaction["reactants"]}) + len(
        {term["species"] for term in reaction["products"]}
    )


def _column_bounds(index: int, count: int, x: int, width: int) -> tuple[int, int]:
    if not count:
        return x, x + width
    start = x + index * width // count
    end = x + (index + 1) * width // count - 1
    return start, max(start, end)


def _state_key(state: dict, state_names: dict[str, str]) -> tuple:
    return (
        _state_group_order(state),
        _composition_key(state),
        state["state"]["kind"],
        state_names.get(state["id"], state["id"]),
        state["id"],
    )


def _state_group_order(state: dict) -> int:
    group = _state_group(state)
    return {
        "electron": 0,
        "positive ion": 1,
        "excited neutral": 2,
        "radical/atom": 3,
        "stable neutral": 4,
        "negative ion": 5,
        "other": 6,
    }[group]


def _state_group(state: dict) -> str:
    if state["id"] == "e":
        return "electron"
    charge = int(state["charge"])
    if charge > 0:
        return "positive ion"
    if charge < 0:
        return "negative ion"
    if state["state"]["kind"] != "ground":
        return "excited neutral"
    classes = {str(value).lower() for value in state.get("classes", [])}
    atom_count = sum(int(value) for value in state.get("composition", {}).values())
    if "radical" in classes or atom_count == 1:
        return "radical/atom"
    if charge == 0:
        return "stable neutral"
    return "other"


def _state_group_color(group: str) -> str:
    return {
        "electron": "#6E7881",
        "positive ion": "#2F6B9A",
        "excited neutral": "#D7B45A",
        "radical/atom": "#71884A",
        "stable neutral": "#C9CFD4",
        "negative ion": "#C56A2D",
        "other": "#B05A7A",
    }[group]


def _composition_key(state: dict) -> tuple:
    composition = state.get("composition", {})
    return tuple(sorted((str(element), int(count)) for element, count in composition.items()))


def _reaction_key(reaction: dict) -> tuple:
    family_order = {"electron": 0, "ion": 1, "neutral": 2, "surface": 3}
    return (
        family_order.get(reaction["family"], 9),
        reaction["process"],
        reaction["depth"],
        reaction["id"],
    )


class _Fonts:
    def __init__(self) -> None:
        self.title = _font(31, bold=True)
        self.subtitle = _font(18)
        self.label_bold = _font(16, bold=True)
        self.label = _font(15)
        self.row = _font(14)
        self.row_small = _font(12)
        self.coefficient = _font(9, bold=True)
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
