"""Read CollisionDB's JSON-header/two-column downloaded datasets.

The published exchange format is described in Atoms 12 (2024), 20,
https://doi.org/10.3390/atoms12030020 and the source's submission specification:
https://db-amdis.org/collisiondb/submitting-data/ . Only integral cross-section
tables with supported energy/area units are converted. Stateful PyValem names,
frame, channels, fit declarations and uncertainties remain available verbatim;
this adapter neither resolves their identity nor runs downloaded fit code.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from acquire import snapshot


@dataclass(frozen=True)
class Dataset:
    metadata: dict
    rows: list[tuple[float, float]]
    point_uncertainties: list[dict]


def parse(path: Path) -> Dataset:
    """Validate the declared coordinates before converting any numerical values."""
    body = path.read_text(encoding="utf-8")
    split = re.split(r"^\s*-{5,}\s*$", body, maxsplit=1, flags=re.M)
    if len(split) != 2:
        raise ValueError("CollisionDB file requires a JSON metadata header and separator")
    metadata = json.loads(split[0])
    x_factor, y_factor = _column_factors(metadata)
    rows: list[tuple[float, float]] = []
    uncertainty: list[dict] = []
    for raw in split[1].splitlines():
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        energy, sigma, errors = _point(line, x_factor, y_factor)
        if rows and energy <= rows[-1][0]:
            raise ValueError("CollisionDB energy grid must be strictly increasing")
        rows.append((energy, sigma))
        if errors:
            uncertainty.append({"energy_eV": energy, "absolute_m2": errors})
    if len(rows) < 2:
        raise ValueError("CollisionDB table must contain at least two points")
    return Dataset(metadata, rows, uncertainty)


def _column_factors(metadata: object) -> tuple[float, float]:
    if not isinstance(metadata, dict):
        raise ValueError("CollisionDB metadata must be a mapping")
    if metadata.get("data_type") != "cross section":
        raise ValueError("only CollisionDB integral cross-section tables are supported")
    reaction = metadata.get("reaction")
    if not isinstance(reaction, str) or not reaction.strip():
        raise ValueError("CollisionDB metadata requires its stateful source reaction")
    combined = _metadata_fields(metadata)
    _require_energy_frame(combined, reaction)
    columns = combined.get("columns")
    if (
        not isinstance(columns, list)
        or len(columns) != 2
        or any(not isinstance(column, dict) for column in columns)
    ):
        raise ValueError("CollisionDB requires exactly two declared columns")
    if columns[0].get("name") != "E" or columns[1].get("name") != "sigma":
        raise ValueError("CollisionDB columns must be E and sigma")
    x_factor = {"eV": 1.0, "keV": 1000.0}.get(columns[0].get("units"))
    y_factor = {"m2": 1.0, "cm2": 1e-4}.get(columns[1].get("units"))
    if x_factor is None or y_factor is None:
        raise ValueError("unsupported CollisionDB energy or cross-section unit")
    return x_factor, y_factor


def _metadata_fields(metadata: dict) -> dict:
    declarations = metadata.get("json_data", {})
    if not isinstance(declarations, dict):
        raise ValueError("CollisionDB json_data must be a mapping")
    for name in ("columns", "frame", "threshold", "method", "fit", "unc_perc", "data_from_fit"):
        if name in declarations and name in metadata and declarations[name] != metadata[name]:
            raise ValueError(f"CollisionDB nested and outer {name} declarations conflict")
    combined = declarations | metadata
    if "data_from_fit" in combined and type(combined["data_from_fit"]) is not bool:
        raise ValueError("CollisionDB data_from_fit must be a boolean")
    return combined


def _require_energy_frame(metadata: dict, reaction: str) -> None:
    """Heavy-particle energies require the source's com/target declaration."""
    left = re.split(r"→|->", reaction, maxsplit=1)[0].strip()
    electron = re.search(r"(?:^|\s\+\s)(?:\d+\s*)?e-(?=$|\s\+\s)", left) is not None
    frame = metadata.get("frame")
    if not electron and frame is None:
        raise ValueError(
            "CollisionDB heavy-particle cross section requires its source energy frame"
        )
    if frame is not None and frame not in {"target", "com"}:
        raise ValueError("CollisionDB energy frame must be target or com")


