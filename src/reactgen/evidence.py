"""Normalize and index read-only evidence for generated candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path

from reactgen import yamlio
from reactgen.chemistry import (
    declared_state_target,
    parse_state_id,
    reaction_declaration_matches,
    reaction_family,
)
from reactgen.chemistry import parse_equation as parse_equation
from reactgen.model import (
    CandidateSet,
    EquationKey,
    ReactionCandidate,
    ReactionKey,
    StateCandidate,
    StateKey,
    Term,
    bind_transformation_states,
    combine_transformations,
    reaction_id,
)
from reactgen.records import (
    TIER_RANK,
    MolecularIdentity,
    NumericDataset,
    ReactionRecord,
    RegistryReaction,
    Species,
    StateRecord,
    bind_dataset_target,
    dataset_payload,
    evidence_tier,
    normalized_dataset,
    normalized_properties,
    normalized_reaction_record,
    normalized_state_record,
    normalized_thermo,
    reaction_has_numeric_declaration,
    review_scope_covers,
    scientific_dataset_content,
    scientific_reaction_content,
    scientific_record_key,
    scientific_state_content,
    selectable_state_record_id,
    snapshot_content,
    state_record_payload,
    validate_numerical_targets,
)
from reactgen.registry import (
    Registry,
    molecular_identity_state,
    validate_reaction_record_targets,
)
from reactgen.registry import (
    registry_reaction_candidate as registry_reaction_candidate,
)
from reactgen.registry import (
    registry_state_candidate as registry_state_candidate,
)
from reactgen.selection import DataSelection
from reactgen.structure import (
    bind_physical_state,
    physical_equation_key,
    physical_reaction_key,
    physical_state_id,
    physical_state_key,
)

_OVERLAY_SECTIONS = {
    "properties",
    "thermo",
    "datasets",
    "states",
    "state_records",
    "reaction_records",
}

StateIdentityKey = tuple[tuple[tuple[str, int], ...], int]
_SourceOffer = tuple[ReactionRecord, ReactionCandidate, dict[str, StateCandidate]]


@dataclass(frozen=True)
class StateEvidence:
    match: str  # exact | compatible | ambiguous | none
    records: tuple[StateRecord, ...]
    selection: DataSelection | None = None
    target: str | None = None
    related_records: tuple[StateRecord, ...] = ()

    @property
    def preferred(self) -> StateRecord | None:
        return min(self.records, key=_state_preference) if self.records else None

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({record.label for record in self.records}))


@dataclass(frozen=True)
class ReactionEvidence:
    records: tuple[ReactionRecord, ...] = ()
    related_records: tuple[ReactionRecord, ...] = ()
    overlay_datasets: tuple[NumericDataset, ...] = ()
    structure_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def exact_records(self) -> tuple[ReactionRecord, ...]:
        return tuple(
            record for record in self.records if record.channel_scope == "product_resolved"
        )

    @property
    def total_records(self) -> tuple[ReactionRecord, ...]:
        return tuple(record for record in self.records if record.channel_scope == "total")

    @property
    def sources(self) -> tuple[str, ...]:
        found = {record.label for record in (*self.records, *self.related_records)}
        found.update(
            dataset.source.get("citation")
            or dataset.source.get("source_id")
            or dataset.source.get("source_type")
            or "reviewed overlay"
            for dataset in self.overlay_datasets
        )
        return tuple(sorted(found))

    @property
    def datasets(self) -> tuple[NumericDataset, ...]:
        return tuple(dataset for record in self.records for dataset in record.datasets) + (
            self.overlay_datasets
        )

    @property
    def reviewed(self) -> bool:
        return any(record.reviewed_for("channel_assertion") for record in self.exact_records)


@dataclass(frozen=True, init=False)
class EvidenceCatalog:
    """An evidence snapshot whose records and indexes cannot diverge.

    Inputs and returned records are independent copies. To change evidence,
    construct or load a new catalog; mutating a retrieved record does not
    change this snapshot or its fingerprint. The fingerprint covers both
    normalized scientific records and the loaded source-file content.
    """

    _state_records: tuple[StateRecord, ...] = field(repr=False)
    _reaction_records: tuple[ReactionRecord, ...] = field(repr=False)
    _overlay_datasets: dict[str, tuple[NumericDataset, ...]] = field(repr=False)
    materials: frozenset[str]
    fingerprint: str = field(init=False)
    _source_fingerprint: str | None = field(repr=False)
    _state_index: dict[StateIdentityKey, tuple[StateRecord, ...]] = field(init=False, repr=False)
    _reaction_index: dict[EquationKey, tuple[ReactionRecord, ...]] = field(init=False, repr=False)
    _source_channel_ids: dict[str, str] = field(init=False, repr=False)

    def __init__(
        self,
        state_records: tuple[StateRecord, ...] | None = None,
        reaction_records: tuple[ReactionRecord, ...] | None = None,
        overlay_datasets: Mapping[str, tuple[NumericDataset, ...]] | None = None,
        materials: frozenset[str] = frozenset(),
        fingerprint: str | None = None,
        *,
        _state_records: tuple[StateRecord, ...] = (),
        _reaction_records: tuple[ReactionRecord, ...] = (),
        _overlay_datasets: Mapping[str, tuple[NumericDataset, ...]] | None = None,
        _source_fingerprint: str | None = None,
    ) -> None:
        """Construct a snapshot; ``fingerprint`` is a source-file base digest.

        The public attribute is the derived digest of this snapshot. Clone or
        update an existing snapshot with ``dataclasses.replace`` rather than
        passing its already-derived digest as a new source-file base.
        """
        # dataclasses.replace supplies stored fields; explicit public inputs
        # override them and rebuild the snapshot and both physical indexes.
        states_input = _state_records if state_records is None else state_records
        reactions_input = _reaction_records if reaction_records is None else reaction_records
        datasets_input = _overlay_datasets if overlay_datasets is None else overlay_datasets
        copied = deepcopy(
            (
                tuple(states_input),
                tuple(reactions_input),
                {target: tuple(records) for target, records in (datasets_input or {}).items()},
            )
        )
        bound_records, source_channel_ids = _bind_reaction_records(copied[1])
        snapshot = (
            copied[0],
            bound_records,
            {
                target: tuple(
                    bind_dataset_target(dataset, target)
                    if re.fullmatch(r"rxn_[0-9a-f]{12}", target)
                    else dataset
                    for dataset in records
                )
                for target, records in copied[2].items()
            },
        )
        validate_numerical_targets(
            (dataset.id, source_channel_ids.get(dataset.reaction_target, dataset.reaction_target))
            for dataset in (
                *(dataset for record in snapshot[1] for dataset in record.datasets),
                *(dataset for records in snapshot[2].values() for dataset in records),
            )
            if dataset.reaction_target is not None
        )
        object.__setattr__(self, "_state_records", snapshot[0])
        object.__setattr__(self, "_reaction_records", snapshot[1])
        object.__setattr__(self, "_overlay_datasets", snapshot[2])
        object.__setattr__(self, "_source_channel_ids", source_channel_ids)
        object.__setattr__(self, "materials", frozenset(materials))
        source_fingerprint = fingerprint if fingerprint is not None else _source_fingerprint
        object.__setattr__(self, "_source_fingerprint", source_fingerprint)
        object.__setattr__(
            self,
            "fingerprint",
            _snapshot_fingerprint(*snapshot, frozenset(materials), source_fingerprint),
        )
        states: dict[StateIdentityKey, list[StateRecord]] = {}
        state_targets: dict[tuple, StateKey] = {}
        for state_record in self._state_records:
            identifier = selectable_state_record_id(state_record)
            state_identity = scientific_record_key(
                state_record_payload(state_record) | {"record_id": identifier}
            )
            state_target = physical_state_key(state_record.candidate)
            if state_identity in state_targets and state_targets[state_identity] != state_target:
                raise ValueError(
                    "scientific state record ID is assigned to different physical targets: "
                    f"{identifier}"
                )
            state_targets[state_identity] = state_target
            states.setdefault(_state_identity(state_record.candidate), []).append(state_record)
        reactions: dict[EquationKey, list[ReactionRecord]] = {}
        for reaction_record in self._reaction_records:
            key = _equation_lookup_key(reaction_record.equation_key)
            reactions.setdefault(key, []).append(reaction_record)
        object.__setattr__(
            self,
            "_state_index",
            {key: tuple(sorted(records, key=_state_preference)) for key, records in states.items()},
        )
        object.__setattr__(
            self,
            "_reaction_index",
            {
                key: tuple(sorted(records, key=lambda item: (item.label, item.id)))
                for key, records in reactions.items()
            },
        )

    @property
    def state_records(self) -> tuple[StateRecord, ...]:
        return deepcopy(self._state_records)

    @property
    def reaction_records(self) -> tuple[ReactionRecord, ...]:
        return deepcopy(self._reaction_records)

    @property
    def overlay_datasets(self) -> dict[str, tuple[NumericDataset, ...]]:
        return deepcopy(self._overlay_datasets)

    def declared_states(
        self, *, structural_context: Iterable[StateCandidate] = ()
    ) -> tuple[StateCandidate, ...]:
        """Expose named state identities without supplying or qualifying their values."""
        stopped = {"rejected", "conflicting"}
        active = [record for record in self._state_records if record.status not in stopped]
        found = {record.candidate.id: record.candidate for record in active}
        for reaction in self._reaction_records:
            if reaction.status not in stopped:
                found.update((state.id, state) for state in reaction.states)
        for record in active:
            for prop in record.properties.values():
                if prop.related_state is not None:
                    related = parse_state_id(prop.related_state)
                    if related is not None:
                        found.setdefault(related.id, related)
        for group in self.scoped_molecular_states(structural_context).values():
            found.update((state.id, state) for state in group)
        return deepcopy(tuple(found[key] for key in sorted(found)))

    def scoped_molecular_states(
        self, context: Iterable[StateCandidate]
    ) -> dict[str, tuple[StateCandidate, ...]]:
        """Project individually identified records onto a graph already in the case."""
        representatives: dict[str, StateCandidate] = {}
        for state in context:
            if (state.structure or "").startswith("smiles:"):
                representatives.setdefault(physical_state_id(state.id), state)
        if not representatives:
            return {}
        scopes = {_molecular_scope(state) for state in representatives.values()}
        inventories = {scope[:-1] for scope in scopes}
        found: dict[str, dict[str, StateCandidate]] = {}
        for record in self._state_records:
            nominal = record.candidate
            if (
                record.molecular_identity is None
                or record.status in {"rejected", "conflicting"}
                or _molecular_scope(nominal)[:-1] not in inventories
            ):
                continue
            explicit = molecular_identity_state(nominal, record.molecular_identity)
            if explicit is not None and _molecular_scope(explicit) in scopes:
                state = bind_physical_state(explicit, representatives)
                found.setdefault(nominal.id, {})[state.id] = state
        return {
            nominal: tuple(states[key] for key in sorted(states))
            for nominal, states in found.items()
        }

    @classmethod
    def load(
        cls,
        registry_path: str | Path | None,
        overlay: str | Path | None = None,
        known: tuple[Path, ...] = (),
    ) -> EvidenceCatalog:
        sources: list[tuple[Path, str | None]] = []
        if registry_path is not None:
            sources.append((Path(registry_path), "registry"))
        sources.extend((path, "snapshot") for path in known)
        if overlay is not None:
            sources.append((Path(overlay), "overlay"))
        return cls._read_sources(sources)

    @classmethod
    def load_paths(cls, paths: tuple[Path, ...]) -> EvidenceCatalog:
        """Load explicit local Registry, snapshot and overlay inputs once.

        Source order never resolves competing evidence. Analysis remains
        read-only and performs no external acquisition or adoption.
        """
        return cls._read_sources(
            [(path, None) for path in sorted({Path(p).resolve() for p in paths})]
        )

    @classmethod
    def from_overlay(cls, document: dict, base: Path) -> EvidenceCatalog:
        """Validate an already-read overlay for inspection or explicit adoption."""
        return cls(
            tuple(_unique_states(_overlay_states(document))),
            tuple(_overlay_reactions(document, base)),
            _overlay_datasets(document, base),
        )

    @classmethod
    def _read_sources(cls, sources: list[tuple[Path, str | None]]) -> EvidenceCatalog:
        states: list[StateRecord] = []
        reactions: list[ReactionRecord] = []
        datasets: dict[str, list[NumericDataset]] = {}
        materials: set[str] = set()
        source_digests: dict[Path, bytes] = {}
        registry_files: set[Path] = set()
        for path, kind in sources:
            if kind == "registry" or (kind is None and path.is_dir()):
                if kind is None and not (path / "species").is_dir():
                    raise ValueError(f"not a Registry directory: {path}")
                registry = Registry.load(path)
                states.extend(_registry_states(registry))
                reactions.extend(_registry_reactions(registry))
                materials.update(registry.materials)
                source_digests.update(registry.document_hashes)
                registry_files.update(file for file in path.rglob("*") if file.is_file())
                continue
            document, source_digests[path] = _read_source_document(path, kind)
            if kind == "snapshot" or (kind is None and "records" in document):
                snapshot_states, snapshot_reactions = _snapshot_records(path, document)
                states.extend(snapshot_states)
                reactions.extend(snapshot_reactions)
            elif kind == "overlay" or _OVERLAY_SECTIONS.intersection(document):
                states.extend(_overlay_states(document))
                reactions.extend(_overlay_reactions(document, path.parent))
                for target, records in _overlay_datasets(document, path.parent).items():
                    datasets.setdefault(target, []).extend(records)
            else:
                raise ValueError(f"unrecognized snapshot or overlay: {path}")
        # The normalized asset carries the byte observation from this read.
        # A second file read could hash different bytes from the declaration.
        for path, checksum in _asset_digests(
            [*(record.datasets for record in reactions), *datasets.values()]
        ):
            source_digests.setdefault(path, checksum)
        source_digests.update(
            (file, hashlib.sha256(file.read_bytes()).digest())
            for file in registry_files - source_digests.keys()
        )
        digest = hashlib.sha256(b"".join(sorted(source_digests.values()))).hexdigest()
        return cls(
            tuple(_unique_states(states)),
            tuple(reactions),
            {target: tuple(records) for target, records in datasets.items()},
            frozenset(materials),
            digest,
        )

    def attested_candidates(
        self,
        surfaces: tuple[str, ...] = (),
        *,
        representatives: Mapping[str, StateCandidate] | None = None,
    ) -> list[tuple[ReactionCandidate, dict[str, StateCandidate]]]:
        """Group active product-resolved proposals by physical channel."""
        found: dict[str, list[_SourceOffer]] = {}
        for record in self._reaction_records:
            if record.channel_scope != "product_resolved" or record.status in {
                "rejected",
                "conflicting",
            }:
                continue
            surface = record.equation_key[1]
            if surface is not None and surface not in surfaces:
                continue
            reaction, states = _source_candidate(record, representatives or {})
            found.setdefault(reaction.id, []).append((record, reaction, states))
        return deepcopy([_source_candidate_group(found[key]) for key in sorted(found)])

    def state(self, candidate: StateCandidate) -> StateEvidence:
        """Keep preferred matches and related targets separate; assess only the former."""
        records = self._state_index.get(_state_identity(candidate), ())
        exact = tuple(record for record in records if _state_matches(candidate, record, exact=True))
        compatible = tuple(
            record for record in records if _state_matches(candidate, record, exact=False)
        )
        selected = exact or compatible
        return StateEvidence(
            "exact" if exact else "compatible" if compatible else "none",
            deepcopy(selected),
            related_records=deepcopy(tuple(record for record in records if record not in selected)),
        )

    def reaction(self, candidate: ReactionCandidate) -> ReactionEvidence:
        offered = tuple(
            dataset_for_reaction(dataset, candidate)
            for dataset in self._overlay_datasets.get(candidate.id, ())
        )
        equation = candidate.equation_key
        physical = physical_equation_key(equation)
        possible = (
            (record, molecular_equation(record.equation_key, record.molecular_identities, equation))
            for record in self._reaction_index.get(_equation_lookup_key(equation), ())
            if record.family is None or record.family == candidate.family
        )
        matched = [
            (record, key) for record, key in possible if physical_equation_key(key) == physical
        ]
        equation_records = tuple(record for record, _ in matched)
        exact = tuple(
            record
            for record in equation_records
            if record.process == candidate.process
            and record.stabilization == candidate.stabilization
        )
        related = tuple(record for record in equation_records if record not in exact)
        compared = [key for _, key in matched if key != equation]
        aliases = {
            state: normalized
            for key in (equation, *compared)
            if compared
            for side in key[2:]
            for state, _ in side
            if (normalized := physical_state_id(state)) != state
        }
        return deepcopy(ReactionEvidence(exact, related, offered, aliases))

    def validate_targets(self, candidates: CandidateSet) -> None:
        """Resolve candidate references before checking numerical physical identities.

        API callers may name their candidates independently of canonical physical
        IDs. Unused evidence references remain available for other analyses.
        """
        bindings = [
            (
                dataset.id,
                self._source_channel_ids.get(dataset.reaction_target, dataset.reaction_target),
            )
            for record in self._reaction_records
            for dataset in record.datasets
            if dataset.reaction_target is not None
        ]
        for reference, datasets in self._overlay_datasets.items():
            target = candidates.reactions.get(reference)
            for dataset in datasets:
                resolved = dataset_for_reaction(dataset, target) if target is not None else dataset
                if resolved.reaction_target is not None:
                    physical_id = (
                        reaction_id(physical_reaction_key(target))
                        if target is not None
                        else self._source_channel_ids.get(
                            resolved.reaction_target, resolved.reaction_target
                        )
                    )
                    bindings.append((resolved.id, physical_id))
        validate_numerical_targets(bindings)


def dataset_for_reaction(
    dataset: NumericDataset,
    target: ReactionCandidate,
    *,
    source: ReactionRecord | None = None,
) -> NumericDataset:
    """Identify an offered quantity's channel, without interpreting or approving its source."""
    raw_target = reaction_record_candidate(source) if source is not None else target
    if source is not None and raw_target.key != target.key:
        projected = molecular_equation(
            raw_target.equation_key, source.molecular_identities, target.equation_key
        )
        if raw_target.key[:5] != target.key[:5] or physical_equation_key(
            projected
        ) != physical_equation_key(target.equation_key):
            raise ValueError(f"dataset {dataset.id} declares a different physical reaction target")
        bound = dataset_for_reaction(dataset, raw_target)
        declaration = bound.declared_target.copy()
        if "reaction" in declaration:
            declaration["reaction"] = target.equation
        if "reaction_id" in declaration:
            declaration["reaction_id"] = reaction_id(target.key)
        dataset = replace(bound, reaction_target=None, declared_target=declaration)
    if not reaction_declaration_matches(dataset.declared_target, target):
        raise ValueError(f"dataset {dataset.id} declares a different physical reaction target")
    return bind_dataset_target(dataset, reaction_id(target.key))


