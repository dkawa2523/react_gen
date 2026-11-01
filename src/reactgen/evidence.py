"""Normalize and index read-only evidence for generated candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
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
    StateCandidate,
    StateKey,
    Term,
    reaction_id,
)
from reactgen.records import (
    TIER_RANK,
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
    scientific_dataset_content,
    scientific_reaction_content,
    scientific_record_key,
    scientific_state_content,
    selectable_state_record_id,
    state_record_payload,
    validate_numerical_targets,
    validate_snapshot,
)
from reactgen.registry import (
    Registry,
)
from reactgen.registry import (
    registry_reaction_candidate as registry_reaction_candidate,
)
from reactgen.registry import (
    registry_state_candidate as registry_state_candidate,
)
from reactgen.selection import DataSelection

StateIdentityKey = tuple[tuple[tuple[str, int], ...], int]


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
        snapshot = (
            copied[0],
            tuple(
                replace(
                    record,
                    datasets=tuple(
                        dataset_for_reaction(dataset, reaction_record_candidate(record))
                        for dataset in record.datasets
                    ),
                )
                for record in copied[1]
            ),
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
            (dataset.id, dataset.reaction_target or "")
            for dataset in (
                *(dataset for record in snapshot[1] for dataset in record.datasets),
                *(dataset for records in snapshot[2].values() for dataset in records),
            )
            if dataset.reaction_target is not None
        )
        object.__setattr__(self, "_state_records", snapshot[0])
        object.__setattr__(self, "_reaction_records", snapshot[1])
        object.__setattr__(self, "_overlay_datasets", snapshot[2])
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
            state_target = state_record.candidate.key
            if state_identity in state_targets and state_targets[state_identity] != state_target:
                raise ValueError(
                    "scientific state record ID is assigned to different physical targets: "
                    f"{identifier}"
                )
            state_targets[state_identity] = state_target
            states.setdefault(_state_identity(state_record.candidate), []).append(state_record)
        reactions: dict[EquationKey, list[ReactionRecord]] = {}
        reaction_targets: dict[str, EquationKey] = {}
        for reaction_record in self._reaction_records:
            reaction_identity = reaction_record.id
            reaction_target = reaction_record.equation_key
            if (
                reaction_identity in reaction_targets
                and reaction_targets[reaction_identity] != reaction_target
            ):
                raise ValueError(
                    "scientific reaction record ID is assigned to different physical targets: "
                    f"{reaction_identity}"
                )
            reaction_targets[reaction_identity] = reaction_target
            reactions.setdefault(reaction_record.equation_key, []).append(reaction_record)
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

    @classmethod
    def load(
        cls,
        registry_path: str | Path | None,
        overlay: str | Path | None = None,
        known: tuple[Path, ...] = (),
    ) -> EvidenceCatalog:
        root = Path(registry_path) if registry_path is not None else None
        if root is not None and not root.is_dir():
            raise FileNotFoundError(f"registry directory not found: {root}")
        if overlay is not None and not Path(overlay).is_file():
            raise FileNotFoundError(f"overlay file not found: {overlay}")
        registry = Registry.load(root) if root is not None and root.is_dir() else None
        states = _registry_states(registry)
        reactions = _registry_reactions(registry)
        for path in known:
            snapshot_states, snapshot_reactions = _load_snapshot(path)
            states.extend(snapshot_states)
            reactions.extend(snapshot_reactions)

        overlay_path = Path(overlay) if overlay is not None else None
        overlay_data = (
            yamlio.load(overlay_path.read_text(encoding="utf-8")) or {}
            if overlay_path is not None and overlay_path.is_file()
            else {}
        )
        if not isinstance(overlay_data, dict):
            raise ValueError("overlay must be a mapping")
        states = _merge_overlay_states(states, overlay_data)
        reactions.extend(
            _overlay_reactions(overlay_data, overlay_path.parent if overlay_path else None)
        )
        datasets = _overlay_datasets(overlay_data, overlay_path.parent if overlay_path else None)

        paths = [path for path in known if path.is_file()]
        paths += [asset for path in known for asset in _snapshot_assets(path)]
        if root is not None and root.is_dir():
            paths += sorted(path for path in root.rglob("*") if path.is_file())
        if overlay_path is not None and overlay_path.is_file():
            paths.append(overlay_path)
        paths += [
            dataset.asset.local_path
            for group in datasets.values()
            for dataset in group
            if dataset.asset is not None and dataset.asset.local_path is not None
        ]
        materials = frozenset(registry.materials) if registry else frozenset()
        return cls(
            tuple(_unique_states(states)),
            tuple(reactions),
            datasets,
            materials,
            _fingerprint(paths),
        )

    @classmethod
    def load_paths(cls, paths: tuple[Path, ...]) -> EvidenceCatalog:
        """Load explicit local Registry, snapshot and overlay inputs once.

        Source order never resolves competing evidence. Analysis remains
        read-only and performs no external acquisition or adoption.
        """
        catalogs = [_load_source(path) for path in sorted({Path(path).resolve() for path in paths})]
        datasets: dict[str, list[NumericDataset]] = {}
        for catalog in catalogs:
            for target, records in catalog.overlay_datasets.items():
                datasets.setdefault(target, []).extend(records)
        digest = hashlib.sha256(
            "".join(sorted(catalog.fingerprint for catalog in catalogs)).encode()
        ).hexdigest()
        state_records = [record for catalog in catalogs for record in catalog.state_records]
        return cls(
            tuple(_unique_states(state_records)),
            tuple(record for catalog in catalogs for record in catalog.reaction_records),
            {target: tuple(records) for target, records in datasets.items()},
            frozenset(material for catalog in catalogs for material in catalog.materials),
            digest,
        )

    def with_attested(
        self,
        mechanical: CandidateSet,
        surfaces: tuple[str, ...] = (),
    ) -> CandidateSet:
        union = CandidateSet(
            states=dict(mechanical.states),
            reactions=dict(mechanical.reactions),
            complete=mechanical.complete,
            stop_reason=mechanical.stop_reason,
            limits=dict(mechanical.limits),
            completion={"mechanical": mechanical.complete, "attested": True},
        )
        return _reachable_union(union, self._attested_candidates(surfaces))

    def _attested_candidates(
        self,
        surfaces: tuple[str, ...],
    ) -> list[tuple[ReactionCandidate, dict[str, StateCandidate]]]:
        found = []
        for record in self.reaction_records:
            if record.channel_scope != "product_resolved":
                continue
            surface = record.equation_key[1]
            if surface is not None and surface not in surfaces:
                continue
            reaction = reaction_record_candidate(record)
            found.append((reaction, {state.id: state for state in record.states}))
        return sorted(found, key=lambda item: item[0].id)

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
        equation_records = tuple(
            record
            for record in self._reaction_index.get(candidate.equation_key, ())
            if record.family is None or record.family == candidate.family
        )
        exact = tuple(
            record
            for record in equation_records
            if record.process == candidate.process
            and record.stabilization == candidate.stabilization
        )
        related = tuple(record for record in equation_records if record not in exact)
        return deepcopy(ReactionEvidence(exact, related, offered))

    def validate_targets(self, candidates: CandidateSet) -> None:
        """Resolve candidate references before checking numerical physical identities.

        API callers may name their candidates independently of canonical physical
        IDs. Unused evidence references remain available for other analyses.
        """
        bindings = [
            (dataset.id, dataset.reaction_target or "")
            for record in self._reaction_records
            for dataset in record.datasets
        ]
        for reference, datasets in self._overlay_datasets.items():
            target = candidates.reactions.get(reference)
            for dataset in datasets:
                resolved = dataset_for_reaction(dataset, target) if target is not None else dataset
                if resolved.reaction_target is not None:
                    bindings.append((resolved.id, resolved.reaction_target))
        validate_numerical_targets(bindings)


def dataset_for_reaction(dataset: NumericDataset, target: ReactionCandidate) -> NumericDataset:
    """Identify an offered quantity's channel, without interpreting or approving its source."""
    if not reaction_declaration_matches(dataset.declared_target, target):
        raise ValueError(f"dataset {dataset.id} declares a different physical reaction target")
    return bind_dataset_target(dataset, reaction_id(target.key))