def _point(line: str, x_factor: float, y_factor: float) -> tuple[float, float, list[float]]:
    parts = line.split()
    if len(parts) != 2:
        raise ValueError("CollisionDB row requires exactly two columns")
    pieces = parts[1].split(":")
    if len(pieces) > 3:
        raise ValueError("CollisionDB row has invalid uncertainty syntax")
    try:
        energy, sigma = float(parts[0]) * x_factor, float(pieces[0]) * y_factor
    except ValueError as error:
        raise ValueError("CollisionDB row has an unsupported or missing value") from error
    if not math.isfinite(energy) or not math.isfinite(sigma) or energy < 0 or sigma < 0:
        raise ValueError("CollisionDB row requires finite nonnegative values")
    errors = []
    if len(pieces) > 1:
        written = ":".join(pieces[1:]).replace(":", ",").split(",")
        if len(written) not in {1, 2}:
            raise ValueError("CollisionDB point uncertainty must have one or two bounds")
        try:
            errors = [float(value) * y_factor for value in written]
        except ValueError as error:
            raise ValueError("CollisionDB point uncertainty must be numeric") from error
        if any(not math.isfinite(value) or value < 0 for value in errors):
            raise ValueError("CollisionDB point uncertainty must be finite and nonnegative")
    return energy, sigma, errors


def record(
    item: Dataset,
    outdir: Path,
    *,
    reaction: str | None = None,
    process_type: str | None = None,
    independent_variable: str | None = None,
    observable: str | None = None,
    channel_scope: str = "unknown",
) -> dict:
    """Preserve unresolved source meanings; explicit mappings are declarations, not approval."""
    metadata = item.metadata
    native = str(metadata.get("qid") or "dataset")
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", native)
    source = _metadata_fields(metadata)
    _require_energy_frame(source, str(metadata["reaction"]))
    conditions = {}
    if source.get("frame") is not None:
        conditions["energy_frame"] = source["frame"]
    if source.get("channel") is not None:
        conditions["composite_channels"] = source["channel"]
    # A free-text source reaction keeps all state/isotope labels. The common
    # matcher can queue an unsupported spelling; only an explicit mapping may
    # replace it. The source's recommended flag does not qualify our review.
    result: dict = {
        "reaction": reaction or metadata["reaction"],
        "type": process_type,
        "form": "table",
        "unit": "m2",
        "independent_variable": independent_variable,
        "observable": observable,
        "channel_scope": channel_scope,
        "status": "imported",
        "validity": {
            "quantity": independent_variable or "collision_energy",
            "minimum": item.rows[0][0],
            "maximum": item.rows[-1][0],
            "unit": "eV",
            "unresolved_conditions": conditions,
        },
        "source": {
            "provider": "iaea_collisiondb",
            "collection": "CollisionDB",
            "record_id": native,
            "citation": json.dumps(metadata.get("refs") or {}, ensure_ascii=False),
            "url": "https://db-amdis.org/collisiondb/datasets/" + native.removeprefix("D") + "/",
        },
        "source_declaration": {
            "metadata": metadata,
            "point_uncertainties": item.point_uncertainties,
            "explicit_mapping": {
                "reaction": reaction,
                "type": process_type,
                "independent_variable": independent_variable,
                "observable": observable,
                "channel_scope": channel_scope,
            },
        },
    }
    threshold = source.get("threshold")
    if threshold is not None:
        result["threshold_eV"] = _nonnegative_number(threshold, "threshold")
    uncertainty = source.get("unc_perc")
    if uncertainty is not None:
        result["uncertainty"] = {"relative": _nonnegative_number(uncertainty, "unc_perc") / 100}
    result["method"] = (
        "calculated"
        if source.get("data_from_fit") is True
        else {
            "experiment": "measured",
            "experimental": "measured",
            "theory": "calculated",
            "estimate": "estimated",
        }.get(str(source.get("method")), "unknown")
    )
    if source.get("data_from_fit") is True:
        _fit_domain(result, source)
    result["asset"] = snapshot.write_table(
        outdir, safe_name, item.rows, "energy_eV,cross_section_m2"
    )
    return result


def _nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"CollisionDB {name} must be numeric")
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"CollisionDB {name} must be numeric") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"CollisionDB {name} must be finite and nonnegative")
    return number


def _fit_domain(result: dict, source: dict) -> None:
    """Limit sampled fit data to its stated energy domain; never run the fit code."""
    fit = source.get("fit")
    if not isinstance(fit, dict):
        raise ValueError("CollisionDB data_from_fit requires its fit declaration")
    columns = source["columns"]
    if columns[0]["units"] != "eV":
        result["validity"]["unresolved_conditions"]["source_fit_energy_domain"] = fit
        return
    validity = result["validity"]
    if fit.get("Elo") is not None:
        validity["minimum"] = max(validity["minimum"], _nonnegative_number(fit["Elo"], "fit.Elo"))
    if fit.get("Ehi") is not None:
        validity["maximum"] = min(validity["maximum"], _nonnegative_number(fit["Ehi"], "fit.Ehi"))
    if validity["minimum"] > validity["maximum"]:
        raise ValueError("CollisionDB sampled table does not overlap the declared fit domain")
