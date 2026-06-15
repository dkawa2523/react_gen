from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


WARNING = "Review sign convention and source consistency before final DNT use."


def fill_reaction_energetics(
    prepared_registry: Path,
    property_provider_chain: list[Any],
    source_profile: dict[str, Any],
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_profile": source_profile.get("name", "custom"),
        "energetics_filled": [],
        "skipped": [],
        "unresolved": [],
        "summary": {
            "n_energetics_filled": 0,
            "n_skipped": 0,
            "n_unresolved": 0,
        },
    }

    reaction_root = prepared_registry / "reactions" / "ion_neutral"
    if not reaction_root.exists():
        return report

    for path in sorted(reaction_root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pair = payload.get("pair", {})
        changed = False
        for channel in payload.get("channels", []):
            if not isinstance(channel, dict):
                continue
            channel_id = channel.get("id")
            if channel.get("type") == "elastic":
                report["skipped"].append({"file": str(path), "id": channel_id, "reason": "elastic_channel"})
                continue
            if channel.get("deltaE_products_minus_reactants_eV") is not None:
                report["skipped"].append({"file": str(path), "id": channel_id, "reason": "deltaE_already_present"})
                continue

            reactants = _reactants_from_pair(pair)
            products = _amounts(channel.get("products", []))
            required_species = sorted({species for species, _ in [*reactants, *products]})
            enthalpies = _enthalpies(required_species, prepared_registry, property_provider_chain)
            missing = [species for species in required_species if species not in enthalpies]
            if missing:
                report["unresolved"].append(
                    {
                        "file": str(path),
                        "id": channel_id,
                        "reason": "missing_enthalpy_formation_eV",
                        "species": missing,
                    }
                )
                continue

            delta_e = _sum_enthalpy(products, enthalpies) - _sum_enthalpy(reactants, enthalpies)
            channel["deltaE_products_minus_reactants_eV"] = delta_e
            channel.setdefault("data", {})["energetics"] = {
                "status": "computed_from_snapshot",
                "method": "products_minus_reactants_enthalpy_formation",
                "source_records": _source_records(required_species, enthalpies),
                "warning": WARNING,
            }
            report["energetics_filled"].append(
                {
                    "file": str(path),
                    "id": channel_id,
                    "deltaE_products_minus_reactants_eV": delta_e,
                    "species": required_species,
                }
            )
            changed = True

        if changed:
            path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    report["summary"]["n_energetics_filled"] = len(report["energetics_filled"])
    report["summary"]["n_skipped"] = len(report["skipped"])
    report["summary"]["n_unresolved"] = len(report["unresolved"])
    return report


def _reactants_from_pair(pair: dict[str, Any]) -> list[tuple[str, float]]:
    reactants = []
    if pair.get("projectile"):
        reactants.append((str(pair["projectile"]), 1.0))
    if pair.get("target"):
        reactants.append((str(pair["target"]), 1.0))
    return reactants


def _amounts(items: Any) -> list[tuple[str, float]]:
    amounts = []
    if not isinstance(items, list):
        return amounts
    for item in items:
        if not isinstance(item, dict) or not item.get("species"):
            continue
        amounts.append((str(item["species"]), float(item.get("n", 1.0))))
    return amounts


def _enthalpies(
    species_ids: list[str],
    prepared_registry: Path,
    property_provider_chain: list[Any],
) -> dict[str, dict[str, Any]]:
    values = {}
    for species_id in species_ids:
        local = _local_enthalpy(prepared_registry, species_id)
        if local is not None:
            values[species_id] = local
            continue
        for provider in property_provider_chain:
            if not hasattr(provider, "find_properties"):
                continue
            candidates = provider.find_properties(species_id, ["enthalpy_formation_eV"])
            candidate = _first_supported_enthalpy(candidates)
            if candidate is not None:
                values[species_id] = candidate
                break
    return values


def _local_enthalpy(prepared_registry: Path, species_id: str) -> dict[str, Any] | None:
    species_dir = prepared_registry / "species"
    if not species_dir.exists():
        return None
    for path in sorted(species_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if payload.get("id") != species_id:
            continue
        prop = payload.get("properties", {}).get("enthalpy_formation_eV")
        if not isinstance(prop, dict) or prop.get("value") is None or prop.get("unit") != "eV":
            return None
        return {
            "species": species_id,
            "property": "enthalpy_formation_eV",
            "value": prop.get("value"),
            "unit": prop.get("unit"),
            "source_record": deepcopy(prop.get("source_record") or prop.get("source")),
        }
    return None


def _first_supported_enthalpy(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("property") != "enthalpy_formation_eV":
            continue
        if candidate.get("unit") == "eV" and candidate.get("value") is not None:
            return deepcopy(candidate)
    return None


def _sum_enthalpy(amounts: list[tuple[str, float]], enthalpies: dict[str, dict[str, Any]]) -> float:
    total = 0.0
    for species, coefficient in amounts:
        total += coefficient * float(enthalpies[species]["value"])
    return total


def _source_records(species_ids: list[str], enthalpies: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for species_id in species_ids:
        source_record = deepcopy(enthalpies[species_id].get("source_record"))
        records.append(
            {
                "species": species_id,
                "property": "enthalpy_formation_eV",
                "source_record": source_record,
            }
        )
    return records
