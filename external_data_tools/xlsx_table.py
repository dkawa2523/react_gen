"""Read sparse tabular rows from an XLSX workbook without spreadsheet semantics."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from defusedxml import ElementTree

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

CellValue = float | str | None


def read_xlsx_rows(path: str | Path, sheet_name: str) -> list[list[CellValue]]:
    """Return a worksheet as rows while preserving sparse column positions."""

    with ZipFile(path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        worksheet_path = _worksheet_path(workbook, sheet_name)
        root = ElementTree.fromstring(workbook.read(worksheet_path))

    rows: list[list[CellValue]] = []
    for row in root.findall(f".//{{{MAIN_NS}}}row"):
        indexed_cells = {
            _column_index(cell.attrib["r"]): _cell_value(cell, shared_strings)
            for cell in row.findall(f"{{{MAIN_NS}}}c")
        }
        width = max(indexed_cells, default=-1) + 1
        rows.append([indexed_cells.get(index) for index in range(width)])
    return rows


def _read_shared_strings(workbook: ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read(path))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def _worksheet_path(workbook: ZipFile, sheet_name: str) -> str:
    root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    relation_id = next(
        (
            sheet.attrib[f"{{{DOCUMENT_REL_NS}}}id"]
            for sheet in root.findall(f".//{{{MAIN_NS}}}sheet")
            if sheet.attrib.get("name") == sheet_name
        ),
        None,
    )
    if relation_id is None:
        raise ValueError(f"worksheet not found: {sheet_name}")

    relationships = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    target = next(
        (
            relation.attrib["Target"]
            for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            if relation.attrib.get("Id") == relation_id
        ),
        None,
    )
    if target is None:
        raise ValueError(f"worksheet relationship not found: {sheet_name}")
    return _safe_workbook_path(target)


def _safe_workbook_path(target: str) -> str:
    relative = PurePosixPath(target.lstrip("/"))
    path = relative if relative.parts[:1] == ("xl",) else PurePosixPath("xl") / relative
    if ".." in path.parts or path.parts[:1] != ("xl",):
        raise ValueError(f"unsafe worksheet path: {target}")
    return path.as_posix()


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha()).upper()
    if not letters:
        raise ValueError(f"invalid cell reference: {reference}")
    value = 0
    for character in letters:
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _cell_value(cell, shared_strings: list[str]) -> CellValue:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))

    value = cell.find(f"{{{MAIN_NS}}}v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        return shared_strings[int(value.text)]
    if cell_type in {"str", "e"}:
        return value.text
    return float(value.text)
