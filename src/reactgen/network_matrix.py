"""Render reaction-state incidence matrices with independent reaction columns."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from reactgen.model import stoichiometric_sum

FAMILY_COLORS = {
    "electron": "#2F6B9A",
    "ion": "#C56A2D",
    "neutral": "#71884A",
    "surface": "#B05A7A",
}
REACTANT = "#C56A2D"
PRODUCT = "#2F6B9A"
UNCHANGED = "#6E7881"
INK = "#1F2933"
MUTED = "#64717D"
GRID = "#D7DDE2"
# At least one pixel is reserved for every reaction column. Larger results use
# separate panels rather than overlapping columns at the image-width bound.
MAX_MATRIX_COLUMNS = 8000


def network_matrix_png(
    *,
    case_name: str,
    states: list[dict],
    state_names: dict[str, str],
    reactions: list[dict],
    exploration_status: str = "",
) -> bytes:
    """Render one complete matrix; use ``network_matrix_pages`` for larger results."""
    if len(reactions) > MAX_MATRIX_COLUMNS:
        raise ValueError(
            f"a single matrix PNG supports at most {MAX_MATRIX_COLUMNS} reaction columns; "
            "use network_matrix_pages to retain every reaction"
        )
    return next(
        network_matrix_pages(
            case_name=case_name,
            states=states,
            state_names=state_names,
            reactions=reactions,
            exploration_status=exploration_status,
        )
    )[2]


def network_matrix_pages(
    *,
    case_name: str,
    states: list[dict],
    state_names: dict[str, str],
    reactions: list[dict],
    exploration_status: str = "",
) -> Iterator[tuple[int, int, bytes]]:
    """Yield disjoint PNG panels with zero-based, half-open reaction ranges.

    All panels use the same state rows and deterministic reaction order. The
    range and full reaction count appear in each image and its PNG metadata.
    """
    ordered_states = sorted(states, key=lambda state: _state_key(state, state_names))
    ordered_reactions = sorted(reactions, key=_reaction_key)
    count = len(ordered_reactions)
    for start in range(0, max(1, count), MAX_MATRIX_COLUMNS):
        stop = min(start + MAX_MATRIX_COLUMNS, count)
        yield (
            start,
            stop,
            _matrix_png(
                case_name,
                ordered_states,
                state_names,
                ordered_reactions[start:stop],
                start,
                count,
                exploration_status,
            ),
        )


def _matrix_png(
    case_name: str,
    ordered_states: list[dict],
    state_names: dict[str, str],
    ordered_reactions: list[dict],
    column_start: int,
    total_count: int,
    exploration_status: str,
) -> bytes:
    reaction_count = len(ordered_reactions)
    state_count = len(ordered_states)
    label_width = 390
    matrix_width = max(1400, min(MAX_MATRIX_COLUMNS, reaction_count * 3))
    row_height = 24
    header_height = 220
    width = label_width + matrix_width + 55
    height = header_height + state_count * row_height + 28
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    fonts = _Fonts()

    draw.text((38, 30), f"{case_name} - reaction-state incidence", INK, fonts.title)
    incidences = sum(_reaction_incidence_count(reaction) for reaction in ordered_reactions)
    split = reaction_count != total_count
    range_label = (
        f"Reactions {column_start + 1:,}-{column_start + reaction_count:,} of {total_count:,}"
    )
    draw.text(
        (38, 74),
        (
            f"{range_label if split else f'Saved candidates: {reaction_count:,} reactions'} | "
            f"{state_count:,} states | "
            f"{incidences:,} directed state-reaction incidences"
        ),
        MUTED,
        fonts.subtitle,
    )
    draw.text((38, 104), exploration_status, INK, fonts.label_bold)
    _draw_legend(draw, fonts, 38, 133)

    matrix_x = label_width
    matrix_y = header_height
    draw.text((38, matrix_y - 29), "State (one row each)", INK, fonts.label_bold)
    draw.text(
        (matrix_x, matrix_y - 29),
        f"Reaction columns (one column each){' - ' + range_label if split else ''}",
        INK,
        fonts.label_bold,
    )
    _draw_family_band(draw, fonts, ordered_reactions, matrix_x, matrix_y - 57, matrix_width)

    previous_group = ""
    for row, state in enumerate(ordered_states):
        y = matrix_y + row * row_height
        group = _state_group(state)
        fill = "#F7F9FA" if row % 2 else "#FFFFFF"
        draw.rectangle((35, y, matrix_x + matrix_width, y + row_height), fill=fill)
        if group != previous_group:
            draw.line((35, y, matrix_x + matrix_width, y), fill=GRID, width=1)
            previous_group = group
        group_color = _state_group_color(group)
        draw.rectangle((35, y + 3, 43, y + row_height - 3), fill=group_color)
        name = state_names.get(state["id"], state["id"])
        draw.text((53, y + 3), name, INK, fonts.row)

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
            )

    matrix_bottom = matrix_y + state_count * row_height
    draw.line((35, matrix_bottom, matrix_x + matrix_width, matrix_bottom), fill=INK, width=2)
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("reactgen.case", case_name)
    if exploration_status:
        metadata.add_text("reactgen.exploration_status", exploration_status)
    metadata.add_text("reactgen.state_count", str(state_count))
    metadata.add_text("reactgen.matrix_columns_px", str(matrix_width))
    metadata.add_text("reactgen.reaction_count", str(reaction_count))
    metadata.add_text("reactgen.total_reaction_count", str(total_count))
    metadata.add_text("reactgen.first_reaction", str(column_start + 1 if reaction_count else 0))
    metadata.add_text("reactgen.last_reaction", str(column_start + reaction_count))
    metadata.add_text(
        "reactgen.reaction_ids_sha256",
        sha256("\n".join(reaction["id"] for reaction in ordered_reactions).encode()).hexdigest(),
    )
    metadata.add_text(
        "reactgen.scope", "reaction_range_no_sampling" if split else "all_candidates_no_sampling"
    )
    image.save(output, format="PNG", optimize=True, pnginfo=metadata)
    return output.getvalue()


def _draw_legend(draw: ImageDraw.ImageDraw, fonts: _Fonts, x: int, y: int) -> None:
    draw.text((x, y), "Participation", INK, fonts.label_bold)
    cursor = x + 120
    for label, reactant, product in (
        ("reactant", 1.0, 0.0),
        ("product", 0.0, 1.0),
        ("both, net change", 1.0, 2.0),
        ("zero-net participant", 1.0, 1.0),
    ):
        draw.rectangle((cursor, y, cursor + 18, y + 20), outline=GRID)
        _draw_participation(draw, (cursor + 1, y + 1, cursor + 17, y + 19), reactant, product)
        draw.text((cursor + 24, y), label, INK, fonts.label)
        cursor += 180


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
) -> None:
    x0, y0, x1, y1 = box
    band = (y1 - y0 + 1) // 3
    if reactant_n and product_n and stoichiometric_sum((product_n, -reactant_n)) == 0:
        draw.rectangle((x0, y0 + band, x1, y1 - band), fill=UNCHANGED)
        return
    if reactant_n:
        draw.rectangle((x0, y0, x1, y0 + band - 1), fill=REACTANT)
    if product_n:
        draw.rectangle((x0, y1 - band + 1, x1, y1), fill=PRODUCT)


def _stoichiometry(state_id: str, reactions: list[dict], side: str) -> list[float]:
    return [
        stoichiometric_sum(
            float(term["n"]) for term in reaction[side] if term["species"] == state_id
        )
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
        "ground neutral atom": 3,
        "ground neutral molecule": 4,
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
    atom_count = sum(int(value) for value in state.get("composition", {}).values())
    if atom_count == 1:
        return "ground neutral atom"
    if charge == 0:
        return "ground neutral molecule"
    return "other"


def _state_group_color(group: str) -> str:
    return {
        "electron": "#6E7881",
        "positive ion": "#2F6B9A",
        "excited neutral": "#D7B45A",
        "ground neutral atom": "#71884A",
        "ground neutral molecule": "#C9CFD4",
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
