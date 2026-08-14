from __future__ import annotations

from pathlib import Path

from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.domain.datasets import reaction_datasets_from_channel
from plasma_reactgen.domain.models import (
    CollisionPair,
    PropertyValue,
    ReactionChannel,
    Species,
    SpeciesAmount,
)
from plasma_reactgen.infrastructure.registry_index import build_registry_index, load_registry_yaml
from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


class FileRegistry(SpeciesRepository, ReactionRepository, RuleRepository):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        index = build_registry_index(self.iter_species_files(), self.iter_reaction_files())
        self._species_index = index.species
        self._reaction_index = index.reactions
        self._pair_index = index.pairs
        self._species_pair_index = index.species_pairs
        self._species_cache: dict[str, Species] = {}

    def get_species(self, species_id: str) -> Species | None:
        if species_id in self._species_cache:
            return self._species_cache[species_id]

        path = self._species_index.get(species_id)
        if path is None:
            return None

        data = load_registry_yaml(path)
        properties = {
            name: PropertyValue(
                value=(payload or {}).get("value"),
                unit=(payload or {}).get("unit"),
                source=(payload or {}).get("source"),
                source_record=(payload or {}).get("source_record"),
            )
            for name, payload in data.get("properties", {}).items()
        }

        species = Species(
            id=data["id"],
            composition=data.get("composition", {}),
            charge=int(data["charge"]),
            classes=set(data.get("classes", [])),
            state=data.get("state", {}),
            properties=properties,
            status=data.get("metadata", {}).get("status", data.get("status", "draft")),
        )

        self._species_cache[species_id] = species
        return species

    def has_species(self, species_id: str) -> bool:
        return species_id in self._species_index

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        path = self._reaction_index.get(pair.key)
        if path is None:
            return []

        data = load_registry_yaml(path)
        channels: list[ReactionChannel] = []
        for ch in data.get("channels", []):
            channel_data = ch.get("data", {}) if isinstance(ch.get("data", {}), dict) else {}
            channels.append(
                ReactionChannel(
                    id=ch["id"],
                    type=ch["type"],
                    products=[
                        SpeciesAmount(species=p["species"], n=float(p.get("n", 1.0)))
                        for p in ch.get("products", [])
                    ],
                    threshold_eV=ch.get("threshold_eV"),
                    deltaE_products_minus_reactants_eV=ch.get("deltaE_products_minus_reactants_eV"),
                    dnt_class=ch.get("dnt_class"),
                    data=channel_data,
                    evidence=ch.get("evidence") or channel_data.get("evidence"),
                    provenance=ch.get("provenance") or channel_data.get("provenance"),
                    source_record=ch.get("source_record") or channel_data.get("source_record"),
                    confidence=ch.get("confidence", channel_data.get("confidence")),
                    datasets=reaction_datasets_from_channel(ch),
                    status=ch.get("status", "draft"),
                    notes=ch.get("notes", []),
                )
            )
        return channels

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        """Return registered pairs whose reactants are active and touch the frontier."""

        candidate_keys = {
            key
            for species_id in frontier_species_ids
            for key in self._species_pair_index.get(species_id, set())
        }
        pairs = [
            self._pair_index[key]
            for key in candidate_keys
            if self._pair_index[key].projectile in active_species_ids
            and self._pair_index[key].target in active_species_ids
        ]
        return sorted(pairs, key=lambda pair: pair.key)

    def has_pair(self, pair: CollisionPair) -> bool:
        return pair.key in self._reaction_index

    def get_reaction_type_catalog(self) -> dict:
        path = self.root / "rules" / "reaction_type_catalog.yaml"
        data = load_registry_yaml(path)
        data.pop("schema_version", None)
        return data

    def get_role_required_properties(self) -> dict:
        path = self.root / "rules" / "role_required_properties.yaml"
        return load_registry_yaml(path)

    def asset_exists(self, relative_path: str | None) -> bool:
        return registry_asset_exists(self.root, relative_path)

    def iter_species_files(self) -> list[Path]:
        species_dir = self.root / "species"
        return sorted(species_dir.glob("*.yaml")) if species_dir.exists() else []

    def iter_reaction_files(self) -> list[Path]:
        reaction_root = self.root / "reactions"
        if not reaction_root.exists():
            return []
        return sorted(reaction_root.glob("*/*.yaml"))