def _bind_reaction_records(
    records: tuple[ReactionRecord, ...],
) -> tuple[tuple[ReactionRecord, ...], dict[str, str]]:
    targets: list[tuple[str, ReactionKey]] = []
    source_channel_ids: dict[str, str] = {}
    bound = []
    for record in records:
        reaction = reaction_record_candidate(record)
        key = physical_reaction_key(reaction)
        targets.append((record.id, key))
        source_channel_ids[reaction.id] = reaction_id(key)
        datasets = tuple(dataset_for_reaction(dataset, reaction) for dataset in record.datasets)
        bound.append(replace(record, datasets=datasets) if datasets else record)
    validate_reaction_record_targets(targets)
    return tuple(bound), source_channel_ids


def _read_source_document(path: Path, kind: str | None) -> tuple[dict, bytes]:
    if not path.is_file():
        raise FileNotFoundError(f"{kind or 'evidence path'} not found: {path}")
    body = path.read_bytes()
    document = yamlio.load(body.decode("utf-8"))
    if kind == "overlay" and document is None:
        document = {}
    if not isinstance(document, dict):
        raise ValueError(f"{kind or 'evidence'} must be a mapping: {path}")
    return document, hashlib.sha256(body).digest()


def _asset_digests(
    groups: list[list[NumericDataset] | tuple[NumericDataset, ...]],
) -> list[tuple[Path, bytes]]:
    return [
        (asset.local_path, bytes.fromhex(asset.sha256))
        for datasets in groups
        for dataset in datasets
        if (asset := dataset.asset) is not None and asset.local_path is not None and asset.sha256
    ]