def _load_source(path: Path) -> EvidenceCatalog:
    if path.is_dir():
        if not (path / "species").is_dir():
            raise ValueError(f"not a Registry directory: {path}")
        return EvidenceCatalog.load(path)
    if not path.is_file():
        raise FileNotFoundError(f"evidence path not found: {path}")
    document = yamlio.load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"evidence must be a mapping: {path}")
    if "records" in document:
        return EvidenceCatalog.load(None, known=(path,))
    if set(document) & {
        "properties",
        "thermo",
        "datasets",
        "states",
        "state_records",
        "reaction_records",
    }:
        return EvidenceCatalog.load(None, overlay=path)
    raise ValueError(f"unrecognized snapshot or overlay: {path}")


def _registry_states(registry: Registry | None) -> list[StateRecord]:
    if registry is None:
        return []
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
        )
        for record in registry.species.values()
    ]
    found.extend(item for species in registry.species.values() for item in species.records)
    return found


def _registry_reactions(registry: Registry | None) -> list[ReactionRecord]:
    if registry is None:
        return []
    found = []
    for reaction in (item for group in registry.channels.values() for item in group):
        candidate = registry_reaction_candidate(reaction, registry.species)
        states = _reaction_states(reaction, registry.species)
        if candidate is None or states is None:
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


