from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.registry_pack_selection import (
    RegistryPackInfo,
    select_registry_pack,
)


@dataclass(frozen=True)
class RegistryResolution:
    registry: Any
    context: dict[str, Any]
    pack: RegistryPackInfo | None = None


class OverlayRegistry:
    """Read-only registry view with later overlays taking precedence."""

    def __init__(self, base: FileRegistry, overlays: list[FileRegistry]):
        self.base = base
        self.overlays = list(overlays)
        self.root = base.root

    def get_species(self, species_id: str) -> Species | None:
        for registry in reversed(self.overlays):
            species = registry.get_species(species_id)
            if species is not None:
                return species
        return self.base.get_species(species_id)

    def has_species(self, species_id: str) -> bool:
        return self.get_species(species_id) is not None

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        pairs = {
            pair.key: pair
            for registry in [self.base, *self.overlays]
            for pair in registry.find_pairs_involving(
                active_species_ids,
                frontier_species_ids,
            )
        }
        return [pair for _, pair in sorted(pairs.items())]

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        channels = self.base.get_channels(pair)
        positions = {channel.id: index for index, channel in enumerate(channels)}
        for registry in self.overlays:
            for channel in registry.get_channels(pair):
                if channel.id in positions:
                    channels[positions[channel.id]] = channel
                else:
                    positions[channel.id] = len(channels)
                    channels.append(channel)
        return channels

    def has_pair(self, pair: CollisionPair) -> bool:
        return self.base.has_pair(pair) or any(
            registry.has_pair(pair) for registry in self.overlays
        )

    def get_reaction_type_catalog(self) -> dict:
        return self.base.get_reaction_type_catalog()

    def get_role_required_properties(self) -> dict:
        return self.base.get_role_required_properties()

    def asset_exists(self, relative_path: str | None) -> bool:
        return any(
            registry.asset_exists(relative_path)
            for registry in [*reversed(self.overlays), self.base]
        )


def resolve_registry(
    *,
    gases: list[str],
    base_registry: str | Path = Path("registry"),
    packs_root: str | Path | None = None,
    explicit_registry: str | Path | None = None,
) -> RegistryResolution:
    """Resolve an explicit registry or automatically overlay a matching pack."""

    if explicit_registry is not None:
        root = Path(explicit_registry)
        return RegistryResolution(
            registry=FileRegistry(root),
            context={
                "mode": "explicit_registry",
                "base_registry": str(root),
                "pack": None,
                "coverage_gap": False,
            },
        )

    base_root = Path(base_registry)
    packs_root = Path(packs_root) if packs_root is not None else base_root.parent / "registry_packs"
    base = FileRegistry(base_root)
    selected = select_registry_pack(gases, packs_root)
    if selected is None:
        return RegistryResolution(
            registry=base,
            context={
                "mode": "base_registry",
                "base_registry": str(base_root),
                "pack": None,
                "coverage_gap": True,
                "coverage_gap_reason": "no_registry_pack_for_input_gases",
            },
        )
    return RegistryResolution(
        registry=OverlayRegistry(base, [FileRegistry(selected.root)]),
        pack=selected,
        context={
            "mode": "base_plus_pack",
            "base_registry": str(base_root),
            "pack": selected.summary(),
            "coverage_gap": False,
        },
    )
