"""Read the local registry into the model.

Layout consumed here::

    registry/species/*.yaml         one species per file
    registry/reactions/<family>/*.yaml   one collision pair per file
    registry/materials/*.yaml       one surface material per file
    registry/assets/**              numerical tables referenced by datasets
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reactgen.model import Term
from reactgen.records import (
    Material,
    NumericDataset,
    Property,
    RegistryReaction,
    RegistryState,
    Species,
    Thermo,
    normalized_dataset,
    normalized_property,
)

PairKey = tuple[str, str, str]  # family, projectile, target


@dataclass
class Registry:
    root: Path
    species: dict[str, Species]
    channels: dict[PairKey, list[RegistryReaction]]
    materials: dict[str, Material]

    @classmethod
    def load(cls, root: str | Path) -> Registry:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"registry not found: {root}")
        species = _load_species(root / "species")
        channels = _load_reactions(root / "reactions", root)
        return cls(
            root=root,
            species=species,
            channels=channels,
            materials=_load_materials(root / "materials"),
        )


def _load_species(directory: Path) -> dict[str, Species]:
    out: dict[str, Species] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = _read(path)
        composition = {str(k): int(v) for k, v in (data.get("composition") or {}).items()}
        charge = int(data.get("charge", 0))
        species = Species(
            id=data["id"],
            composition=composition,
            charge=charge,
            classes=frozenset(data.get("classes") or []),
            state=_state(data.get("state") or {}),
            properties=_properties(data.get("properties") or {}),
            thermo=_thermo(data.get("thermo")),
            status=(data.get("metadata") or {}).get("status", "draft"),
        )
        out[species.id] = species
    out.setdefault(
        "e",
        Species(
            id="e",
            composition={},
            charge=-1,
            classes=frozenset({"electron"}),
            properties={
                "mass_amu": Property(
                    5.4858e-4,
                    "amu",
                    "physical constant",
                    tier="curated",
                )
            },
            status="curated",
        ),
    )
    return out


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _state(data: dict) -> RegistryState:
    return RegistryState(
        kind=data.get("kind", "ground"),
        label=data.get("label", ""),
        energy_eV=_optional_float(data.get("excitation_energy_eV")),
        resolution=data.get("resolution", "resolved"),
        members=tuple(data.get("members") or ()),
        existence=data.get("existence", "unknown"),
        configuration=data.get("configuration"),
        term=data.get("term"),
        j=None if data.get("J") is None else str(data["J"]),
        parity=data.get("parity"),
        degeneracy=_optional_float(data.get("degeneracy")),
        lifetime_s=_optional_float(data.get("lifetime_s")),
    )


def _thermo(data: dict | None) -> Thermo | None:
    """NASA 7-coefficient polynomial, if the species declares one."""

    if not data or len(data.get("low", ())) != 7 or len(data.get("high", ())) != 7:
        return None
    return Thermo(
        low=tuple(float(value) for value in data["low"]),
        high=tuple(float(value) for value in data["high"]),
        t_min=float(data.get("t_min", 200.0)),
        t_mid=float(data.get("t_mid", 1000.0)),
        t_max=float(data.get("t_max", 6000.0)),
        source=data.get("source"),
        tier=str(data.get("evidence_tier") or "reviewed"),
    )


def _properties(data: dict) -> dict[str, Property]:
    return {
        name: normalized_property(entry, "reviewed")
        for name, entry in data.items()
        if isinstance(entry, dict)
    }


def _load_reactions(directory: Path, root: Path) -> dict[PairKey, list[RegistryReaction]]:
    channels: dict[PairKey, list[RegistryReaction]] = {}
    for path in sorted(directory.glob("*/*.yaml")):
        data = _read(path)
        pair = data.get("pair") or {}
        family = pair.get("family") or path.parent.name
        key: PairKey = (family, pair["projectile"], pair.get("target", pair["projectile"]))
        channels[key] = [_channel(entry, family, key, root) for entry in data.get("channels") or []]
    return channels


def _channel(entry: dict, family: str, key: PairKey, root: Path) -> RegistryReaction:
    _, projectile, target = key
    reactants = [Term(projectile)] if family == "unimolecular" else [Term(projectile), Term(target)]
    if family == "surface":
        reactants = [Term(projectile)]
    return RegistryReaction(
        id=entry["id"],
        family=family,
        type=entry.get("type", "unspecified"),
        reactants=reactants,
        products=[Term(p["species"], float(p.get("n", 1))) for p in entry.get("products") or []],
        threshold_eV=_number(entry.get("threshold_eV")),
        delta_e_eV=_number(entry.get("deltaE_products_minus_reactants_eV")),
        third_body=entry.get("third_body"),
        surface=target if family == "surface" else None,
        reverse=entry.get("reverse"),
        datasets=_datasets(entry, entry["id"], root),
        source=_source(entry.get("source_record") or entry.get("provenance") or {}),
        status=entry.get("status", "draft"),
    )


def _datasets(entry: dict, reaction_id: str, root: Path) -> list[NumericDataset]:
    data = entry.get("data") or {}
    records = list(data.get("datasets") or [])
    reference = data.get("cross_section")
    if reference and not records:
        records.append(
            {
                "id": f"{reaction_id}__cross_section",
                "kind": "cross_section",
                "representation": "table" if reference.get("path") else "reference_only",
                "asset": {"path": reference.get("path")},
                "source": {"source_type": reference.get("source")},
                "status": reference.get("status", "draft"),
                "preferred": True,
            }
        )
    return [
        normalized_dataset(
            record,
            base=root,
            default_id=f"{reaction_id}__{record.get('kind', 'data')}",
            allowed_asset_root=root,
        )
        for record in records
    ]


def _source(data: dict) -> dict[str, str]:
    keep = ("source_type", "source_id", "citation", "url", "record_id")
    return {k: str(data[k]) for k in keep if data.get(k)}


def _load_materials(directory: Path) -> dict[str, Material]:
    if not directory.is_dir():
        return {}
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        data = _read(path)
        out[data["id"]] = Material(
            id=data["id"], name=data.get("name", data["id"]), notes=data.get("notes", "")
        )
    return out


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _number(value: object) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
