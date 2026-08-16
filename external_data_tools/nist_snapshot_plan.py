from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROPERTY_FIELD_MAP = {
    "target.polarizability_A3": "polarizability_A3",
    "target.dipole_moment_D": "dipole_moment_D",
    "target.collision_radius_A": "collision_radius_A",
    "ionization_energy_eV": "ionization_energy_eV",
    "electron_affinity_eV": "electron_affinity_eV",
    "enthalpy_formation_eV": "enthalpy_formation_eV",
    "polarizability_A3": "polarizability_A3",
    "dipole_moment_D": "dipole_moment_D",
    "collision_radius_A": "collision_radius_A",
}

NIST_SOURCE_SUGGESTIONS = {
    "polarizability_A3": ["NIST CCCBDB SRD 101"],
    "dipole_moment_D": ["NIST CCCBDB SRD 101"],
    "electron_affinity_eV": ["NIST Chemistry WebBook SRD 69"],
    "enthalpy_formation_eV": ["NIST Chemistry WebBook SRD 69", "NIST CCCBDB SRD 101"],
}


def build_nist_snapshot_plan(workspace_or_outputs: Path) -> dict[str, Any]:
    path = _resolve_input_path(workspace_or_outputs)
    payload = _read_yaml(path)
    items = _items_from_payload(path, payload)
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for item in items:
        species = _species_for_item(item)
        property_name = _property_for_item(item)
        if not species or not property_name:
            continue
        if property_name == "collision_radius_A":
            continue

        record = grouped.setdefault(
            species,
            {"species": species, "properties": [], "suggested_sources": []},
        )
        if property_name not in record["properties"]:
            record["properties"].append(property_name)
        for source in _suggested_sources(species, property_name):
            if source not in record["suggested_sources"]:
                record["suggested_sources"].append(source)

    return {
        "schema_version": 1,
        "snapshot_request": {
            "name": "nist_required_properties",
            "generated_at": _utc_now(),
        },
        "required_records": list(grouped.values()),
    }


def write_nist_snapshot_plan(workspace_or_outputs: Path, output: Path) -> dict[str, Any]:
    plan = build_nist_snapshot_plan(workspace_or_outputs)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan required manually prepared NIST local snapshot records."
    )
    parser.add_argument("workspace_or_outputs", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("external_data/snapshots/nist_required_properties.yaml"),
    )
    args = parser.parse_args(argv)

    plan = write_nist_snapshot_plan(args.workspace_or_outputs, args.output)
    print(
        "nist snapshot plan: "
        f"required_records={len(plan['required_records'])} "
        f"output={args.output}"
    )
    return 0


def _resolve_input_path(workspace_or_outputs: Path) -> Path:
    path = Path(workspace_or_outputs)
    if path.is_dir():
        prepare_report = path / "prepare_report.yaml"
        missing_data = path / "missing_data.yaml"
        if prepare_report.exists():
            return prepare_report
        if missing_data.exists():
            return missing_data
    if path.exists():
        return path
    raise FileNotFoundError(f"NIST planning input not found: {path}")


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed YAML: {path}") from exc


def _items_from_payload(path: Path, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("NIST planning input must be a YAML mapping")
    if path.name == "prepare_report.yaml":
        items = payload.get("unresolved", [])
    else:
        items = payload.get("missing_data", [])
    if not isinstance(items, list):
        raise ValueError("NIST planning input items must be a list")
    return [item for item in items if isinstance(item, dict)]


def _property_for_item(item: dict[str, Any]) -> str | None:
    field = str(item.get("field") or item.get("property") or "")
    if field in PROPERTY_FIELD_MAP:
        return PROPERTY_FIELD_MAP[field]
    if "." in field:
        tail = field.rsplit(".", 1)[-1]
        return PROPERTY_FIELD_MAP.get(tail)
    return None


def _species_for_item(item: dict[str, Any]) -> str | None:
    species = item.get("species")
    if species:
        return str(species)
    subject_kind = item.get("subject_kind")
    subject_id = item.get("subject_id")
    if subject_kind == "species" and subject_id:
        return str(subject_id)
    if subject_kind == "dnt_task":
        target = item.get("target") or item.get("target_species")
        if target:
            return str(target)
    return str(subject_id) if subject_id and subject_kind != "reaction" else None


def _suggested_sources(species: str, property_name: str) -> list[str]:
    if property_name == "ionization_energy_eV":
        if _looks_atomic(species):
            return ["NIST ASD"]
        return ["NIST Chemistry WebBook SRD 69"]
    return list(NIST_SOURCE_SUGGESTIONS.get(property_name, []))


def _looks_atomic(species: str) -> bool:
    base = species.rstrip("+-")
    if base.endswith("_p") or base.endswith("_m"):
        base = base[:-2]
    return len(base) <= 2 and base[:1].isupper() and (len(base) == 1 or base[1:].islower())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