def _load_snapshot(path: Path) -> tuple[list[StateRecord], list[ReactionRecord]]:
    document = validate_snapshot(yamlio.load(path.read_text(encoding="utf-8")))
    source_data = document.get("source") or {}
    if not isinstance(source_data, dict):
        raise ValueError("snapshot.source must be a mapping")
    default_kind = str(document.get("kind") or "rate_coefficient")
    states: list[StateRecord] = []
    reactions: list[ReactionRecord] = []
    for index, record in enumerate(document["records"]):
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
    )
    return replace(candidate, id=reaction_id(candidate.key))


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
    candidate = replace(
        candidate,
        origin="attested_only",
        introduced_by=("snapshot",),
    )
    return normalized_state_record(
        record, candidate, default_source, preserved_record_id=preserved_record_id
    )


def _merge_overlay_states(records: list[StateRecord], overlay: dict) -> list[StateRecord]:
    """Keep each source declaration intact; quantity selection handles alternatives."""
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


def _reachable_union(
    union: CandidateSet,
    attested: list[tuple[ReactionCandidate, dict[str, StateCandidate]]],
) -> CandidateSet:
    state_keys = union.state_by_key()
    reaction_keys = union.reaction_by_key()
    pending = attested
    while pending:
        carried = []
        changed = False
        for reaction, states in pending:
            if not {term.species for term in reaction.reactants}.issubset(union.states):
                carried.append((reaction, states))
                continue
            additions = {
                state.id: state
                for term in reaction.products
                if (state := states.get(term.species)) is not None and state.key not in state_keys
            }
            limit = None
            if len(union.states) + len(additions) > union.limits.get("max_species", 10000):
                limit = "max_species"
            elif reaction.key not in reaction_keys and len(union.reactions) >= union.limits.get(
                "max_reactions", 100000
            ):
                limit = "max_reactions"
            if limit:
                union.complete = False
                union.completion["attested"] = False
                union.stop_reason = f"{limit} during attested addition"
                return union
            for state in additions.values():
                union.states[state.id] = state
                state_keys[state.key] = state
                changed = True
            if reaction.key not in reaction_keys:
                union.reactions[reaction.id] = reaction
                reaction_keys[reaction.key] = reaction
                changed = True
        if not changed:
            break
        pending = carried
    return union


def _state_matches(candidate: StateCandidate, record: StateRecord, *, exact: bool) -> bool:
    found = record.candidate
    if found.composition != candidate.composition or found.charge != candidate.charge:
        return False
    if found.phase != candidate.phase and (
        exact or "unknown" not in {found.phase, candidate.phase}
    ):
        return False
    if exact and found.structure != candidate.structure:
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


def _snapshot_assets(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    document = yamlio.load(path.read_text(encoding="utf-8")) or {}
    found = []
    for record in document.get("records") or []:
        asset = record.get("asset")
        written = asset.get("path") if isinstance(asset, dict) else asset
        if not written:
            continue
        candidate = Path(str(written))
        if not candidate.is_absolute():
            candidate = (path.parent / candidate).resolve()
        if candidate.is_file():
            found.append(candidate)
    return found


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

    def encode(value: object) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)

    def numeric_content(records: tuple[NumericDataset, ...]) -> list[str]:
        return sorted(
            encode(scientific_dataset_content(dataset_payload(record))) for record in records
        )

    content = {
        "states": sorted(
            encode(
                {
                    "id": record.id,
                    "record_id": record.record_id,
                    "content": scientific_state_content(record),
                }
            )
            for record in states
        ),
        "reactions": sorted(
            encode(
                {
                    "content": scientific_reaction_content(record),
                    "datasets": numeric_content(record.datasets),
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
    return hashlib.sha256(encode(content).encode("utf-8")).hexdigest()


def _fingerprint(paths: list[Path]) -> str:
    """Content-only fingerprint: moving the same evidence does not change output."""

    contents = sorted(hashlib.sha256(path.read_bytes()).digest() for path in set(paths))
    digest = hashlib.sha256()
    for content in contents:
        digest.update(content)
    return digest.hexdigest()
