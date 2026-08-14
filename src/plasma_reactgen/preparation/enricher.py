from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.data_sources.chemical_identity_snapshot import (
    ChemicalIdentitySnapshotProvider,
    enrich_species_identity_metadata,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile
from plasma_reactgen.preparation.preparer import prepare_case


def enrich_case(
    input_path: str | Path,
    registry_root: str | Path,
    workspace: str | Path,
    source_profile: str | dict[str, Any] | None = None,
    *,
    fresh: bool = False,
) -> dict[str, Any]:
    input_path = Path(input_path)
    registry_root = Path(registry_root)
    workspace = Path(workspace)
    prepared_registry = workspace / "prepared_registry"
    reused_existing_workspace = prepared_registry.exists()
    workspace_mode = "reuse" if reused_existing_workspace else "new"
    if fresh:
        workspace_mode = "fresh"

    if fresh:
        _clear_generated_workspace_files(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    _copy_registry_missing_files(registry_root, prepared_registry)

    profile = _resolve_source_profile(source_profile, registry_root)
    prepare_report = prepare_case(
        input_path=input_path,
        registry_root=registry_root,
        source_profile=profile,
        output_dir=prepared_registry,
        preserve_local_overlays=True,
    )
    (prepared_registry / "prepare_report.yaml").replace(workspace / "prepare_report.yaml")

    identity_report = _run_identity_enrichment(prepared_registry, profile)

    config = load_case_config(input_path, registry_root)
    enrichment_report = _enrichment_report(
        case_name=config.case.name,
        source_profile_name=profile.get("name", "custom"),
        prepared_registry=prepared_registry,
        prepare_report=prepare_report,
        identity_report=identity_report,
        workspace_mode=workspace_mode,
        reused_existing_workspace=reused_existing_workspace and not fresh,
    )
    _write_yaml(workspace / "enrichment_report.yaml", enrichment_report)
    return enrichment_report


def _resolve_source_profile(
    source_profile: str | dict[str, Any] | None,
    registry_root: Path,
) -> dict[str, Any]:
    if isinstance(source_profile, dict):
        return dict(source_profile)
    return load_source_profile(source_profile, registry_root)


def _copy_registry_missing_files(registry_root: Path, prepared_registry: Path) -> None:
    if not registry_root.exists():
        return
    for source in sorted(path for path in registry_root.rglob("*") if path.is_file()):
        relative = source.relative_to(registry_root)
        target = prepared_registry / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _clear_generated_workspace_files(workspace: Path) -> None:
    """Remove only artifacts owned by ``enrich`` from a workspace."""

    root = workspace.resolve()
    for name in (
        "prepared_registry",
        "source_cache",
        "prepare_report.yaml",
        "enrichment_report.yaml",
        "cross_section_mapping_report.yaml",
    ):
        target = workspace / name
        if not target.exists():
            continue
        resolved = target.resolve()
        if resolved.parent != root:
            raise ValueError(f"refusing to clear workspace path outside workspace: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()


def _enrichment_report(
    *,
    case_name: str,
    source_profile_name: str,
    prepared_registry: Path,
    prepare_report: dict[str, Any],
    workspace_mode: str,
    reused_existing_workspace: bool,
    identity_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = prepare_report.get("summary", {})
    report = {
        "schema_version": 2,
        "case": {"name": case_name},
        "source_profile": source_profile_name,
        "prepared_registry": str(prepared_registry),
        "workspace": {
            "mode": workspace_mode,
            "reused_existing_prepared_registry": reused_existing_workspace,
        },
        "summary": {
            "species_seeded": int(summary.get("n_species_written", 0)),
            "species_seeded_from_reactions": int(summary.get("n_species_seeded_from_reactions", 0)),
            "properties_filled": int(summary.get("n_properties_filled", 0)),
            "properties_filled_for_seeded_species": int(
                summary.get("n_properties_filled_for_seeded_species", 0)
            ),
            "property_conflicts": int(summary.get("n_property_conflicts", 0)),
            "reaction_channels_imported": int(summary.get("n_reaction_channels_imported", 0)),
            "cross_section_assets_registered": _count_cross_section_assets(prepared_registry),
            "unresolved_product_species": int(summary.get("n_unresolved_product_species", 0)),
            "identity_species_updated": int(
                (identity_report or {}).get("summary", {}).get("n_updated_species", 0)
            ),
            "identity_conflicts": int(
                (identity_report or {}).get("summary", {}).get("n_conflicts", 0)
            ),
        },
        "prepare_report": str(prepared_registry.parent / "prepare_report.yaml"),
        "source_cache": prepare_report.get("source_cache", []),
    }
    if identity_report is not None:
        report["chemical_identity"] = identity_report
    return report


def _run_identity_enrichment(
    prepared_registry: Path, profile: dict[str, Any]
) -> dict[str, Any] | None:
    providers = profile.get("species_identity", [])
    if not isinstance(providers, list) or "chemical_identity_snapshot" not in providers:
        return None
    config = profile.get("chemical_identity_snapshot", {})
    if not isinstance(config, dict) or not config.get("snapshot"):
        return None
    provider = ChemicalIdentitySnapshotProvider(config["snapshot"])
    return enrich_species_identity_metadata(prepared_registry, provider)


def _count_cross_section_assets(prepared_registry: Path) -> int:
    assets = prepared_registry / "assets" / "cross_sections"
    if not assets.exists():
        return 0
    return len(list(assets.glob("*.csv")))


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
