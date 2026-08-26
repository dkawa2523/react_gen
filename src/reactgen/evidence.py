"""Normalize and index read-only evidence for generated candidates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from reactgen import naming
from reactgen.chemistry import candidate_state, parse_state_id
from reactgen.model import (
    ELECTRON,
    CandidateSet,
    EquationKey,
    ReactionCandidate,
    StateCandidate,
    Term,
    canonical_family,
    canonical_process,
    reaction_id,
)
from reactgen.records import (
    TIER_RANK,
    NumericDataset,
    Property,
    ReactionRecord,
    RegistryReaction,
    Species,
    StateRecord,
    Thermo,
    evidence_tier,
    normalized_dataset,
    normalized_property,
)
from reactgen.registry import Registry

StateIdentityKey = tuple[tuple[tuple[str, int], ...], int]


@dataclass(frozen=True)
class StateEvidence:
    match: str  # exact | compatible | ambiguous | none
    records: tuple[StateRecord, ...]

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
        return any(record.reviewed for record in self.exact_records)


@dataclass
class EvidenceCatalog:
    """One immutable evidence view with indexes built once at load time."""

    state_records: tuple[StateRecord, ...] = ()
    reaction_records: tuple[ReactionRecord, ...] = ()
    overlay_datasets: dict[str, tuple[NumericDataset, ...]] = field(default_factory=dict)
    materials: frozenset[str] = frozenset()
    fingerprint: str = field(default_factory=lambda: hashlib.sha256(b"").hexdigest())
    _state_index: dict[StateIdentityKey, tuple[StateRecord, ...]] = field(init=False, repr=False)
    _reaction_index: dict[EquationKey, tuple[ReactionRecord, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        states: dict[StateIdentityKey, list[StateRecord]] = {}
        for state_record in self.state_records:
            states.setdefault(_state_identity(state_record.candidate), []).append(state_record)
        reactions: dict[EquationKey, list[ReactionRecord]] = {}
        for reaction_record in self.reaction_records:
            reactions.setdefault(reaction_record.equation_key, []).append(reaction_record)
        self._state_index = {
            key: tuple(sorted(records, key=_state_preference)) for key, records in states.items()
        }
        self._reaction_index = {
            key: tuple(sorted(records, key=lambda item: (item.label, item.id)))
            for key, records in reactions.items()
        }

    @classmethod
    def load(
        cls,
        registry_path: str | Path | None,
        overlay: str | Path | None = None,
        known: tuple[Path, ...] = (),
    ) -> EvidenceCatalog:
        root = Path(registry_path) if registry_path is not None else None
        registry = Registry.load(root) if root is not None and root.is_dir() else None
        states = _registry_states(registry)
        reactions = _registry_reactions(registry)
        for path in known:
            snapshot_states, snapshot_reactions = _load_snapshot(path)
            states.extend(snapshot_states)
            reactions.extend(snapshot_reactions)

        overlay_path = Path(overlay) if overlay is not None else None
        overlay_data = (
            yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
            if overlay_path is not None and overlay_path.is_file()
            else {}
        )
        states = _merge_overlay_states(states, overlay_data)
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
        )
        return _reachable_union(union, self._attested_candidates(surfaces))

    def _attested_candidates(
        self,
        surfaces: tuple[str, ...],
    ) -> list[tuple[ReactionCandidate, dict[str, StateCandidate]]]:
        found = []
        for record in self.reaction_records:
            surface = record.equation_key[1]
            if surface is not None and surface not in surfaces:
                continue
            family = record.family or _family_of_terms(record.states, record.equation_key)
            reactants, products = record.equation_key[2], record.equation_key[3]
            reaction = ReactionCandidate(
                id="",
                reactants=tuple(Term(name, count) for name, count in reactants),
                products=tuple(Term(name, count) for name, count in products),
                family=family,
                process=record.process,
                origin="attested_only",
                generation_rule=f"{record.origin}:{record.id}",
                depth=0,
                third_body=record.equation_key[0],
                surface=surface,
            )
            reaction = replace(reaction, id=reaction_id(reaction.key))
            found.append((reaction, {state.id: state for state in record.states}))
        return found

    def state(self, candidate: StateCandidate) -> StateEvidence:
        records = self._state_index.get(_state_identity(candidate), ())
        exact = tuple(record for record in records if _state_matches(candidate, record, exact=True))
        if _state_records_conflict(exact):
            return StateEvidence("ambiguous", exact)
        if exact:
            return StateEvidence("exact", exact)
        compatible = tuple(
            record for record in records if _state_matches(candidate, record, exact=False)
        )
        return StateEvidence("compatible", compatible) if compatible else StateEvidence("none", ())

    def reaction(self, candidate: ReactionCandidate) -> ReactionEvidence:
        equation_records = tuple(
            record
            for record in self._reaction_index.get(candidate.equation_key, ())
            if record.family is None or record.family == candidate.family
        )
        exact = tuple(record for record in equation_records if record.process == candidate.process)
        related = tuple(
            record for record in equation_records if record.process != candidate.process
        )
        return ReactionEvidence(exact, related, self.overlay_datasets.get(candidate.id, ()))


def registry_state_candidate(record: Species) -> StateCandidate:
    if record.id == ELECTRON:
        from reactgen.chemistry import electron_state

        return replace(electron_state(), origin="attested_only", introduced_by=("registry",))
    kind, resolution, label = _registry_state(record)
    return candidate_state(
        record.composition,
        record.charge,
        kind,
        label=label,
        resolution=resolution,
        classes=record.classes,
        origin="attested_only",
        introduced_by=(f"registry:{record.id}",),
    )


def registry_reaction_candidate(
    record: RegistryReaction,
    species: dict[str, Species],
) -> ReactionCandidate | None:
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
    )
    return replace(candidate, id=reaction_id(candidate.key))


def parse_equation(text: str) -> tuple[EquationKey, tuple[StateCandidate, ...]] | None:
    left, separator, right = text.partition("->")
    if not separator:
        return None
    reactants = _parse_side(left)
    products = _parse_side(right)
    if reactants is None or products is None:
        return None
    left_terms, left_states, left_third = reactants
    right_terms, right_states, right_third = products
    if left_third != right_third:
        return None
    third_body = "M" if left_third or right_third else None
    return (
        (third_body, None, left_terms, right_terms),
        tuple({state.id: state for state in (*left_states, *right_states)}.values()),
    )


def _registry_states(registry: Registry | None) -> list[StateRecord]:
    if registry is None:
        return []
    return [
        StateRecord(
            id=record.id,
            candidate=registry_state_candidate(record),
            properties=dict(record.properties),
            thermo=record.thermo,
            energy_eV=record.state.energy_eV,
            existence=(
                record.state.existence if record.state.existence != "unknown" else "confirmed"
            ),
            configuration=record.state.configuration,
            term=record.state.term,
            j=record.state.j,
            parity=record.state.parity,
            degeneracy=record.state.degeneracy,
            lifetime_s=record.state.lifetime_s,
            status=record.status,
            # Registry membership attests identity independently of whether an
            # individual transport property in the record is estimated.
            tier="reviewed",
            source={"source_id": f"registry:{record.id}"},
            origin="registry",
        )
        for record in registry.species.values()
    ]


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
                threshold_eV=reaction.threshold_eV,
                delta_e_eV=reaction.delta_e_eV,
                status=reaction.status,
                tier=evidence_tier(reaction.status, source),
                source=source,
                origin="registry",
            )
        )
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
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    source_data = {str(key): str(value) for key, value in (document.get("source") or {}).items()}
    default_kind = str(document.get("kind") or "rate_coefficient")
    states: list[StateRecord] = []
    reactions: list[ReactionRecord] = []
    for index, record in enumerate(document.get("records") or []):
        written = record.get("reaction")
        if not written:
            continue
        parsed = parse_equation(str(written))
        if parsed is None:
            continue
        equation_key, candidates = parsed
        status = str(record.get("status") or "imported")
        source = source_data | {
            str(key): str(value) for key, value in (record.get("source") or {}).items()
        }
        dataset = normalized_dataset(
            record,
            base=path.parent,
            default_id=f"{path.stem}:{index}",
            default_kind=default_kind,
            default_source=source,
        )
        family = record.get("family")
        reactions.append(
            ReactionRecord(
                id=str(record.get("id") or f"{path.stem}:{index}"),
                equation_key=equation_key,
                family=canonical_family(str(family)) if family is not None else None,
                process=canonical_process(
                    str(record.get("type") or "attested"),
                    family=str(family or ""),
                    third_body=equation_key[0],
                    surface=equation_key[1],
                ),
                states=candidates,
                datasets=(dataset,),
                threshold_eV=_optional_float(record.get("threshold_eV")),
                delta_e_eV=_optional_float(record.get("deltaE_products_minus_reactants_eV")),
                channel_scope=dataset.channel_scope,
                status=status,
                tier=evidence_tier(status, source),
                source=source,
                origin="snapshot",
            )
        )
        states.extend(
            StateRecord(
                id=state.id,
                candidate=replace(
                    state,
                    origin="attested_only",
                    introduced_by=(f"snapshot:{path.stem}",),
                ),
                status=status,
                tier=evidence_tier(status, source),
                existence=(
                    "confirmed"
                    if evidence_tier(status, source) in {"curated", "reviewed"}
                    else "unknown"
                ),
                source=source,
                origin="snapshot",
            )
            for state in candidates
        )
    return states, reactions


def _merge_overlay_states(records: list[StateRecord], overlay: dict) -> list[StateRecord]:
    properties = overlay.get("properties") or {}
    thermos = overlay.get("thermo") or {}
    for state_id in sorted(set(properties) | set(thermos)):
        candidate = parse_state_id(str(state_id))
        if candidate is None:
            continue
        props = _properties(properties.get(state_id) or {})
        thermo = _thermo(thermos.get(state_id))
        matches = [
            index
            for index, record in enumerate(records)
            if _state_matches(candidate, record, exact=True) and record.origin == "registry"
        ]
        if len(matches) == 1:
            index = matches[0]
            current = records[index]
            records[index] = replace(
                current,
                properties=props | current.properties,
                thermo=current.thermo or thermo,
            )
            continue
        identity_reviewed = any(
            prop.tier in {"curated", "reviewed"} for prop in props.values()
        ) or (thermo is not None and thermo.tier in {"curated", "reviewed"})
        records.append(
            StateRecord(
                id=str(state_id),
                candidate=replace(
                    candidate,
                    origin="attested_only",
                    introduced_by=("overlay",),
                ),
                properties=props,
                thermo=thermo,
                existence="confirmed" if identity_reviewed else "unknown",
                status="reviewed" if identity_reviewed else "imported",
                tier="reviewed" if identity_reviewed else "imported",
                source={"source_id": "overlay"},
                origin="overlay",
            )
        )
    return records


def _overlay_datasets(
    overlay: dict,
    base: Path | None,
) -> dict[str, tuple[NumericDataset, ...]]:
    return {
        str(reaction_id_): tuple(
            normalized_dataset(
                item,
                base=base,
                default_id=f"{reaction_id_}:overlay",
                default_source={"source_id": "reviewed overlay"},
            )
            for item in items
        )
        for reaction_id_, items in (overlay.get("datasets") or {}).items()
    }


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
            for term in reaction.products:
                state = states.get(term.species)
                if state is not None and state.key not in state_keys:
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


def _registry_state(record: Species) -> tuple[str, str, str]:
    if record.state.kind == "ground":
        return ("ground", "resolved", "")
    label = naming.normalize_state(record.state.label) or ""
    if record.state.label == "vibrational" or "vibrational" in record.classes:
        return ("vibrational", record.state.resolution, "")
    if record.state.resolution == "lumped":
        if "metastable" in record.classes:
            return ("metastable", "lumped", "")
        if "resonant" in record.classes:
            return ("resonant", "lumped", "")
        return ("electronic", "lumped", label)
    return ("resolved", "resolved", label)


def _state_matches(candidate: StateCandidate, record: StateRecord, *, exact: bool) -> bool:
    found = record.candidate
    if found.composition != candidate.composition or found.charge != candidate.charge:
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


def _state_preference(record: StateRecord) -> tuple[int, str, str]:
    return (TIER_RANK.get(record.tier, 5), record.origin, record.id)


def _state_records_conflict(records: tuple[StateRecord, ...]) -> bool:
    if not records:
        return False
    best = min(TIER_RANK.get(record.tier, 5) for record in records)
    compared = tuple(record for record in records if TIER_RANK.get(record.tier, 5) == best)
    if any(record.status == "conflicting" for record in compared):
        return True
    existence = {
        record.existence
        for record in compared
        if record.existence not in {"unknown", "hypothetical"}
    }
    return len(existence) > 1


def _state_identity(candidate: StateCandidate) -> StateIdentityKey:
    return (tuple(sorted(candidate.composition.items())), candidate.charge)


def _family_of_terms(states: tuple[StateCandidate, ...], equation: EquationKey) -> str:
    reactant_ids = {name for name, _count in equation[2]}
    reactants = [state for state in states if state.id in reactant_ids]
    if any(state.id == ELECTRON for state in reactants):
        return "electron"
    if any(state.charge for state in reactants):
        return "ion"
    return "neutral"


def _parse_side(
    text: str,
) -> tuple[tuple[tuple[str, float], ...], tuple[StateCandidate, ...], bool] | None:
    counts: dict[str, float] = {}
    states: dict[str, StateCandidate] = {}
    third_body = False
    for piece in re.split(r"\s+\+\s+", text.strip()):
        token = piece.strip()
        if not token:
            continue
        count_text, separator, name = token.rpartition(" ")
        count = float(count_text) if separator and _is_number(count_text) else 1.0
        written = name if separator and _is_number(count_text) else token
        if written == "M":
            third_body = True
            continue
        state = parse_state_id(written)
        if state is None:
            return None
        counts[state.id] = counts.get(state.id, 0.0) + count
        states[state.id] = state
    return (tuple(sorted(counts.items())), tuple(states.values()), third_body)


def _properties(data: dict) -> dict[str, Property]:
    return {
        str(name): normalized_property(entry)
        for name, entry in data.items()
        if isinstance(entry, dict)
    }


def _thermo(data: object) -> Thermo | None:
    if not isinstance(data, dict):
        return None
    if len(data.get("low") or ()) != 7 or len(data.get("high") or ()) != 7:
        return None
    return Thermo(
        low=tuple(float(value) for value in data["low"]),
        high=tuple(float(value) for value in data["high"]),
        t_min=float(data.get("t_min", 200.0)),
        t_mid=float(data.get("t_mid", 1000.0)),
        t_max=float(data.get("t_max", 6000.0)),
        source=data.get("source"),
        tier=evidence_tier(str(data.get("status") or data.get("evidence_tier") or "imported")),
    )


def _unique_states(records: list[StateRecord]) -> list[StateRecord]:
    found: dict[tuple, StateRecord] = {}
    for record in records:
        key = (record.candidate.key, record.origin, record.id, record.label)
        found.setdefault(key, record)
    return list(found.values())


def _snapshot_assets(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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


def _fingerprint(paths: list[Path]) -> str:
    """Content-only fingerprint: moving the same evidence does not change output."""

    contents = sorted(hashlib.sha256(path.read_bytes()).digest() for path in set(paths))
    digest = hashlib.sha256()
    for content in contents:
        digest.update(content)
    return digest.hexdigest()


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _optional_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
