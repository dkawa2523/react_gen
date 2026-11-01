"""Convert NIST WebBook species pages without choosing or approving a value.

Only gas formation enthalpies and IE/EA tables enter existing Property records.
Other quantities (including Shomate coefficients and appearance energies) stay
in the raw page; they are not interchangeable with these quantities. Multiple
determinations remain separate. Units, references, qualifications and identity
are retained for the common ingestion/review path.

Source formats and definitions:
https://webbook.nist.gov/chemistry/guide/
https://webbook.nist.gov/chemistry/ion/
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlencode

from acquire.targets import GroundRequest, records_for
from reactgen.naming import parse_formula

ROOT = "https://webbook.nist.gov"
TABLE = re.compile(r"<table\b([^>]*)>(.*?)</table>", re.I | re.S)
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
TAG = re.compile(r"<[^>]*>", re.S)
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
VALUE = re.compile(rf"(?P<qualifier>[<>≤≥~≈]?)\s*(?P<value>{NUMBER})(?:\s*±\s*(?P<unc>{NUMBER}))?")


@dataclass(frozen=True)
class Page:
    identity: dict
    properties: list[dict]


def url(identifier: str) -> str:
    """Use an explicit WebBook ID/CAS; formula and fuzzy-name lookup is separate."""
    if re.fullmatch(r"\d+-\d+-\d+", identifier):
        identifier = "C" + identifier.replace("-", "")
    if not re.fullmatch(r"C\d+", identifier):
        raise ValueError("WebBook query must be an explicit CAS number or C-prefixed WebBook ID")
    return ROOT + "/cgi/cbook.cgi?" + urlencode({"ID": identifier, "Mask": 21, "Units": "SI"})


def _text(body: str) -> str:
    return " ".join(unescape(TAG.sub("", body)).replace("\xa0", " ").split())


def parse(body: str) -> Page:
    """Read one identified page, refusing search results and changed table layouts."""
    identity = _identity(body)
    records = []
    for attributes, table in TABLE.findall(body):
        match = re.search(r'aria-label=["\'](.*?)["\']', attributes, re.I)
        label = unescape(match.group(1)) if match else ""
        for row_index, row in enumerate(ROW.findall(table)):
            cells_html = CELL.findall(row)
            cells = [_text(cell) for cell in cells_html]
            if not cells or "<th" in row.lower():
                continue
            record = _property(label, cells)
            if record is None:
                continue
            record["source_declaration"] = record["source_declaration"] | {
                "identity": identity,
                "table": label,
                "row_index": row_index,
                "cells": cells,
                "links": [unescape(link) for link in re.findall(r'href=["\'](.*?)["\']', row)],
            }
            records.append(record)
    return Page(identity, records)


def _identity(body: str) -> dict:
    identity: dict = {}
    for raw in re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        body,
        re.I | re.S,
    ):
        entity = json.loads(raw)
        if isinstance(entity, dict) and entity.get("@type") == "MolecularEntity":
            if identity:
                raise ValueError("WebBook page contains multiple species identities")
            identity = entity
    if not parse_formula(str(identity.get("molecularFormula", ""))):
        raise ValueError(
            "WebBook page must identify one species with a supported molecular formula"
        )
    cas = re.search(r"CAS Registry Number:</strong>\s*([0-9-]+)", body)
    if cas is not None:
        identity = identity | {"cas": cas.group(1)}
    other_names = re.search(r"Other names:</strong>(.*?)</li>", body, re.I | re.S)
    if other_names is not None:
        identity = identity | {"other_names": _text(other_names.group(1)).split(";")}

    return identity


def _property_cells(label: str, cells: list[str]) -> tuple[str, ...] | None:
    if label == "One dimensional data":
        if len(cells) != 6:
            raise ValueError("WebBook one-dimensional data row must have six columns")
        return tuple(cells)
    elif label in {"Ionization energy determinations", "Electron affinity determinations"}:
        if len(cells) != 4:
            raise ValueError("WebBook IE/EA row must have four columns")
        raw_value, method, reference, comment = cells
        quantity = "IE" if label.startswith("Ionization") else "EA"
        return quantity, raw_value, "eV", method, reference, comment
    return None


def _energy_value(raw_value: str, unit: str, quantity: str) -> dict:
    parsed = VALUE.fullmatch(raw_value)
    if parsed is None:
        raise ValueError(f"unsupported WebBook {quantity} value: {raw_value!r}")
    factor = {"eV": 1.0, "kJ/mol": 1000 / 96485.33212, "J/mol": 1 / 96485.33212}.get(unit)
    if factor is None:
        raise ValueError(f"unsupported WebBook {quantity} unit: {unit!r}")
    value = float(parsed["value"]) * factor
    uncertainty = float(parsed["unc"]) * factor if parsed["unc"] else None
    if not math.isfinite(value) or (uncertainty is not None and not math.isfinite(uncertainty)):
        raise ValueError("WebBook values must be finite")
    result: dict = {"value": value, "unit": "eV", "status": "imported"}
    if uncertainty is not None:
        if uncertainty < 0:
            raise ValueError("WebBook uncertainty must be nonnegative")
        result["uncertainty"] = {"absolute": uncertainty, "unit": "eV"}
    if parsed["qualifier"]:
        result["qualifier"] = parsed["qualifier"]
    return result


def _property(label: str, cells: list[str]) -> dict | None:
    extracted = _property_cells(label, cells)
    if extracted is None:
        return None
    quantity, raw_value, unit, method, reference, comment = extracted

    compact = quantity.replace(" ", "")
    formation = compact in {"ΔfH°gas", "ΔfH°gas,0K"}
    name = {
        "ΔfH°gas": "enthalpy_formation_eV",
        "ΔfH°gas,0K": "enthalpy_formation_eV",
        "IE": "ionization_energy_eV",
        "IE(evaluated)": "ionization_energy_eV",
        "EA": "electron_affinity_eV",
        "EA(evaluated)": "electron_affinity_eV",
    }.get(compact)
    if name is None:
        return None
    result = _energy_value(raw_value, unit, quantity) | {"property": name}
    if not formation and "vertical" in comment.lower():
        result["definition"] = "vertical"
    elif not formation and "adiabatic" in comment.lower():
        result["definition"] = "adiabatic"
    if formation:
        # "Standard conditions" is not an explicit reference temperature;
        # only the separate 0 K quantity supplies a temperature here.
        result["formation_reference"] = {
            "temperature_K": 0.0 if compact.endswith(",0K") else None,
            "basis": "standard_elements",
        }
    if "evaluated" in quantity or method in {"Review", "EVAL"}:
        result["method"] = "evaluated"
    if label in {"Ionization energy determinations", "Electron affinity determinations"}:
        # The page groups determinations with different precursor states: the
        # N2 page includes a metastable ionization measurement among its IE
        # rows. Their initial state needs the cited original source; a formula
        # match and a blank Comment must not assert ground-state applicability.
        result["qualifier"] = "source_state_unconfirmed"
    result["source"] = {
        "provider": "nist_webbook",
        "collection": "SRD69",
        "citation": reference if reference != "N/A" else "NIST Chemistry WebBook, SRD 69",
    }
    result["source_declaration"] = {"quantity": quantity, "method": method, "comment": comment}
    return result


def records(page: Page, request: GroundRequest, source_url: str) -> list[dict]:
    """Assign the requested target only after checking composition; do not approve it."""
    formula = str(page.identity["molecularFormula"])
    if parse_formula(formula) != request.target.composition:
        raise ValueError("WebBook source composition differs from the requested target")
    if page.identity.get("cas") is not None and url(str(page.identity["cas"])) != source_url:
        raise ValueError("WebBook page identity differs from the explicit source query")
    out = []
    for row in page.properties:
        declaration = row["source_declaration"]
        row_digest = hashlib.sha256(
            json.dumps(declaration["cells"], ensure_ascii=True).encode("utf-8")
        ).hexdigest()[:20]
        source = row["source"] | {
            "url": source_url,
        }
        # The WebBook identifies species, but does not publish unique IDs for
        # these determinations. This converter's row key is not a native ID.
        out.append(
            row
            | {
                "source": source,
                "source_species": page.identity.get("name", formula),
                "source_declaration": declaration
                | {
                    "derived_row_key": row_digest,
                    "derived_row_key_rule": "first 20 SHA256 hex characters of ASCII JSON cells",
                    "native_quantity_record_id": None,
                },
            }
        )
    return records_for(request, out, identity=page.identity)
