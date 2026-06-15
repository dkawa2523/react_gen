from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.preparation.missing_plan import resolve_missing_data_path


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
    "polarizability_A3": "Fill from reviewed local snapshot, NIST/CCCBDB-style snapshot, or internal property DB.",
    "dipole_moment_D": "Fill from reviewed molecular data; use 0 only when symmetry/source review supports it.",
    "enthalpy_formation_eV": "Fill from reviewed thermochemistry snapshot such as internal ATcT-style data.",
}


def generate_missing_input_templates(
    outputs_or_missing_data: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    missing_path = resolve_missing_data_path(Path(outputs_or_missing_data))
    output_dir = Path(output_dir)
    missing_payload = _read_yaml(missing_path)
    prepare_report_path = _find_prepare_report_path(Path(outputs_or_missing_data), missing_path)
    coverage_report_path = _find_coverage_report_path(Path(outputs_or_missing_data), missing_path)
    missing_items = [
        *_missing_items(missing_payload),
        *_prepare_report_items(prepare_report_path),
        *_coverage_report_items(coverage_report_path),
    ]

    templates = build_missing_input_templates(missing_items)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for filename, payload in templates.items():
        path = output_dir / filename
        _write_yaml(path, payload)
        written[filename] = path

    readme = _readme_payload(missing_path, _case_name(missing_payload))
    readme_path = output_dir / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    written["README.md"] = readme_path

    return {
        "schema_version": 1,
        "missing_data": str(missing_path),
        "prepare_report": str(prepare_report_path) if prepare_report_path is not None else None,
        "coverage_report": str(coverage_report_path) if coverage_report_path is not None else None,
        "output_dir": str(output_dir),
        "files": {name: str(path) for name, path in written.items()},
        "summary": {
            "n_missing_items": len(missing_items),
            "n_species_property_records": len(templates["species_properties.yaml"]["records"]),
            "n_reaction_channel_records": len(templates["reaction_channels.yaml"]["records"]),
            "n_cross_section_mappings": len(templates["cross_section_mapping.yaml"]["mappings"]),
            "n_reaction_energetics_records": len(templates["reaction_energetics.yaml"]["records"]),
            "n_manual_review_items": len(templates["manual_review.yaml"]["items"]),
        },
        "data_fetched": False,
        "registry_mutated": False,
    }


def build_missing_input_templates(missing_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    species_properties: list[dict[str, Any]] = []
    reaction_channels: list[dict[str, Any]] = []
    cross_section_mappings: list[dict[str, Any]] = []
    reaction_energetics: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    seen: set[tuple[str, str, str | None]] = set()
    for item in missing_items:
        field = str(item.get("field") or "")
        subject = str(item.get("subject_id") or item.get("id") or "unknown")
        key = (subject, field, item.get("required_by"))
        if key in seen:
            continue
        seen.add(key)

        property_name = _property_name_from_field(field)
        if property_name is not None:
            species = _species_from_item(item, property_name)
            species_properties.append(_species_property_record(item, species, property_name))
            continue

        if field in {"data.cross_section", "data.cross_section.path"}:
            cross_section_mappings.append(_cross_section_mapping(item))
            continue

        if field in {"deltaE_products_minus_reactants_eV", "threshold_eV"}:
            reaction_energetics.append(_reaction_energetics_record(item))
            continue

        if field == "reaction_pair_coverage":
            reaction_channels.append(_reaction_channel_pair_record(item))
            continue

        if field == "registry/species":
            reaction_channels.append(_reaction_channel_seed_record(item))
            continue

        manual_review.append(_manual_review_item(item))

    return {
        "species_properties.yaml": {
            "schema_version": 1,
            "records": species_properties,
        },
        "reaction_channels.yaml": {
            "schema_version": 1,
            "records": reaction_channels,
        },
        "cross_section_mapping.yaml": {
            "schema_version": 1,
            "mappings": cross_section_mappings,
        },
        "reaction_energetics.yaml": {
            "schema_version": 1,
            "records": reaction_energetics,
        },
        "manual_review.yaml": {
            "schema_version": 1,
            "items": manual_review,
        },
    }


def _species_property_record(item: dict[str, Any], species: str, property_name: str) -> dict[str, Any]:
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
            "notes": [
                PROPERTY_GUIDANCE.get(
                    property_name,
                    "Fill from reviewed local/internal data or literature. Do not invent values.",
                )
            ],
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
            "Import a reviewed local CSV/TSV asset first, then set asset_path to assets/cross_sections/<file>.csv."
        ],
    }