def _registry_states(registry: Registry) -> list[StateRecord]:
    found = [
        StateRecord(
            id=record.id,
            candidate=registry_state_candidate(record),
            properties=dict(record.properties),
            thermo=record.thermo,
            energy_eV=record.state.energy_eV,
            existence=record.state.existence,
            configuration=record.state.configuration,
            term=record.state.term,
            j=record.state.j,
            parity=record.state.parity,
            degeneracy=record.state.degeneracy,
            lifetime_s=record.state.lifetime_s,
            status=record.state.status or record.status,
            tier=evidence_tier(record.state.status or record.status, record.state.source),
            source={"source_id": f"registry:{record.id}"} | record.state.source,
            origin="registry",
            existence_source=record.state.existence_source,
            members=record.state.members,
            provenance=record.state.provenance,
            source_declaration=record.state.source_declaration,
            method=record.state.method,
            review_scope=record.state.review_scope,
            molecular_identity=record.molecular_identity,
        )
        for record in registry.species.values()
    ]
    found.extend(item for species in registry.species.values() for item in species.records)
    return found


def _registry_reactions(registry: Registry) -> list[ReactionRecord]:
    found = []
    identities = {
        registry_state_candidate(species).id: species.molecular_identity
        for species in registry.species.values()
        if species.molecular_identity is not None
    }
    for reaction in (item for group in registry.channels.values() for item in group):
        candidate = registry.channel_locations[reaction.id][2]
        states = _reaction_states(reaction, registry.species)
        if states is None:
            continue
        source = dict(reaction.source) or {"source_id": f"registry:{reaction.id}"}
        found.append(
            ReactionRecord(
                id=reaction.id,
                equation_key=candidate.equation_key,
                family=candidate.family,
                process=candidate.process,
                states=states,
                datasets=tuple(reaction.datasets),
                energy_properties=reaction.energy_properties,
                status=reaction.status,
                tier=evidence_tier(reaction.status, source),
                source=source,
                origin="registry",
                stabilization=reaction.stabilization,
                provenance=reaction.provenance,
                source_declaration=reaction.source_declaration,
                method=reaction.method,
                review_scope=reaction.review_scope,
                transformation=candidate.transformation,
                molecular_identities={
                    state.id: identities[state.id] for state in states if state.id in identities
                },
            )
        )
        found.extend(reaction.records)
    return found


