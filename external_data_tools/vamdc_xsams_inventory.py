"""Convert a cached VAMDC XSAMS response into a compact review inventory."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from defusedxml import ElementTree


def build_xsams_inventory(xsams_path: Path, *, output: Path) -> dict[str, Any]:
    """Extract identifiers and units without claiming a registry channel mapping."""

    source = Path(xsams_path)
    root = ElementTree.parse(source).getroot()
    species = _species_records(root)
    states = _state_records(root)
    processes = _process_records(root)
    sources = _source_records(root)
    unresolved = _unresolved_records(species, states, processes)
    payload = {
        "schema_version": 1,
        "source": {
            "database": "VAMDC",
            "format": "XSAMS",
            "raw_file": str(source),
        },
        "status": "inventory_requires_explicit_registry_mapping",
        "species": species,
        "states": states,
        "processes": processes,
        "references": sources,
        "unresolved": unresolved,
        "summary": {
            "n_species": len(species),
            "n_states": len(states),
            "n_processes": len(processes),
            "n_references": len(sources),
            "n_unresolved": len(unresolved),
            "process_types": dict(sorted(Counter(item["type"] for item in processes).items())),
        },
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a review inventory from one locally cached VAMDC XSAMS file."
    )
    parser.add_argument("xsams", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    result = build_xsams_inventory(args.xsams, output=args.output)
    summary = result["summary"]
    print(
        "vamdc xsams inventory: "
        f"species={summary['n_species']} states={summary['n_states']} "
        f"processes={summary['n_processes']} unresolved={summary['n_unresolved']} "
        f"output={args.output}"
    )
    return 1 if summary["n_unresolved"] else 0


def _species_records(root: Any) -> list[dict[str, Any]]:
    records = []
    for element in root.iter():
        kind = _local_name(element.tag)
        if kind not in {"AtomicSpecies", "Ion", "MolecularSpecies", "Molecule", "Particle"}:
            continue
        species_id = _attribute(element, "speciesID", "speciesId")
        records.append(
            {
                "species_id": species_id,
                "kind": kind,
                "symbol_or_formula": _first_text(
                    element,
                    "ElementSymbol",
                    "StoichiometricFormula",
                    "ParticleName",
                ),
                "ion_charge": _first_number(element, "IonCharge"),
            }
        )
    return records


def _state_records(root: Any) -> list[dict[str, Any]]:
    records = []
    for species in root.iter():
        species_id = _attribute(species, "speciesID", "speciesId")
        if not species_id:
            continue
        for state in species.iter():
            kind = _local_name(state.tag)
            if kind not in {"AtomicState", "MolecularState"}:
                continue
            energy = _first_element(state, "AtomicStateEnergy", "StateEnergy")
            value_element = _first_element(energy, "Value") if energy is not None else None
            records.append(
                {
                    "state_id": _attribute(state, "stateID", "stateId"),
                    "species_id": species_id,
                    "kind": kind,
                    "energy": _number(value_element.text if value_element is not None else None),
                    "energy_unit": (
                        _attribute(value_element, "units") if value_element is not None else None
                    ),
                    "description": _first_text(state, "Description", "StateDescription"),
                }
            )
    return records


def _process_records(root: Any) -> list[dict[str, Any]]:
    process_names = {
        "CollisionalTransition",
        "RadiativeTransition",
        "NonRadiativeTransition",
    }
    records = []
    for element in root.iter():
        process_type = _local_name(element.tag)
        if process_type not in process_names:
            continue
        records.append(
            {
                "process_id": _attribute(
                    element,
                    "id",
                    "processID",
                    "transitionID",
                ),
                "type": process_type,
                "reactant_refs": _refs(element, "Reactant"),
                "product_refs": _refs(element, "Product"),
                "source_refs": _text_values(element, "SourceRef"),
            }
        )
    return records


def _source_records(root: Any) -> list[dict[str, Any]]:
    records = []
    for element in root.iter():
        if _local_name(element.tag) != "Source":
            continue
        records.append(
            {
                "source_id": _attribute(element, "sourceID", "sourceId"),
                "title": _first_text(element, "Title"),
                "authors": _text_values(element, "Name"),
                "year": _first_number(element, "Year"),
            }
        )
    return records


def _unresolved_records(
    species: list[dict[str, Any]],
    states: list[dict[str, Any]],
    processes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unresolved: list[dict[str, Any]] = []
    unresolved.extend(
        {"kind": "species", "reason": "missing_species_id", "record": item}
        for item in species
        if not item["species_id"]
    )
    unresolved.extend(
        {"kind": "state", "reason": "missing_state_id", "record": item}
        for item in states
        if not item["state_id"]
    )
    unresolved.extend(
        {"kind": "process", "reason": "missing_process_id", "record": item}
        for item in processes
        if not item["process_id"]
    )
    return unresolved


def _refs(element: Any, name: str) -> list[dict[str, str]]:
    records = []
    for item in element.iter():
        if _local_name(item.tag) != name:
            continue
        record = {
            key: value for key in ("speciesRef", "stateRef") if (value := _attribute(item, key))
        }
        if record:
            records.append(record)
    return records


def _text_values(element: Any, name: str) -> list[str]:
    return [
        str(item.text).strip()
        for item in element.iter()
        if _local_name(item.tag) == name and item.text and str(item.text).strip()
    ]


def _first_text(element: Any, *names: str) -> str | None:
    item = _first_element(element, *names)
    if item is None:
        return None
    value = _first_element(item, "Value")
    text = value.text if value is not None else item.text
    return str(text).strip() if text and str(text).strip() else None


def _first_number(element: Any, *names: str) -> float | None:
    text = _first_text(element, *names)
    return _number(text)


def _first_element(element: Any, *names: str) -> Any | None:
    wanted = set(names)
    for item in element.iter():
        if item is not element and _local_name(item.tag) in wanted:
            return item
    return None


def _attribute(element: Any | None, *names: str) -> str | None:
    if element is None:
        return None
    for name in names:
        if element.get(name):
            return str(element.get(name))
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


if __name__ == "__main__":
    raise SystemExit(main())
