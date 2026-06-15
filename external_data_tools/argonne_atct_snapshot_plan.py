from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ENERGETICS_REASON = "needed_for_deltaE_products_minus_reactants_eV"
PROPERTY_FIELDS = {
    "enthalpy_formation_eV",
    "ionization_energy_eV",
    "electron_affinity_eV",
}


def build_argonne_atct_snapshot_plan(workspace_or_outputs: Path) -> dict[str, Any]:
    root = Path(workspace_or_outputs)
    files = _input_files(root)
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for path in files:
        payload = _read_yaml(path)
        if path.name == "network.reactions.yaml":
            _collect_from_network_reactions(payload, grouped)
        elif path.name == "prepare_report.yaml":
            _collect_from_prepare_report(payload, grouped)
        elif path.name == "missing_data.yaml":
            _collect_from_missing_data(payload, grouped)

    return {
        "schema_version": 1,
        "snapshot_request": {
            "name": "argonne_atct_required_thermochemistry",
            "generated_at": _utc_now(),
        },
        "required_records": list(grouped.values()),
    }


def write_argonne_atct_snapshot_plan(workspace_or_outputs: Path, output: Path) -> dict[str, Any]:
    plan = build_argonne_atct_snapshot_plan(workspace_or_outputs)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan required Argonne/ATcT-style local thermochemistry snapshot records."
    )
    parser.add_argument("workspace_or_outputs", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("external_data/argonne_atct/required_thermochemistry.yaml"),
    )
    args = parser.parse_args(argv)

    plan = write_argonne_atct_snapshot_plan(args.workspace_or_outputs, args.output)
    print(
        "argonne/atct snapshot plan: "
        f"required_records={len(plan['required_records'])} "
        f"output={args.output}"
    )
    return 0


def _input_files(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_file():
        return [path]

    candidates = [
        path / "prepare_report.yaml",
        path / "missing_data.yaml",
        path / "network.reactions.yaml",
        path / "outputs" / "missing_data.yaml",
        path / "outputs" / "network.reactions.yaml",
    ]
    found = [candidate for candidate in candidates if candidate.exists()]
    if not found:
        raise FileNotFoundError(f"no prepare_report.yaml, missing_data.yaml, or network.reactions.yaml found under {path}")
    return found


def _collect_from_network_reactions(payload: dict[str, Any], grouped: OrderedDict[str, dict[str, Any]]) -> None:
    reactions = payload.get("reactions", [])
    if not isinstance(reactions, list):
        return
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        if reaction.get("family") != "ion_neutral" or reaction.get("type") == "elastic":
            continue
        if reaction.get("deltaE_products_minus_reactants_eV") is not None:
            continue
        for species in _reaction_species(reaction):
            _add_requirement(grouped, species, "enthalpy_formation_eV", ENERGETICS_REASON)


def _collect_from_prepare_report(payload: dict[str, Any], grouped: OrderedDict[str, dict[str, Any]]) -> None:
    for item in payload.get("unresolved", []):
        if not isinstance(item, dict):
            continue
        species = item.get("species") or item.get("subject_id")
        prop = item.get("property") or _property_from_field(item.get("field"))
        if species and prop in PROPERTY_FIELDS:
            _add_requirement(grouped, str(species), prop, "missing_property")

    for item in payload.get("unresolved_reactions", []):
        if not isinstance(item, dict):
            continue
        if item.get("reason") in {"missing_deltaE_products_minus_reactants_eV", "missing_reaction_energetics"}:
            for species in item.get("species", []):
                _add_requirement(grouped, str(species), "enthalpy_formation_eV", ENERGETICS_REASON)


def _collect_from_missing_data(payload: dict[str, Any], grouped: OrderedDict[str, dict[str, Any]]) -> None:
    for item in payload.get("missing_data", []):
        if not isinstance(item, dict):
            continue
        field = _property_from_field(item.get("field"))
        species = item.get("species")
        if not species and item.get("subject_kind") == "species":
            species = item.get("subject_id")
        if species and field in PROPERTY_FIELDS:
            _add_requirement(grouped, str(species), field, "missing_property")
        if item.get("field") == "deltaE_products_minus_reactants_eV":
            for species_id in item.get("species", []):
                _add_requirement(grouped, str(species_id), "enthalpy_formation_eV", ENERGETICS_REASON)


def _reaction_species(reaction: dict[str, Any]) -> list[str]:
    species = []
    reactants = reaction.get("reactants", [])
    if isinstance(reactants, list):
        for item in reactants:
            if isinstance(item, dict) and item.get("species"):
                species.append(str(item["species"]))
            elif isinstance(item, str):
                species.append(item)
    for item in reaction.get("products", []):
        if isinstance(item, dict) and item.get("species"):
            species.append(str(item["species"]))
    return species


def _property_from_field(field: Any) -> str | None:
    field_text = str(field or "")
    if field_text in PROPERTY_FIELDS:
        return field_text
    if "." in field_text:
        tail = field_text.rsplit(".", 1)[-1]
        if tail in PROPERTY_FIELDS:
            return tail
    return None


def _add_requirement(
    grouped: OrderedDict[str, dict[str, Any]],
    species: str,
    property_name: str,
    reason: str,
) -> None:
    if not species:
        return
    record = grouped.setdefault(species, {"species": species, "properties": [], "reason": []})
    if property_name not in record["properties"]:
        record["properties"].append(property_name)
    if reason not in record["reason"]:
        record["reason"].append(reason)


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML input must be a mapping: {path}")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
