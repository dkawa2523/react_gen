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

from reactgen import naming, yamlio
from reactgen.chemistry import candidate_state, electron_state, parse_equation
from reactgen.model import ELECTRON, ReactionCandidate, StateCandidate, Term, reaction_id
from reactgen.records import (
    Material,
    NumericDataset,
    Property,
    ReactionRecord,
    RegistryReaction,
    RegistryState,
    Species,
    StateRecord,
    normalized_dataset,
    normalized_number,
    normalized_property,
    normalized_reaction_energy_properties,
    normalized_reaction_record,
    normalized_state_record,
    normalized_thermo,
    review_scope,
    scientific_method,
    source_information,
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
        channels = _load_reactions(root / "reactions", root, species)
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
        composition = data.get("composition") or {}
        if not isinstance(composition, dict) or any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in composition.values()
        ):
            raise ValueError(f"{path}: composition must have positive integer atom counts")
        charge = data.get("charge", 0)
        if isinstance(charge, bool) or not isinstance(charge, int):
            raise ValueError(f"{path}: charge must be an integer")
        status = (data.get("metadata") or {}).get("status", "draft")
        species = Species(
            id=data["id"],
            composition=composition,
            charge=charge,
            classes=frozenset(data.get("classes") or []),
            state=_state(data.get("state") or {}),
            properties=_properties(data.get("properties") or {}, "imported"),
            thermo=normalized_thermo(data.get("thermo")),
            status=status,
            phase=str(data.get("phase") or "unknown"),
            structure=data.get("structure"),
        )
        species = replace(species, records=_scientific_states(data, species, path))
        if species.id in out:
            raise ValueError(f"{path}: duplicate species id {species.id}")
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


def _scientific_states(data: dict, species: Species, path: Path) -> tuple[StateRecord, ...]:
    entries = data.get("records") or []
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError(f"{path}: records must be a list of scientific state records")
    candidate = registry_state_candidate(species)
    declarations = []
    for entry in entries:
        if entry.get("species") not in {None, species.id, candidate.id}:
            raise ValueError(f"{path}: scientific record names a different species")
        for name, expected in (("phase", candidate.phase), ("structure", candidate.structure)):
            if name in entry and entry[name] != expected:
                raise ValueError(f"{path}: scientific record {name} contradicts the target")
        state = entry.get("state") or {}
        if not isinstance(state, dict) or any(
            getattr(candidate.state, name, None) != value for name, value in state.items()
        ):
            raise ValueError(f"{path}: scientific record state contradicts the target")
        declarations.append(
            normalized_state_record(entry, candidate, origin="registry", preserved_record_id=True)
        )
    return tuple(declarations)


def _state(data: dict) -> RegistryState:
    source = data.get("source") or {}
    if not isinstance(source, dict):
        raise ValueError("state.source must be a mapping")
    provenance, declaration = source_information(data)
    return RegistryState(
        kind=data.get("kind", "ground"),
        label=data.get("label", ""),
        energy_eV=normalized_number(data.get("excitation_energy_eV")),
        resolution=data.get("resolution", "resolved"),
        members=tuple(data.get("members") or ()),
        existence=data.get("existence", "unknown"),
        configuration=data.get("configuration"),
        term=data.get("term"),
        j=None if data.get("J") is None else str(data["J"]),
        parity=data.get("parity"),
        degeneracy=normalized_number(data.get("degeneracy")),
        lifetime_s=normalized_number(data.get("lifetime_s")),
        existence_source=data.get("existence_source"),
        status=data.get("status"),
        source={str(key): str(value) for key, value in source.items() if value is not None},
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(data),
        review_scope=review_scope(data),
    )


def _properties(data: dict, default_tier: str) -> dict[str, Property]:
    return {
        name: normalized_property(entry, default_tier, quantity=name)
        for name, entry in data.items()
        if isinstance(entry, dict)
    }


def _load_reactions(
    directory: Path, root: Path, species: dict[str, Species]
) -> dict[PairKey, list[RegistryReaction]]:
    """Retain every pair's channels with unique IDs across the Registry.

    Repeated IDs are input errors even when their declarations agree: adoption
    must have one unambiguous file and channel to update. Independent sources
    need distinct record IDs. Dataset-ID conflicts remain numerical evidence
    for ``data_use`` to assess, rather than channel identity errors.
    Sorting pairs and channel IDs makes the returned order reproducible; it
    does not assign priority to any source or numerical declaration.
    """
    channels: dict[PairKey, list[RegistryReaction]] = {}
    locations: dict[str, tuple[PairKey, dict, Path, int]] = {}
    for path in sorted(directory.glob("*/*.yaml")):
        data = _read(path)
        pair = data.get("pair") or {}
        family = pair.get("family") or path.parent.name
        key: PairKey = (family, pair["projectile"], pair.get("target", pair["projectile"]))
        group = channels.setdefault(key, [])
        for index, entry in enumerate(data.get("channels") or [], start=1):
            channel_id = entry.get("id")
            if not isinstance(channel_id, str) or not channel_id.strip():
                raise ValueError(f"{path}: channel {index} id must be nonempty text")
            if channel_id in locations:
                previous_key, previous_entry, previous_path, previous_index = locations[channel_id]
                content = (
                    "same declaration"
                    if (key, entry) == (previous_key, previous_entry)
                    else "different declarations"
                )
                raise ValueError(
                    f"duplicate channel id {channel_id!r} ({content}): "
                    f"{previous_path} channel {previous_index} and {path} channel {index}; "
                    "independent source records require distinct IDs"
                )
            locations[channel_id] = (key, entry, path, index)
            channel = _channel(entry, family, key, root)
            channel.records = _scientific_reactions(entry, channel, species, path)
            group.append(channel)
    return {
        key: sorted(group, key=lambda channel: channel.id)
        for key, group in sorted(channels.items())
    }