def _reaction_states(
    reaction: RegistryReaction,
    species: dict[str, Species],
) -> tuple[StateCandidate, ...] | None:
    records = []
    for term in (*reaction.reactants, *reaction.products):
        found = species.get(term.species)
        if found is None:
            return None
        records.append(registry_state_candidate(found))
    return tuple({state.id: state for state in records}.values())


def _snapshot_records(path: Path, document: dict) -> tuple[list[StateRecord], list[ReactionRecord]]:
    records, source_data, default_kind = snapshot_content(document)
    states: list[StateRecord] = []
    reactions: list[ReactionRecord] = []
    for index, record in enumerate(records):
        written = record.get("reaction")
        if not written:
            state = snapshot_state(record, source_data)
            if state is None:
                raise ValueError(
                    f"snapshot record {index} has an unidentified state target; "
                    "use ingest to retain unresolved declarations in its review queue"
                )
            states.append(state)
            continue
        datasets = (
            (
                normalized_dataset(
                    record,
                    base=path.parent,
                    default_kind=default_kind,
                    default_source=source_data,
                ),
            )
            if reaction_has_numeric_declaration(record)
            else ()
        )
        reaction = snapshot_reaction(record, source_data, datasets=datasets)
        if reaction is None:
            raise ValueError(
                f"snapshot record {index} has an unidentified reaction target; "
                "use ingest to retain unresolved declarations in its review queue"
            )
        reactions.append(reaction)
        if reaction.status in {"rejected", "conflicting"}:
            continue
        states.extend(
            StateRecord(
                id=state.id,
                candidate=replace(
                    state,
                    origin="attested_only",
                    introduced_by=(f"snapshot:{path.stem}",),
                ),
                existence="unknown",
                source={key: value for key, value in reaction.source.items() if key != "record_id"},
                provenance=replace(reaction.provenance, record_id=None),
                source_declaration={
                    "derived_from_reaction": reaction.id,
                    "reaction_source": deepcopy(reaction.source),
                    "reaction_declaration": deepcopy(reaction.source_declaration),
                },
                origin="snapshot",
            )
            for state in reaction.states
        )
    return states, reactions


