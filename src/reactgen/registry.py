"""Read the local registry into the model.

Layout consumed here::

    registry/species/*.yaml         one species per file
    registry/reactions/<family>/*.yaml   one collision pair per file
    registry/materials/*.yaml       one surface material per file
    registry/assets/**              numerical tables referenced by datasets
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from reactgen import naming, yamlio
from reactgen.chemistry import (
    candidate_state,
    electron_state,
    parse_equation,
    reaction_declaration_matches,
    state_id,
)
from reactgen.model import (
    ELECTRON,
    ReactionCandidate,
    ReactionKey,
    StateCandidate,
    Term,
    bind_transformation_states,
    reaction_id,
)
from reactgen.records import (
    Material,
    MolecularIdentity,
    NumericDataset,
    Property,
    ReactionRecord,
    RegistryReaction,
    RegistryState,
    Species,
    StateRecord,
    bind_dataset_target,
    normalized_dataset,
    normalized_number,
    normalized_properties,
    normalized_reaction_energy_properties,
    normalized_reaction_record,
    normalized_source,
    normalized_state_record,
    normalized_thermo,
    review_scope,
    scientific_method,
    source_information,
    validate_numerical_targets,
)
from reactgen.structure import StructureUnavailable, structure_key

PairKey = tuple[str, str, str]  # family, projectile, target
ChannelLocation = tuple[Path, int, ReactionCandidate]


@dataclass
class Registry:
    root: Path
    species: dict[str, Species]
    channels: dict[PairKey, list[RegistryReaction]]
    materials: dict[str, Material]
    species_locations: dict[str, Path] = field(default_factory=dict, repr=False, compare=False)
    channel_locations: dict[str, ChannelLocation] = field(
        default_factory=dict, repr=False, compare=False
    )
    document_hashes: dict[Path, bytes] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls, root: str | Path) -> Registry:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"registry not found: {root}")
        hashes: dict[Path, bytes] = {}
        species, species_locations = _load_species(root / "species", hashes)
        channels, channel_locations = _load_reactions(root / "reactions", root, species, hashes)
        return cls(
            root=root,
            species=species,
            channels=channels,
            materials=_load_materials(root / "materials", hashes),
            species_locations=species_locations,
            channel_locations=channel_locations,
            document_hashes=hashes,
        )


def _load_species(
    directory: Path, hashes: dict[Path, bytes]
) -> tuple[dict[str, Species], dict[str, Path]]:
    out: dict[str, Species] = {}
    locations: dict[str, Path] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = _read(path, hashes)
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
            properties=normalized_properties(data.get("properties")),
            thermo=normalized_thermo(data.get("thermo")),
            status=status,
            phase=str(data.get("phase") or "unknown"),
            structure=data.get("structure"),
            molecular_identity=read_molecular_identity(data.get("molecular_identity")),
        )
        if species.molecular_identity is not None:
            try:
                molecular_identity_state(
                    registry_state_candidate(species),
                    species.molecular_identity,
                    verify_graph=False,
                )
            except ValueError as error:
                raise ValueError(f"{path}: {error}") from error
        species = replace(species, records=_scientific_states(data, species, path))
        if species.id in out:
            raise ValueError(f"{path}: duplicate species id {species.id}")
        out[species.id] = species
        locations[species.id] = path
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
    return out, locations


def read_molecular_identity(declaration: object) -> MolecularIdentity | None:
    if declaration is None:
        return None
    if not isinstance(declaration, dict) or set(declaration) != {"smiles", "source"}:
        raise ValueError("molecular_identity must contain smiles and source")
    return MolecularIdentity(declaration["smiles"], normalized_source(declaration["source"]))


def molecular_identity_state(
    nominal: StateCandidate, identity: MolecularIdentity, *, verify_graph: bool = True
) -> StateCandidate | None:
    """Apply the cited graph only to its declared phase, charge and level."""
    if not nominal.composition or nominal.structure is not None or nominal.phase == "unknown":
        raise ValueError("molecular_identity requires a structure-free species in a declared phase")
    level = nominal.state
    structure = "smiles:" + identity.smiles
    identifier = state_id(
        nominal.composition,
        nominal.charge,
        level.kind,
        level.label,
        resolution=level.resolution,
        phase=nominal.phase,
        structure=structure,
    )
    candidate = replace(nominal, id=identifier, structure=structure)
    if verify_graph:
        try:
            structure_key(candidate)
        except StructureUnavailable:
            return None
    return candidate


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
        record = normalized_state_record(
            entry, candidate, origin="registry", preserved_record_id=True
        )
        if identity := read_molecular_identity(entry.get("molecular_identity")):
            molecular_identity_state(candidate, identity, verify_graph=False)
            record = replace(record, molecular_identity=identity)
        declarations.append(record)
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


def _load_reactions(
    directory: Path, root: Path, species: dict[str, Species], hashes: dict[Path, bytes]
) -> tuple[dict[PairKey, list[RegistryReaction]], dict[str, ChannelLocation]]:
    """Retain every pair's channels with unique IDs across the Registry.

    Repeated IDs are input errors even when their declarations agree: adoption
    must have one unambiguous file and channel to update. Independent sources
    need distinct record IDs. A dataset ID must identify one physical channel;
    conflicts within that target remain numerical evidence for ``data_use``.
    Sorting pairs and channel IDs makes the returned order reproducible; it
    does not assign priority to any source or numerical declaration.
    """
    channels: dict[PairKey, list[RegistryReaction]] = {}
    locations: dict[str, tuple[PairKey, dict, Path, int]] = {}
    resolved: dict[str, ChannelLocation] = {}
    numerical_bindings: list[tuple[str, str]] = []
    scientific_bindings: list[tuple[str, ReactionKey]] = []
    for path in sorted(directory.glob("*/*.yaml")):
        data = _read(path, hashes)
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
            try:
                channel = _channel(entry, family, key, root)
            except ValueError as error:
                raise ValueError(f"{path}: channel {channel_id!r}: {error}") from error
            target = _bind_channel_datasets(channel, species, path)
            resolved[channel.id] = path, index - 1, target
            numerical_bindings.extend((dataset.id, target.id) for dataset in channel.datasets)
            channel.records = _scientific_reactions(entry, target, species, path)
            scientific_bindings.append((channel.id, target.key))
            scientific_bindings.extend((record.id, target.key) for record in channel.records)
            group.append(channel)
    validate_numerical_targets(numerical_bindings)
    validate_reaction_record_targets(scientific_bindings)
    return (
        {
            key: sorted(group, key=lambda channel: channel.id)
            for key, group in sorted(channels.items())
        },
        resolved,
    )


def validate_reaction_record_targets(bindings: Iterable[tuple[str, ReactionKey]]) -> None:
    """An independent scientific ID must keep the same full physical channel."""
    targets: dict[str, ReactionKey] = {}
    for identifier, target in bindings:
        if targets.setdefault(identifier, target) != target:
            raise ValueError(
                "scientific reaction record ID is assigned to different physical targets: "
                f"{identifier}"
            )


def _bind_channel_datasets(
    channel: RegistryReaction, species: dict[str, Species], path: Path
) -> ReactionCandidate:
    target = registry_reaction_candidate(channel, species)
    if target is None:
        missing = sorted(
            {term.species for term in (*channel.reactants, *channel.products)} - species.keys()
        )
        raise ValueError(
            f"{path}: channel {channel.id!r} references unregistered species: {', '.join(missing)}"
        )
    bound = []
    for dataset in channel.datasets:
        if not reaction_declaration_matches(dataset.declared_target, target):
            raise ValueError(
                f"{path}: dataset {dataset.id!r} contradicts channel {channel.id!r} physical target"
            )
        try:
            bound.append(bind_dataset_target(dataset, target.id))
        except ValueError as error:
            raise ValueError(f"{path}: channel {channel.id!r}: {error}") from error
    channel.datasets = bound
    return target


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
        products=[
            Term(p["species"], _stoichiometric_number(p.get("n", 1)))
            for p in entry.get("products") or []
        ],
        energy_properties=normalized_reaction_energy_properties(entry | {"source": source_data}),
        third_body=entry.get("third_body"),
        surface=target if family == "surface" else None,
        reverse=entry.get("reverse"),
        datasets=_datasets(entry, entry["id"], root),
        source=_source(source_data),
        status=entry.get("status", "draft"),
        stabilization=entry.get("stabilization"),
        transformation=entry.get("transformation", {}),
        provenance=provenance,
        source_declaration=declaration,
        method=scientific_method(entry, source_data),
        review_scope=review_scope(entry),
    )


def _stoichiometric_number(value: object) -> float:
    try:
        number = normalized_number(value, "stoichiometric coefficient")
    except OverflowError as error:
        raise ValueError("stoichiometric coefficient must be finite") from error
    if number is None:
        raise ValueError("stoichiometric coefficient must be a number, not null")
    return number


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
        transformation=bind_transformation_states(record.transformation, mapped),
    )
    return replace(candidate, id=reaction_id(candidate.key))


def _scientific_reactions(
    data: dict, target: ReactionCandidate, species: dict[str, Species], path: Path
) -> tuple[ReactionRecord, ...]:
    entries = data.get("records") or []
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError(f"{path}: records must be a list of scientific reaction records")
    if not entries:
        return ()
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
        mapped = {key: registry_state_candidate(value).id for key, value in species.items()}
        declarations.append(
            replace(
                record, transformation=bind_transformation_states(record.transformation, mapped)
            )
        )
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


def _load_materials(directory: Path, hashes: dict[Path, bytes]) -> dict[str, Material]:
    if not directory.is_dir():
        return {}
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        data = _read(path, hashes)
        out[data["id"]] = Material(
            id=data["id"], name=data.get("name", data["id"]), notes=data.get("notes", "")
        )
    return out


def _read(path: Path, hashes: dict[Path, bytes]) -> dict:
    body = path.read_bytes()
    hashes[path] = hashlib.sha256(body).digest()
    return yamlio.load(body.decode("utf-8")) or {}
