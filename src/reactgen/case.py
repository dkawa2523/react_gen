"""Validated physical inputs and explicit bounds on the candidate grammar."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from functools import cached_property
from math import isfinite
from pathlib import Path

from reactgen import yamlio
from reactgen.chemistry import formula, parse_equation, parse_state_id, reaction_family
from reactgen.model import (
    CONDITION_INPUT_FIELDS,
    ReactionCandidate,
    StateCandidate,
    Term,
    reaction_id,
)
from reactgen.naming import parse
from reactgen.selection import DataSelection
from reactgen.structure import StructureUnavailable, input_structure, structure_key

_MolecularStateBindings = Mapping[str, tuple[StateCandidate, ...]]


@dataclass(frozen=True)
class CollisionPair:
    """One explicit entrance pair and its nominal collision energy."""

    projectile_state: str
    target_state: str
    collision_energy_eV: float
    collision_energy_frame: str
    target_at_rest: bool | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name != "target_at_rest" and value is None:
                raise ValueError(f"{name} is required for a collision pair")
            object.__setattr__(self, name, _validated_condition(name, value))
        for written in self.key:
            state = parse_state_id(written)
            if state is None or state.phase != "gas":
                raise ValueError("a collision pair must identify two gas states")

    @property
    def key(self) -> tuple[str, str]:
        return min(self.projectile_state, self.target_state), max(
            self.projectile_state, self.target_state
        )


@dataclass(frozen=True)
class Conditions:
    gas_temperature_K: float | None = None
    electron_temperature_eV: float | None = None
    reduced_field_Td: float | None = None
    ion_energy_eV: float | None = None
    ion_temperature_K: float | None = None
    surface_temperature_K: float | None = None
    electron_energy_eV: float | None = None
    collision_energy_eV: float | None = None
    collision_energy_frame: str | None = None
    projectile_state: str | None = None
    target_state: str | None = None
    target_at_rest: bool | None = None
    collision_pairs: tuple[CollisionPair, ...] = ()

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name != "collision_pairs":
                object.__setattr__(
                    self, item.name, _validated_condition(item.name, getattr(self, item.name))
                )
        if not isinstance(self.collision_pairs, tuple) or any(
            not isinstance(pair, CollisionPair) for pair in self.collision_pairs
        ):
            raise ValueError("collision_pairs must contain validated collision pairs")
        if self.collision_pairs and any(
            getattr(self, item.name) is not None for item in fields(CollisionPair)
        ):
            raise ValueError(
                "collision_pairs and single collision energy/role fields cannot be combined"
            )
        if len({pair.key for pair in self.collision_pairs}) != len(self.collision_pairs):
            raise ValueError("specify one collision condition per pair of incoming states")
        object.__setattr__(
            self, "collision_pairs", tuple(sorted(self.collision_pairs, key=lambda pair: pair.key))
        )

    @cached_property
    def collision_pair_index(self) -> dict[tuple[str, str], tuple[int, CollisionPair]]:
        return {pair.key: (index, pair) for index, pair in enumerate(self.collision_pairs)}

    @classmethod
    def from_document(cls, document: object) -> Conditions:
        values = yamlio.mapping(document, "conditions", {item.name for item in fields(cls)}).copy()
        if "collision_pairs" in values:
            values["collision_pairs"] = _collision_pairs(values["collision_pairs"])
        for key in CONDITION_INPUT_FIELDS.values():
            value = values.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"conditions.{key} must be numeric")
            try:
                values[key] = float(value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(f"conditions.{key} must be a finite number") from error
        return cls(**values)

    def document(self) -> dict:
        result = {
            key: value
            for key, value in asdict(self).items()
            if key != "collision_pairs" and value is not None
        }
        if self.collision_pairs:
            result["collision_pairs"] = [
                {key: value for key, value in asdict(pair).items() if value is not None}
                for pair in self.collision_pairs
            ]
        return result

    def value_of(self, quantity: str) -> float | None:
        return getattr(self, CONDITION_INPUT_FIELDS.get(quantity, ""), None)

    @staticmethod
    def input_field(quantity: str) -> str | None:
        """Return the accepted input field for a supported physical quantity."""
        return CONDITION_INPUT_FIELDS.get(quantity)


@dataclass(frozen=True)
class Limits:
    max_depth: int = 12
    max_species: int = 300
    max_reactions: int = 10000
    max_charge_abs: int = 1
    max_leaving_atoms: int = 2
    max_atoms: int | None = None
    max_candidate_trials: int = 100000
    expand_unresolved_states: bool = True

    def __post_init__(self) -> None:
        if type(self.expand_unresolved_states) is not bool:
            raise ValueError("limits.expand_unresolved_states must be boolean")
        if any(
            type(value) is not int or value < 1
            for key, value in asdict(self).items()
            if key != "expand_unresolved_states" and (key != "max_atoms" or value is not None)
        ):
            raise ValueError("all generation limits must be positive integers")
        if self.max_charge_abs != 1:
            raise ValueError(
                "the mechanical grammar supports max_charge_abs=1 only; "
                "evidence may supply other charges"
            )

    def document(self) -> dict[str, int | bool]:
        result = asdict(self)
        if self.max_atoms is None:
            del result["max_atoms"]
        if self.expand_unresolved_states:
            del result["expand_unresolved_states"]
        return result


@dataclass(frozen=True)
class RequestedReaction:
    """One gas-phase hypothesis explicitly submitted for assessment."""

    equation: str
    process: str
    stabilization: str | None = None
    candidate: ReactionCandidate = field(init=False, repr=False)
    states: tuple[StateCandidate, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        parsed = parse_equation(self.equation) if isinstance(self.equation, str) else None
        if parsed is None or any(state.phase != "gas" for state in parsed[1]):
            raise ValueError("reaction equation must identify gas states and use ' -> '")
        if not isinstance(self.process, str) or not self.process.strip():
            raise ValueError("reaction process must be a nonempty name")
        stabilization = self.stabilization
        if stabilization is not None and (
            not isinstance(stabilization, str) or not stabilization.strip()
        ):
            raise ValueError("reaction stabilization must be a nonempty name")
        key, states = parsed
        reaction = ReactionCandidate(
            "",
            tuple(Term(*term) for term in key[2]),
            tuple(Term(*term) for term in key[3]),
            reaction_family(key),
            self.process,
            "requested",
            "input.reactions",
            0,
            third_body=key[0],
            stabilization=stabilization.strip() if stabilization else None,
        )
        object.__setattr__(self, "candidate", replace(reaction, id=reaction_id(reaction.key)))
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "equation", reaction.equation)
        object.__setattr__(self, "process", reaction.process)
        object.__setattr__(self, "stabilization", reaction.stabilization)

    def document(self) -> dict[str, str]:
        fields = {"equation": self.equation, "process": self.process}
        if self.stabilization is not None:
            fields["stabilization"] = self.stabilization
        return fields


@dataclass(frozen=True)
class Case:
    """An analysis request; name is display metadata, never a rule selector."""

    name: str
    gases: tuple[str, ...]
    conditions: Conditions = field(default_factory=Conditions)
    surfaces: tuple[str, ...] = ()
    limits: Limits = Limits()
    data_selection: DataSelection = field(default_factory=DataSelection)
    supplies: tuple[str, ...] = ()
    structures: dict[str, str] = field(default_factory=dict)
    reactions: tuple[RequestedReaction, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a nonempty string")
        if not isinstance(self.gases, tuple) or not self.gases:
            raise ValueError("gases must contain at least one neutral ground-state formula")
        normalized = []
        for gas in self.gases:
            if not isinstance(gas, str):
                raise ValueError("gases must contain neutral ground-state chemical-formula strings")
            named = parse(gas)
            if not named.composition or named.charge or named.excited:
                raise ValueError(f"unsupported input formula for a neutral ground-state gas: {gas}")
            normalized.append(formula(named.composition))
        object.__setattr__(self, "gases", tuple(sorted(set(normalized))))
        self._validate_supplies()
        self._validate_structures()
        if not isinstance(self.surfaces, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.surfaces
        ):
            raise ValueError("surfaces must be a list of nonempty identifiers")
        object.__setattr__(self, "surfaces", tuple(sorted(set(self.surfaces))))
        if not isinstance(self.conditions, Conditions) or not isinstance(self.limits, Limits):
            raise ValueError("conditions and limits must be validated input types")
        if self.limits.max_atoms is None:
            object.__setattr__(
                self,
                "limits",
                replace(self.limits, max_atoms=input_atom_limit((*self.gases, *self.supplies))),
            )
        if not isinstance(self.data_selection, DataSelection):
            raise ValueError("data_selection must be a validated DataSelection")
        self._validate_reactions()

    def _validate_reactions(self) -> None:
        if not isinstance(self.reactions, tuple) or any(
            not isinstance(item, RequestedReaction) for item in self.reactions
        ):
            raise ValueError("reactions must contain validated RequestedReaction inputs")
        by_id = {item.candidate.id: item for item in self.reactions}
        object.__setattr__(self, "reactions", tuple(by_id[key] for key in sorted(by_id)))

    def _validate_supplies(self) -> None:
        if not isinstance(self.supplies, tuple):
            raise ValueError("supplies must be a list of particle state identifiers")
        supplied = []
        for written in self.supplies:
            state = parse_state_id(written) if isinstance(written, str) else None
            if state is None or state.phase != "gas":
                raise ValueError("supplies must identify gas particle states")
            supplied.append(state.id)
        object.__setattr__(self, "supplies", tuple(sorted(set(supplied))))

    def _validate_structures(self) -> None:
        if not isinstance(self.structures, dict):
            raise ValueError("structures must map input states to SMILES")
        inputs = {f"{gas}@ground" for gas in self.gases} | set(self.supplies)
        normalized: dict[str, str] = {}
        for written, smiles in self.structures.items():
            state = parse_state_id(written) if isinstance(written, str) else None
            if state is None or not state.composition or state.id not in inputs:
                raise ValueError("structures keys must identify an input gas or supply")
            if not isinstance(smiles, str) or not smiles.strip():
                raise ValueError("structures values must be nonempty SMILES")
            if state.id in normalized and normalized[state.id] != smiles:
                raise ValueError("conflicting structures for one input state")
            normalized[state.id] = smiles
        object.__setattr__(self, "structures", dict(sorted(normalized.items())))

    def input_particles(
        self,
    ) -> tuple[tuple[StateCandidate, ...], list[dict], dict[str, dict[str, str]]]:
        """Bind explicit structures and retain the original spelling of mapped inputs."""
        inputs = {}
        for written in (*self.gases, *self.supplies):
            state = parse_state_id(written)
            if state is None:
                raise ValueError(f"invalid input particle: {written}")
            inputs[state.id] = state
        particles = {}
        gaps = []
        structure_bindings = {}
        for state in inputs.values():
            mapped = self.structures.get(state.id)
            bound, unavailable = input_structure(state, mapped)
            if mapped is not None:
                structure_bindings[state.id] = {"smiles": mapped, "state": bound.id}
            if unavailable:
                gaps.append({"target": bound.id, "operation": "graph_input", "reason": unavailable})
            particles[bound.id] = replace(
                bound, classes=bound.classes | {"feed"}, introduced_by=("input",), depth=0
            )
        return (
            tuple(particles[identifier] for identifier in sorted(particles)),
            gaps,
            structure_bindings,
        )

    def bound_conditions(
        self,
        particles: tuple[StateCandidate, ...],
        molecular_states: _MolecularStateBindings | None = None,
    ) -> Conditions:
        """Resolve participant roles against supplied and individually identified states."""
        conditions = self.conditions
        return replace(
            conditions,
            projectile_state=_bound_role(
                conditions.projectile_state,
                particles,
                "conditions.projectile_state",
                molecular_states,
            ),
            target_state=_bound_role(
                conditions.target_state, particles, "conditions.target_state", molecular_states
            ),
            collision_pairs=tuple(
                _bound_collision_pair(pair, particles, index, molecular_states)
                for index, pair in enumerate(conditions.collision_pairs)
            ),
        )

    def bound_reactions(
        self,
        particles: tuple[StateCandidate, ...],
        molecular_states: _MolecularStateBindings | None = None,
    ) -> tuple[RequestedReaction, ...]:
        """Bind feed aliases and independently identified levels to equation participants."""
        bound = []
        for item in self.reactions:
            identifiers = {
                state.id: _bound_participant(
                    state, particles, f"reactions participant {state.id}", molecular_states
                )
                for state in item.states
            }
            if any(original != resolved for original, resolved in identifiers.items()):
                reaction = replace(
                    item.candidate,
                    reactants=tuple(
                        Term(identifiers[term.species], term.n) for term in item.candidate.reactants
                    ),
                    products=tuple(
                        Term(identifiers[term.species], term.n) for term in item.candidate.products
                    ),
                )
                item = replace(item, equation=reaction.equation)
            bound.append(item)
        return tuple(bound)

    @classmethod
    def load(cls, path: str | Path) -> Case:
        return cls.from_document(yamlio.load(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_document(cls, document: object) -> Case:
        data = yamlio.mapping(document, "input", {item.name for item in fields(cls)})
        gases = data.get("gases")
        if not isinstance(gases, list):
            raise ValueError("gases must be a list of neutral ground-state formulas")
        surfaces = data.get("surfaces", [])
        if not isinstance(surfaces, list):
            raise ValueError("surfaces must be a list of identifiers")
        supplies = data.get("supplies", [])
        if not isinstance(supplies, list):
            raise ValueError("supplies must be a list")
        limits = yamlio.mapping(
            data.get("limits", {}), "limits", {item.name for item in fields(Limits)}
        )
        reactions = data.get("reactions", [])
        if not isinstance(reactions, list):
            raise ValueError("reactions must be a list of equation and process mappings")
        return cls(
            data.get("name", "analysis"),
            tuple(gases),
            Conditions.from_document(data.get("conditions", {})),
            tuple(surfaces),
            Limits(**limits),
            DataSelection.from_document(data.get("data_selection", {})),
            tuple(supplies),
            data.get("structures", {}),
            tuple(_requested_reaction(record, index) for index, record in enumerate(reactions, 1)),
        )

    def document(self) -> dict:
        document = asdict(self)
        document["gases"] = list(self.gases)
        document["surfaces"] = list(self.surfaces)
        document["supplies"] = list(self.supplies)
        document["conditions"] = self.conditions.document()
        document["limits"] = self.limits.document()
        if self.data_selection.quantities or self.data_selection.targets:
            document["data_selection"] = self.data_selection.document()
        else:
            del document["data_selection"]
        if self.reactions:
            document["reactions"] = [item.document() for item in self.reactions]
        else:
            del document["reactions"]
        return document


def _requested_reaction(record: object, index: int) -> RequestedReaction:
    subject = f"reactions[{index}]"
    fields = yamlio.mapping(record, subject, {"equation", "process", "stabilization"})
    if "equation" not in fields or "process" not in fields:
        raise ValueError(f"{subject}: equation and process are required")
    try:
        return RequestedReaction(fields["equation"], fields["process"], fields.get("stabilization"))
    except ValueError as error:
        raise ValueError(f"{subject}: {error}") from error


def _collision_pairs(value: object) -> tuple[CollisionPair, ...]:
    if not isinstance(value, list):
        raise ValueError("conditions.collision_pairs must be a list of collision pairs")
    allowed = {item.name for item in fields(CollisionPair)}
    pairs = []
    for index, entry in enumerate(value):
        subject = f"conditions.collision_pairs[{index}]"
        data = yamlio.mapping(entry, subject, allowed)
        missing = allowed - data.keys() - {"target_at_rest"}
        if missing:
            raise ValueError(f"{subject} requires {', '.join(sorted(missing))}")
        try:
            pairs.append(CollisionPair(**data))
        except ValueError as error:
            raise ValueError(f"{subject}: {error}") from error
    return tuple(pairs)


def _bound_collision_pair(
    pair: CollisionPair,
    particles: tuple[StateCandidate, ...],
    index: int,
    molecular_states: _MolecularStateBindings | None,
) -> CollisionPair:
    subject = f"conditions.collision_pairs[{index}]"
    return replace(
        pair,
        projectile_state=_bound_role(
            pair.projectile_state, particles, f"{subject}.projectile_state", molecular_states
        )
        or pair.projectile_state,
        target_state=_bound_role(
            pair.target_state, particles, f"{subject}.target_state", molecular_states
        )
        or pair.target_state,
    )


def _bound_role(
    identifier: str | None,
    particles: tuple[StateCandidate, ...],
    subject: str,
    molecular_states: _MolecularStateBindings | None,
) -> str | None:
    if identifier is not None and (state := parse_state_id(identifier)) is not None:
        return _bound_participant(state, particles, subject, molecular_states)
    return identifier


def _bound_participant(
    requested: StateCandidate,
    particles: tuple[StateCandidate, ...],
    subject: str,
    molecular_states: _MolecularStateBindings | None,
) -> str:
    if any(item.id == requested.id for item in particles):
        return requested.id
    comparable = [item for item in particles if item.key[:-1] == requested.key[:-1]]
    if requested.structure is not None and comparable:
        graph = _optional_graph_key(requested)
        comparable = [
            item for item in comparable if graph is not None and _optional_graph_key(item) == graph
        ]
    if not comparable and molecular_states is not None:
        comparable = list(molecular_states.get(requested.id, ()))
    if len(comparable) > 1:
        raise ValueError(
            f"{subject} is ambiguous; choose one of {', '.join(item.id for item in comparable)}"
        )
    return comparable[0].id if comparable else requested.id


def _optional_graph_key(state: StateCandidate) -> str | None:
    try:
        return structure_key(state)
    except StructureUnavailable:
        return None


def _validated_condition(name: str, value: object) -> object:
    if value is None:
        return None
    if name == "collision_energy_frame":
        if not isinstance(value, str) or value not in {"com", "lab"}:
            raise ValueError("collision_energy_frame must be com or lab")
        return value
    if name in {"projectile_state", "target_state"}:
        state = parse_state_id(value) if isinstance(value, str) else None
        if state is None:
            raise ValueError(f"conditions.{name} must identify a particle state")
        return state.id
    if name == "target_at_rest":
        if type(value) is not bool:
            raise ValueError("target_at_rest must be boolean")
        return value
    return _validated_number(name, value)


def _validated_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"conditions.{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"conditions.{name} must be a finite number") from error
    if not isfinite(number):
        raise ValueError(f"conditions.{name} must be a finite number")
    if number < 0 or (
        (name.endswith("temperature_K") or name.endswith("temperature_eV")) and number == 0
    ):
        raise ValueError(f"conditions.{name} is outside its physical domain")
    return number


def input_atom_limit(particles: tuple[str, ...]) -> int:
    """Default resource envelope holds any first two-input association."""
    counts = [
        sum(state.composition.values())
        for written in particles
        if isinstance(written, str) and (state := parse_state_id(written)) is not None
    ]
    return 2 * max(counts, default=1)
