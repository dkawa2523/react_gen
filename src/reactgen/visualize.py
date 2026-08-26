"""Small dependency-free SVG views for assessment outputs."""

from __future__ import annotations

from collections import Counter
from html import escape

VERDICTS = ("pass", "fail", "unknown", "not_applicable")
COLORS = {
    "pass": "#2F6B9A",
    "fail": "#C56A2D",
    "unknown": "#7A8793",
    "not_applicable": "#D7DCE0",
}
INK = "#27313A"
MUTED = "#66727C"
GRID = "#D9DEE2"


def summary_rows(rows: list[dict]) -> list[dict]:
    """Count assessment verdicts by entity and in total."""

    result = []
    for entity in ("state", "reaction", "all"):
        selected = rows if entity == "all" else [row for row in rows if row["entity"] == entity]
        counts = Counter(row["verdict"] for row in selected)
        result.append(
            {
                "entity": entity,
                **{verdict: counts[verdict] for verdict in VERDICTS},
                "total": len(selected),
            }
        )
    return result


def verdict_counts_svg(layer: str, rows: list[dict]) -> str:
    """Render a layer profile with a direct data-supported interpretation."""

    summaries = summary_rows(rows)[:2]
    width, height = 1100, 520
    x0, bar_width, bar_height = 190, 820, 34
    parts = [_svg_start(width, height)]
    parts.extend(
        [
            _text(48, 50, f"{_layer_title(layer)} — assessment profile", 24, weight=600),
            _text(
                48,
                78,
                "Bar length is share within entity; the table gives exact count and percent.",
                13,
                color=MUTED,
            ),
            _rect(48, 98, 962, 52, "#F5F7F8", stroke=GRID, radius=7),
            _text(66, 130, _layer_insight(summaries), 14, weight=600),
        ]
    )
    for index, summary in enumerate(summaries):
        y = 185 + index * 135
        entity = str(summary["entity"]).title()
        total = int(summary["total"])
        parts.append(_text(48, y + 24, entity, 16, weight=600))
        parts.append(_text(48, y + 45, f"n={total}", 11, color=MUTED))
        if total == 0:
            parts.append(_rect(x0, y, bar_width, bar_height, "#F2F4F5", stroke=GRID))
            parts.append(_text(x0 + 14, y + 23, "not assessed", 13, color=MUTED))
        else:
            cursor = float(x0)
            for verdict in VERDICTS:
                count = int(summary[verdict])
                if count == 0:
                    continue
                segment = bar_width * count / total
                parts.append(_rect(cursor, y, segment, bar_height, COLORS[verdict]))
                if segment >= 54:
                    text_color = INK if verdict == "not_applicable" else "#FFFFFF"
                    parts.append(
                        _text(
                            cursor + segment / 2,
                            y + 23,
                            str(count),
                            11,
                            color=text_color,
                            anchor="middle",
                            weight=600,
                        )
                    )
                cursor += segment
            parts.append(_rect(x0, y, bar_width, bar_height, "none", stroke=INK))
        cell_width = bar_width / 4
        for verdict_index, verdict in enumerate(VERDICTS):
            count = int(summary[verdict])
            percent = 100 * count / total if total else 0
            cell_x = x0 + verdict_index * cell_width
            parts.append(_rect(cell_x, y + 48, cell_width - 8, 46, "#FAFBFC", stroke=GRID))
            parts.append(_rect(cell_x + 10, y + 62, 12, 12, COLORS[verdict], stroke=INK))
            parts.append(_text(cell_x + 29, y + 72, verdict, 10, weight=600))
            parts.append(
                _text(
                    cell_x + cell_width - 17,
                    y + 72,
                    f"{count} ({percent:.1f}%)" if total else "—",
                    10,
                    color=MUTED,
                    anchor="end",
                )
            )
    parts.append("</svg>")
    return "".join(parts)