def _reaction_energetics_record(item: dict[str, Any]) -> dict[str, Any]:
    field = str(item.get("field") or "")
    record = {
        "reaction_id": str(item.get("subject_id") or item.get("id") or "unknown"),
        "unit": "eV",
        "why_needed": item.get("message") or item.get("required_by"),
        "source_record": {
            "source_type": "manual_review",
            "citation": None,
            "source_id": None,
            "notes": [
                "Fill from reviewed reaction energetics or compute externally from reviewed thermochemistry."
            ],
        },
    }
    if field == "threshold_eV":
        record["threshold_eV"] = None
    else:
        record["deltaE_products_minus_reactants_eV"] = None
    return record


def _reaction_channel_pair_record(item: dict[str, Any]) -> dict[str, Any]:
    pair = _pair_from_item(item)
    return {
        "pair": pair,
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


def _species_from_item(item: dict[str, Any], property_name: str) -> str:
    field = str(item.get("field") or "")
    subject = str(item.get("subject_id") or item.get("id") or "unknown")
    prefix = field.split(".", 1)[0] if "." in field else ""
    if "__" in subject and prefix in {"target", "neutral"}:
        return subject.split("__", 1)[1]
    if "__" in subject and prefix in {"ion", "projectile"}:
        return subject.split("__", 1)[0]
    if item.get("subject_kind") == "dnt_task" and "__" in subject and property_name in PROPERTY_UNITS:
        return subject.split("__", 1)[1]
    return subject


def _property_name_from_field(field: str) -> str | None:
    if field in PROPERTY_UNITS:
        return field
    if "." in field:
        suffix = field.rsplit(".", 1)[-1]
        if suffix in PROPERTY_UNITS:
            return suffix
    return None


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed YAML: {path}") from exc


def _missing_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("missing_data", [])
    else:
        raise ValueError("missing-data payload must be a mapping or a list")
    if not isinstance(items, list):
        raise ValueError("missing_data must be a list")
    return [item for item in items if isinstance(item, dict)]


def _find_prepare_report_path(original_input: Path, missing_path: Path) -> Path | None:
    candidates = []
    if original_input.is_dir():
        candidates.append(original_input / "prepare_report.yaml")
    candidates.extend(
        [
            missing_path.parent / "prepare_report.yaml",
            missing_path.parent.parent / "prepare_report.yaml",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _find_coverage_report_path(original_input: Path, missing_path: Path) -> Path | None:
    candidates = []
    if original_input.is_dir():
        candidates.append(original_input / "coverage_report.yaml")
    candidates.extend(
        [
            missing_path.parent / "coverage_report.yaml",
            missing_path.parent.parent / "coverage_report.yaml",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _prepare_report_items(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = _read_yaml(path)
    if not isinstance(payload, dict):
        return []
    items: list[dict[str, Any]] = []
    for key in ("unresolved", "unresolved_reactions", "reaction_channels_skipped"):
        for item in payload.get(key, []) if isinstance(payload.get(key), list) else []:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "subject_kind": item.get("kind", "prepare_report"),
                    "subject_id": item.get("id") or item.get("species") or item.get("pair") or "unknown",
                    "field": item.get("property") or item.get("field") or item.get("reason") or key,
                    "required_by": key,
                    "severity": "warning",
                    "message": item.get("reason") or "Unresolved prepare/enrichment report item.",
                }
            )
    return items


def _coverage_report_items(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = _read_yaml(path)
    if not isinstance(payload, dict):
        return []
    pairs = payload.get("pairs", {})
    if not isinstance(pairs, dict):
        return []
    missing_pairs = pairs.get("missing", [])
    if not isinstance(missing_pairs, list):
        return []
    items = []
    for pair in missing_pairs:
        if not isinstance(pair, dict):
            continue
        pair_key = str(pair.get("pair_key") or "")
        family, projectile, target = _split_pair_key(pair_key)
        items.append(
            {
                "subject_kind": "collision_pair",
                "subject_id": pair_key or pair.get("pair_label") or "unknown",
                "field": "reaction_pair_coverage",
                "required_by": "coverage_report",
                "severity": "warning",
                "message": pair.get("reason") or "No registered reaction file for this collision pair.",
                "pair": {
                    "family": pair.get("family") or family,
                    "projectile": projectile,
                    "target": target,
                    "label": pair.get("pair_label"),
                    "depth": pair.get("depth"),
                },
            }
        )
    return items


def _pair_from_item(item: dict[str, Any]) -> dict[str, Any]:
    pair = item.get("pair")
    if isinstance(pair, dict):
        return {
            "family": pair.get("family"),
            "projectile": pair.get("projectile"),
            "target": pair.get("target"),
        }
    family, projectile, target = _split_pair_key(str(item.get("subject_id") or ""))
    return {"family": family, "projectile": projectile, "target": target}


def _split_pair_key(pair_key: str) -> tuple[str | None, str | None, str | None]:
    parts = pair_key.split("|")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def _case_name(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    case = payload.get("case")
    if isinstance(case, dict) and case.get("name"):
        return str(case["name"])
    return None


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _readme_payload(missing_path: Path, case_name: str | None = None) -> str:
    case_guidance = _case_guidance(case_name)
    return f"""# Manual Missing Data Inputs

Generated from `{missing_path}`.

These files are fill-in templates only. They do not contain guessed physical
values, do not fetch data, and do not mutate curated `registry/`.

Recommended workflow:

1. Fill only values that have been reviewed from internal data, local snapshots,
   transport/DNT fits, or literature.
2. Keep `source_record` provenance with citation/source IDs wherever possible.
3. Convert filled property records into an `internal_file` property snapshot or
   another reviewed local source profile input.
4. Import cross-section tables with `reactgen import-cross-sections`, then copy
   the resulting `assets/cross_sections/<file>.csv` path into
   `cross_section_mapping.yaml`.
5. Keep uncertain or unsupported fields in `manual_review.yaml`.

Do not invent collision radii, reaction energetics, cross sections, or species
composition just to satisfy diagnostics.

{case_guidance}
"""


def _case_guidance(case_name: str | None) -> str:
    if case_name == "ar_o2_simple":
        return """## Case-Specific Recommendations: Ar/O2

- Review/import O2 electron cross sections.
- Fill O2 DNT properties from reviewed transport/DNT sources.
- Review Ar+ + O2 ion-neutral energetics before DNT use.
"""
    if case_name == "ar_cf4_fluorocarbon":
        return """## Case-Specific Recommendations: Ar/CF4

- Review/import CF4 and CFx electron cross sections.
- Fill CFx thermochemistry from reviewed local snapshots or internal data.
- Review Ar+ + CF4 ion-neutral energetics before DNT use.
"""
    if case_name == "sf6_o2_electronegative":
        return """## Case-Specific Recommendations: Ar/SF6/O2

- Review/import SF6 attachment and dissociation cross sections.
- Review negative ion channels before expanding chemistry.
- Fill SFx thermochemistry and DNT properties from reviewed sources.
"""
    return """## Case-Specific Recommendations

- Use the missing plan to prioritize reviewed properties, reaction energetics,
  reaction channels, and cross-section mappings for this case.
"""
