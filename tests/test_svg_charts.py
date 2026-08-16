from __future__ import annotations

from plasma_reactgen.visualization.svg_charts import (
    write_grouped_bar_chart,
    write_horizontal_bar_chart,
)


def test_horizontal_chart_sorts_limits_and_aggregates_remaining_values(tmp_path):
    output = tmp_path / "horizontal.svg"

    write_horizontal_bar_chart(
        output,
        "Counts",
        {"B": 3, "A": 5, "C": 2, "zero": 0},
        max_items=2,
        color_map={"A": "#123456"},
    )

    svg = output.read_text(encoding="utf-8")
    assert svg.index(">A</text>") < svg.index(">B</text>")
    assert "<title>A: 5</title>" in svg
    assert "fill='#123456'" in svg
    assert "<title>Other: 2</title>" in svg
    assert "zero" not in svg


def test_horizontal_chart_writes_explicit_no_data_state(tmp_path):
    output = tmp_path / "empty.svg"

    write_horizontal_bar_chart(output, "Empty", {})

    svg = output.read_text(encoding="utf-8")
    assert "No data" in svg
    assert "<title>No data: 0</title>" in svg


def test_grouped_chart_writes_bars_labels_and_wrapped_legend(tmp_path):
    output = tmp_path / "grouped.svg"
    series = {
        "depth 0": {"long-electron-category": 4, "long-ion-category": 2},
        "depth 1": {"long-electron-category": 1, "long-ion-category": 3},
    }

    write_grouped_bar_chart(output, "Grouped", series, width=420)

    svg = output.read_text(encoding="utf-8")
    assert "<title>depth 0 / long-electron-category: 4</title>" in svg
    assert "<title>depth 1 / long-ion-category: 3</title>" in svg
    assert "long-electron-category" in svg
    assert "long-ion-category" in svg


def test_empty_grouped_chart_uses_horizontal_no_data_rendering(tmp_path):
    output = tmp_path / "empty-grouped.svg"

    write_grouped_bar_chart(output, "Empty grouped", {})

    svg = output.read_text(encoding="utf-8")
    assert "Horizontal bar chart with count axis." in svg
    assert "No data" in svg