def _layer_insight(summaries: list[dict]) -> str:
    reaction = summaries[1]
    state = summaries[0]
    focus = reaction if int(reaction["total"]) else state
    total = int(focus["total"])
    entity = str(focus["entity"])
    if total == 0:
        return "No candidates are assessed at this layer."
    failed = int(focus["fail"])
    unknown = int(focus["unknown"])
    passed = int(focus["pass"])
    if failed:
        return f"{failed}/{total} {entity} candidates fail; inspect failure reasons before use."
    if unknown:
        return f"{unknown}/{total} {entity} candidates remain unknown; evidence is the main gap."
    if passed == total:
        return f"All {total} assessed {entity} candidates pass this layer."
    return f"{passed}/{total} assessed {entity} candidates pass this layer."


def reaction_family_rows(layer: str, reactions: list[dict]) -> list[dict]:
    """Count reaction verdicts by physical reaction family."""

    families = sorted({str(reaction["family"]) for reaction in reactions})
    rows = []
    for family in families:
        selected = [reaction for reaction in reactions if reaction["family"] == family]
        counts = Counter(reaction["assessments"][layer]["verdict"] for reaction in selected)
        rows.append(
            {
                "family": family,
                **{verdict: counts[verdict] for verdict in VERDICTS},
                "total": len(selected),
            }
        )
    return rows


def reaction_family_svg(layer: str, reactions: list[dict]) -> str:
    """Show absolute reaction-family volume and verdict composition for one layer."""

    rows = reaction_family_rows(layer, reactions)
    width = 1100
    height = max(430, 245 + len(rows) * 72)
    x0, max_width = 215, 760
    maximum = max((int(row["total"]) for row in rows), default=1)
    parts = [_svg_start(width, height)]
    parts.extend(
        [
            _text(48, 50, f"{_layer_title(layer)} — reactions by family", 24, weight=600),
            _text(
                48,
                78,
                "Common count scale preserves family volume; segment color shows verdict.",
                13,
                color=MUTED,
            ),
            _rect(48, 98, 927, 52, "#F5F7F8", stroke=GRID, radius=7),
            _text(66, 130, _family_insight(rows), 14, weight=600),
        ]
    )
    for index, row in enumerate(rows):
        y = 185 + index * 72
        total = int(row["total"])
        parts.append(_text(48, y + 23, str(row["family"]).title(), 14, weight=600))
        parts.append(_rect(x0, y, max_width, 32, "#F0F2F3", stroke=GRID, radius=3))
        cursor = float(x0)
        for verdict in VERDICTS:
            count = int(row[verdict])
            if count == 0:
                continue
            segment = max_width * count / maximum
            parts.append(_rect(cursor, y, segment, 32, COLORS[verdict]))
            if segment >= 34:
                text_color = INK if verdict == "not_applicable" else "#FFFFFF"
                parts.append(
                    _text(
                        cursor + segment / 2,
                        y + 22,
                        str(count),
                        10,
                        color=text_color,
                        anchor="middle",
                        weight=600,
                    )
                )
            cursor += segment
        parts.append(_text(x0 + max_width + 14, y + 22, f"n={total}", 12, weight=600))
        detail = "  ".join(f"{verdict}={row[verdict]}" for verdict in VERDICTS)
        parts.append(_text(x0, y + 51, detail, 10, color=MUTED))
    legend_y = height - 28
    cursor = 215.0
    for verdict in VERDICTS:
        parts.append(_rect(cursor, legend_y - 11, 13, 13, COLORS[verdict], stroke=INK))
        parts.append(_text(cursor + 19, legend_y, verdict, 11))
        cursor += 145
    parts.append("</svg>")
    return "".join(parts)


def _family_insight(rows: list[dict]) -> str:
    if not rows:
        return "No reactions are assessed at this layer."
    unresolved = max(rows, key=lambda row: (int(row["fail"]) + int(row["unknown"]), row["family"]))
    gap = int(unresolved["fail"]) + int(unresolved["unknown"])
    if gap:
        return (
            f"Largest unresolved family: {unresolved['family']} "
            f"({gap}/{unresolved['total']} fail or unknown)."
        )
    largest = max(rows, key=lambda row: (int(row["total"]), row["family"]))
    return (
        f"All assessed families pass; largest family is {largest['family']} (n={largest['total']})."
    )


