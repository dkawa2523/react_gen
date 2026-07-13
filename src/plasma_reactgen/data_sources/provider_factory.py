from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

class SourceProviderConfigurationError(ValueError):
    """Raised when strict source profiles request unavailable providers."""


@dataclass
class ProviderBuildResult:
    providers: list[Any]
    unavailable_sources: list[dict[str, Any]]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return self.unavailable_sources


def build_species_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    providers = _build_in_profile_order(
        builder,
        "species_identity",
        {
            "internal_file": builder.internal_species,
            "internal_species_db": builder.internal_species,
            "chemicals_optional": builder.chemicals_species,
            "chemicals_local": builder.chemicals_species,
        },
    )
    return builder.result(providers)


def build_property_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    providers = _build_in_profile_order(
        builder,
        "properties",
        {
            "internal_file": builder.internal_properties,
            "internal_property_db": builder.internal_properties,
            "nist_snapshot": builder.nist_properties,
            "argonne_atct_snapshot": builder.argonne_atct_properties,
            "chemicals_optional": builder.chemicals_properties,
            "chemicals_local": builder.chemicals_properties,
        },
    )
    return builder.result(providers)


def build_reaction_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    factories = {
        "internal_file": builder.internal_reactions,
        "internal_reaction_db": builder.internal_reactions,
        "ion_reaction_table": builder.ion_reaction_tables,
    }
    names: list[str] = []
    for section in ("electron_reactions", "ion_neutral_reactions"):
        for name in profile.get(section, []):
            if name not in names:
                names.append(name)
    providers: list[Any] = []
    for name in names:
        factory = factories.get(str(name))
        if factory is not None:
            providers.extend(factory())
    return builder.result(providers)


def _build_in_profile_order(
    builder: "_ProviderFactory",
    section: str,
    factories: dict[str, Any],
) -> list[Any]:
    names = builder.profile.get(section, [])
    if not isinstance(names, list):
        return []
    providers: list[Any] = []
    for name in names:
        factory = factories.get(str(name))
        if factory is not None:
            providers.extend(factory())
    return providers


def available_provider_names() -> dict[str, list[str]]:
    return {
        "species_identity": [
            "local_registry",
            "internal_species_db",
            "internal_file",
            "chemical_identity_snapshot",
            "chemicals_optional",
            "chemicals_local",
        ],
        "properties": [
            "local_registry",
            "internal_property_db",
            "internal_file",
            "nist_snapshot",
            "argonne_atct_snapshot",
            "chemicals_optional",
            "chemicals_local",
        ],
        "ion_neutral_reactions": [
            "local_registry",
            "internal_reaction_db",
            "internal_file",
            "ion_reaction_table",
            "literature_candidates",
        ],
        "electron_reactions": [
            "local_registry",
            "internal_reaction_db",
            "internal_file",
        ],
    }


