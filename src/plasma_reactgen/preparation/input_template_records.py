"""Classify missing-data items and build manual-input records."""

from __future__ import annotations

from typing import Any

from plasma_reactgen.preparation.input_report_reader import split_pair_key

PROPERTY_UNITS = {
    "mass_amu": "amu",
    "ionization_energy_eV": "eV",
    "electron_affinity_eV": "eV",
    "enthalpy_formation_eV": "eV",
    "dipole_moment_D": "D",
    "polarizability_A3": "A3",
    "collision_radius_A": "A",
}

PROPERTY_GUIDANCE = {
    "collision_radius_A": "Fill from internal DNT/transport fit or reviewed literature.",
    "polarizability_A3": (
        "Fill from reviewed local snapshot, NIST/CCCBDB-style snapshot, or internal property DB."
    ),
    "dipole_moment_D": (
        "Fill from reviewed molecular data; use 0 only when symmetry/source review supports it."
    ),
    "enthalpy_formation_eV": (
        "Fill from reviewed thermochemistry snapshot such as internal ATcT-style data."
    ),
}


def build_missing_input_templates(
    missing_items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "species": [],
        "channels": [],
        "cross_sections": [],
        "energetics": [],
        "manual": [],
    }
    seen: set[tuple[str, str, Any]] = set()
    for item in missing_items:
        identity = _item_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        _classify(item, grouped)

    return {
        "species_properties.yaml": {"schema_version": 1, "records": grouped["species"]},
        "reaction_channels.yaml": {"schema_version": 1, "records": grouped["channels"]},
        "cross_section_mapping.yaml": {
            "schema_version": 1,
            "mappings": grouped["cross_sections"],
        },
        "reaction_energetics.yaml": {
            "schema_version": 1,
            "records": grouped["energetics"],
        },
        "manual_review.yaml": {"schema_version": 1, "items": grouped["manual"]},
    }


def _item_identity(item: dict[str, Any]) -> tuple[str, str, Any]:
    return (
        str(item.get("subject_id") or item.get("id") or "unknown"),
        str(item.get("field") or ""),
        item.get("required_by"),
    )


def _classify(item: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> None:
    field = str(item.get("field") or "")
    property_name = _property_name_from_field(field)
    if property_name is not None:
        species = _species_from_item(item)
        grouped["species"].append(_species_property_record(item, species, property_name))
    elif field in {"data.cross_section", "data.cross_section.path"}:
        grouped["cross_sections"].append(_cross_section_mapping(item))
    elif field in {"deltaE_products_minus_reactants_eV", "threshold_eV"}:
        grouped["energetics"].append(_reaction_energetics_record(item))
    elif field == "reaction_pair_coverage":
        grouped["channels"].append(_reaction_channel_pair_record(item))
    elif field == "registry/species":
        grouped["channels"].append(_reaction_channel_seed_record(item))
    else:
        grouped["manual"].append(_manual_review_item(item))


def _species_property_record(
    item: dict[str, Any],
    species: str,
    property_name: str,
) -> dict[str, Any]:
    guidance = PROPERTY_GUIDANCE.get(
        property_name,
        "Fill from reviewed local/internal data or literature. Do not invent values.",
    )
    return {
        "species": species,
        "property": property_name,
        "value": None,
        "unit": PROPERTY_UNITS.get(property_name),
        "status": "estimated" if property_name == "collision_radius_A" else "literature_supported",
        "why_needed": item.get("message") or item.get("required_by"),
        "required_by": item.get("required_by"),
        "source_record": {
            "source_type": "manual_review",
            "citation": None,
            "source_id": None,
            "notes": [guidance],
        },
    }


def _cross_section_mapping(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "reaction_id": str(item.get("subject_id") or item.get("id") or "unknown"),
        "asset_path": None,
        "source": None,
        "mapping_status": "manual_review_required",
        "why_needed": item.get("message") or item.get("required_by"),
        "process_label_original": None,
        "notes": [
            "Import a reviewed local CSV/TSV asset first, then set asset_path to "
            "assets/cross_sections/<file>.csv."
        ],
    }


def _reaction_energetics_record(item: dict[str, Any]) -> dict[str, Any]:
    record = {
        "reaction_id": str(item.get("subject_id") or item.get("id") or "unknown"),
        "unit": "eV",
        "why_needed": item.get("message") or item.get("required_by"),
        "source_record": {
            "source_type": "manual_review",
            "citation": None,
            "source_id": None,
            "notes": [
                "Fill from reviewed reaction energetics or compute externally "
                "from reviewed thermochemistry."
            ],
        },
    }
    field = str(item.get("field") or "")
    record["threshold_eV" if field == "threshold_eV" else "deltaE_products_minus_reactants_eV"] = (
        None
    )
    return record


def _reaction_channel_pair_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": _pair_from_item(item),
        "placeholder_channels": [
            {
                "id": None,
                "type": None,
                "products": [],
                "threshold_eV": None,
                "deltaE_products_minus_reactants_eV": None,
                "dnt_class": None,
                "status": "imported",
                "source_record": {
                    "source_type": "manual_review",
                    "citation": None,
                    "source_id": None,
                },
            }
        ],
        "why_needed": item.get("message") or item.get("required_by"),
        "notes": [
            "Fill only reviewed reaction channels for this missing collision pair.",
            "Validate species references, charge balance, and element balance before using.",
        ],
    }


def _reaction_channel_seed_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_id": str(item.get("subject_id") or "unknown"),
        "field": item.get("field"),
        "why_needed": item.get("message") or item.get("required_by"),
        "action": "seed_missing_species_or_review_reaction_products",
        "species_candidate": {
            "id": str(item.get("subject_id") or "unknown"),
            "composition": {},
            "charge": None,
            "classes": [],
            "state": {},
            "properties": {},
            "metadata": {
                "status": "imported",
                "source_record": {
                    "source_type": "manual_review",
                    "citation": None,
                    "source_id": None,
                },
            },
        },
    }


def _manual_review_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_kind": item.get("subject_kind"),
        "subject_id": item.get("subject_id") or item.get("id"),
        "field": item.get("field"),
        "required_by": item.get("required_by"),
        "severity": item.get("severity"),
        "message": item.get("message"),
        "action": "manual_review",
        "notes": ["No automatic template is available for this field."],
    }


def _species_from_item(item: dict[str, Any]) -> str:
    field = str(item.get("field") or "")
    subject = str(item.get("subject_id") or item.get("id") or "unknown")
    if "__" not in subject:
        return subject
    left, right = subject.split("__", 1)
    prefix = field.split(".", 1)[0] if "." in field else ""
    if prefix in {"target", "neutral"}:
        return right
    if prefix in {"ion", "projectile"}:
        return left
    if item.get("subject_kind") == "dnt_task":
        return right
    return subject


def _property_name_from_field(field: str) -> str | None:
    if field in PROPERTY_UNITS:
        return field
    suffix = field.rsplit(".", 1)[-1]
    return suffix if suffix in PROPERTY_UNITS else None


def _pair_from_item(item: dict[str, Any]) -> dict[str, Any]:
    pair = item.get("pair")
    if isinstance(pair, dict):
        return {
            "family": pair.get("family"),
            "projectile": pair.get("projectile"),
            "target": pair.get("target"),
        }
    family, projectile, target = split_pair_key(str(item.get("subject_id") or ""))
    return {"family": family, "projectile": projectile, "target": target}
