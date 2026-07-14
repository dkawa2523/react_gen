from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import CaseConfig, CaseInfo, ExpansionConfig
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.application.reaction_catalog import available_dataset_ids
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.equations import format_equation
from plasma_reactgen.domain.models import CollisionPair, SpeciesAmount
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.indexer import check_registry_details
from plasma_reactgen.validation.validators import validate_reaction

from .cache import safe_filename, sha256_file
from .lxcat_raw_import import parse_lxcat_raw_file
from .registry_admin_io import (
    duplicate_report as _duplicate_report,
    find_import as _find_import,
    read_yaml as _read_yaml,
    record_import as _record_import,
    write_numeric_csv as _write_numeric_csv,
    write_report as _write_report,
    write_yaml as _write_yaml,
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
REDISTRIBUTION_VALUES = {"permitted", "internal", "site-local"}


def plan_registry_pack(
    *,
    seed_gases: list[str],
    max_depth: int,
    registry_root: str | Path,
) -> dict[str, Any]:
    plan, _, _ = _analyze_registry_pack(seed_gases, max_depth, Path(registry_root))
    return plan


def _analyze_registry_pack(
    seed_gases: list[str],
    max_depth: int,
    registry_root: Path,
) -> tuple[dict[str, Any], Any, FileRegistry]:
    """Build the network once for both planning and pack construction."""

    registry = FileRegistry(registry_root)
    config = CaseConfig(
        case=CaseInfo(name="registry_pack_plan"),
        gases=list(seed_gases),
        expansion=ExpansionConfig(max_depth=max_depth),
    )
    network = ReactionNetworkBuilder(
        NetworkBuilderDependencies(registry, registry, registry)
    ).generate(config)
    states = build_state_list(network, registry)
    dnt_tasks = build_dnt_tasks(network, asset_exists=registry.asset_exists)
    missing = build_missing_data(network, states, dnt_tasks=dnt_tasks)

    missing_cross_sections = sorted(
        reaction.id
        for reaction in network.reactions
        if not available_dataset_ids(reaction, "cross_section", registry.asset_exists)
    )
    missing_rates = sorted(
        reaction.id
        for reaction in network.reactions
        if not available_dataset_ids(reaction, "rate_coefficient", registry.asset_exists)
    )
    ion_neutral_missing = sorted(
        task["pair_id"]
        for task in dnt_tasks
        if not any(
            item["available"]
            for datasets in task["existing_datasets"].values()
            for item in datasets
        )
    )
    dnt_properties_missing = sorted(
        {
            f"{task['pair_id']}:{side}.{name}"
            for task in dnt_tasks
            for side, properties in task["required_properties"].items()
            for name, prop in properties.items()
            if not prop["available"]
        }
    )
    generated_species = sorted(
        species_id
        for species_id, node in network.species_nodes.items()
        if "reaction_product" in node.roles and species_id not in set(seed_gases)
    )
    missing_pairs = _admin_missing_pairs(network.species, registry)
    plan = {
        "schema_version": 1,
        "seed_gases": list(seed_gases),
        "max_depth": max_depth,
        "registry": str(registry_root),
        "missing_reaction_pairs": missing_pairs,
        "generated_species": generated_species,
        "reactions_missing_cross_sections": missing_cross_sections,
        "reactions_missing_rate_coefficients": missing_rates,
        "ion_neutral_pairs_missing_existing_data": ion_neutral_missing,
        "dnt_properties_missing": dnt_properties_missing,
        "missing_data": [
            {
                "subject_kind": item.subject_kind,
                "subject_id": item.subject_id,
                "field": item.field,
                "severity": item.severity,
            }
            for item in missing
        ],
        "summary": {
            "n_species": len(network.species_nodes),
            "n_reactions": len(network.reactions),
            "n_missing_reaction_pairs": len(missing_pairs),
            "n_reactions_missing_cross_sections": len(missing_cross_sections),
            "n_reactions_missing_rate_coefficients": len(missing_rates),
            "n_dnt_properties_missing": len(dnt_properties_missing),
        },
    }
    return plan, network, registry


def import_property_snapshot(
    snapshot: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    snapshot = Path(snapshot)
    registry_root = Path(registry_root)
    digest = sha256_file(snapshot)
    duplicate = _find_import(registry_root, "property_snapshot", digest)
    if duplicate is not None:
        return _duplicate_report("property_snapshot", snapshot, digest, duplicate)

    records = _property_records(snapshot)
    species_paths = _species_paths(registry_root)
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for record in records:
        species_id = str(record.get("species_id") or record.get("species") or "")
        raw_name = str(record.get("property") or record.get("name") or "")
        normalized = PROPERTY_ALIASES.get(raw_name)
        if not species_id or normalized is None:
            review.append({"record": record, "reason": "unsupported_property_or_species"})
            continue
        path = species_paths.get(species_id)
        if path is None:
            review.append({"record": record, "reason": "species_id_not_found"})
            continue
        try:
            value = float(record.get("value"))
        except (TypeError, ValueError):
            review.append({"record": record, "reason": "non_numeric_value"})
            continue
        property_name, default_unit = normalized
        quality = str(record.get("quality") or "evaluated").lower()
        if quality not in QUALITY_VALUES:
            review.append({"record": record, "reason": "unsupported_quality"})
            continue
        payload = _read_yaml(path)
        properties = payload.setdefault("properties", {})
        source_record = _source_record(record, snapshot, digest)
        properties[property_name] = {
            "value": value,
            "unit": record.get("unit") or default_unit,
            "source": record.get("source") or snapshot.name,
            "quality": quality,
            "source_record": source_record,
        }
        _write_yaml(path, payload)
        applied.append({"species_id": species_id, "property": property_name})

    report = {
        "schema_version": 1,
        "kind": "property_snapshot",
        "input_file": str(snapshot),
        "sha256": digest,
        "applied": applied,
        "review": review,
        "duplicate": False,
        "summary": {"n_applied": len(applied), "n_review": len(review)},
    }
    _record_import(registry_root, report)
    _write_report(report_dir, "property_snapshot_import.yaml", report)
    return report


def import_rate_snapshot(
    snapshot: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    snapshot = Path(snapshot)
    registry_root = Path(registry_root)
    digest = sha256_file(snapshot)
    duplicate = _find_import(registry_root, "rate_snapshot", digest)
    if duplicate is not None:
        return _duplicate_report("rate_snapshot", snapshot, digest, duplicate)
    records = _generic_records(snapshot)
    channels = _channel_records(registry_root)
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        matches = _exact_channel_matches(record, channels)
        if len(matches) != 1:
            review.append(
                {
                    "record": record,
                    "reason": "ambiguous_mapping" if len(matches) > 1 else "no_exact_mapping",
                    "candidate_reaction_ids": [match["reaction_id"] for match in matches],
                }
            )
            continue
        match = matches[0]
        representation = str(record.get("representation") or "constant")
        if representation not in {"constant", "table", "arrhenius"}:
            review.append({"record": record, "reason": "unsupported_representation"})
            continue
        dataset_id = f"ds_{safe_filename(match['reaction_id'])}_rate_{digest[:12]}_{index:03d}"
        dataset = {
            "id": dataset_id,
            "kind": "rate_coefficient",
            "representation": representation,
            "unit": record.get("unit"),
            "parameters": dict(record.get("parameters", {})) if isinstance(record.get("parameters"), dict) else {},
            "validity": _temperature_validity(record),
            "source_record": _source_record(record, snapshot, digest),
            "status": "imported",
            "preferred": bool(record.get("preferred", False)),
        }
        if representation == "constant" and "value" in record:
            dataset["parameters"]["value"] = record["value"]
        if representation == "constant" and "constant" in record:
            dataset["parameters"]["value"] = record["constant"]
        if representation == "arrhenius":
            for key in ("A", "n", "Ea", "Ea_eV", "T0_K"):
                if key in record and key not in dataset["parameters"]:
                    dataset["parameters"][key] = record[key]
        if representation == "table":
            asset_path = _rate_table_asset(record, snapshot, registry_root, digest, index)
            if asset_path is None:
                review.append({"record": record, "reason": "rate_table_data_missing"})
                continue
            dataset["path"] = asset_path
            dataset["independent_variable"] = record.get("independent_variable") or "temperature"
            dataset["dependent_variable"] = record.get("dependent_variable") or "rate_coefficient"
        if _append_dataset(match, dataset):
            applied.append({"reaction_id": match["reaction_id"], "dataset_id": dataset_id})
    report = {
        "schema_version": 1,
        "kind": "rate_snapshot",
        "input_file": str(snapshot),
        "sha256": digest,
        "applied": applied,
        "review": review,
        "duplicate": False,
        "summary": {"n_applied": len(applied), "n_review": len(review)},
    }
    _record_import(registry_root, report)
    _write_report(report_dir, "rate_snapshot_import.yaml", report)
    return report


def import_lxcat_raw(
    raw_file: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    """Import local LXCat blocks and apply only unique exact reaction matches."""

    if redistribution_status not in REDISTRIBUTION_VALUES:
        raise ValueError(f"unsupported redistribution status: {redistribution_status}")
    raw_file = Path(raw_file)
    registry_root = Path(registry_root)
    digest = sha256_file(raw_file)
    duplicate = _find_import(registry_root, "lxcat_raw", digest)
    if duplicate is not None:
        return _duplicate_report("lxcat_raw", raw_file, digest, duplicate)

    blocks = _split_lxcat_blocks(raw_file)
    channels = _channel_records(registry_root)
    assets: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    temp_root = (Path(report_dir) if report_dir else registry_root) / ".lxcat_blocks"
    try:
        for index, block in enumerate(blocks, start=1):
            temp_path = temp_root / f"{digest[:12]}_{index:03d}.txt"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(block, encoding="utf-8")
            try:
                parsed = parse_lxcat_raw_file(temp_path)
            except ValueError as exc:
                review.append({"block": index, "reason": "unsupported_block", "message": str(exc)})
                continue
            header = _source_header(block)
            match_record = {
                "reaction_id": parsed.reaction_id,
                "equation": parsed.process_label_original,
            }
            matches = _exact_channel_matches(match_record, channels)
            asset_name = f"lxcat_{digest[:12]}_{index:03d}.csv"
            relative_path = f"assets/cross_sections/{asset_name}"
            asset_path = registry_root / relative_path
            _write_numeric_csv(asset_path, parsed.rows, ("energy_eV", "cross_section_m2"))
            metadata = {
                "original_file": str(raw_file),
                "sha256": digest,
                "block_index": index,
                "source_header": header,
                "database": _header_value(header, "database"),
                "contributor": _header_value(header, "contributor"),
                "citation": _header_value(header, "citation"),
                "process_label_original": parsed.process_label_original,
                "reaction_id": parsed.reaction_id,
                "units": {"energy": "eV", "cross_section": "m2"},
                "redistribution_status": redistribution_status,
                "license_note": "Follow the original LXCat database citation and redistribution terms.",
            }
            _write_yaml(asset_path.with_suffix(".metadata.yaml"), metadata)
            assets.append({"path": relative_path, "metadata": metadata})
            if len(matches) != 1:
                review.append(
                    {
                        "block": index,
                        "asset_path": relative_path,
                        "reason": "ambiguous_mapping" if len(matches) > 1 else "no_exact_mapping",
                        "candidate_reaction_ids": [match["reaction_id"] for match in matches],
                    }
                )
                continue
            match = matches[0]
            dataset_id = f"ds_{safe_filename(match['reaction_id'])}_xs_{digest[:12]}_{index:03d}"
            dataset = {
                "id": dataset_id,
                "kind": "cross_section",
                "representation": "table",
                "independent_variable": "energy",
                "dependent_variable": "cross_section",
                "unit": "m2",
                "path": relative_path,
                "validity": {
                    "minimum": parsed.rows[0]["energy_eV"],
                    "maximum": parsed.rows[-1]["energy_eV"],
                    "unit": "eV",
                },
                "source_record": {
                    "source_type": "lxcat_local_export",
                    "sha256": digest,
                    "database": metadata["database"],
                    "contributor": metadata["contributor"],
                    "citation": metadata["citation"],
                    "redistribution_status": redistribution_status,
                },
                "status": "imported",
            }
            if _append_dataset(match, dataset):
                applied.append({"reaction_id": match["reaction_id"], "dataset_id": dataset_id})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)

    report = {
        "schema_version": 1,
        "kind": "lxcat_raw",
        "input_file": str(raw_file),
        "sha256": digest,
        "assets": assets,
        "applied": applied,
        "review": review,
        "duplicate": False,
        "summary": {
            "n_blocks": len(blocks),
            "n_assets": len(assets),
            "n_applied": len(applied),
            "n_review": len(review),
        },
    }
    _record_import(registry_root, report)
    _write_report(report_dir, "lxcat_raw_import.yaml", report)
    return report


def build_registry_pack(
    *,
    pack_id: str,
    version: str,
    seed_gases: list[str],
    max_depth: int,
    registry_root: str | Path,
    packs_root: str | Path = Path("registry_packs"),
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    if redistribution_status not in REDISTRIBUTION_VALUES:
        raise ValueError(f"unsupported redistribution status: {redistribution_status}")
    registry_root = Path(registry_root)
    packs_root = Path(packs_root)
    validation = validate_registry_pack_source(registry_root)
    if validation["errors"]:
        return {
            "schema_version": 1,
            "built": False,
            "pack_id": pack_id,
            "version": version,
            "validation": validation,
        }

    plan, network, registry = _analyze_registry_pack(
        seed_gases, max_depth, registry_root
    )
    pack_root = packs_root / safe_filename(pack_id) / safe_filename(version)
    staging_root = pack_root.parent / f".{safe_filename(version)}.tmp"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    (staging_root / "species").mkdir(parents=True)
    (staging_root / "reactions").mkdir(parents=True)
    (staging_root / "assets" / "cross_sections").mkdir(parents=True)
    (staging_root / "assets" / "rate_coefficients").mkdir(parents=True)

    supported_species = sorted(network.species)
    species_paths = _species_paths(registry_root)
    for species_id in supported_species:
        path = species_paths.get(species_id)
        if path is not None:
            shutil.copy2(path, staging_root / "species" / path.name)

    pair_keys = {reaction.source_pair_key for reaction in network.reactions}
    source_manifest: list[dict[str, Any]] = []
    excluded_assets: list[dict[str, Any]] = []
    for path in registry.iter_reaction_files():
        payload = _read_yaml(path)
        pair = payload.get("pair", {})
        key = f"{pair.get('family')}|{pair.get('projectile')}|{pair.get('target')}"
        if key not in pair_keys:
            continue
        destination = staging_root / "reactions" / str(pair["family"]) / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        for channel in payload.get("channels", []):
            source_manifest.extend(_channel_sources(channel))
            for asset in _channel_assets(channel):
                source_path = registry_root / asset["path"]
                if (
                    redistribution_status == "permitted"
                    and asset["redistribution_status"] == "permitted"
                    and source_path.is_file()
                ):
                    target = staging_root / asset["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, target)
                    metadata_path = source_path.with_suffix(".metadata.yaml")
                    if metadata_path.is_file():
                        shutil.copy2(metadata_path, target.with_suffix(".metadata.yaml"))
                else:
                    excluded_assets.append(asset)

    manifest = {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "seed_gases": list(seed_gases),
        "supported_species": supported_species,
        "recommended_max_depth": max_depth,
        "source_manifest": _unique_dicts(source_manifest),
        "data_coverage_summary": plan["summary"],
        "redistribution_status": redistribution_status,
        "excluded_numeric_assets": _unique_dicts(excluded_assets),
        "validation": validation,
    }
    _write_yaml(staging_root / "pack.yaml", manifest)
    _replace_directory(staging_root, pack_root)
    _update_pack_index(packs_root, manifest, pack_root)
    return {
        "schema_version": 1,
        "built": True,
        "pack_root": str(pack_root),
        "pack": manifest,
        "validation": validation,
    }


def _replace_directory(staging: Path, destination: Path) -> None:
    """Publish a fully-built directory while preserving the old copy on failure."""

    backup = destination.with_name(f".{destination.name}.old")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.rename(backup)
    try:
        staging.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def validate_registry_pack_source(registry_root: str | Path) -> dict[str, list[str]]:
    registry_root = Path(registry_root)
    details = check_registry_details(registry_root, strict=True)
    errors = list(details["errors"])
    warnings = list(details["warnings"])
    registry = FileRegistry(registry_root)
    dataset_ids: dict[str, str] = {}
    species = {
        species_id: registry.get_species(species_id)
        for species_id in _species_paths(registry_root)
    }
    for path in registry.iter_reaction_files():
        payload = _read_yaml(path)
        pair_data = payload.get("pair", {})
        pair = CollisionPair(
            str(pair_data.get("family")),
            str(pair_data.get("projectile")),
            str(pair_data.get("target")),
        )
        for channel in payload.get("channels", []):
            products = [
                SpeciesAmount(str(item.get("species")), float(item.get("n", 1)))
                for item in channel.get("products", [])
            ]
            validation = validate_reaction(
                [SpeciesAmount(pair.projectile), SpeciesAmount(pair.target)],
                products,
                {key: value for key, value in species.items() if value is not None},
            )
            if validation.get("charge_balance") == "failed" or validation.get("element_balance") == "failed":
                errors.append(f"reaction {channel.get('id')}: charge or element balance failed")
            if not _channel_sources(channel):
                warnings.append(f"reaction {channel.get('id')}: source metadata is missing")
            datasets = channel.get("data", {}).get("datasets", [])
            for dataset in datasets if isinstance(datasets, list) else []:
                dataset_id = dataset.get("id")
                if not dataset_id:
                    errors.append(f"reaction {channel.get('id')}: dataset id is missing")
                elif str(dataset_id) in dataset_ids:
                    errors.append(
                        f"duplicate dataset id '{dataset_id}': "
                        f"{dataset_ids[str(dataset_id)]} and {channel.get('id')}"
                    )
                else:
                    dataset_ids[str(dataset_id)] = str(channel.get("id"))
                if not dataset.get("unit") and dataset.get("kind") not in {"threshold", "reaction_energy"}:
                    errors.append(f"dataset {dataset.get('id')}: unit is missing")
                source = dataset.get("source_record") or dataset.get("source")
                if not source:
                    warnings.append(f"dataset {dataset.get('id')}: source metadata is missing")
                asset_path = dataset.get("path") or (dataset.get("asset") or {}).get("path")
                if asset_path and not (registry_root / asset_path).is_file():
                    errors.append(f"dataset {dataset.get('id')}: asset does not exist: {asset_path}")
    return {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def _admin_missing_pairs(species: dict[str, Any], registry: FileRegistry) -> list[str]:
    """Enumerate maintenance candidates without affecting normal generation."""

    ids = sorted(species)
    candidates: dict[str, CollisionPair] = {}
    for species_id in ids:
        if species_id == "e":
            continue
        item = species[species_id]
        family = "electron" if item.charge == 0 else "electron_ion"
        pair = CollisionPair(family, "e", species_id)
        candidates[pair.key] = pair
    non_electron = [species_id for species_id in ids if species_id != "e"]
    for left_index, left_id in enumerate(non_electron):
        for right_id in non_electron[left_index + 1 :]:
            left = species[left_id]
            right = species[right_id]
            if left.charge == 0 and right.charge == 0:
                pair = CollisionPair("neutral_neutral", left_id, right_id)
            elif left.charge != 0 and right.charge != 0:
                pair = CollisionPair("ion_ion", left_id, right_id)
            else:
                ion_id, neutral_id = (
                    (left_id, right_id) if left.charge != 0 else (right_id, left_id)
                )
                pair = CollisionPair("ion_neutral", ion_id, neutral_id)
            candidates[pair.key] = pair
    return sorted(
        pair.key for pair in candidates.values() if not registry.has_pair(pair)
    )


def _property_records(path: Path) -> list[dict[str, Any]]:
    records = _generic_records(path)
    expanded: list[dict[str, Any]] = []
    for record in records:
        if record.get("property") or record.get("name"):
            expanded.append(record)
            continue
        species_id = record.get("species_id") or record.get("species") or record.get("id")
        common = {
            key: record.get(key)
            for key in ("source", "citation", "quality", "redistribution_status")
            if record.get(key) is not None
        }
        for name in PROPERTY_ALIASES:
            if name not in record or record[name] in (None, ""):
                continue
            expanded.append(
                {
                    "species_id": species_id,
                    "property": name,
                    "value": record[name],
                    "unit": record.get(f"{name}_unit"),
                    **common,
                }
            )
    return expanded


def _generic_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = _read_yaml(path)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    for key in ("records", "properties", "rates"):
        records = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(records, list):
            return [dict(item) for item in records if isinstance(item, dict)]
    return [dict(payload)] if isinstance(payload, dict) and payload else []


def _species_paths(registry_root: Path) -> dict[str, Path]:
    result = {}
    for path in sorted((registry_root / "species").glob("*.yaml")):
        payload = _read_yaml(path)
        if payload.get("id"):
            result[str(payload["id"])] = path
    return result


def _channel_records(registry_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((registry_root / "reactions").glob("*/*.yaml")):
        payload = _read_yaml(path)
        pair = payload.get("pair", {})
        reactants = [
            SpeciesAmount(str(pair.get("projectile"))),
            SpeciesAmount(str(pair.get("target"))),
        ]
        for index, channel in enumerate(payload.get("channels", [])):
            products = [
                SpeciesAmount(str(item.get("species")), float(item.get("n", 1)))
                for item in channel.get("products", [])
            ]
            records.append(
                {
                    "reaction_id": str(channel.get("id") or ""),
                    "equation": format_equation(reactants, products),
                    "path": path,
                    "channel_index": index,
                }
            )
    return records


def _exact_channel_matches(
    record: dict[str, Any],
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reaction_id = str(record.get("reaction_id") or "").strip()
    if reaction_id:
        return [channel for channel in channels if channel["reaction_id"] == reaction_id]
    equation = _normalize_equation(record.get("equation") or record.get("reaction"))
    if not equation:
        return []
    return [channel for channel in channels if _normalize_equation(channel["equation"]) == equation]


def _normalize_equation(value: Any) -> str:
    return " ".join(str(value or "").replace("=>", "->").split())


def _append_dataset(match: dict[str, Any], dataset: dict[str, Any]) -> bool:
    path = Path(match["path"])
    payload = _read_yaml(path)
    channel = payload["channels"][match["channel_index"]]
    data = channel.setdefault("data", {})
    datasets = data.setdefault("datasets", [])
    if any(item.get("id") == dataset["id"] for item in datasets if isinstance(item, dict)):
        return False
    datasets.append(dataset)
    _write_yaml(path, payload)
    return True


def _temperature_validity(record: dict[str, Any]) -> dict[str, Any]:
    minimum = record.get("temperature_min") or record.get("temperature_min_K")
    maximum = record.get("temperature_max") or record.get("temperature_max_K")
    validity = {"unit": record.get("temperature_unit") or "K"}
    if minimum not in (None, ""):
        validity["minimum"] = float(minimum)
    if maximum not in (None, ""):
        validity["maximum"] = float(maximum)
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
        if not source.is_absolute():
            source = snapshot.parent / source
        if not source.is_file():
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return relative
    table = record.get("table")
    if not isinstance(table, list) or not table:
        return None
    rows = [row for row in table if isinstance(row, dict)]
    if not rows:
        return None
    fields = tuple(rows[0])
    _write_numeric_csv(destination, rows, fields)
    return relative


def _source_record(record: dict[str, Any], source_file: Path, digest: str) -> dict[str, Any]:
    redistribution = str(record.get("redistribution_status") or "site-local")
    if redistribution not in REDISTRIBUTION_VALUES:
        redistribution = "site-local"
    return {
        "source_type": record.get("source_type") or "local_snapshot",
        "source": record.get("source") or source_file.name,
        "citation": record.get("citation"),
        "sha256": digest,
        "redistribution_status": redistribution,
    }


def _split_lxcat_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) >= 5 and set(stripped) <= {"-", "="}:
            if blocks[-1]:
                blocks.append([])
            continue
        blocks[-1].append(line)
    common_header = blocks[0] if blocks and not _has_numeric_rows(blocks[0]) else []
    result = [
        "\n".join([*common_header, *block]).strip() + "\n"
        for block in blocks
        if _has_numeric_rows(block)
    ]
    return result or [text]


def _has_numeric_rows(lines: list[str]) -> bool:
    count = 0
    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            float(parts[0])
            float(parts[1])
            count += 1
        except ValueError:
            continue
    return count >= 2


def _source_header(block: str) -> list[str]:
    header = []
    for line in block.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) >= 2:
            try:
                float(parts[0])
                float(parts[1])
                continue
            except ValueError:
                pass
        if line.strip():
            header.append(line.rstrip())
    return header


def _header_value(header: list[str], key: str) -> str | None:
    prefix = key.lower()
    for line in header:
        normalized = line.strip()
        if ":" not in normalized:
            continue
        name, value = normalized.split(":", 1)
        if name.strip().lower() == prefix:
            return value.strip()
    return None


def _channel_sources(channel: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for value in (
        channel.get("source_record"),
        channel.get("provenance"),
        channel.get("evidence"),
    ):
        if isinstance(value, dict) and value:
            sources.append(dict(value))
    data = channel.get("data", {})
    for dataset in data.get("datasets", []) if isinstance(data, dict) else []:
        source = dataset.get("source_record") or dataset.get("source")
        if isinstance(source, dict) and source:
            sources.append(dict(source))
        elif source:
            sources.append({"source": source})
    return sources


def _channel_assets(channel: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    data = channel.get("data", {})
    if not isinstance(data, dict):
        return assets
    legacy = data.get("cross_section")
    if isinstance(legacy, dict) and legacy.get("path"):
        assets.append(
            {
                "path": str(legacy["path"]),
                "kind": "cross_section",
                "redistribution_status": str(legacy.get("redistribution_status") or "site-local"),
            }
        )
    for dataset in data.get("datasets", []) if isinstance(data.get("datasets"), list) else []:
        asset = dataset.get("asset")
        path = dataset.get("path") or (asset.get("path") if isinstance(asset, dict) else None)
        if not path:
            continue
        source = dataset.get("source_record") or dataset.get("source") or {}
        redistribution = (
            source.get("redistribution_status")
            if isinstance(source, dict)
            else dataset.get("redistribution_status")
        )
        assets.append(
            {
                "path": str(path),
                "kind": str(dataset.get("kind") or "unknown"),
                "redistribution_status": str(redistribution or "site-local"),
            }
        )
    return assets


def _unique_dicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for record in records:
        key = yaml.safe_dump(record, sort_keys=True, allow_unicode=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _update_pack_index(packs_root: Path, manifest: dict[str, Any], pack_root: Path) -> None:
    path = packs_root / "index.yaml"
    index = _read_yaml(path) if path.is_file() else {"schema_version": 1, "packs": []}
    entry = {
        "id": manifest["id"],
        "version": manifest["version"],
        "path": pack_root.relative_to(packs_root).as_posix(),
        "seed_gases": manifest["seed_gases"],
        "redistribution_status": manifest["redistribution_status"],
    }
    packs = [
        item
        for item in index.setdefault("packs", [])
        if not (item.get("id") == entry["id"] and item.get("version") == entry["version"])
    ]
    packs.append(entry)
    index["packs"] = sorted(packs, key=lambda item: (str(item.get("id")), str(item.get("version"))))
    _write_yaml(path, index)
