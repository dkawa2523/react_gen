from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.data_sources.cache import record_source_file
from plasma_reactgen.data_sources.provider_factory import (
    build_property_providers,
    build_reaction_providers,
    build_species_providers,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile
from plasma_reactgen.domain.identifiers import pair_filename, to_file_key
from plasma_reactgen.domain.models import CollisionPair, PropertyValue
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.property_enrichment import enrich_species_properties
from plasma_reactgen.preparation.reaction_enrichment import enrich_reaction_channels


def prepare_case(
    input_path: str | Path,
    registry_root: str | Path,
    source_profile: str | dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    preserve_local_overlays: bool = False,
) -> dict[str, Any]:
    input_path = Path(input_path)
    registry_root = Path(registry_root)
    output_dir = Path(output_dir) if output_dir is not None else input_path.parent / "prepared_registry"

    config = load_case_config(input_path, registry_root)
    profile = _resolve_source_profile(source_profile, registry_root)
    internal_root = _internal_root(profile)
    nist_root = _nist_root(profile)
    ion_reaction_table_files = _ion_reaction_table_files(profile)
    chemicals_species_name = _chemicals_provider_name(profile, "species_identity")
    chemicals_properties_name = _chemicals_provider_name(profile, "properties")
    uses_chemicals_species = chemicals_species_name is not None
    uses_chemicals_properties = chemicals_properties_name is not None
    species_result = build_species_providers(profile)
    property_result = build_property_providers(profile)
    reaction_result = build_reaction_providers(profile)
    species_providers = species_result.providers
    property_providers = property_result.providers
    reaction_providers = reaction_result.providers
    provider_warnings = [
        *species_result.warnings,
        *property_result.warnings,
        *reaction_result.warnings,
    ]
    unavailable_sources = [
        *species_result.unavailable_sources,
        *property_result.unavailable_sources,
        *reaction_result.unavailable_sources,
    ]

    report = {
        "schema_version": 1,
        "source_profile": {
            "name": profile.get("name", "custom"),
            "internal_file_root": str(internal_root) if internal_root is not None else None,
            "nist_snapshot_root": str(nist_root) if nist_root is not None else None,
            "ion_reaction_table_files": [str(path) for path in ion_reaction_table_files],
            "chemicals_optional": uses_chemicals_species or uses_chemicals_properties,
        },
        "prepared_registry": str(output_dir),
        "registry_mutated": False,
        "auto_promoted": False,
        "summary": {
            "n_species_written": 0,
            "n_properties_written": 0,
            "n_reaction_files_written": 0,
            "n_species_seeded_from_reactions": 0,
            "n_properties_filled_for_seeded_species": 0,
            "n_unresolved_product_species": 0,
        },
        "entries": [],
        "source_cache": [],
        "source_provider_warnings": provider_warnings,
        "unavailable_sources": unavailable_sources,
        "species_seeded_from_reactions": [],
        "properties_filled_for_seeded_species": [],
        "unresolved_product_species": [],
    }

    source_cache_root = output_dir.parent / "source_cache"
    if internal_root is not None:
        report["source_cache"].extend(_record_existing_source_files(source_cache_root, "internal_file", _internal_source_files(internal_root)))
    if ion_reaction_table_files:
        report["source_cache"].extend(_record_existing_source_files(source_cache_root, "ion_reaction_table", ion_reaction_table_files))

    if not (species_providers or property_providers or reaction_providers):
        _write_yaml(output_dir / "prepare_report.yaml", report)
        return report

    registry = FileRegistry(registry_root)

    prepared_species: dict[str, dict[str, Any]] = {}
    for query in config.gases:
        local_species = registry.get_species(query)
        if local_species is not None:
            prepared_species[query] = _species_payload_from_registry(local_species)
            continue

        for species_provider in species_providers:
            candidates = species_provider.find_species(query)
            if not candidates:
                continue
            species = _species_payload_from_candidate(candidates[0])
            prepared_species[species["id"]] = species
            report["summary"]["n_species_written"] += 1
            report["entries"].append({"kind": "species", "id": species["id"]})
            break

    species_ids = sorted({*config.gases, *prepared_species})

    for species_id, species in prepared_species.items():
        if _has_prepared_provenance(species) or property_providers:
            _write_yaml(output_dir / "species" / f"{to_file_key(species_id)}.yaml", species)

    enrichment_report = enrich_species_properties(output_dir, property_providers, profile)
    if not preserve_local_overlays:
        _remove_unmodified_local_overlays(output_dir)
    properties_filled = list(enrichment_report["properties_filled"])
    property_conflicts = list(enrichment_report["property_conflicts"])
    unresolved_properties = list(enrichment_report["unresolved"])
    properties_filled_for_seeded_species: list[dict[str, Any]] = []

    report["properties_filled"] = enrichment_report["properties_filled"]
    report["property_conflicts"] = enrichment_report["property_conflicts"]
    report["unresolved"] = enrichment_report["unresolved"]
    report["summary"]["n_properties_written"] = enrichment_report["summary"]["n_properties_filled"]
    report["summary"]["n_properties_filled"] = enrichment_report["summary"]["n_properties_filled"]
    report["summary"]["n_property_conflicts"] = enrichment_report["summary"]["n_property_conflicts"]
    report["summary"]["n_unresolved_properties"] = enrichment_report["summary"]["n_unresolved"]

    if reaction_providers:
        reaction_report = enrich_reaction_channels(
            output_dir,
            reaction_providers,
            config,
            profile,
            species_providers=species_providers,
        )
        seeded_species_ids = sorted(
            {
                item["species"]
                for item in reaction_report.get("species_seeded_from_reactions", [])
                if item.get("species")
            }
        )
        if seeded_species_ids and property_providers:
            seeded_property_report = enrich_species_properties(
                output_dir,
                property_providers,
                profile,
                species_ids=seeded_species_ids,
            )
            properties_filled_for_seeded_species = seeded_property_report["properties_filled"]
            properties_filled.extend(seeded_property_report["properties_filled"])
            property_conflicts.extend(seeded_property_report["property_conflicts"])
            unresolved_properties.extend(seeded_property_report["unresolved"])

            report["properties_filled"] = properties_filled
            report["property_conflicts"] = property_conflicts
            report["unresolved"] = unresolved_properties
            report["summary"]["n_properties_written"] = len(properties_filled)
            report["summary"]["n_properties_filled"] = len(properties_filled)
            report["summary"]["n_property_conflicts"] = len(property_conflicts)
            report["summary"]["n_unresolved_properties"] = len(unresolved_properties)

        report["species_seeded_from_reactions"] = reaction_report["species_seeded_from_reactions"]
        report["properties_filled_for_seeded_species"] = properties_filled_for_seeded_species
        report["unresolved_product_species"] = reaction_report["unresolved_product_species"]
        report["reaction_pairs_imported"] = reaction_report["reaction_pairs_imported"]
        report["reaction_channels_imported"] = reaction_report["reaction_channels_imported"]
        report["reaction_channels_skipped"] = reaction_report["reaction_channels_skipped"]
        report["unresolved_reactions"] = reaction_report["unresolved_reactions"]
        report["summary"]["n_reaction_files_written"] = reaction_report["summary"]["n_reaction_pairs_imported"]
        report["summary"]["n_reaction_pairs_imported"] = reaction_report["summary"]["n_reaction_pairs_imported"]
        report["summary"]["n_reaction_channels_imported"] = reaction_report["summary"]["n_reaction_channels_imported"]
        report["summary"]["n_reaction_channels_skipped"] = reaction_report["summary"]["n_reaction_channels_skipped"]
        report["summary"]["n_species_seeded_from_reactions"] = reaction_report["summary"]["n_species_seeded_from_reactions"]
        report["summary"]["n_properties_filled_for_seeded_species"] = len(properties_filled_for_seeded_species)
        report["summary"]["n_unresolved_product_species"] = reaction_report["summary"]["n_unresolved_product_species"]
        report["summary"]["n_unresolved_reactions"] = reaction_report["summary"]["n_unresolved_reactions"]

    _write_yaml(output_dir / "prepare_report.yaml", report)
    return report


def _resolve_source_profile(
    source_profile: str | dict[str, Any] | None,
    registry_root: Path,
) -> dict[str, Any]:
    if isinstance(source_profile, dict):
        return deepcopy(source_profile)
    return load_source_profile(source_profile, registry_root)


def _internal_root(profile: dict[str, Any]) -> Path | None:
    internal_file = profile.get("internal_file")
    if not isinstance(internal_file, dict) or not internal_file.get("root"):
        return None
    return Path(internal_file["root"])


def _nist_root(profile: dict[str, Any]) -> Path | None:
    nist_snapshot = profile.get("nist_snapshot")
    if not isinstance(nist_snapshot, dict) or not nist_snapshot.get("root"):
        return None
    return Path(nist_snapshot["root"])


def _ion_reaction_table_files(profile: dict[str, Any]) -> list[Path]:
    ion_table = profile.get("ion_reaction_table")
    if not isinstance(ion_table, dict):
        return []
    files = ion_table.get("files", [])
    if not isinstance(files, list):
        return []
    return [Path(path) for path in files if path]


def _internal_source_files(root: Path) -> list[Path]:
    candidates = [
        root / "species" / "species.yaml",
        root / "species" / "species.yml",
        root / "species" / "species.json",
        root / "species" / "species.csv",
        root / "properties" / "properties.yaml",
        root / "properties" / "properties.yml",
        root / "properties" / "properties.json",
        root / "properties" / "properties.csv",
        root / "reactions" / "electron.yaml",
        root / "reactions" / "electron.yml",
        root / "reactions" / "electron.json",
        root / "reactions" / "electron.csv",
        root / "reactions" / "ion_neutral.yaml",
        root / "reactions" / "ion_neutral.yml",
        root / "reactions" / "ion_neutral.json",
        root / "reactions" / "ion_neutral.csv",
        root / "cross_sections" / "index.yaml",
        root / "cross_sections" / "index.yml",
        root / "cross_sections" / "index.json",
        root / "cross_sections" / "index.csv",
    ]
    return [path for path in candidates if path.exists()]


def _record_existing_source_files(cache_root: Path, source_name: str, files: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in files:
        if path.exists():
            records.append(record_source_file(cache_root, source_name, path))
    return records


def _profile_includes(profile: dict[str, Any], section: str, provider_name: str) -> bool:
    providers = profile.get(section, [])
    return isinstance(providers, list) and provider_name in providers


def _chemicals_provider_name(profile: dict[str, Any], section: str) -> str | None:
    providers = profile.get(section, [])
    if not isinstance(providers, list):
        return None
    for name in ("chemicals_optional", "chemicals_local"):
        if name in providers:
            return name
    return None


def _species_payload_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    species_id = candidate["id"]
    properties = deepcopy(candidate.get("properties", {}))
    if candidate.get("molecular_weight_amu") is not None:
        properties.setdefault(
            "mass_amu",
            {
                "value": candidate["molecular_weight_amu"],
                "unit": "amu",
                "source": "chemicals molecular weight databank",
                "source_record": deepcopy(candidate.get("source_record")),
            },
        )
    metadata = {
        "status": candidate.get("status", "imported"),
        "source_record": deepcopy(candidate.get("source_record")),
        "notes": ["Prepared from enrichment source data; curated registry was not mutated."],
    }
    if candidate.get("cas"):
        metadata["cas"] = candidate["cas"]
    if candidate.get("aliases"):
        metadata["aliases"] = list(candidate["aliases"])

    return {
        "schema_version": 1,
        "id": species_id,
        "display_name": candidate.get("display_name", species_id),
        "formula": candidate.get("formula"),
        "composition": deepcopy(candidate.get("composition", {})),
        "charge": int(candidate.get("charge", 0)),
        "classes": list(candidate.get("classes", [])),
        "state": deepcopy(candidate.get("state", {})),
        "properties": properties,
        "metadata": metadata,
    }


def _species_payload_from_registry(species) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": species.id,
        "display_name": species.id,
        "composition": deepcopy(species.composition),
        "charge": species.charge,
        "classes": sorted(species.classes),
        "state": deepcopy(species.state),
        "properties": {
            name: _property_value_payload(prop)
            for name, prop in sorted(species.properties.items())
        },
        "metadata": {
            "status": species.status,
            "notes": ["Prepared overlay; curated registry was not mutated."],
        },
    }


def _minimal_species_payload(species_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": species_id,
        "display_name": species_id,
        "composition": {},
        "charge": 0,
        "classes": [],
        "state": {},
        "properties": {},
        "metadata": {
            "status": "prepared",
            "notes": ["Prepared overlay; curated registry was not mutated."],
        },
    }


def _property_can_fill_gap(
    registry: FileRegistry,
    prepared_species: dict[str, dict[str, Any]],
    candidate: dict[str, Any],
) -> bool:
    species_id = candidate.get("species")
    property_name = candidate.get("property")
    if not species_id or not property_name:
        return False

    local_species = registry.get_species(species_id)
    if local_species is not None:
        prop = local_species.properties.get(property_name)
        if prop is not None and prop.value is not None:
            return False

    prepared = prepared_species.get(species_id)
    if prepared is not None:
        existing = prepared.get("properties", {}).get(property_name)
        if isinstance(existing, dict) and existing.get("value") is not None:
            return False

    return True


def _apply_property_candidate(species: dict[str, Any], candidate: dict[str, Any]) -> None:
    property_name = candidate["property"]
    species.setdefault("properties", {})[property_name] = {
        "value": candidate.get("value"),
        "unit": candidate.get("unit"),
        "source": candidate.get("source"),
        "evidence_type": candidate.get("evidence_type"),
        "status": candidate.get("status", "imported"),
        "source_record": deepcopy(candidate.get("source_record")),
    }


def _reaction_file_payload(pair: CollisionPair, channels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pair": {
            "family": pair.family,
            "projectile": pair.projectile,
            "target": pair.target,
        },
        "channels": [_channel_payload(channel) for channel in channels],
        "metadata": {
            "status": "prepared",
            "notes": ["Prepared from internal file data; curated registry was not mutated."],
        },
    }


def _channel_payload(channel: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(channel)
    payload.pop("pair", None)
    return payload


def _electron_pairs(species_ids: list[str]) -> list[CollisionPair]:
    return [CollisionPair("electron", "e", species_id) for species_id in species_ids]


def _has_prepared_provenance(species: dict[str, Any]) -> bool:
    source_types = {"internal_file_db", "python_package", "public_database_snapshot"}
    metadata = species.get("metadata", {})
    if (metadata.get("source_record") or {}).get("source_type") in source_types:
        return True
    for prop in species.get("properties", {}).values():
        if isinstance(prop, dict) and (prop.get("source_record") or {}).get("source_type") in source_types:
            return True
    return False


def _remove_unmodified_local_overlays(output_dir: Path) -> None:
    species_dir = output_dir / "species"
    if not species_dir.exists():
        return
    for path in sorted(species_dir.glob("*.yaml")):
        species = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if _has_prepared_provenance(species):
            continue
        path.unlink()


def _property_value_payload(prop: PropertyValue) -> dict[str, Any]:
    return {
        "value": prop.value,
        "unit": prop.unit,
        "source": prop.source,
    }


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