def _channel(entry: dict, family: str, key: PairKey, root: Path) -> RegistryReaction:
    _, projectile, target = key
    reactants = [Term(projectile)] if family == "unimolecular" else [Term(projectile), Term(target)]
    if family == "surface":
        reactants = [Term(projectile)]
    source_data = entry.get("source_record") or entry.get("provenance") or {}
    provenance, declaration = source_information(entry | {"source": source_data})
    return RegistryReaction(
        id=entry["id"],
        family=family,
        type=entry.get("type", "unspecified"),
        reactants=reactants,
        products=[Term(p["species"], float(p.get("n", 1))) for p in entry.get("products") or []],
        energy_properties=normalized_reaction_energy_properties(entry | {"source": source_data}),
        third_body=entry.get("third_body"),
        surface=target if family == "surface" else None,
        reverse=entry.get("reverse"),
        datasets=_datasets(entry, entry["id"], root),
        source=_source(source_data),
        status=entry.get("status", "draft"),
        stabilization=entry.get("stabilization"),
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(entry, source_data),
        review_scope=review_scope(entry),
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
    return {str(key): str(value) for key, value in data.items() if value is not None}


def registry_reaction_candidate(
    record: RegistryReaction, species: dict[str, Species]
) -> ReactionCandidate | None:
    """Map one Registry channel to its complete physical target."""
    mapped = {}
    for term in (*record.reactants, *record.products):
        found = species.get(term.species)
        if found is None:
            return None
        mapped[term.species] = registry_state_candidate(found).id
    candidate = ReactionCandidate(
        id="",
        reactants=tuple(Term(mapped[term.species], term.n) for term in record.reactants),
        products=tuple(Term(mapped[term.species], term.n) for term in record.products),
        family=record.family,
        process=record.type,
        origin="attested_only",
        generation_rule=f"registry:{record.id}",
        depth=0,
        third_body=record.third_body,
        surface=record.surface,
        stabilization=record.stabilization,
    )
    return replace(candidate, id=reaction_id(candidate.key))


def _scientific_reactions(
    data: dict, channel: RegistryReaction, species: dict[str, Species], path: Path
) -> tuple[ReactionRecord, ...]:
    entries = data.get("records") or []
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError(f"{path}: records must be a list of scientific reaction records")
    if not entries:
        return ()
    target = registry_reaction_candidate(channel, species)
    if target is None:
        raise ValueError(f"{path}: scientific reaction record has unresolved participants")
    declarations = []
    for entry in entries:
        if "datasets" in entry:
            raise ValueError(f"{path}: scientific reaction records use data.datasets for numbers")
        parsed = parse_equation(str(entry.get("reaction") or ""))
        if parsed is None:
            raise ValueError(f"{path}: scientific reaction record has an invalid equation")
        equation, states = parsed
        if entry.get("third_body") not in {None, equation[0]}:
            raise ValueError(
                f"{path}: scientific reaction record third_body contradicts its equation"
            )
        equation = equation[0], entry.get("surface"), equation[2], equation[3]
        record = normalized_reaction_record(
            entry, equation, states, origin="registry", preserved_record_id=True
        )
        if (
            record.equation_key != target.equation_key
            or (record.family is not None and record.family != target.family)
            or record.process != target.process
            or record.stabilization != target.stabilization
        ):
            raise ValueError(f"{path}: scientific reaction record contradicts its channel target")
        declarations.append(record)
    return tuple(declarations)


def registry_state_candidate(record: Species) -> StateCandidate:
    """One physical target mapping for Registry loading, evaluation and adoption."""
    if record.id == ELECTRON:
        return replace(electron_state(), origin="attested_only", introduced_by=("registry",))
    state = record.state
    if state.kind == "ground":
        kind, resolution, label = "ground", "resolved", ""
    else:
        label = naming.normalize_state(state.label) or ""
        if state.label == "vibrational" or "vibrational" in record.classes:
            kind, resolution, label = "vibrational", state.resolution, ""
        elif state.resolution == "lumped":
            kind = (
                "metastable"
                if "metastable" in record.classes
                else ("resonant" if "resonant" in record.classes else "electronic")
            )
            resolution = "lumped"
            if kind in {"metastable", "resonant"}:
                label = ""
        else:
            kind, resolution = "resolved", "resolved"
    return candidate_state(
        record.composition,
        record.charge,
        kind,
        label=label,
        resolution=resolution,
        classes=record.classes,
        origin="attested_only",
        introduced_by=(f"registry:{record.id}",),
        phase=record.phase,
        structure=record.structure,
    )


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
    return yamlio.load(path.read_text(encoding="utf-8")) or {}