def snapshot_reaction(
    record: dict,
    default_source: dict | None = None,
    *,
    origin: str = "snapshot",
    base: Path | None = None,
    datasets: tuple[NumericDataset, ...] | None = None,
    preserved_record_id: bool = False,
) -> ReactionRecord | None:
    """Normalize the same physical reaction claim at every local data boundary."""
    parsed = parse_equation(str(record.get("reaction") or ""))
    if parsed is None:
        return None
    equation, states = parsed
    stated_third = record.get("third_body")
    if stated_third is not None and stated_third != equation[0]:
        raise ValueError("reaction record third_body contradicts its equation")
    equation = equation[0], record.get("surface"), equation[2], equation[3]
    if datasets is None:
        entries = record.get("datasets")
        if entries is not None:
            if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                raise ValueError("reaction record datasets must be a list of records")
            datasets = tuple(normalized_dataset(item, base=base) for item in entries)
        elif preserved_record_id or not reaction_has_numeric_declaration(record):
            datasets = ()
        else:
            datasets = (normalized_dataset(record, base=base, default_source=default_source),)
    return normalized_reaction_record(
        record,
        equation,
        states,
        default_source,
        origin=origin,
        datasets=datasets,
        preserved_record_id=preserved_record_id,
    )


def reaction_record_candidate(record: ReactionRecord) -> ReactionCandidate:
    """Resolve a record's target; existence and data qualification are separate."""
    third_body, surface, reactants, products = record.equation_key
    candidate = ReactionCandidate(
        id="",
        reactants=tuple(Term(name, count) for name, count in reactants),
        products=tuple(Term(name, count) for name, count in products),
        family=record.family or reaction_family(record.equation_key),
        process=record.process,
        origin="attested_only",
        generation_rule=f"{record.origin}:{record.id}",
        depth=0,
        third_body=third_body,
        surface=surface,
        stabilization=record.stabilization,
        transformation=record.transformation,
    )
    return replace(candidate, id=reaction_id(candidate.key))