def statistics_rows(
    rows_by_layer: dict[str, list[dict]], states: list[dict], reactions: list[dict]
) -> list[dict]:
    """Return the tidy source table used by the all-layer statistics view."""

    rows = []
    for layer, assessed in rows_by_layer.items():
        for summary in summary_rows(assessed)[:2]:
            for verdict in VERDICTS:
                rows.append(
                    {
                        "metric": "assessment_verdict",
                        "layer": layer,
                        "entity": summary["entity"],
                        "category": verdict,
                        "count": summary[verdict],
                        "total": summary["total"],
                    }
                )

    for stage, count in _readiness_counts(reactions):
        rows.append(
            {
                "metric": "reaction_readiness",
                "layer": "cumulative",
                "entity": "reaction",
                "category": stage,
                "count": count,
                "total": len(reactions),
            }
        )

    state_charges = Counter(_charge_label(int(state["charge"])) for state in states)
    state_excitations = Counter(str(state["state_axes"]["excitation"]) for state in states)
    state_resolutions = Counter(str(state["state"]["resolution"]) for state in states)
    state_lifetimes = Counter(str(state["state_axes"]["lifetime_class"]) for state in states)
    reaction_families = Counter(str(reaction["family"]) for reaction in reactions)
    reaction_depths = Counter(str(reaction["depth"]) for reaction in reactions)
    for metric, entity, counts, total in (
        ("state_charge", "state", state_charges, len(states)),
        ("state_excitation", "state", state_excitations, len(states)),
        ("state_resolution", "state", state_resolutions, len(states)),
        ("state_lifetime_class", "state", state_lifetimes, len(states)),
        ("reaction_family", "reaction", reaction_families, len(reactions)),
        ("reaction_depth", "reaction", reaction_depths, len(reactions)),
    ):
        for category, count in sorted(counts.items(), key=_category_sort_key):
            rows.append(
                {
                    "metric": metric,
                    "layer": "all",
                    "entity": entity,
                    "category": category,
                    "count": count,
                    "total": total,
                }
            )
    return rows


def statistics_svg(
    rows_by_layer: dict[str, list[dict]], states: list[dict], reactions: list[dict]
) -> str:
    """Render cumulative readiness and independent assessment status."""

    width, height = 1280, 1120
    readiness = _readiness_counts(reactions)
    drops = [readiness[index - 1][1] - count for index, (_, count) in enumerate(readiness) if index]
    largest_drop_index = 1 + max(range(len(drops)), key=drops.__getitem__) if drops else 0
    parts = [_svg_start(width, height)]
    parts.extend(
        [
            _text(48, 52, "Overall assessment — reaction readiness", 25, weight=600),
            _text(
                48,
                82,
                "Cumulative bars require pass at every preceding layer; this is diagnostic, "
                "not a candidate-deletion pipeline.",
                13,
                color=MUTED,
            ),
            _rect(48, 102, 1135, 56, "#F5F7F8", stroke=GRID, radius=7),
            _text(66, 136, _readiness_insight(readiness), 14, weight=600),
            _text(48, 198, "Cumulative pass-only coverage", 18, weight=600),
        ]
    )
    maximum = max(1, len(reactions))
    for index, (stage, count) in enumerate(readiness):
        y = 220 + index * 47
        color = "#C56A2D" if index == largest_drop_index and index else "#2F6B9A"
        parts.append(_text(48, y + 20, stage, 12, weight=600))
        parts.append(_rect(270, y, 820, 28, "#EEF0F2", stroke=GRID, radius=3))
        parts.append(_rect(270, y, 820 * count / maximum, 28, color, radius=3))
        percent = 100 * count / maximum
        parts.append(_text(1105, y + 20, f"{count} ({percent:.1f}%)", 12, weight=600))

    parts.extend(
        _assessment_panel(
            "Independent reaction verdicts by layer", rows_by_layer, "reaction", 48, 535, 1184
        )
    )
    parts.append(_text(48, 850, "State-data coverage", 18, weight=600))
    state_layers = ("consistency", "state", "thermochemistry")
    for index, layer in enumerate(state_layers):
        summary = next(
            item for item in summary_rows(rows_by_layer[layer]) if item["entity"] == "state"
        )
        x = 48 + index * 390
        total = int(summary["total"])
        parts.append(_rect(x, 875, 360, 155, "#FAFBFC", stroke=GRID, radius=8))
        parts.append(_text(x + 18, 905, _layer_title(layer), 15, weight=600))
        parts.append(_text(x + 18, 934, f"pass  {summary['pass']} / {total}", 13))
        parts.append(_text(x + 18, 960, f"fail  {summary['fail']} / {total}", 13))
        parts.append(_text(x + 18, 986, f"unknown  {summary['unknown']} / {total}", 13))
        coverage = 100 * int(summary["pass"]) / total if total else 0
        parts.append(_text(x + 342, 1012, f"{coverage:.1f}% pass", 12, anchor="end", weight=600))
    parts.append("</svg>")
    return "".join(parts)


