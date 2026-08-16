from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from external_data_tools.cache import safe_filename, sha256_file
from external_data_tools.registry_admin_io import (
    duplicate_report,
    find_import,
    write_numeric_csv,
)
from external_data_tools.registry_records import (
    append_dataset,
    channel_records,
    exact_channel_matches,
)
from external_data_tools.registry_snapshot_records import (
    finish_snapshot_report,
    read_snapshot_records,
    snapshot_source_record,
)


def import_rate_snapshot(
    snapshot: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(snapshot)
    root = Path(registry_root)
    digest = sha256_file(source)
    duplicate = find_import(root, "rate_snapshot", digest)
    if duplicate is not None:
        return duplicate_report("rate_snapshot", source, digest, duplicate)

    channels = channel_records(root)
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for index, record in enumerate(read_snapshot_records(source), start=1):
        result, error = _apply_rate_record(record, index, channels, source, root, digest)
        if result is not None:
            applied.append(result)
        elif error is not None:
            review.append(error)
    return finish_snapshot_report(
        "rate_snapshot",
        source,
        root,
        digest,
        applied,
        review,
        report_dir,
    )


def _apply_rate_record(
    record: dict[str, Any],
    index: int,
    channels: list[dict[str, Any]],
    source: Path,
    registry_root: Path,
    digest: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    matches = exact_channel_matches(record, channels)
    if len(matches) != 1:
        return None, {
            "record": record,
            "reason": "ambiguous_mapping" if len(matches) > 1 else "no_exact_mapping",
            "candidate_reaction_ids": [match["reaction_id"] for match in matches],
        }
    match = matches[0]
    dataset, error = _rate_dataset(record, match, source, registry_root, digest, index)
    if error is not None:
        return None, {"record": record, "reason": error}
    if dataset is None or not append_dataset(match, dataset):
        return None, None
    return {"reaction_id": match["reaction_id"], "dataset_id": dataset["id"]}, None


def _rate_dataset(
    record: dict[str, Any],
    match: dict[str, Any],
    source: Path,
    registry_root: Path,
    digest: str,
    index: int,
) -> tuple[dict[str, Any] | None, str | None]:
    representation = str(record.get("representation") or "constant")
    if representation not in {"constant", "table", "arrhenius"}:
        return None, "unsupported_representation"
    dataset_id = f"ds_{safe_filename(match['reaction_id'])}_rate_{digest[:12]}_{index:03d}"
    parameters_value = record.get("parameters")
    parameters = dict(parameters_value) if isinstance(parameters_value, dict) else {}
    dataset = {
        "id": dataset_id,
        "kind": "rate_coefficient",
        "representation": representation,
        "unit": record.get("unit"),
        "parameters": parameters,
        "validity": _temperature_validity(record),
        "source_record": snapshot_source_record(record, source, digest),
        "status": "imported",
        "preferred": bool(record.get("preferred", False)),
    }
    _add_rate_parameters(dataset, record, representation)
    if representation != "table":
        return dataset, None
    asset_path = _rate_table_asset(record, source, registry_root, digest, index)
    if asset_path is None:
        return None, "rate_table_data_missing"
    dataset.update(
        {
            "path": asset_path,
            "independent_variable": record.get("independent_variable") or "temperature",
            "dependent_variable": record.get("dependent_variable") or "rate_coefficient",
        }
    )
    return dataset, None


def _add_rate_parameters(
    dataset: dict[str, Any],
    record: dict[str, Any],
    representation: str,
) -> None:
    parameters = dataset["parameters"]
    if representation == "constant":
        for key in ("value", "constant"):
            if key in record:
                parameters["value"] = record[key]
    elif representation == "arrhenius":
        for key in ("A", "n", "Ea", "Ea_eV", "T0_K"):
            if key in record and key not in parameters:
                parameters[key] = record[key]


def _temperature_validity(record: dict[str, Any]) -> dict[str, Any]:
    minimum = record.get("temperature_min") or record.get("temperature_min_K")
    maximum = record.get("temperature_max") or record.get("temperature_max_K")
    validity = {"unit": record.get("temperature_unit") or "K"}
    if minimum not in (None, ""):
        validity["minimum"] = float(str(minimum))
    if maximum not in (None, ""):
        validity["maximum"] = float(str(maximum))
    return validity


def _rate_table_asset(
    record: dict[str, Any],
    snapshot: Path,
    registry_root: Path,
    digest: str,
    index: int,
) -> str | None:
    relative = f"assets/rate_coefficients/rate_{digest[:12]}_{index:03d}.csv"
    destination = registry_root / relative
    source_value = record.get("path") or record.get("asset_path")
    if source_value:
        source = Path(source_value)
        source = source if source.is_absolute() else snapshot.parent / source
        if not source.is_file():
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return relative
    table = record.get("table")
    rows = [row for row in table if isinstance(row, dict)] if isinstance(table, list) else []
    if not rows:
        return None
    write_numeric_csv(destination, rows, tuple(rows[0]))
    return relative
