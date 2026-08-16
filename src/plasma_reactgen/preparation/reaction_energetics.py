from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.preparation.enthalpy_lookup import (
    load_local_enthalpies,
    resolve_enthalpies,
)
from plasma_reactgen.preparation.reaction_energy_calculation import (
    apply_computed_energetics,
    products_minus_reactants,
    reactants_from_pair,
    required_species,
    species_amounts,
)


def fill_reaction_energetics(
    prepared_registry: Path,
    property_provider_chain: list[Any],
    source_profile: dict[str, Any],
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    report = _empty_report(source_profile)
    reaction_root = prepared_registry / "reactions" / "ion_neutral"
    if not reaction_root.exists():
        return report

    local_enthalpies = load_local_enthalpies(prepared_registry)
    for path in sorted(reaction_root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if _fill_reaction_payload(
            payload,
            path,
            local_enthalpies,
            property_provider_chain,
            report,
        ):
            _write_yaml(path, payload)

    _finalize_report(report)
    return report


def _fill_reaction_payload(
    payload: dict[str, Any],
    path: Path,
    local_enthalpies: dict[str, dict[str, Any]],
    property_providers: list[Any],
    report: dict[str, Any],
) -> bool:
    changed = False
    pair = payload.get("pair", {})
    for channel in payload.get("channels", []):
        if not isinstance(channel, dict):
            continue
        if _fill_channel(
            channel,
            pair,
            path,
            local_enthalpies,
            property_providers,
            report,
        ):
            changed = True
    return changed


def _fill_channel(
    channel: dict[str, Any],
    pair: dict[str, Any],
    path: Path,
    local_enthalpies: dict[str, dict[str, Any]],
    property_providers: list[Any],
    report: dict[str, Any],
) -> bool:
    channel_id = channel.get("id")
    skip_reason = _skip_reason(channel)
    if skip_reason is not None:
        report["skipped"].append({"file": str(path), "id": channel_id, "reason": skip_reason})
        return False

    reactants = reactants_from_pair(pair)
    products = species_amounts(channel.get("products", []))
    species_ids = required_species(reactants, products)
    enthalpies = resolve_enthalpies(species_ids, local_enthalpies, property_providers)
    missing = [species for species in species_ids if species not in enthalpies]
    if missing:
        report["unresolved"].append(
            {
                "file": str(path),
                "id": channel_id,
                "reason": "missing_enthalpy_formation_eV",
                "species": missing,
            }
        )
        return False

    delta_e = products_minus_reactants(reactants, products, enthalpies)
    apply_computed_energetics(channel, delta_e, species_ids, enthalpies)
    report["energetics_filled"].append(
        {
            "file": str(path),
            "id": channel_id,
            "deltaE_products_minus_reactants_eV": delta_e,
            "species": species_ids,
        }
    )
    return True


def _skip_reason(channel: dict[str, Any]) -> str | None:
    if channel.get("type") == "elastic":
        return "elastic_channel"
    if channel.get("deltaE_products_minus_reactants_eV") is not None:
        return "deltaE_already_present"
    return None


def _empty_report(source_profile: dict[str, Any]) -> dict[str, Any]:
    return {
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


def _finalize_report(report: dict[str, Any]) -> None:
    report["summary"] = {
        "n_energetics_filled": len(report["energetics_filled"]),
        "n_skipped": len(report["skipped"]),
        "n_unresolved": len(report["unresolved"]),
    }


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
