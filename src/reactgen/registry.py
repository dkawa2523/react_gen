"""Read the local registry into the model.

Layout consumed here::

    registry/species/*.yaml         one species per file
    registry/reactions/<family>/*.yaml   one collision pair per file
    registry/materials/*.yaml       one surface material per file
    registry/assets/**              numerical tables referenced by datasets
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from reactgen import naming
from reactgen.model import (
    Dataset,
    Material,
    Property,
    Reaction,
    Species,
    State,
    Term,
    Thermo,
    Uncertainty,
    Validity,
)

PairKey = tuple[str, str, str]  # family, projectile, target

_VALIDITY_QUANTITY = {"K": "gas_temperature", "Td": "reduced_field", "eV": "electron_temperature"}

# Enough of the periodic table to derive a molecular mass when none is recorded.
ATOMIC_MASS = {
    "H": 1.008,
    "He": 4.0026,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "Si": 28.085,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Ar": 39.948,
    "Br": 79.904,
    "Cu": 63.546,
    "Y": 88.906,
}
ELECTRON_MASS_AMU = 5.4858e-4


@dataclass
class Registry:
    root: Path
    species: dict[str, Species]
    channels: dict[PairKey, list[Reaction]]
    potentials: dict[PairKey, dict]
    materials: dict[str, Material]
    overlay_root: Path | None
    _aliases: dict[str, str]
    _pairs_of: dict[str, list[PairKey]]
    _index: naming.Index | None = None

    @classmethod
    def load(cls, root: str | Path, overlay: str | Path | None = None) -> Registry:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"registry not found: {root}")
        species = _load_species(root / "species")
        channels, potentials = _load_reactions(root / "reactions")
        overlay_root = None
        if overlay is not None and Path(overlay).is_file():
            overlay_root = Path(overlay).parent
            _apply_overlay(_read(Path(overlay)), species, channels)
        return cls(
            root=root,
            species=species,
            channels=channels,
            potentials=potentials,
            materials=_load_materials(root / "materials"),
            overlay_root=overlay_root,
            _aliases=_build_aliases(root / "species", species),
            _pairs_of=_index_by_species(channels),
        )

    @property
    def capabilities(self) -> frozenset[str]:
        """Kinds of data this registry actually holds.

        A capability nobody has populated is out of scope rather than a pile of
        individual gaps, so the backlog reflects real work instead of the shape
        of the schema.
        """

        found = set()
        if any(species.thermo for species in self.species.values()):
            found.add("thermochemistry")
        if any(species.state.resolution != "state_resolved" for species in self.species.values()):
            found.add("state_resolution")
        if self.potentials:
            found.add("short_range_potential")
        for reaction in (r for group in self.channels.values() for r in group):
            if reaction.family == "surface":
                found.add("surface_chemistry")
            for dataset in reaction.datasets:
                if dataset.uncertainty:
                    found.add("uncertainty")
                if dataset.usable and dataset.kind == "cross_section":
                    found.add("cross_section")
        return frozenset(found)

    def resolve(self, name: str) -> str | None:
        """Map a written species name onto a registered id, or None."""

        return self.identify(name).species

    def identify(self, name: str) -> naming.Match:
        """Resolve a written name, reporting ambiguity instead of choosing."""

        if self._index is None:
            self._index = naming.Index(self.species, self._aliases)
        return self._index.resolve(name)

    def pairs_touching(self, active: set[str], frontier: set[str]) -> list[PairKey]:
        """Registered pairs whose reactants are all active and at least one new."""
        seen: set[PairKey] = set()
        for species_id in frontier:
            for key in self._pairs_of.get(species_id, ()):
                _, projectile, target = key
                if projectile in active and target in active:
                    seen.add(key)
        return sorted(seen)

    def asset_path(self, relative: str | None) -> Path | None:
        """Resolve an asset under the registry, or under the overlay that added it.

        Each root is a containment boundary: a path that escapes its own root is
        rejected rather than followed.
        """

        if not relative:
            return None
        for root in (self.root, self.overlay_root):
            if root is None:
                continue
            path = (root / relative).resolve()
            if root.resolve() in path.parents and path.is_file():
                return path
        return None

    def table(self, relative: str | None) -> list[tuple[float, float]]:
        """Two-column numeric asset, e.g. energy_eV and cross_section_m2."""

        path = self.asset_path(relative)
        if path is None:
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                rows.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue  # header or comment
        return sorted(rows)


def _apply_overlay(
    overlay: dict,
    species: dict[str, Species],
    channels: dict[PairKey, list[Reaction]],
) -> None:
    """Merge reviewed imports on top of the curated registry, in memory only."""

    for species_id, properties in (overlay.get("properties") or {}).items():
        found = species.get(species_id)
        if found is not None:
            found.properties.update(_properties(properties))

    for species_id, data in (overlay.get("thermo") or {}).items():
        found = species.get(species_id)
        fit = _thermo(data)
        if found is not None and fit is not None:
            species[species_id] = replace(found, thermo=fit)

    by_id = {r.id: r for group in channels.values() for r in group}
    for reaction_id, records in (overlay.get("datasets") or {}).items():
        reaction = by_id.get(reaction_id)
        if reaction is not None:
            reaction.datasets.extend(_dataset(record, reaction_id) for record in records)


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
            properties=_with_derived_mass(
                _properties(data.get("properties") or {}), composition, charge
            ),
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
            properties={"mass_amu": Property(5.4858e-4, "amu", "physical constant")},
            status="curated",
        ),
    )
    return out


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _state(data: dict) -> State:
    return State(
        kind=data.get("kind", "ground"),
        label=data.get("label", ""),
        energy_eV=_optional_float(data.get("excitation_energy_eV")),
        resolution=data.get("resolution", "state_resolved"),
        members=tuple(data.get("members") or ()),
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
    )


def _properties(data: dict) -> dict[str, Property]:
    return {
        name: Property(
            value=_number(entry.get("value")),
            unit=entry.get("unit"),
            source=entry.get("source"),
        )
        for name, entry in data.items()
        if isinstance(entry, dict)
    }


def _with_derived_mass(
    properties: dict[str, Property], composition: dict[str, int], charge: int
) -> dict[str, Property]:
    """Fill in a molecular mass from the formula when the registry has none."""

    if properties.get("mass_amu", Property()).known or not composition:
        return properties
    if any(element not in ATOMIC_MASS for element in composition):
        return properties
    mass = sum(ATOMIC_MASS[element] * count for element, count in composition.items())
    properties["mass_amu"] = Property(
        value=mass - charge * ELECTRON_MASS_AMU, unit="amu", source="derived from composition"
    )
    return properties


def _load_reactions(directory: Path) -> tuple[dict[PairKey, list[Reaction]], dict[PairKey, dict]]:
    channels: dict[PairKey, list[Reaction]] = {}
    potentials: dict[PairKey, dict] = {}
    for path in sorted(directory.glob("*/*.yaml")):
        data = _read(path)
        pair = data.get("pair") or {}
        family = pair.get("family") or path.parent.name
        key: PairKey = (family, pair["projectile"], pair.get("target", pair["projectile"]))
        channels[key] = [_channel(entry, family, key) for entry in data.get("channels") or []]
        if pair.get("potential"):
            potentials[key] = dict(pair["potential"])
    return channels, potentials


def _channel(entry: dict, family: str, key: PairKey) -> Reaction:
    _, projectile, target = key
    reactants = [Term(projectile)] if family == "unimolecular" else [Term(projectile), Term(target)]
    if family == "surface":
        reactants = [Term(projectile)]
    return Reaction(
        id=entry["id"],
        family=family,
        type=entry.get("type", "unspecified"),
        reactants=reactants,
        products=[Term(p["species"], float(p.get("n", 1))) for p in entry.get("products") or []],
        threshold_eV=_number(entry.get("threshold_eV")),
        delta_e_eV=_number(entry.get("deltaE_products_minus_reactants_eV")),
        dnt_class=entry.get("dnt_class"),
        third_body=entry.get("third_body"),
        surface=target if family == "surface" else None,
        reverse=entry.get("reverse"),
        datasets=_datasets(entry, entry["id"]),
        source=_source(entry.get("source_record") or entry.get("provenance") or {}),
        status=entry.get("status", "draft"),
    )


def _datasets(entry: dict, reaction_id: str) -> list[Dataset]:
    data = entry.get("data") or {}
    records = list(data.get("datasets") or [])
    legacy = data.get("cross_section")
    if legacy and not records:
        records.append(
            {
                "id": f"{reaction_id}__cross_section",
                "kind": "cross_section",
                "representation": "table" if legacy.get("path") else "reference_only",
                "asset": {"path": legacy.get("path")},
                "source": {"source_type": legacy.get("source")},
                "status": legacy.get("status", "draft"),
                "preferred": True,
            }
        )
    return [_dataset(record, reaction_id) for record in records]


def _dataset(record: dict, reaction_id: str) -> Dataset:
    asset = record.get("asset") or {}
    return Dataset(
        id=record.get("id", f"{reaction_id}__{record.get('kind', 'data')}"),
        reaction_id=reaction_id,
        kind=record.get("kind", "rate_coefficient"),
        form=record.get("representation", "reference_only"),
        unit=record.get("unit"),
        params={
            k: v for k, v in (record.get("parameters") or {}).items() if _number(v) is not None
        },
        asset=asset.get("path"),
        validity=_validity(record.get("validity")),
        uncertainty=_uncertainty(record.get("uncertainty"), record.get("parameters") or {}),
        source=_source(record.get("source") or {}),
        status=record.get("status", "draft"),
        preferred=bool(record.get("preferred")),
    )


def _uncertainty(data: dict | None, parameters: dict) -> Uncertainty | None:
    """Read the dedicated block, falling back to the older in-parameters spelling."""

    if not data:
        factor = _number(parameters.get("uncertainty_factor"))
        relative = _number(parameters.get("relative_uncertainty"))
        return Uncertainty(factor, relative) if factor or relative else None
    return Uncertainty(
        factor=_number(data.get("factor")),
        relative=_number(data.get("relative")),
        note=data.get("note"),
    )


def _validity(data: dict | None) -> Validity | None:
    if not data:
        return None
    unit = data.get("unit")
    quantity = data.get("quantity") or _VALIDITY_QUANTITY.get(unit or "", "gas_temperature")
    return Validity(
        quantity=quantity,
        minimum=_number(data.get("minimum")),
        maximum=_number(data.get("maximum")),
        unit=unit,
    )


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


def _build_aliases(directory: Path, species: dict[str, Species]) -> dict[str, str]:
    aliases = {naming.fold(species_id): species_id for species_id in species}
    for path in sorted(directory.glob("*.yaml")):
        data = _read(path)
        species_id = data["id"]
        names = [path.stem, data.get("display_name", ""), *(data.get("aliases") or [])]
        for name in filter(None, names):
            aliases.setdefault(naming.fold(str(name)), species_id)
    return aliases


def _index_by_species(channels: dict[PairKey, list[Reaction]]) -> dict[str, list[PairKey]]:
    out: dict[str, list[PairKey]] = {}
    for key in channels:
        for species_id in {key[1], key[2]}:
            out.setdefault(species_id, []).append(key)
    return out


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _number(value: object) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