def _source_candidate(
    record: ReactionRecord, representatives: Mapping[str, StateCandidate]
) -> tuple[ReactionCandidate, dict[str, StateCandidate]]:
    candidate = reaction_record_candidate(record)
    bound = bound_molecular_participants(record, representatives)
    states = {
        state.id: bind_physical_state(bound.get(state.id, state), representatives)
        for state in record.states
    }
    aliases = {name: state.id for name, state in states.items() if state.id != name}
    if aliases:
        _, _, reactants, products = physical_equation_key(record.equation_key, aliases)
        candidate = replace(
            candidate,
            reactants=tuple(Term(*term) for term in reactants),
            products=tuple(Term(*term) for term in products),
            transformation=bind_transformation_states(record.transformation, aliases),
        )
        candidate = replace(candidate, id=reaction_id(candidate.key))
    return candidate, {state.id: state for state in states.values()}


def bound_molecular_participants(
    record: ReactionRecord, representatives: Mapping[str, StateCandidate]
) -> dict[str, StateCandidate]:
    """Find explicit representatives of the locally identified Registry participants."""
    if not record.molecular_identities:
        return {}
    structured = {
        state.id.split(";structure=", 1)[0]
        for state in representatives.values()
        if (state.structure or "").startswith("smiles:")
    }
    return {
        state.id: representative
        for state in record.states
        if state.id in structured
        and (identity := record.molecular_identities.get(state.id)) is not None
        and (explicit := molecular_identity_state(state, identity)) is not None
        and (representative := representatives.get(physical_state_id(explicit.id))) is not None
    }


def _molecular_scope(state: StateCandidate) -> tuple:
    key = physical_state_key(state)
    return key[0], key[1], key[5], key[6]


def molecular_reference_id(record: StateRecord, target: str, reference: str | None) -> str | None:
    """Resolve a same-molecule reference using this exact state record's graph proof."""
    identity = record.molecular_identity
    if identity is None or reference is None or ";structure=" not in target:
        return reference
    related, bound = parse_state_id(reference), parse_state_id(target)
    if (
        related is None
        or bound is None
        or related.structure is not None
        or related.state.kind != "ground"
        or related.state.resolution != "resolved"
        or _molecular_scope(related)[:-1] != _molecular_scope(bound)[:-1]
    ):
        return reference
    explicit = molecular_identity_state(record.candidate, identity)
    if explicit is None or physical_state_key(explicit) != physical_state_key(bound):
        return reference
    projected = molecular_identity_state(related, identity, verify_graph=False)
    return physical_state_id(projected.id) if projected is not None else reference


def _equation_lookup_key(equation: EquationKey) -> EquationKey:
    """Group possible targets by the state axes that require no graph matching."""
    aliases = {
        name: name.split(";structure=", 1)[0]
        for side in equation[2:]
        for name, _ in side
        if ";structure=" in name
    }
    return physical_equation_key(equation, aliases)


