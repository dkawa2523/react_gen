"""External format declarations must survive conversion without relabelling."""

import csv
from pathlib import Path

import pytest

from acquire import lxcat, snapshot
from acquire.cli import main


def block(columns: str = "Energy (eV) | Cross section (m2)", row: str = "1 2e-20") -> str:
    return f"ELASTIC\nAr\nCOLUMNS: {columns}\n-----\n0 1e-20\n{row}\n-----\n"


@pytest.mark.parametrize(
    "columns",
    [
        "Energy (keV) | Cross section (m2)",
        "Energy (eV) | Cross section (cm2)",
        "Temperature (K) | Cross section (m2)",
        "Cross section (m2) | Energy (eV)",
    ],
)
def test_explicit_unit_or_quantity_mismatch_is_not_relabelled(
    tmp_path: Path, capsys, columns: str
) -> None:
    path = tmp_path / "source.txt"
    path.write_text(block() + block(columns), encoding="utf-8")
    output = tmp_path / "converted"
    assert main(["lxcat", str(path), "--out", str(output)]) == 2
    assert "expected COLUMNS" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "columns", ["Energy (eV) | Cross-section (m^2)", "Energy (eV) | Cross section (m²)"]
)
def test_equivalent_standard_column_spellings_are_accepted(tmp_path: Path, columns: str) -> None:
    path = tmp_path / "source.txt"
    path.write_text(block(columns), encoding="utf-8")
    assert lxcat.parse(path)[0].table == [(0, 1e-20), (1, 2e-20)]


@pytest.mark.parametrize("row", ["1 invalid", "1", "1 2e-20 3"])
def test_malformed_table_rows_are_not_dropped(tmp_path: Path, row: str) -> None:
    path = tmp_path / "source.txt"
    path.write_text(block(row=row), encoding="utf-8")
    with pytest.raises(ValueError, match="table row"):
        lxcat.parse(path)


def test_headerless_fixed_format_remains_supported(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text(
        block().replace("COLUMNS: Energy (eV) | Cross section (m2)\n", ""), encoding="utf-8"
    )
    assert lxcat.parse(path)[0].table == [(0, 1e-20), (1, 2e-20)]


def test_table_conversion_retains_all_parsed_precision(tmp_path: Path) -> None:
    rows = [(1.23456789012345, 2.34567890123456e-25)]
    relative = snapshot.write_table(tmp_path, "precision", rows, "energy_eV,cross_section_m2")
    with (tmp_path / relative).open(encoding="utf-8", newline="") as stream:
        table = list(csv.reader(stream))[1:]
    assert [tuple(map(float, row)) for row in table] == rows


@pytest.mark.parametrize("value", [True, "1"])
def test_internal_table_values_are_checked_before_output(tmp_path: Path, value) -> None:
    with pytest.raises(ValueError, match="must be numbers"):
        snapshot.write_table(tmp_path, "invalid", [(1, value)], "x,y")
    assert not (tmp_path / "assets").exists()
