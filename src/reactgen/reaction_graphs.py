"""Standalone figures of saved reaction results."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from hashlib import sha256
from html import escape
from math import ceil
from textwrap import wrap

from reactgen.model import THIRD_BODY, Term
from reactgen.presentation import diagram_terms, exploration_status_text, reaction_equation
from reactgen.reaction_tables import energy_values, state_labels

_COLORS = {
    "pass": "#235d83",
    "fail": "#a53a44",
    "unknown": "#886319",
    "not_applicable": "#6a7480",
    "not_recorded": "#bbc3cc",
}
_VERDICTS = {
    "pass": "Pass",
    "fail": "Fail",
    "unknown": "Unresolved",
    "not_applicable": "Not applicable",
    "not_recorded": "Not recorded",
}
_JUDGMENTS = {
    "conservation": "Conservation",
    "consistency": "Process consistency",
    "state": "Participant state support",
    "energy": "Collision energy necessary condition",
    "thermochemistry": "Thermochemical assessment",
    "reaction_evidence": "Reaction evidence",
    "kinetics": "Rate coefficient availability",
}
_STYLE = """
text{font-family:system-ui,'Segoe UI',sans-serif;fill:#233140;font-size:15px}
.title{font-size:27px;font-weight:650}
.subtitle{font-size:18px;font-weight:600}
.secondary{font-size:13px;fill:#536577}
.axis{font-size:13px;fill:#536577}
.grid{stroke:#dce4ea;stroke-width:1}
.zero{stroke:#506579;stroke-width:1.5}
.node{fill:#f2f6f9;stroke:#adbbc8;stroke-width:1}
.environment{fill:#fff8eb;stroke:#b69968;stroke-dasharray:4 3}
.third-body{stroke-dasharray:4 3}
"""
_ENERGY_ROWS_PER_PAGE = 24


def energy_graphs(
    document: dict, reactions: Iterable[dict], *, selection: str = ""
) -> dict[str, str]:
    """Plot saved nominal COM residuals by applied input; absent values have no marks."""
    labels = state_labels(document)
    grouped: dict[tuple, list[tuple[dict, dict]]] = defaultdict(list)
    for reaction in reactions:
        values = energy_values(document, reaction)
        if values["collision_input"]:
            # The stored input already establishes applicability. The entrance
            # terms only keep distinct collisions apart for a scalar case input.
            entrance = tuple(sorted((term["species"], term["n"]) for term in reaction["reactants"]))
            key = (
                entrance,
                values["collision_input"],
                values["incident_energy_eV"],
                values["incident_energy_frame"],
                values["projectile_state"],
                values["target_state"],
            )
            grouped[key].append((reaction, values))

    figures = {}
    generation = document["metadata"]["generation"]
    for key, group in grouped.items():
        points = [
            (reaction, values)
            for reaction, values in group
            if values["collision_energy_margin_eV"] is not None
        ]
        if points:
            figures.update(_energy_pages(key, group, points, labels, generation, selection))
    return figures


def _energy_pages(
    key: tuple,
    group: list[tuple[dict, dict]],
    points: list[tuple[dict, dict]],
    labels: dict[str, str],
    generation: Mapping[str, object],
    selection: str,
) -> dict[str, str]:
    entrance, source, incident, frame, projectile, target = key
    title = "Collision energy residual by reaction"
    pair = (
        f"{labels.get(projectile, projectile)} on {labels.get(target, target)}"
        if projectile is not None and target is not None
        else " + ".join(str(Term(labels.get(state, state), count)) for state, count in entrance)
    )
    condition = pair if incident is None else f"{pair} · {incident:g} eV ({frame or 'frame unset'})"
    name = re.sub(r"[^a-zA-Z0-9]+", "-", "-".join(state for state, _ in entrance))
    signature = sha256(repr(key).encode()).hexdigest()[:8]
    filename = f"energy-{name.strip('-')[:60]}-{signature}"
    points.sort(
        key=lambda item: (item[0]["process"], reaction_equation(item[0], labels), item[0]["id"])
    )
    values = [point["collision_energy_margin_eV"] for _, point in points]
    scale = max(map(abs, values)) or 1.0
    lower = min(0.0, min(values) / scale)
    upper = max(0.0, max(values) / scale)
    if lower == upper:
        lower, upper = -1.0, 1.0
    total = ceil(len(points) / _ENERGY_ROWS_PER_PAGE)
    figures = {}
    scope = exploration_status_text(generation)
    verdicts = {_energy_verdict(reaction) for reaction, _ in points}
    processes = {_energy_process_label(reaction) for reaction, _ in points}
    shared_process = next(iter(processes)) if len(processes) == 1 else None
    condition_lines = _wrapped(condition, 64)
    scope_y = 77 + 21 * len(condition_lines)
    for page, start in enumerate(range(0, len(points), _ENERGY_ROWS_PER_PAGE), start=1):
        rows = points[start : start + _ENERGY_ROWS_PER_PAGE]
        annotation = f"Residuals {len(points):,} / {len(group):,} bound"
        if total > 1:
            annotation += f" · {page}/{total}"
        context = _figure_context(annotation, generation, selection)
        plot_top = scope_y + 42 + 18 * (len(context) - 1)
        header = [
            _text(28, 40, title, "title"),
            *_text_lines(28, 69, condition_lines, "subtitle", spacing=21),
            *_text_lines(28, scope_y, context, "secondary"),
            _text(28, plot_top - 25, shared_process or "Reaction · process", "secondary"),
            _text(822, plot_top - 25, "Nominal COM residual (eV)", "secondary", anchor="middle"),
        ]
        plot, bottom = _energy_plot(
            rows, labels, scale, lower, upper, plot_top, show_process=shared_process is None
        )
        height = bottom + 75
        body = header + plot + _energy_legend(height - 22, verdicts)
        suffix = f"-{page:03d}" if total > 1 else ""
        figures[f"{filename}{suffix}.svg"] = _svg(
            1220,
            height,
            title,
            f"{condition}. Saved input: {source}. {annotation}. {scope} {selection}".rstrip(),
            body,
        )
    return figures


def _energy_plot(
    rows: list[tuple[dict, dict]],
    labels: dict[str, str],
    scale: float,
    lower: float,
    upper: float,
    top: int,
    *,
    show_process: bool,
) -> tuple[list[str], int]:
    def position(value: float) -> float:
        return 590 + 465 * (value - lower) / (upper - lower)

    row_labels = [
        _energy_row_labels(reaction, labels, show_process=show_process) for reaction, _ in rows
    ]
    row_heights = [
        10 + 18 * (len(equation_lines) + len(process_lines))
        for _, equation_lines, process_lines in row_labels
    ]
    bottom = top + sum(row_heights)
    center = position(0.0)
    ticks = [lower + (upper - lower) * part / 4 for part in range(5)]
    ticks = [0.0, *(tick for tick in ticks if abs(position(tick) - center) >= 62)]
    body = [
        f'<line x1="{center:.2f}" y1="{top}" x2="{center:.2f}" y2="{bottom}" class="zero"/>',
        f'<line x1="590" y1="{bottom}" x2="1055" y2="{bottom}" class="grid"/>',
    ]
    for tick in ticks:
        x = position(tick)
        body.append(
            f'<line x1="{x:.2f}" y1="{bottom}" x2="{x:.2f}" y2="{bottom + 5}" class="grid"/>'
        )
        body.append(_text(x, bottom + 19, f"{tick * scale:.3g}", "axis", anchor="middle"))

    row_top = top
    for (reaction, values), (equation, eq_lines, process_lines), height in zip(
        rows, row_labels, row_heights, strict=True
    ):
        y = row_top + height // 2
        verdict = _energy_verdict(reaction)
        color = _COLORS[verdict]
        value = values["collision_energy_margin_eV"]
        x = position(value / scale)
        detail = _energy_point_detail(reaction, values, equation, verdict)
        body.extend(
            (
                f"<g><title>{escape(detail)}</title>",
                f'<line x1="28" y1="{row_top + height}" x2="1190" '
                f'y2="{row_top + height}" class="grid"/>',
                *_text_lines(28, row_top + 18, eq_lines),
                *_text_lines(28, row_top + 18 + 18 * len(eq_lines), process_lines, "secondary"),
                f'<line x1="{center:.2f}" y1="{y}" x2="{x:.2f}" y2="{y}" stroke="{color}"/>',
                _energy_mark(x, y, verdict),
                _text(1190, y + 5, f"{value:+.5g}", anchor="end"),
                "</g>",
            )
        )
        row_top += height
    return body, bottom


def _energy_row_labels(
    reaction: dict, labels: dict[str, str], *, show_process: bool
) -> tuple[str, list[str], list[str]]:
    equation = reaction_equation(reaction, labels)
    process_lines = _wrapped(_energy_process_label(reaction), 42) if show_process else []
    return equation, _wrapped(equation, 37), process_lines


def _energy_process_label(reaction: dict) -> str:
    process = reaction["process"].replace("_", " ")
    if stabilization := reaction.get("stabilization"):
        process += f" · {stabilization}"
    return process


def _energy_verdict(reaction: dict) -> str:
    return reaction.get("assessments", {}).get("energy", {}).get("verdict", "not_recorded")


def _energy_point_detail(reaction: dict, values: dict, equation: str, verdict: str) -> str:
    def display(value: float | None) -> str:
        return "unavailable" if value is None else f"{value:.12g} eV"

    relative = display(values["relative_collision_energy_eV"])
    difference = display(values["state_energy_difference_eV"])
    margin = display(values["collision_energy_margin_eV"])
    claim = reaction.get("assessments", {}).get("energy", {})
    return (
        f"{equation} [{reaction['id']}]\n"
        f"COM input: {relative}; endpoint difference: {difference}; residual: {margin}\n"
        f"{_VERDICTS[verdict]} · {claim.get('message', '')}"
    )


def _energy_mark(x: float, y: int, verdict: str) -> str:
    color = _COLORS[verdict]
    if verdict == "pass":
        return f'<circle cx="{x:.2f}" cy="{y}" r="5" fill="{color}"/>'
    if verdict == "fail":
        points = f"{x:.2f},{y - 6} {x + 6:.2f},{y} {x:.2f},{y + 6} {x - 6:.2f},{y}"
        return f'<polygon points="{points}" fill="{color}"/>'
    if verdict == "not_applicable":
        return (
            f'<path d="M {x - 4:.2f} {y - 4} l 8 8 m -8 0 l 8 -8" '
            f'stroke="{color}" stroke-width="2"/>'
        )
    if verdict == "not_recorded":
        return (
            f'<line x1="{x - 4:.2f}" y1="{y}" x2="{x + 4:.2f}" y2="{y}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
    return (
        f'<rect x="{x - 4:.2f}" y="{y - 4}" width="8" height="8" '
        f'fill="white" stroke="{color}" stroke-width="2"/>'
    )


def _energy_legend(y: int, present: set[str]) -> list[str]:
    return [
        _energy_mark(34 + 145 * index, y - 5, verdict)
        + _text(46 + 145 * index, y, _VERDICTS[verdict], "secondary")
        for index, verdict in enumerate(key for key in _VERDICTS if key in present)
    ]


def judgment_graph(
    reactions: Iterable[dict],
    judgment: str,
    *,
    selection: str = "",
    generation: Mapping[str, object] | None = None,
) -> str:
    """Show one recorded judgment's outcome distribution, with counts per family."""
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for reaction in reactions:
        claim = reaction.get("assessments", {}).get(judgment)
        verdict = "not_recorded" if claim is None else claim["verdict"]
        by_family[reaction["family"]][verdict] += 1
    title = _JUDGMENTS.get(judgment, judgment.replace("_", " ").capitalize())
    total = sum(sum(counts.values()) for counts in by_family.values())
    context = _figure_context(f"n = {total:,}", generation or {}, selection)
    offset_y = 18 * (len(context) - 1)
    body = [
        _text(28, 40, title, "title"),
        *_text_lines(28, 67, context, "secondary"),
    ]
    if not by_family:
        return _svg(1190, 110 + offset_y, title, "No reactions match the selection.", body)

    bar_x, bar_width = 150, 400
    heading_y = 102 + offset_y
    for offset, (verdict, label) in enumerate(_VERDICTS.items()):
        x = 605 + 115 * offset
        body.append(f'<circle cx="{x - 8}" cy="{heading_y - 4}" r="4" fill="{_COLORS[verdict]}"/>')
        body.append(_text(x, heading_y, label, "secondary"))
    for percentage in (0, 25, 50, 75, 100):
        tick_x = bar_x + bar_width * percentage / 100
        body.append(_text(tick_x, heading_y, f"{percentage}%", "axis", anchor="middle"))

    for index, (family, counts) in enumerate(sorted(by_family.items())):
        y = 124 + offset_y + 42 * index
        body.extend(_judgment_bar(family, counts, y, bar_x, bar_width))
    scope = exploration_status_text(generation) if generation is not None else ""
    return _svg(
        1190,
        148 + offset_y + 42 * len(by_family),
        title,
        (
            f"Recorded outcomes per collision family in {total:,} selected reactions. "
            f"{scope} {selection}"
        ).rstrip(),
        body,
    )


def _judgment_bar(
    family: str, counts: Counter[str], y: int, bar_x: int, bar_width: int
) -> list[str]:
    total = sum(counts.values())
    x = float(bar_x)
    body = [_text(28, y + 16, family), _text(28, y + 31, f"n = {total:,}", "secondary")]
    for index, (verdict, label) in enumerate(_VERDICTS.items()):
        count = counts[verdict]
        width = bar_width * count / total
        if count:
            body.append(
                f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="23" '
                f'fill="{_COLORS[verdict]}">'
                f"<title>{escape(label)}: {count:,} / {total:,}</title></rect>"
            )
        body.append(_text(605 + 115 * index, y + 17, f"{count:,}"))
        x += width
    return body


def reaction_diagram(document: dict, reaction_id: str) -> str:
    """Draw the participant graph of one saved reaction, including stoichiometry."""
    reaction = next((item for item in document["reactions"] if item["id"] == reaction_id), None)
    if reaction is None:
        raise ValueError(f"unknown saved reaction: {reaction_id}")

    labels = state_labels(document)
    left = _diagram_side(reaction, "reactants", labels)
    right = _diagram_side(reaction, "products", labels)
    process = _wrapped(reaction["process"].replace("_", " "), 15)
    ports = max(len(left), len(right))
    process_height = max(_box_height(process), 20 + 12 * ports)
    process_half = process_height // 2
    half_span = max(_side_height(left) // 2, _side_height(right) // 2, process_half)
    center = 110 + half_span
    environment = _diagram_environment(reaction)
    environment_height = _box_height(environment) + 10 if environment else 0
    title = f"{reaction['family'].capitalize()} reaction"
    body = [
        _text(28, 42, title, "title"),
        _text(188, 82, "Reactants", "subtitle", anchor="middle"),
        _text(932, 82, "Products", "subtitle", anchor="middle"),
        *_diagram_nodes(left, center, outgoing=True),
        *_diagram_nodes(right, center, outgoing=False),
        *_diagram_box(440, center - process_half, 240, process_height, process, "node"),
    ]
    if environment:
        body.extend(
            _diagram_box(
                440,
                center + process_half + 10,
                240,
                _box_height(environment),
                environment,
                "environment",
            )
        )
    return _svg(
        1120,
        center + max(half_span, process_half + environment_height) + 26,
        title,
        f"{reaction_equation(reaction, labels)} [{reaction_id}]",
        body,
    )


def _diagram_side(reaction: dict, side: str, labels: dict[str, str]) -> list[tuple[str, list[str]]]:
    nodes = [
        (species, _wrapped(str(Term(labels.get(species, species), count)), 21))
        for species, count in diagram_terms(reaction, side)
    ]
    return nodes or [("", ["∅"])]


def _diagram_environment(reaction: dict) -> list[str]:
    lines = []
    if surface := reaction.get("surface"):
        lines.extend(_wrapped(f"Surface · {surface}", 15))
    if stabilization := reaction.get("stabilization"):
        lines.extend(_wrapped(f"Stabilization · {stabilization.replace('_', ' ')}", 15))
    return lines


def _box_height(lines: list[str]) -> int:
    return 16 + 18 * len(lines)


def _side_height(nodes: list[tuple[str, list[str]]]) -> int:
    return sum(_box_height(lines) for _, lines in nodes) + 14 * (len(nodes) - 1)


def _diagram_nodes(nodes: list[tuple[str, list[str]]], center: int, *, outgoing: bool) -> list[str]:
    x = 28 if outgoing else 772
    begin, end = (348, 439) if outgoing else (681, 771)
    midpoint = (begin + end) // 2
    body: list[str] = []
    top = center - _side_height(nodes) // 2
    for index, (identity, lines) in enumerate(nodes):
        height = _box_height(lines)
        y = top + height // 2
        port = center + 12 * index - 6 * (len(nodes) - 1)
        start_y, end_y = (y, port) if outgoing else (port, y)
        style = "node third-body" if identity == THIRD_BODY else "node"
        body.extend(
            (
                f'<path d="M {begin},{start_y} C {midpoint},{start_y} {midpoint},{end_y} '
                f'{end},{end_y}" fill="none" stroke="#536577" marker-end="url(#arrow)"/>',
                f"<g><title>{escape(identity)}</title>",
                *_diagram_box(x, top, 320, height, lines, style),
                "</g>",
            )
        )
        top += height + 14
    return body


def _diagram_box(
    x: int, y: int, width: int, height: int, lines: list[str], style: str
) -> list[str]:
    baseline = y + height // 2 - 9 * (len(lines) - 1) + 5
    return [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" class="{style}"/>',
        *_text_lines(x + width // 2, baseline, lines, anchor="middle"),
    ]


def _figure_context(annotation: str, generation: Mapping[str, object], selection: str) -> list[str]:
    if generation.get("complete") is False:
        annotation += " · Partial exploration"
    return [annotation, *_wrapped(selection, 90)]


def _wrapped(value: str, columns: int) -> list[str]:
    return wrap(value, width=columns, break_on_hyphens=False)


def _text_lines(
    x: float,
    y: float,
    lines: list[str],
    style: str = "",
    *,
    spacing: int = 18,
    anchor: str = "start",
) -> list[str]:
    return [
        _text(x, y + spacing * index, line, style, anchor=anchor)
        for index, line in enumerate(lines)
    ]


def _text(
    x: float,
    y: float,
    value: str,
    style: str = "",
    *,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" class="{style}" text-anchor="{anchor}">'
        f"{escape(value)}</text>"
    )


def _svg(width: int, height: int, title: str, description: str, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>'
        f"<style>{_STYLE}</style>"
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#536577"/></marker></defs>'
        '<rect width="100%" height="100%" fill="white"/>' + "".join(body) + "</svg>"
    )