def molecular_equation(
    equation: EquationKey,
    identities: Mapping[str, MolecularIdentity],
    target: EquationKey,
    *,
    saved_aliases: Mapping[str, str] | None = None,
) -> EquationKey:
    """Project only this Registry record's qualified nominal participants."""
    if not identities:
        return equation

    def comparison(identifier: str) -> str:
        if saved_aliases is not None:
            return saved_aliases.get(identifier, identifier)
        return physical_state_id(identifier)

    participant_ids = {
        comparison(name) for side in target[2:] for name, _ in side if ";structure=" in name
    }
    nominal_ids = {name.split(";structure=", 1)[0] for name in participant_ids}
    aliases = {}
    for name, identity in identities.items():
        if name not in nominal_ids:
            continue
        state = parse_state_id(name)
        if state is None:
            raise ValueError(f"invalid nominal molecular identity target: {name}")
        explicit = molecular_identity_state(state, identity, verify_graph=saved_aliases is None)
        if explicit is not None and comparison(explicit.id) in participant_ids:
            aliases[name] = explicit.id
    return physical_equation_key(equation, aliases)


def _source_candidate_group(
    offers: list[_SourceOffer],
) -> tuple[ReactionCandidate, dict[str, StateCandidate]]:
    # The representative names discovery provenance only. Each independently
    # qualified transformation can describe a different valid role mapping.
    _, candidate, states = min(offers, key=lambda offer: (offer[0].id, offer[0].label))
    reviewed_mapping = any(
        reaction.transformation and record.reviewed_for("channel_assertion")
        for record, reaction, _ in offers
    )
    mappings: dict[str, list[dict]] = {}
    for record, reaction, _ in offers:
        usable = (
            record.reviewed_for("channel_assertion")
            if reviewed_mapping
            else review_scope_covers(record.review_scope, "channel_assertion")
        )
        if usable and reaction.transformation:
            mappings.setdefault(record.id, []).append(reaction.transformation)
    transformations = combine_transformations(
        sorted(
            (
                choices[0]
                for choices in mappings.values()
                if all(choice == choices[0] for choice in choices)
            ),
            key=_encode_declaration,
        )
    )
    return replace(candidate, transformation=transformations), states


def snapshot_state(
    record: dict,
    default_source: dict[str, str],
    *,
    preserved_record_id: bool = False,
) -> StateRecord | None:
    written = record.get("species")
    candidate = declared_state_target(str(written), record) if written else None
    if candidate is None:
        return None
    return snapshot_state_record(
        record, candidate, default_source, preserved_record_id=preserved_record_id
    )


def snapshot_state_record(
    record: dict,
    candidate: StateCandidate,
    default_source: dict[str, str],
    *,
    preserved_record_id: bool = False,
) -> StateRecord:
    """Normalize the payload for a target resolved from the same declaration."""
    candidate = replace(
        candidate,
        origin="attested_only",
        introduced_by=("snapshot",),
    )
    return normalized_state_record(
        record, candidate, default_source, preserved_record_id=preserved_record_id
    )


def _overlay_states(overlay: dict) -> list[StateRecord]:
    """Keep each source declaration intact; quantity selection handles alternatives."""
    records: list[StateRecord] = []
    properties = _overlay_mapping(overlay, "properties")
    thermos = _overlay_mapping(overlay, "thermo")
    identities = _overlay_mapping(overlay, "states")
    for state_id in sorted(set(properties) | set(thermos) | set(identities)):
        record = _legacy_overlay_state(state_id, identities.get(state_id))
        records.append(
            replace(
                record,
                properties=record.properties | normalized_properties(properties.get(state_id)),
                thermo=normalized_thermo(thermos.get(state_id)) or record.thermo,
                origin="overlay",
            )
        )
    grouped = _overlay_mapping(overlay, "state_records")
    for state_id, entries in sorted(grouped.items()):
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise ValueError("overlay.state_records entries must be lists of scientific records")
        for entry in entries:
            if entry.get("species") not in {None, state_id}:
                raise ValueError("overlay state record contradicts its target ID")
            incoming = snapshot_state({"species": state_id, **entry}, {}, preserved_record_id=True)
            if incoming is None:
                raise ValueError(f"overlay state record has an invalid target: {state_id}")
            records.append(replace(incoming, origin="overlay"))
    return records


def _legacy_overlay_state(state_id: str, identity: object) -> StateRecord:
    candidate = parse_state_id(state_id)
    if candidate is None:
        raise ValueError(f"overlay has an invalid state target: {state_id}")
    if identity is None:
        identity = {}
    if not isinstance(identity, dict) or identity.get("species") not in {None, state_id}:
        raise ValueError(f"overlay.states.{state_id} must describe its named target")
    record = snapshot_state({"species": state_id, "phase": candidate.phase, **identity}, {})
    if record is None:
        raise ValueError(f"overlay has an unidentified state target: {state_id}")
    return record


