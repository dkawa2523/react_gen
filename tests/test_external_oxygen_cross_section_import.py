from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import yaml

from external_data_tools.oxygen_cross_sections import TARGETS, parse_oxygen_cross_section
from external_data_tools.registry_oxygen_import import (
    import_oxygen_cross_section_file,
    import_oxygen_cross_sections,
)
from external_data_tools.xlsx_table import read_xlsx_rows


def test_oxygen_parser_converts_source_units_and_preserves_uncertainty(tmp_path: Path) -> None:
    workbook = _write_workbook(tmp_path / "oxygen.xlsx")

    rows = parse_oxygen_cross_section(workbook, TARGETS[0])

    assert rows == [
        {
            "energy_eV": 1.0,
            "cross_section_m2": pytest.approx(2.0e-20),
            "uncertainty_percent": 5.0,
        },
        {
            "energy_eV": 2.0,
            "cross_section_m2": pytest.approx(3.0e-20),
            "uncertainty_percent": 4.0,
        },
    ]


def test_oxygen_import_attaches_seven_process_tables_to_six_channels(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "registry")
    workbook = _write_workbook(tmp_path / "oxygen.xlsx")

    result = import_oxygen_cross_section_file(workbook, registry_root=registry)

    assert result["summary"] == {"n_requested": 7, "n_applied": 7, "n_review": 0}
    reaction = _read_yaml(registry / "reactions" / "electron" / "e__O2.yaml")
    datasets = {
        channel["id"]: channel.get("data", {}).get("datasets", [])
        for channel in reaction["channels"]
    }
    assert len(datasets["e_O2_elastic"]) == 2
    assert [item["preferred"] for item in datasets["e_O2_elastic"]] == [False, True]
    assert all(len(items) == 1 for key, items in datasets.items() if key != "e_O2_elastic")
    assert all("cross_section" not in channel.get("data", {}) for channel in reaction["channels"])
    assert all((registry / item["asset_path"]).is_file() for item in result["results"])
    assert all(item["row_count"] == 2 for item in result["results"])

    repeated = import_oxygen_cross_section_file(workbook, registry_root=registry)

    assert repeated["summary"] == {"n_requested": 7, "n_applied": 0, "n_review": 0}


def test_oxygen_workflow_downloads_once_and_writes_report(tmp_path: Path, monkeypatch) -> None:
    registry = _write_registry(tmp_path / "registry")
    fixture = _write_workbook(tmp_path / "fixture.xlsx")
    requested_urls: list[str] = []

    def download_fixture(url: str, destination: Path) -> dict[str, str]:
        requested_urls.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fixture.read_bytes())
        return {"downloaded_at": "2026-08-14T00:00:00Z"}

    monkeypatch.setattr(
        "external_data_tools.registry_oxygen_import.download_url",
        download_fixture,
    )
    reports = tmp_path / "reports"

    result = import_oxygen_cross_sections(registry_root=registry, report_dir=reports)

    assert len(requested_urls) == 1
    assert result["summary"]["n_applied"] == 7
    assert _read_yaml(reports / "oxygen_cross_section_import.yaml")["summary"] == result["summary"]
    metadata_path = registry / result["results"][0]["asset_path"]
    metadata = _read_yaml(metadata_path.with_suffix(".metadata.yaml"))
    assert metadata["downloaded_at"] == "2026-08-14T00:00:00Z"
    assert metadata["conversion"] == "1e-16 cm2 = 1e-20 m2"


def test_oxygen_parser_rejects_invalid_numeric_tables(tmp_path: Path) -> None:
    negative = _write_workbook(
        tmp_path / "negative.xlsx",
        values=((1.0, -1.0, 5.0), (2.0, 3.0, 4.0)),
    )
    with pytest.raises(ValueError, match="non-negative"):
        parse_oxygen_cross_section(negative, TARGETS[0])

    non_monotonic = _write_workbook(
        tmp_path / "non_monotonic.xlsx",
        values=((2.0, 2.0, 5.0), (1.0, 3.0, 4.0)),
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_oxygen_cross_section(non_monotonic, TARGETS[0])


def test_xlsx_reader_rejects_missing_sheet_and_unsafe_relationship(tmp_path: Path) -> None:
    workbook = _write_workbook(tmp_path / "oxygen.xlsx")
    with pytest.raises(ValueError, match="worksheet not found"):
        read_xlsx_rows(workbook, "missing")

    unsafe = _write_workbook(tmp_path / "unsafe.xlsx", first_target="../outside.xml")
    with pytest.raises(ValueError, match="unsafe worksheet path"):
        read_xlsx_rows(unsafe, TARGETS[0].sheet)


def _write_registry(root: Path) -> Path:
    path = root / "reactions" / "electron" / "e__O2.yaml"
    _write_yaml(
        path,
        {
            "pair": {"family": "electron", "projectile": "e", "target": "O2"},
            "channels": [
                {
                    "id": reaction_id,
                    "type": "test",
                    "products": [{"species": "O2", "n": 1}],
                    "data": {"cross_section": {"path": None, "status": "needs_import"}},
                }
                for reaction_id in dict.fromkeys(item.reaction_id for item in TARGETS)
            ],
        },
    )
    return root


def _write_workbook(
    path: Path,
    *,
    values: tuple[tuple[float, float, float], ...] = (
        (1.0, 2.0, 5.0),
        (2.0, 3.0, 4.0),
    ),
    first_target: str = "worksheets/sheet1.xml",
) -> Path:
    unique_sheets = list(dict.fromkeys(target.sheet for target in TARGETS))
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(unique_sheets, start=1)
    )
    relationships = "".join(
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="{first_target if index == 1 else target}"/>'
        )
        for index, target in enumerate(
            (f"worksheets/sheet{number}.xml" for number in range(1, len(unique_sheets) + 1)),
            start=1,
        )
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        for index, sheet_name in enumerate(unique_sheets, start=1):
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                _worksheet_xml(values, electronic=sheet_name == "electronic excitation"),
            )
    return path


def _worksheet_xml(
    values: tuple[tuple[float, float, float], ...],
    *,
    electronic: bool,
) -> str:
    rows = [
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Energy (eV)</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Cross section</t></is></c></row>'
    ]
    for index, (energy, cross_section, uncertainty) in enumerate(values, start=2):
        second_state = (
            f'<c r="D{index}"><v>{energy}</v></c><c r="E{index}"><v>{cross_section / 2}</v></c>'
            if electronic
            else ""
        )
        rows.append(
            f'<row r="{index}"><c r="A{index}"><v>{energy}</v></c>'
            f'<c r="B{index}"><v>{cross_section}</v></c>'
            f'<c r="C{index}"><v>{uncertainty}</v></c>{second_state}</row>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
