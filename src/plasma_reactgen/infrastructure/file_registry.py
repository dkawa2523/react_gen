from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import yaml

from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.domain.datasets import reaction_datasets_from_channel
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, ReactionChannel, Species, SpeciesAmount
from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


class FileRegistry(SpeciesRepository, ReactionRepository, RuleRepository):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._species_index: dict[str, Path] = {}
        self._reaction_index: dict[str, Path] = {}
        self._pair_index: dict[str, CollisionPair] = {}
        self._species_pair_index: dict[str, set[str]] = defaultdict(set)
        self._species_cache: dict[str, Species] = {}
        self._scan_registry()

    def get_species(self, species_id: str) -> Species | None:
        if species_id in self._species_cache:
            return self._species_cache[species_id]

        path = self._species_index.get(species_id)
        if path is None:
            return None

        data = self._read_yaml(path)
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

        data = self._read_yaml(path)
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
        data = self._read_yaml(path)
        data.pop("schema_version", None)
        return data

    def get_role_required_properties(self) -> dict:
        path = self.root / "rules" / "role_required_properties.yaml"
        return self._read_yaml(path)

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

    def _scan_registry(self) -> None:
        self._species_index.clear()
        self._reaction_index.clear()
        self._pair_index.clear()
        self._species_pair_index.clear()

        species_paths: dict[str, Path] = {}
        for path in self.iter_species_files():
            data = self._read_yaml(path)
            sid = data.get("id")
            if sid:
                if sid in species_paths:
                    raise ValueError(
                        f"duplicate species id '{sid}': {species_paths[sid]} and {path}"
                    )
                species_paths[sid] = path
                self._species_index[sid] = path

        pair_paths: dict[str, Path] = {}
        channel_paths: dict[str, Path] = {}
        for path in self.iter_reaction_files():
            data = self._read_yaml(path)
            pair_data = data.get("pair", {})
            if not pair_data:
                continue
            family = pair_data.get("family")
            projectile = pair_data.get("projectile")
            target = pair_data.get("target")
            if not all(isinstance(value, str) and value for value in (family, projectile, target)):
                continue
            pair = CollisionPair(family=family, projectile=projectile, target=target)
            key = pair.key
            if key in pair_paths:
                raise ValueError(
                    f"duplicate reaction pair '{key}': {pair_paths[key]} and {path}"
                )
            pair_paths[key] = path
            for channel in data.get("channels", []):
                channel_id = channel.get("id") if isinstance(channel, dict) else None
                if not channel_id:
                    continue
                channel_id = str(channel_id)
                if channel_id in channel_paths:
                    raise ValueError(
                        f"duplicate reaction channel id '{channel_id}': "
                        f"{channel_paths[channel_id]} and {path}"
                    )
                channel_paths[channel_id] = path
            self._reaction_index[key] = path
            self._pair_index[key] = pair
            self._species_pair_index[projectile].add(key)
            self._species_pair_index[target].add(key)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