def composition_svg(states: list[dict], reactions: list[dict]) -> str:
    """Render generated candidate composition separately from assessment readiness."""

    width, height = 1280, 1135
    parts = [_svg_start(width, height)]
    parts.extend(
        [
            _text(48, 52, "Generated candidate composition", 25, weight=600),
            _text(
                48,
                82,
                "These counts describe generation breadth; they do not imply physical "
                "validation or numerical readiness.",
                13,
                color=MUTED,
            ),
            _text(48, 112, f"States: {len(states)}", 15, weight=600),
            _text(180, 112, f"Reactions: {len(reactions)}", 15, weight=600),
        ]
    )
    charges = Counter(_charge_label(int(state["charge"])) for state in states)
    excitations = Counter(str(state["state_axes"]["excitation"]) for state in states)
    resolutions = Counter(str(state["state"]["resolution"]) for state in states)
    lifetimes = Counter(str(state["state_axes"]["lifetime_class"]) for state in states)
    families = Counter(str(reaction["family"]) for reaction in reactions)
    depths = Counter(str(reaction["depth"]) for reaction in reactions)
    parts.extend(_category_panel("States by charge", charges, 48, 145, 550, 285))
    parts.extend(_category_panel("States by excitation", excitations, 650, 145, 550, 285))
    parts.extend(_category_panel("States by resolution", resolutions, 48, 475, 550, 285))
    parts.extend(_category_panel("States by lifetime class", lifetimes, 650, 475, 550, 285))
    parts.extend(_category_panel("Reactions by family", families, 48, 805, 550, 285))
    parts.extend(_category_panel("Reactions by generation depth", depths, 650, 805, 550, 285))
    parts.append("</svg>")
    return "".join(parts)


def screening_retention_svg(rows: list[dict]) -> str:
    """Render state and reaction retention through one ordered cumulative screen."""

    width, height = 1280, 700
    stage_rows = {
        entity: [row for row in rows if row["entity"] == entity] for entity in ("state", "reaction")
    }
    finals = {entity: selected[-1] for entity, selected in stage_rows.items()}
    parts = [_svg_start(width, height)]
    parts.extend(
        [
            _text(48, 50, "Cumulative screening retention", 25, weight=600),
            _text(48, 78, _screening_stage_title(stage_rows["reaction"]), 14, color=MUTED),
            _text(
                48,
                102,
                "Each applied step requires pass at that step and every preceding step; "
                "the CandidateSet is unchanged.",
                13,
                color=MUTED,
            ),
            _rect(48, 122, 1168, 54, "#F5F7F8", stroke=GRID, radius=7),
            _text(
                66,
                155,
                "Final retained: "
                f"{finals['state']['retained']}/{finals['state']['total']} states, "
                f"{finals['reaction']['retained']}/{finals['reaction']['total']} reactions.",
                14,
                weight=600,
            ),
        ]
    )
    parts.extend(_screening_panel("States", stage_rows["state"], 48, 205, 560))
    parts.extend(_screening_panel("Reactions", stage_rows["reaction"], 656, 205, 560))
    parts.append("</svg>")
    return "".join(parts)


