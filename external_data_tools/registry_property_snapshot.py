from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.cache import sha256_file
from external_data_tools.registry_admin_io import (
    duplicate_report,
    find_import,
    read_yaml,
    write_yaml,
)
from external_data_tools.registry_records import species_paths
from external_data_tools.registry_snapshot_records import (
    finish_snapshot_report,
    read_snapshot_records,
    snapshot_source_record,
)

PROPERTY_ALIASES = {
    "mass": ("mass_amu", "amu"),
    "mass_amu": ("mass_amu", "amu"),
    "enthalpy": ("enthalpy_formation_eV", "eV"),
    "enthalpy_formation_eV": ("enthalpy_formation_eV", "eV"),
    "ionization_energy": ("ionization_energy_eV", "eV"),
    "ionization_energy_eV": ("ionization_energy_eV", "eV"),
    "electron_affinity": ("electron_affinity_eV", "eV"),
    "electron_affinity_eV": ("electron_affinity_eV", "eV"),
    "dipole": ("dipole_moment_D", "D"),
    "dipole_moment_D": ("dipole_moment_D", "D"),
    "polarizability": ("polarizability_A3", "A3"),
    "polarizability_A3": ("polarizability_A3", "A3"),
    "collision_radius": ("collision_radius_A", "A"),
    "collision_radius_A": ("collision_radius_A", "A"),
}
QUALITY_VALUES = {"experimental", "evaluated", "calculated", "estimated"}


def import_property_snapshot(
    snapshot: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(snapshot)
    root = Path(registry_root)
    digest = sha256_file(source)
    duplicate = find_import(root, "property_snapshot", digest)
    if duplicate is not None:
        return duplicate_report("property_snapshot", source, digest, duplicate)

    paths = species_paths(root)
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for record in _property_records(source):
        result, error = _apply_property_record(record, paths, source, digest)
        if result is not None:
            applied.append(result)
        elif error is not None:
            review.append({"record": record, "reason": error})
    return finish_snapshot_report(
        "property_snapshot",
        source,
        root,
        digest,
        applied,
        review,
        report_dir,
    )


def _apply_property_record(
    record: dict[str, Any],
    paths: dict[str, Path],
    source: Path,
    digest: str,
) -> tuple[dict[str, Any] | None, str | None]:
    target, error = _property_target(record, paths)
    if target is None:
        return None, error
    species_id, path, property_name, default_unit = target
    value = _float_value(record.get("value"))
    if value is None:
        return None, "non_numeric_value"
    quality = str(record.get("quality") or "evaluated").lower()
    if quality not in QUALITY_VALUES:
        return None, "unsupported_quality"

    payload = read_yaml(path)
    payload.setdefault("properties", {})[property_name] = {
        "value": value,
        "unit": record.get("unit") or default_unit,
        "source": record.get("source") or source.name,
        "quality": quality,
        "source_record": snapshot_source_record(record, source, digest),
    }
    write_yaml(path, payload)
    return {"species_id": species_id, "property": property_name}, None


def _property_target(
    record: dict[str, Any],
    paths: dict[str, Path],
) -> tuple[tuple[str, Path, str, str] | None, str | None]:
    species_id = str(record.get("species_id") or record.get("species") or "")
    property_key = str(record.get("property") or record.get("name") or "")
    normalized = PROPERTY_ALIASES.get(property_key)
    if not species_id or normalized is None:
        return None, "unsupported_property_or_species"
    path = paths.get(species_id)
    if path is None:
        return None, "species_id_not_found"
    property_name, default_unit = normalized
    return (species_id, path, property_name, default_unit), None


def _property_records(path: Path) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for record in read_snapshot_records(path):
        expanded.extend(_expand_property_record(record))
    return expanded


def _expand_property_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    if record.get("property") or record.get("name"):
        return [record]
    species_id = record.get("species_id") or record.get("species") or record.get("id")
    common = {
        key: record.get(key)
        for key in ("source", "citation", "quality", "redistribution_status")
        if record.get(key) is not None
    }
    return [
        {
            "species_id": species_id,
            "property": name,
            "value": record[name],
            "unit": record.get(f"{name}_unit"),
            **common,
        }
        for name in PROPERTY_ALIASES
        if name in record and record[name] not in (None, "")
    ]


def _float_value(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
