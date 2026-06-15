from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from plasma_reactgen.infrastructure.file_registry import FileRegistry


class SourceProviderConfigurationError(ValueError):
    """Raised when strict source profiles request unavailable providers."""


@dataclass
class ProviderBuildResult:
    providers: list[Any]
    warnings: list[dict[str, Any]]
    unavailable_sources: list[dict[str, Any]]

    def __iter__(self) -> Iterator[Any]:
        return iter(self.providers)

    def __len__(self) -> int:
        return len(self.providers)

    def __getitem__(self, index: int) -> Any:
        return self.providers[index]


def build_species_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    providers: list[Any] = []
    providers.extend(builder.internal_species())
    providers.extend(builder.local_species())
    providers.extend(builder.chemical_identity_species())
    providers.extend(builder.chemicals_species())
    return builder.result(providers)


def build_property_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    providers: list[Any] = []
    providers.extend(builder.internal_properties())
    providers.extend(builder.local_properties())
    providers.extend(builder.nist_properties())
    providers.extend(builder.argonne_atct_properties())
    providers.extend(builder.chemicals_properties())
    return builder.result(providers)


def build_reaction_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = _ProviderFactory(profile)
    providers: list[Any] = []
    providers.extend(builder.internal_reactions())
    providers.extend(builder.local_reactions())
    providers.extend(builder.ion_reaction_tables())
    return builder.result(providers)


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
        self.warnings: list[dict[str, Any]] = []
        self.unavailable_sources: list[dict[str, Any]] = []

    def result(self, providers: list[Any]) -> ProviderBuildResult:
        result = ProviderBuildResult(
            providers=providers,
            warnings=self.warnings,
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

    def local_species(self) -> list[Any]:
        if not self._listed("species_identity", "local_registry"):
            return []
        registry = self._local_registry()
        if registry is None:
            return []
        from plasma_reactgen.data_sources.local_registry import LocalRegistrySpeciesProvider

        return [LocalRegistrySpeciesProvider(registry)]

    def local_properties(self) -> list[Any]:
        if not self._listed("properties", "local_registry"):
            return []
        registry = self._local_registry()
        if registry is None:
            return []
        from plasma_reactgen.data_sources.local_registry import LocalRegistryPropertyProvider

        return [LocalRegistryPropertyProvider(registry)]

    def local_reactions(self) -> list[Any]:
        if not (
            self._listed("ion_neutral_reactions", "local_registry")
            or self._listed("electron_reactions", "local_registry")
        ):
            return []
        registry = self._local_registry()
        if registry is None:
            return []
        from plasma_reactgen.data_sources.local_registry import LocalRegistryReactionProvider

        return [LocalRegistryReactionProvider(registry)]

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

    def chemical_identity_species(self) -> list[Any]:
        if not self._listed("species_identity", "chemical_identity_snapshot"):
            return []
        config = self.profile.get("chemical_identity_snapshot")
        snapshot = config.get("snapshot") if isinstance(config, dict) else None
        if not snapshot:
            self._warn_missing_config(
                "species_identity",
                "chemical_identity_snapshot",
                "chemical_identity_snapshot.snapshot",
            )
            return []
        from plasma_reactgen.data_sources.chemical_identity_snapshot import ChemicalIdentitySnapshotProvider

        return [_ChemicalIdentitySpeciesAdapter(ChemicalIdentitySnapshotProvider(snapshot))]

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

    def _local_registry(self) -> FileRegistry | None:
        config = self.profile.get("local_registry")
        if not isinstance(config, dict):
            return None
        registry = config.get("registry")
        if registry is not None:
            return registry
        root = config.get("root") or config.get("registry_root")
        if root:
            return FileRegistry(root)
        return None

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
        self.warnings.append(item)
        self.unavailable_sources.append(item)


class _ChemicalIdentitySpeciesAdapter:
    def __init__(self, provider: Any):
        self.provider = provider

    def find_species(self, query: str) -> list[dict[str, Any]]:
        candidates = []
        for record in self.provider.find_species(query):
            species_id = record.get("species")
            if not species_id:
                continue
            candidates.append(
                {
                    "id": species_id,
                    "formula": record.get("formula"),
                    "aliases": list(record.get("aliases", [])),
                    "composition": {},
                    "charge": 0,
                    "classes": [],
                    "state": {},
                    "status": record.get("status", "imported"),
                    "source_record": {
                        "source_type": "local_snapshot",
                        "database": "chemical_identity_snapshot",
                        "source_id": species_id,
                    },
                }
            )
        return candidates


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