def _screening_panel(title: str, rows: list[dict], x: float, y: float, width: float) -> list[str]:
    parts = [_rect(x, y, width, 420, "#FAFBFC", stroke=GRID, radius=8)]
    total = int(rows[0]["total"]) if rows else 0
    parts.append(_text(x + 18, y + 31, f"{title} · denominator n={total}", 17, weight=600))
    label_width = 160
    bar_x = x + label_width
    bar_width = width - label_width - 95
    for index, row in enumerate(rows):
        top = y + 56 + index * 55
        retained = int(row["retained"])
        rejected = int(row["rejected_at_step"])
        percent = 100 * retained / total if total else 0.0
        label_lines = _screening_step_label(row)
        for line_index, label in enumerate(label_lines):
            label_y = top + (13 if len(label_lines) > 1 else 19) + line_index * 13
            parts.append(_text(x + 17, label_y, label, 10, weight=600))
        parts.append(_rect(bar_x, top, bar_width, 27, "#EEF0F2", stroke=GRID, radius=3))
        fill = "#FFFFFF" if row["applicability"] == "not_applicable" else "#2F6B9A"
        stroke = "#7A8793" if row["applicability"] == "not_applicable" else "#2F6B9A"
        parts.append(
            _rect(
                bar_x,
                top,
                bar_width * retained / max(1, total),
                27,
                fill,
                stroke=stroke,
                radius=3,
            )
        )
        parts.append(
            _text(
                x + width - 16,
                top + 18,
                f"{retained} ({percent:.1f}%)",
                11,
                anchor="end",
                weight=600,
            )
        )
        if rejected:
            parts.append(
                _text(
                    bar_x + min(bar_width - 4, bar_width * retained / max(1, total) + 7),
                    top + 43,
                    f"-{rejected} at step",
                    10,
                    color="#A4582C",
                )
            )
        elif row["applicability"] == "not_applicable":
            parts.append(_text(bar_x + 7, top + 43, "not applied", 10, color=MUTED))
    return parts


def _screening_stage_title(rows: list[dict]) -> str:
    layers = [row["step"] for row in rows if row["step"] != "all"]
    return " → ".join(_screening_gate_label(str(layer)) for layer in layers)


def _screening_step_label(row: dict) -> list[str]:
    if row["step"] == "all":
        return ["All candidates"]
    label = _screening_gate_label(str(row["step"]))
    prefix = "" if row["applicability"] == "not_applicable" else "+ "
    suffix = " (N/A)" if row["applicability"] == "not_applicable" else " pass"
    if " OR " in label:
        left, right = label.split(" OR ", maxsplit=1)
        return [f"{prefix}{left} OR", f"{right}{suffix}"]
    return [f"{prefix}{label}{suffix}"]


def _screening_gate_label(value: str) -> str:
    return " OR ".join(part.replace("_", " ").title() for part in value.split("_or_"))


def _readiness_counts(reactions: list[dict]) -> list[tuple[str, int]]:
    stages = [
        ("All reaction candidates", None),
        ("Consistency pass", "consistency"),
        ("+ State pass", "state"),
        ("+ Thermochemistry pass", "thermochemistry"),
        ("+ Reaction evidence pass", "reaction_evidence"),
        ("+ Kinetics pass", "kinetics"),
    ]
    active = list(reactions)
    result = []
    for label, layer in stages:
        if layer is not None:
            active = [
                reaction
                for reaction in active
                if reaction["assessments"][layer]["verdict"] == "pass"
            ]
        result.append((label, len(active)))
    return result


def _readiness_insight(readiness: list[tuple[str, int]]) -> str:
    if not readiness or readiness[0][1] == 0:
        return "No reaction candidates are available for readiness assessment."
    total = readiness[0][1]
    final = readiness[-1][1]
    drops = [readiness[index - 1][1] - count for index, (_, count) in enumerate(readiness) if index]
    largest = max(range(len(drops)), key=drops.__getitem__)
    bottleneck = readiness[largest + 1][0].removeprefix("+ ")
    return (
        f"{final}/{total} reactions pass all five layers; largest cumulative loss is at "
        f"{bottleneck} (-{drops[largest]})."
    )