class _ProviderFactory:
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.unavailable_sources: list[dict[str, Any]] = []

    def result(self, providers: list[Any]) -> ProviderBuildResult:
        result = ProviderBuildResult(
            providers=providers,
            unavailable_sources=self.unavailable_sources,
        )
        if self.profile.get("strict_sources") and result.unavailable_sources:
            names = ", ".join(item["source"] for item in result.unavailable_sources)
            raise SourceProviderConfigurationError(f"strict source profile has unavailable providers: {names}")
        return result

    def internal_species(self) -> list[Any]:
        if not self._uses_internal("species_identity") and self._internal_root() is None:
            return []
        root = self._internal_root_or_warn("species_identity", "internal_file")
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFileSpeciesProvider

        return [InternalFileSpeciesProvider(root)]

    def internal_properties(self) -> list[Any]:
        if not self._uses_internal("properties") and self._internal_root() is None:
            return []
        root = self._internal_root_or_warn("properties", "internal_file")
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFilePropertyProvider

        return [InternalFilePropertyProvider(root)]

    def internal_reactions(self) -> list[Any]:
        if (
            not self._uses_internal("ion_neutral_reactions")
            and not self._uses_internal("electron_reactions")
            and self._internal_root() is None
        ):
            return []
        root = self._internal_root_or_warn("ion_neutral_reactions", "internal_file")
        if root is None:
            return []
        from plasma_reactgen.data_sources.internal_file import InternalFileReactionProvider

        return [InternalFileReactionProvider(root)]

    def nist_properties(self) -> list[Any]:
        if not self._listed("properties", "nist_snapshot"):
            return []
        config = self.profile.get("nist_snapshot")
        root = config.get("root") if isinstance(config, dict) else None
        if not root:
            self._warn_missing_config("properties", "nist_snapshot", "nist_snapshot.root")
            return []
        from plasma_reactgen.data_sources.nist_snapshot import NistSnapshotPropertyProvider

        return [NistSnapshotPropertyProvider(root)]

    def argonne_atct_properties(self) -> list[Any]:
        if not self._listed("properties", "argonne_atct_snapshot"):
            return []
        config = self.profile.get("argonne_atct_snapshot")
        files = _paths_from_config(config, "files")
        if not files:
            self._warn_missing_config("properties", "argonne_atct_snapshot", "argonne_atct_snapshot.files")
            return []
        from plasma_reactgen.data_sources.argonne_atct_snapshot import ArgonneAtctSnapshotPropertyProvider

        return [ArgonneAtctSnapshotPropertyProvider(files)]

    def chemicals_species(self) -> list[Any]:
        provider_name = self._chemicals_provider_name("species_identity")
        if provider_name is None:
            return []
        from plasma_reactgen.data_sources.chemicals_provider import ChemicalsSpeciesProvider

        return [ChemicalsSpeciesProvider(provider_name=provider_name)]

    def chemicals_properties(self) -> list[Any]:
        provider_name = self._chemicals_provider_name("properties")
        if provider_name is None:
            return []
        from plasma_reactgen.data_sources.chemicals_provider import ChemicalsPropertyProvider

        return [ChemicalsPropertyProvider(provider_name=provider_name)]

    def ion_reaction_tables(self) -> list[Any]:
        if not self._listed("ion_neutral_reactions", "ion_reaction_table"):
            return []
        config = self.profile.get("ion_reaction_table")
        files = _paths_from_config(config, "files")
        if not files:
            self._warn_missing_config("ion_neutral_reactions", "ion_reaction_table", "ion_reaction_table.files")
            return []
        from plasma_reactgen.data_sources.ion_reaction_table import IonReactionTableProvider

        return [IonReactionTableProvider(files)]

    def _internal_root(self) -> Path | None:
        config = self.profile.get("internal_file")
        if isinstance(config, dict) and config.get("root"):
            return Path(config["root"])
        return None

    def _internal_root_or_warn(self, section: str, source_name: str) -> Path | None:
        root = self._internal_root()
        if root is None:
            self._warn_missing_config(section, source_name, "internal_file.root")
        return root

    def _uses_internal(self, section: str) -> bool:
        return (
            self._listed(section, "internal_file")
            or self._listed(section, "internal_species_db")
            or self._listed(section, "internal_property_db")
            or self._listed(section, "internal_reaction_db")
        )

    def _listed(self, section: str, name: str) -> bool:
        if self._disabled(name):
            return False
        values = self.profile.get(section, [])
        return isinstance(values, list) and name in values

    def _disabled(self, name: str) -> bool:
        disabled = self.profile.get("disabled_sources", [])
        if not isinstance(disabled, list):
            return False
        disabled_names = {str(item) for item in disabled}
        aliases = {
            "internal_species_db": "internal_file",
            "internal_property_db": "internal_file",
            "internal_reaction_db": "internal_file",
            "internal_cross_section_db": "internal_file",
            "chemicals_local": "chemicals_optional",
            "pubchem_offline": "pubchem",
            "pubchem_online": "pubchem",
        }
        return name in disabled_names or aliases.get(name) in disabled_names

    def _chemicals_provider_name(self, section: str) -> str | None:
        values = self.profile.get(section, [])
        if not isinstance(values, list):
            return None
        for name in ("chemicals_optional", "chemicals_local"):
            if name in values:
                return name
        return None

    def _warn_missing_config(self, section: str, source_name: str, required: str) -> None:
        item = {
            "source": source_name,
            "section": section,
            "reason": "missing_config",
            "required": required,
        }
        self.unavailable_sources.append(item)


def _paths_from_config(config: Any, key: str) -> list[Path]:
    if not isinstance(config, dict):
        return []
    value = config.get(key)
    if isinstance(value, list):
        return [Path(item) for item in value if item]
    for single_key in ("file", "path", "snapshot"):
        if config.get(single_key):
            return [Path(config[single_key])]
    return []
