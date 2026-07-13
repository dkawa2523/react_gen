from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, ReactionChannel, Species, SpeciesAmount
from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


class FileRegistry(SpeciesRepository, ReactionRepository, RuleRepository):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._species_index: dict[str, Path] = {}
        self._reaction_index: dict[str, Path] = {}
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
                    data=ch.get("data", {}),
                    status=ch.get("status", "draft"),
                    notes=ch.get("notes", []),
                )
            )
        return channels

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

        for path in self.iter_species_files():
            data = self._read_yaml(path)
            sid = data.get("id")
            if sid:
                self._species_index[sid] = path

        for path in self.iter_reaction_files():
            data = self._read_yaml(path)
            pair_data = data.get("pair", {})
            if not pair_data:
                continue
            key = f"{pair_data.get('family')}|{pair_data.get('projectile')}|{pair_data.get('target')}"
            self._reaction_index[key] = path

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