def _overlay_datasets(
    overlay: dict,
    base: Path | None,
) -> dict[str, tuple[NumericDataset, ...]]:
    grouped = _overlay_mapping(overlay, "datasets")
    found = {}
    for reaction_id_, items in grouped.items():
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("overlay.datasets entries must be lists of numeric records")
        found[reaction_id_] = tuple(
            normalized_dataset(
                item,
                base=base,
            )
            for item in items
        )
    return found


def _overlay_mapping(overlay: dict, name: str) -> dict:
    """Validate legacy and current overlay containers before interpreting targets."""
    value = overlay.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict) or any(
        not isinstance(target, str) or not target.strip() for target in value
    ):
        raise ValueError(f"overlay.{name} must be a mapping with nonempty target IDs")
    return value


def _overlay_reactions(overlay: dict, base: Path | None) -> list[ReactionRecord]:
    grouped = _overlay_mapping(overlay, "reaction_records")
    found = []
    for target, entries in sorted(grouped.items()):
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise ValueError("overlay.reaction_records entries must be lists of scientific records")
        for entry in entries:
            if "datasets" in entry:
                raise ValueError("reaction_records use overlay.datasets for numerical records")
            record = snapshot_reaction(entry, origin="overlay", base=base, preserved_record_id=True)
            if record is None or reaction_record_candidate(record).id != target:
                raise ValueError("overlay reaction record contradicts its target ID")
            found.append(record)
    return found


def _state_matches(candidate: StateCandidate, record: StateRecord, *, exact: bool) -> bool:
    found = record.candidate
    if candidate.structure is not None and record.molecular_identity is not None:
        found = molecular_identity_state(found, record.molecular_identity) or found
    if found.composition != candidate.composition or found.charge != candidate.charge:
        return False
    if found.phase != candidate.phase and (
        exact or "unknown" not in {found.phase, candidate.phase}
    ):
        return False
    if (exact or (found.structure is not None and candidate.structure is not None)) and (
        physical_state_key(found)[-1] != physical_state_key(candidate)[-1]
    ):
        return False
    if found.state.kind == candidate.state.kind and found.state.label == candidate.state.label:
        return not exact or found.state.resolution == candidate.state.resolution
    if exact or candidate.state.resolution != "lumped":
        return False
    if candidate.state.kind == "electronic":
        return found.state.kind in {"electronic", "metastable", "resonant", "resolved"}
    if candidate.state.kind in {"metastable", "resonant"}:
        return found.state.kind == "electronic" and found.state.resolution == "lumped"
    if candidate.state.kind == "vibrational":
        return found.state.kind == "resolved" and found.state.label.startswith("v")
    return False


def _state_preference(record: StateRecord) -> tuple[int, int, int, str, str]:
    assertion = (
        record.reviewed
        and record.existence_source is not None
        and record.existence not in {"unknown", "hypothetical"}
    )
    origin_rank = {"registry": 0, "overlay": 1, "snapshot": 2}.get(record.origin, 3)
    return (
        0 if assertion else 1,
        TIER_RANK.get(record.tier, 5),
        origin_rank,
        record.id,
        record.label,
    )


def _state_identity(candidate: StateCandidate) -> StateIdentityKey:
    return (tuple(sorted(candidate.composition.items())), candidate.charge)


def _unique_states(records: list[StateRecord]) -> list[StateRecord]:
    """Remove identical declarations without merging independent scientific records."""
    found: dict[tuple, list[StateRecord]] = {}
    for record in records:
        group = found.setdefault(record.candidate.key, [])
        if record not in group:
            group.append(record)
    return [record for group in found.values() for record in group]


def _encode_declaration(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _snapshot_fingerprint(
    states: tuple[StateRecord, ...],
    reactions: tuple[ReactionRecord, ...],
    datasets: dict[str, tuple[NumericDataset, ...]],
    materials: frozenset[str],
    source_fingerprint: str | None,
) -> str:
    """Identify the actual snapshot, including explicit in-memory evidence updates.

    Sorting removes input order, and the existing science-content views keep
    asset storage paths out when saved checksums identify the bytes. This
    operation never reads assets: evaluation verifies their current integrity.
    """

    def numeric_content(records: tuple[NumericDataset, ...]) -> list[str]:
        return sorted(
            _encode_declaration(scientific_dataset_content(dataset_payload(record)))
            for record in records
        )

    content = {
        "states": sorted(
            _encode_declaration(
                {
                    "id": record.id,
                    "record_id": record.record_id,
                    "content": scientific_state_content(record),
                    **(
                        {"molecular_identity": record.molecular_identity}
                        if record.molecular_identity is not None
                        else {}
                    ),
                }
            )
            for record in states
        ),
        "reactions": sorted(
            _encode_declaration(
                {
                    "content": scientific_reaction_content(record),
                    "datasets": numeric_content(record.datasets),
                    **(
                        {"molecular_identities": record.molecular_identities}
                        if record.molecular_identities
                        else {}
                    ),
                }
            )
            for record in reactions
        ),
        "overlay_datasets": {
            target: numeric_content(records) for target, records in datasets.items()
        },
        "materials": sorted(materials),
        "source_files": source_fingerprint,
    }
    return hashlib.sha256(_encode_declaration(content).encode("utf-8")).hexdigest()
