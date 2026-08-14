"""Resolve prepare-time providers and record their local source inputs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plasma_reactgen.data_sources.cache import record_source_file
from plasma_reactgen.data_sources.provider_factory import (
    build_property_providers,
    build_reaction_providers,
    build_species_providers,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile

_INTERNAL_SOURCE_LOCATIONS = (
    ("species", "species"),
    ("properties", "properties"),
    ("reactions", "electron"),
    ("reactions", "ion_neutral"),
    ("cross_sections", "index"),
)
_SOURCE_SUFFIXES = ("yaml", "yml", "json", "csv")


@dataclass(frozen=True)
class PreparationContext:
    internal_root: Path | None
    nist_root: Path | None
    ion_reaction_table_files: list[Path]
    uses_chemicals: bool
    species_providers: list[Any]
    property_providers: list[Any]
    reaction_providers: list[Any]
    provider_warnings: list[dict[str, Any]]
    unavailable_sources: list[dict[str, Any]]

    @property
    def has_providers(self) -> bool:
        return bool(self.species_providers or self.property_providers or self.reaction_providers)


def resolve_source_profile(
    source_profile: str | dict[str, Any] | None,
    registry_root: Path,
) -> dict[str, Any]:
    if isinstance(source_profile, dict):
        return deepcopy(source_profile)
    return load_source_profile(source_profile, registry_root)


def build_preparation_context(profile: dict[str, Any]) -> PreparationContext:
    species = build_species_providers(profile)
    properties = build_property_providers(profile)
    reactions = build_reaction_providers(profile)
    return PreparationContext(
        internal_root=_configured_root(profile, "internal_file"),
        nist_root=_configured_root(profile, "nist_snapshot"),
        ion_reaction_table_files=_ion_reaction_table_files(profile),
        uses_chemicals=any(
            _chemicals_provider_name(profile, section)
            for section in ("species_identity", "properties")
        ),
        species_providers=species.providers,
        property_providers=properties.providers,
        reaction_providers=reactions.providers,
        provider_warnings=[
            *species.warnings,
            *properties.warnings,
            *reactions.warnings,
        ],
        unavailable_sources=[
            *species.unavailable_sources,
            *properties.unavailable_sources,
            *reactions.unavailable_sources,
        ],
    )


def record_context_sources(
    report: dict[str, Any],
    source_cache_root: Path,
    context: PreparationContext,
) -> None:
    if context.internal_root is not None:
        report["source_cache"].extend(
            _record_source_files(
                source_cache_root,
                "internal_file",
                _internal_source_files(context.internal_root),
            )
        )
    if context.ion_reaction_table_files:
        report["source_cache"].extend(
            _record_source_files(
                source_cache_root,
                "ion_reaction_table",
                context.ion_reaction_table_files,
            )
        )


def _configured_root(profile: dict[str, Any], key: str) -> Path | None:
    config = profile.get(key)
    if not isinstance(config, dict) or not config.get("root"):
        return None
    return Path(config["root"])


def _ion_reaction_table_files(profile: dict[str, Any]) -> list[Path]:
    config = profile.get("ion_reaction_table")
    files = config.get("files", []) if isinstance(config, dict) else []
    return [Path(path) for path in files if path] if isinstance(files, list) else []


def _internal_source_files(root: Path) -> list[Path]:
    candidates = (
        root / directory / f"{stem}.{suffix}"
        for directory, stem in _INTERNAL_SOURCE_LOCATIONS
        for suffix in _SOURCE_SUFFIXES
    )
    return [path for path in candidates if path.exists()]


def _record_source_files(
    cache_root: Path,
    source_name: str,
    files: list[Path],
) -> list[dict[str, Any]]:
    return [record_source_file(cache_root, source_name, path) for path in files if path.exists()]


def _chemicals_provider_name(profile: dict[str, Any], section: str) -> str | None:
    providers = profile.get(section, [])
    if not isinstance(providers, list):
        return None
    return next(
        (name for name in ("chemicals_optional", "chemicals_local") if name in providers),
        None,
    )


__all__ = [
    "PreparationContext",
    "build_preparation_context",
    "record_context_sources",
    "resolve_source_profile",
]