def _assessment_panel(
    title: str,
    rows_by_layer: dict[str, list[dict]],
    entity: str,
    x: float,
    y: float,
    width: float,
) -> list[str]:
    parts = [_text(x, y, title, 18, weight=600)]
    bar_x = x + 245
    bar_width = width - 350
    for index, (layer, rows) in enumerate(rows_by_layer.items()):
        top = y + 30 + index * 45
        summary = next(item for item in summary_rows(rows) if item["entity"] == entity)
        total = int(summary["total"])
        parts.append(_text(x, top + 20, _layer_title(layer), 13))
        if total == 0:
            parts.append(_rect(bar_x, top, bar_width, 28, "#F2F4F5", stroke=GRID, radius=3))
            parts.append(_text(bar_x + 10, top + 19, "not assessed", 11, color=MUTED))
        else:
            cursor = bar_x
            for verdict in VERDICTS:
                count = int(summary[verdict])
                if count == 0:
                    continue
                segment = bar_width * count / total
                parts.append(_rect(cursor, top, segment, 28, COLORS[verdict]))
                if segment >= 55:
                    text_color = INK if verdict == "not_applicable" else "#FFFFFF"
                    parts.append(
                        _text(
                            cursor + segment / 2,
                            top + 19,
                            str(count),
                            11,
                            color=text_color,
                            anchor="middle",
                            weight=600,
                        )
                    )
                cursor += segment
            parts.append(_rect(bar_x, top, bar_width, 28, "none", stroke=INK, radius=3))
        parts.append(_text(bar_x + bar_width + 12, top + 20, f"n={total}", 12, weight=600))

    legend_y = y + 278
    cursor = bar_x
    for verdict in VERDICTS:
        parts.append(_rect(cursor, legend_y - 11, 13, 13, COLORS[verdict], stroke=INK))
        parts.append(_text(cursor + 19, legend_y, verdict, 11))
        cursor += 140
    return parts


def _category_panel(
    title: str,
    counts: Counter[str],
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[str]:
    parts = [_rect(x, y, width, height, "#FAFBFC", stroke=GRID, radius=8)]
    parts.append(_text(x + 18, y + 30, title, 17, weight=600))
    ordered = sorted(counts.items(), key=_category_sort_key)
    maximum = max(counts.values(), default=1)
    label_width = 105
    bar_x = x + label_width
    bar_width = width - label_width - 45
    spacing = min(34, 245 / max(1, len(ordered)))
    for index, (category, count) in enumerate(ordered):
        top = y + 55 + index * spacing
        parts.append(_text(x + 16, top + 15, category, 12))
        parts.append(_rect(bar_x, top, bar_width, 20, "#EEF0F2", radius=2))
        parts.append(_rect(bar_x, top, bar_width * count / maximum, 20, "#4C7899", radius=2))
        parts.append(_text(x + width - 15, top + 15, str(count), 12, anchor="end", weight=600))
    return parts


def _category_sort_key(item: tuple[str, int]) -> tuple[int, int | str]:
    category = item[0]
    try:
        return (0, int(category))
    except ValueError:
        return (1, category)


def _charge_label(charge: int) -> str:
    if charge == 0:
        return "neutral (0)"
    if charge == -1:
        return "negative (-1)"
    if charge == 1:
        return "positive (+1)"
    return f"charge {charge:+d}"


def _layer_title(layer: str) -> str:
    return layer.replace("_", " ").title()


def _svg_start(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        '<rect width="100%" height="100%" fill="#FFFFFF"/>'
    )


def _text(
    x: float,
    y: float,
    value: str,
    size: int,
    *,
    color: str = INK,
    anchor: str = "start",
    weight: int = 400,
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    fill: str,
    *,
    stroke: str = "none",
    radius: float = 0,
) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
        f'rx="{radius:.1f}" fill="{fill}" stroke="{stroke}"/>'
    )
