from __future__ import annotations

from typing import Any

from plasma_reactgen.data_sources.base import (
    CrossSectionProvider,
    PropertyProvider,
    ReactionProvider,
    SpeciesProvider,
)
from plasma_reactgen.data_sources.models import (
    CrossSectionCandidate,
    PropertyCandidate,
    ReactionCandidate,
    SpeciesCandidate,
)


_PROVIDERS: dict[str, dict[str, Any]] = {}


class _EmptySpeciesProvider(SpeciesProvider):
    def find_species(self, query: Any) -> list[SpeciesCandidate]:
        return []


class _EmptyPropertyProvider(PropertyProvider):
    def find_properties(
        self,
        species_id: str,
        property_names: list[str] | None = None,
    ) -> list[PropertyCandidate]:
        return []


class _EmptyReactionProvider(ReactionProvider):
    def find_reactions(
        self,
        reactants: list[str],
        family: str | None = None,
    ) -> list[ReactionCandidate]:
        return []

    def find_channels(self, pair: Any) -> list[ReactionCandidate]:
        return []


class _EmptyCrossSectionProvider(CrossSectionProvider):
    def find_cross_sections(self, pair: Any) -> list[CrossSectionCandidate]:
        return []


def register_provider(kind: str, name: str, provider: Any) -> None:
    _PROVIDERS.setdefault(kind, {})[name] = provider


def get_providers(kind: str, profile: dict[str, Any]) -> list[Any]:
    names = profile.get(kind, [])
    if not isinstance(names, list):
        return []

    providers = _PROVIDERS.get(kind, {})
    return [providers[name] for name in names if name in providers]


def register_local_registry_providers(file_registry: Any) -> None:
    from plasma_reactgen.data_sources.local_registry import (
        LocalAssetCrossSectionProvider,
        LocalRegistryPropertyProvider,
        LocalRegistryReactionProvider,
        LocalRegistrySpeciesProvider,
    )

    register_provider(
        "species_identity",
        "local_registry",
        LocalRegistrySpeciesProvider(file_registry),
    )
    register_provider(
        "properties",
        "local_registry",
        LocalRegistryPropertyProvider(file_registry),
    )
    register_provider(
        "ion_neutral_reactions",
        "local_registry",
        LocalRegistryReactionProvider(file_registry),
    )
    register_provider(
        "electron_cross_sections",
        "local_assets",
        LocalAssetCrossSectionProvider(file_registry),
    )


def register_internal_file_providers(root: Any) -> None:
    from plasma_reactgen.data_sources.internal_file import (
        InternalFileCrossSectionProvider,
        InternalFilePropertyProvider,
        InternalFileReactionProvider,
        InternalFileSpeciesProvider,
    )

    species = InternalFileSpeciesProvider(root)
    properties = InternalFilePropertyProvider(root)
    reactions = InternalFileReactionProvider(root)
    cross_sections = InternalFileCrossSectionProvider(root)

    register_provider("species_identity", "internal_species_db", species)
    register_provider("species_identity", "internal_file", species)
    register_provider("properties", "internal_property_db", properties)
    register_provider("properties", "internal_file", properties)
    register_provider("ion_neutral_reactions", "internal_reaction_db", reactions)
    register_provider("ion_neutral_reactions", "internal_file", reactions)
    register_provider("electron_reactions", "internal_reaction_db", reactions)
    register_provider("electron_reactions", "internal_file", reactions)
    register_provider("electron_cross_sections", "internal_cross_section_db", cross_sections)
    register_provider("electron_cross_sections", "internal_file", cross_sections)


def register_chemicals_optional_providers() -> None:
    from plasma_reactgen.data_sources.chemicals_provider import (
        ChemicalsPropertyProvider,
        ChemicalsSpeciesProvider,
    )

    for name in ("chemicals_optional", "chemicals_local"):
        register_provider("species_identity", name, ChemicalsSpeciesProvider(provider_name=name))
        register_provider("properties", name, ChemicalsPropertyProvider(provider_name=name))


def register_pubchem_provider(config: dict[str, Any] | None = None) -> None:
    from plasma_reactgen.data_sources.pubchem_provider import PubChemProvider

    config = config or {}
    provider = PubChemProvider(
        enabled=bool(config.get("enabled", False)),
        mode=str(config.get("mode", "online")),
        cache_dir=config.get("cache_dir", "external_data/pubchem/cache"),
    )
    for name in ("pubchem_offline", "pubchem_online"):
        register_provider("species_identity", name, provider)
        register_provider("properties", name, provider)


def register_nist_snapshot_provider(root: Any) -> None:
    from plasma_reactgen.data_sources.nist_snapshot import NistSnapshotPropertyProvider

    register_provider("properties", "nist_snapshot", NistSnapshotPropertyProvider(root))


def register_argonne_atct_snapshot_provider(files: Any) -> None:
    from plasma_reactgen.data_sources.argonne_atct_snapshot import ArgonneAtctSnapshotPropertyProvider

    register_provider("properties", "argonne_atct_snapshot", ArgonneAtctSnapshotPropertyProvider(files))


def register_chemical_identity_snapshot_provider(snapshot: Any) -> None:
    from plasma_reactgen.data_sources.chemical_identity_snapshot import ChemicalIdentitySnapshotProvider

    register_provider("species_identity", "chemical_identity_snapshot", ChemicalIdentitySnapshotProvider(snapshot))


def register_lxcat_offline_provider(root: Any) -> None:
    from plasma_reactgen.data_sources.lxcat_offline import LxcatOfflineCrossSectionProvider

    register_provider("electron_cross_sections", "lxcat_offline", LxcatOfflineCrossSectionProvider(root))


def register_ion_reaction_table_provider(files: Any) -> None:
    from plasma_reactgen.data_sources.ion_reaction_table import IonReactionTableProvider

    register_provider("ion_neutral_reactions", "ion_reaction_table", IonReactionTableProvider(files))


def _register_builtin_placeholders() -> None:
    species = _EmptySpeciesProvider()
    properties = _EmptyPropertyProvider()
    reactions = _EmptyReactionProvider()
    cross_sections = _EmptyCrossSectionProvider()

    for name in (
        "local_registry",
        "internal_species_db",
        "pubchem_offline",
        "pubchem_online",
        "chemicals_optional",
        "chemicals_local",
        "chemical_identity_snapshot",
    ):
        register_provider("species_identity", name, species)

    for name in (
        "local_registry",
        "internal_property_db",
        "nist_snapshot",
        "argonne_atct_snapshot",
        "pubchem_offline",
        "pubchem_online",
        "chemicals_optional",
        "chemicals_local",
    ):
        register_provider("properties", name, properties)

    for name in ("local_assets", "internal_cross_section_db", "lxcat_offline"):
        register_provider("electron_cross_sections", name, cross_sections)

    for name in ("local_registry", "internal_reaction_db", "ion_reaction_table", "literature_candidates"):
        register_provider("ion_neutral_reactions", name, reactions)


_register_builtin_placeholders()
register_pubchem_provider()
register_chemicals_optional_providers()
