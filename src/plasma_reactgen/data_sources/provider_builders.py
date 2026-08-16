from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plasma_reactgen.data_sources.provider_profile import (
    ProviderProfile,
    configured_paths,
    selected_chemicals_provider,
    uses_internal_provider,
)


class SourceProviderConfigurationError(ValueError):
    """Raised when strict source profiles request unavailable providers."""


@dataclass
class ProviderBuildResult:
    providers: list[Any]
    unavailable_sources: list[dict[str, Any]]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return self.unavailable_sources


class ProviderBuilder:
    """Construct configured local adapters without owning selection order."""

    def __init__(self, profile: dict[str, Any]):
        self.profile = ProviderProfile(profile)
        self.unavailable_sources: list[dict[str, Any]] = []

    def result(self, providers: list[Any]) -> ProviderBuildResult:
        result = ProviderBuildResult(providers, self.unavailable_sources)
        if self.profile.strict and result.unavailable_sources:
            names = ", ".join(item["source"] for item in result.unavailable_sources)
            raise SourceProviderConfigurationError(
                f"strict source profile has unavailable providers: {names}"
            )
        return result

    def internal_species(self) -> list[Any]:
        root = self._internal_root_or_warn("species_identity")
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFileSpeciesProvider

        return [InternalFileSpeciesProvider(root)]

    def internal_properties(self) -> list[Any]:
        root = self._internal_root_or_warn("properties")
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFilePropertyProvider

        return [InternalFilePropertyProvider(root)]

    def internal_reactions(self) -> list[Any]:
        section = "ion_neutral_reactions"
        if not uses_internal_provider(self.profile, section):
            section = "electron_reactions"
        root = self._internal_root_or_warn(section)
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFileReactionProvider

        return [InternalFileReactionProvider(root)]

    def nist_properties(self) -> list[Any]:
        config = self.profile.data.get("nist_snapshot")
        root = config.get("root") if isinstance(config, dict) else None
        if not root:
            self._warn_missing_config("properties", "nist_snapshot", "nist_snapshot.root")
            return []
        from plasma_reactgen.data_sources.nist_snapshot import NistSnapshotPropertyProvider

        return [NistSnapshotPropertyProvider(root)]

    def argonne_atct_properties(self) -> list[Any]:
        files = configured_paths(self.profile, "argonne_atct_snapshot")
        if not files:
            self._warn_missing_config(
                "properties",
                "argonne_atct_snapshot",
                "argonne_atct_snapshot.files",
            )
            return []
        from plasma_reactgen.data_sources.argonne_atct_snapshot import (
            ArgonneAtctSnapshotPropertyProvider,
        )

        return [ArgonneAtctSnapshotPropertyProvider(files)]

    def chemicals_species(self) -> list[Any]:
        provider_name = selected_chemicals_provider(self.profile, "species_identity")
        if provider_name is None:
            return []
        from plasma_reactgen.data_sources.chemicals_provider import ChemicalsSpeciesProvider

        return [ChemicalsSpeciesProvider(provider_name=provider_name)]

    def chemicals_properties(self) -> list[Any]:
        provider_name = selected_chemicals_provider(self.profile, "properties")
        if provider_name is None:
            return []
        from plasma_reactgen.data_sources.chemicals_provider import ChemicalsPropertyProvider

        return [ChemicalsPropertyProvider(provider_name=provider_name)]

    def ion_reaction_tables(self) -> list[Any]:
        files = configured_paths(self.profile, "ion_reaction_table")
        if not files:
            self._warn_missing_config(
                "ion_neutral_reactions",
                "ion_reaction_table",
                "ion_reaction_table.files",
            )
            return []
        from plasma_reactgen.data_sources.ion_reaction_table import IonReactionTableProvider

        return [IonReactionTableProvider(files)]

    def _internal_root_or_warn(self, section: str) -> Path | None:
        root = self.profile.internal_root()
        if root is None:
            self._warn_missing_config(section, "internal_file", "internal_file.root")
        return root

    def _warn_missing_config(self, section: str, source_name: str, required: str) -> None:
        self.unavailable_sources.append(
            {
                "source": source_name,
                "section": section,
                "reason": "missing_config",
                "required": required,
            }
        )
