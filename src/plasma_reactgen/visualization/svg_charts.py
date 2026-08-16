from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from plasma_reactgen.visualization.svg_chart_layout import (
    build_grouped_bar_layout,
    build_horizontal_bar_layout,
)
from plasma_reactgen.visualization.svg_chart_primitives import prepare_svg_output, write_svg
from plasma_reactgen.visualization.svg_grouped_bar import render_grouped_bar_chart
from plasma_reactgen.visualization.svg_horizontal_bar import render_horizontal_bar_chart


def write_horizontal_bar_chart(
    path: str | Path,
    title: str,
    values: Mapping[str, int | float],
    *,
    subtitle: str | None = None,
    color_map: Mapping[str, str] | None = None,
    width: int = 1120,
    min_height: int = 300,
    sort_by_value: bool = True,
    max_items: int | None = None,
) -> None:
    """Write a dependency-free, publication-oriented horizontal SVG chart."""

    output = prepare_svg_output(path)
    layout = build_horizontal_bar_layout(
        values,
        has_subtitle=subtitle is not None,
        width=width,
        min_height=min_height,
        sort_by_value=sort_by_value,
        max_items=max_items,
    )
    write_svg(output, render_horizontal_bar_chart(output, title, subtitle, layout, color_map))


def write_grouped_bar_chart(
    path: str | Path,
    title: str,
    series: Mapping[str, Mapping[str, int | float]],
    *,
    subtitle: str | None = None,
    color_map: Mapping[str, str] | None = None,
    width: int = 1080,
    min_height: int = 440,
) -> None:
    """Write a grouped SVG chart for small group-by-category summaries."""

    if not series:
        write_horizontal_bar_chart(
            path,
            title,
            {},
            subtitle=subtitle,
            color_map=color_map,
            width=width,
            min_height=min_height,
        )
        return

    output = prepare_svg_output(path)
    layout = build_grouped_bar_layout(
        series,
        has_subtitle=subtitle is not None,
        width=width,
        min_height=min_height,
    )
    write_svg(
        output,
        render_grouped_bar_chart(output, title, subtitle, layout, series, color_map),
    )
