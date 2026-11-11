"""Registry-independent candidate types and canonical keys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
from math import isfinite
from typing import NamedTuple

ELECTRON = "e"
THIRD_BODY = "M"
VERIFIED_STRUCTURE_BASIS = "verified_explicit_smiles"

# One source record supplies the complete state difference in either direction.
DIRECT_STATE_RELATION = "direct_state_relation"
REVERSED_STATE_RELATION = "reversed_state_relation"
EXACT_STATE_RELATION_OPERATIONS = (DIRECT_STATE_RELATION, REVERSED_STATE_RELATION)

# The same physical-quantity vocabulary is used by evaluation and user-facing
# prerequisite labels. Values name actual fields of the validated Conditions.
CONDITION_INPUT_FIELDS = {
    "gas_temperature": "gas_temperature_K",
    "electron_temperature": "electron_temperature_eV",
    "reduced_field": "reduced_field_Td",
    "ion_energy": "ion_energy_eV",
    "ion_temperature": "ion_temperature_K",
    "surface_temperature": "surface_temperature_K",
    "electron_energy": "electron_energy_eV",
    "collision_energy": "collision_energy_eV",
}

FAMILY_ALIASES = {
    "electron_ion": "electron",
    "ion_neutral": "ion",
    "ion_ion": "ion",
    "neutral_neutral": "neutral",
    "three_body": "neutral",
    "unimolecular": "neutral",
}

PROCESS_ALIASES = {
    "charge_transfer": "charge_exchange",
    "electron_detachment": "collisional_detachment",
    "neutralization": "mutual_neutralization",
    "three_body_recombination": "three_body_association",
}


def canonical_family(family: str) -> str:
    written = _channel_name(family)
    return FAMILY_ALIASES.get(written, written)


def canonical_process(
    process: str,
    *,
    family: str = "",
    third_body: str | None = None,
    surface: str | None = None,
) -> str:
    """Resolve source vocabulary before reaction identity is built."""

    raw_family = _channel_name(family)
    written = PROCESS_ALIASES.get(_channel_name(process), _channel_name(process))
    if (surface is not None or raw_family == "surface") and written in {
        "association",
        "recombination",
    }:
        return "surface_recombination"
    if (third_body is not None or raw_family == "three_body") and written in {
        "association",
        "recombination",
        "three_body_association",
    }:
        return "three_body_association"
    return written


def _channel_name(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class Term(NamedTuple):
    """One species with its stoichiometric count.

    The count is a float so surface channels can express a branching fraction
    such as ``F -> 0.5 F2``.
    """

    species: str
    n: float = 1.0

    def __str__(self) -> str:
        if self.n == 1:
            return self.species
        count = int(self.n) if self.n == int(self.n) else self.n
        return f"{count} {self.species}"


def validate_stoichiometric_terms(terms: Iterable[tuple[str, float]]) -> None:
    """Validate each source term before duplicate species can be combined.

    Scientific records require positive finite counts, including fractional
    counts. Candidate equations may still represent invalid hypotheses for
    assessment, so neither ``Term`` nor ``side_key`` enforces this boundary.
    """
    totals: dict[str, float] = {}
    for species, count in terms:
        if not isinstance(species, str) or not species.strip():
            raise ValueError("stoichiometric species must be nonempty text")
        finite = False
        if not isinstance(count, bool) and isinstance(count, int | float):
            try:
                finite = isfinite(count)
            except OverflowError:
                finite = False
        if not finite or count <= 0:
            raise ValueError(
                f"stoichiometric coefficient for {species!r} must be a finite positive number"
            )
        total = totals.get(species, 0.0) + count
        if not isfinite(total):
            raise ValueError(f"summed stoichiometric coefficient for {species!r} must be finite")
        totals[species] = total


def stoichiometric_sum(values: Iterable[float]) -> float:
    """Sum counts without treating small physical contributions as zero.

    Arithmetic uses the decimal representation retained by serialization,
    before one final conversion to float. Thus declared 0.1 + 0.2 cancels 0.3,
    while a separately declared tiny term survives beside a cancelled pair.
    This is canonical coefficient arithmetic, not measurement uncertainty.
    """
    terms = tuple(values)
    if any(not isfinite(value) for value in terms):
        # Invalid hypotheses remain representable for the consistency
        # assessment. Scientific-record boundaries reject these originals.
        return sum(terms)
    if all(abs(value) <= 2**53 and float(value).is_integer() for value in terms):
        return float(sum(int(value) for value in terms))
    return float(sum((Fraction(str(value)) for value in terms), start=Fraction()))


def stoichiometric_product(value: float, count: int) -> float:
    """Multiply a declared coefficient by an exact atom count or integer charge."""
    if not isfinite(value):
        return value * count
    if abs(value) <= 2**53 and float(value).is_integer():
        return float(int(value) * count)
    return float(Fraction(str(value)) * count)


StateKey = tuple[tuple[tuple[str, int], ...], int, str, str, str, str, str | None]
# A reaction channel is not identified by stoichiometry alone.  Elastic
# scattering and charge exchange can have the same equation while requiring
# different evidence and numerical data.
ReactionKey = tuple[str, str, str | None, str | None, str | None, tuple, tuple]
EquationKey = tuple[str | None, str | None, tuple, tuple]


def state_excitation(kind: str, label: str = "") -> str:
    """Return the physical excitation axis without resolution or lifetime semantics."""

    if kind == "vibrational" or (kind == "resolved" and label.startswith("v")):
        return "vibrational"
    if kind in {"electronic", "metastable", "resonant", "resolved"}:
        return "electronic"
    return kind


def state_lifetime_class(kind: str, classes: frozenset[str] | set[str]) -> str:
    """Return the radiative/lifetime role independently of excitation and resolution."""

    if "mixed_lifetime" in classes:
        return "mixed_metastable_resonant"
    if kind == "metastable" or "metastable" in classes:
        return "metastable"
    if kind == "resonant" or "resonant" in classes:
        return "resonant_radiative"
    if state_excitation(kind) == "electronic" and kind != "ground":
        return "unspecified"
    return "not_applicable"


def canonical_state_label(kind: str, label: str = "") -> str:
    """Return a stable machine label; display symbols are a separate concern."""

    return label or kind


@dataclass(frozen=True)
class CandidateState:
    kind: str
    resolution: str = "lumped"
    label: str = ""

    @property
    def manifold(self) -> str:
        return state_excitation(self.kind, self.label)


@dataclass(frozen=True)
class StateCandidate:
    id: str
    composition: dict[str, int]
    charge: int
    state: CandidateState
    classes: frozenset[str] = frozenset()
    origin: str = "mechanical"
    depth: int = 0
    introduced_by: tuple[str, ...] = ()
    phase: str = "gas"
    structure: str | None = None

    @property
    def key(self) -> StateKey:
        return (
            tuple(sorted(self.composition.items())),
            self.charge,
            self.state.kind,
            self.state.label,
            self.state.resolution,
            self.phase,
            self.structure,
        )


def binary_collision_partners(terms: tuple[Term, ...]) -> tuple[str, str] | None:
    """The canonical pair for one integer two-particle entrance channel."""
    side = side_key(terms)
    if len(side) == 1 and side[0][1] == 2:
        return side[0][0], side[0][0]
    if len(side) == 2 and side[0][1] == side[1][1] == 1:
        return side[0][0], side[1][0]
    return None


def side_key(terms: tuple[Term, ...] | list[Term]) -> tuple[tuple[str, float], ...]:
    totals: dict[str, list[float]] = {}
    for term in terms:
        totals.setdefault(term.species, []).append(term.n)
    return tuple(
        (name, count)
        for name, values in sorted(totals.items())
        if (count := stoichiometric_sum(values)) != 0
    )


@dataclass(frozen=True)
class ReactionCandidate:
    id: str
    reactants: tuple[Term, ...]
    products: tuple[Term, ...]
    family: str
    process: str
    origin: str
    generation_rule: str
    depth: int
    third_body: str | None = None
    surface: str | None = None
    stabilization: str | None = None
    transformation: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_family = self.family
        object.__setattr__(self, "family", canonical_family(raw_family))
        object.__setattr__(
            self,
            "process",
            canonical_process(
                self.process,
                family=raw_family,
                third_body=self.third_body,
                surface=self.surface,
            ),
        )
        if self.process in {"attachment", "recombination"} and self.stabilization is None:
            object.__setattr__(self, "stabilization", "unspecified")

    @property
    def key(self) -> ReactionKey:
        return (
            self.family,
            self.process,
            self.third_body,
            self.surface,
            self.stabilization,
            side_key(self.reactants),
            side_key(self.products),
        )

    @property
    def equation_key(self) -> EquationKey:
        return (
            self.third_body,
            self.surface,
            side_key(self.reactants),
            side_key(self.products),
        )

    @property
    def equation(self) -> str:
        left = [str(term) for term in self.reactants]
        right = [str(term) for term in self.products]
        if self.third_body:
            left.append(THIRD_BODY)
            right.append(THIRD_BODY)
        if self.surface:
            left.append(f"[{self.surface}]")
        return f"{' + '.join(left)} -> {' + '.join(right)}"


def reaction_id(key: ReactionKey) -> str:
    encoded = json.dumps(key, separators=(",", ":"), ensure_ascii=True)
    return "rxn_" + hashlib.sha256(encoded.encode()).hexdigest()[:12]


def bind_transformation_states(declaration: dict, states: dict[str, str]) -> dict:
    """Map transformation participant references, retaining atom maps and raw declarations.

    Only fields that name physical states are translated. Bond actions, SMILES,
    group inventories and other scientific content are not interpreted here.
    """
    mapped = deepcopy(declaration)
    for key in (
        "parent",
        "collider",
        "collider_product",
        "initial",
        "final",
        "target",
        "donor",
        "acceptor",
        "donor_product",
        "acceptor_product",
        "product",
    ):
        value = mapped.get(key)
        if isinstance(value, str):
            mapped[key] = states.get(value, value)
    for key in ("partners", "partner_products", "fragments", "initial", "final", "reactants"):
        values = mapped.get(key)
        if isinstance(values, list):
            mapped[key] = [
                states.get(value, value) if isinstance(value, str) else value for value in values
            ]
    for key in ("reactant_graphs", "products"):
        entries = mapped.get(key)
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("state"), str):
                    entry["state"] = states.get(entry["state"], entry["state"])
    alternatives = mapped.get("alternatives")
    if isinstance(alternatives, list):
        mapped["alternatives"] = [
            bind_transformation_states(item, states) if isinstance(item, dict) else item
            for item in alternatives
        ]
    return mapped


def combine_transformations(declarations: Iterable[dict]) -> dict:
    """Retain distinct alternative role maps for the same physical equation."""
    alternatives: list[dict] = []
    for declared in declarations:
        if not declared:
            continue
        items = declared.get("alternatives") if declared.get("kind") == "alternatives" else None
        if isinstance(items, list) and items and all(isinstance(item, dict) for item in items):
            alternatives.extend(item for item in items if item not in alternatives)
        elif declared not in alternatives:
            alternatives.append(declared)
    if not alternatives:
        return {}
    if len(alternatives) == 1:
        return alternatives[0]
    return {"kind": "alternatives", "alternatives": alternatives}


@dataclass
class CandidateSet:
    states: dict[str, StateCandidate] = field(default_factory=dict)
    reactions: dict[str, ReactionCandidate] = field(default_factory=dict)
    complete: bool = True
    stop_reason: str = "closure"
    limits: dict[str, int | bool] = field(default_factory=dict)
    completion: dict[str, bool] = field(default_factory=dict)
    trials: int = 0
    generation_gaps: list[dict] = field(default_factory=list)
    unexpanded: list[dict] = field(default_factory=list)

    def nongas_participants(self, reaction: ReactionCandidate) -> dict[str, str]:
        """Retain known and unknown material phases; the electron is intrinsic."""
        return {
            term.species: phase
            for term in (*reaction.reactants, *reaction.products)
            if term.species != ELECTRON and (phase := self.states[term.species].phase) != "gas"
        }


@dataclass(frozen=True)
class Requirement:
    """A missing prerequisite for a particular conclusion, with the work it needs.

    ``target`` identifies the state, reaction or source whose information is
    missing. ``quantity`` is an accepted input name only for ``user_inputs``;
    source declarations and unsupported models are not case input fields.
    """

    responsibility: str
    target: str
    quantity: str
    reason: str = ""

    def __post_init__(self) -> None:
        for name in ("responsibility", "target", "quantity"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"requirement.{name} must be a nonempty string")
        if not isinstance(self.reason, str):
            raise ValueError("requirement.reason must be a string")


def numerical_requirements(
    inputs: Iterable[str],
    transforms: Iterable[str],
    target: str,
    reason: str,
) -> tuple[Requirement, ...]:
    """Normalize numerical prerequisite vocabulary at its producing boundary.

    This assigns work to the accepted input interface; it does not qualify a
    source or supply a physical model. Historical string requirements use the
    same adapter, while current results persist the assigned responsibility.
    """
    result = []
    for quantity in sorted(set(inputs)):
        if field_name := CONDITION_INPUT_FIELDS.get(quantity):
            role, quantity = "user_inputs", f"conditions.{field_name}"
        elif quantity in {"dataset_applicability_conditions", "dataset_independent_variable"}:
            role = "source_information"
        elif quantity == "rate_law_selection":
            role, quantity = "source_selection", "data_selection"
        elif quantity == "numerical_quantity_selection":
            role = "source_selection"
        elif quantity in {
            "electron_energy_distribution",
            "collision_energy_distribution",
            "surface_incident_flux_model",
        }:
            role = "external_models"
        else:
            role = "unsupported_inputs"
        result.append(Requirement(role, target, quantity, reason))
    result.extend(
        Requirement("transforms", target, quantity, reason) for quantity in sorted(set(transforms))
    )
    return tuple(result)


def numerical_requirement_fields(
    requirements: Iterable[Requirement],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive the historical input/transform fields from canonical work records.

    Review, missing numerical representations, and exclusions were not input
    fields and are not relabelled as scalar conditions by this adapter.
    """
    inputs, transforms = set(), set()
    axes = {field_name: quantity for quantity, field_name in CONDITION_INPUT_FIELDS.items()}
    for item in requirements:
        if item.responsibility == "transforms":
            transforms.add(item.quantity)
        elif item.responsibility == "user_inputs":
            name = item.quantity.removeprefix("conditions.")
            inputs.add(axes.get(name, item.quantity))
        elif item.responsibility == "source_information" and item.quantity in {
            "dataset_applicability_conditions",
            "dataset_independent_variable",
        }:
            inputs.add(item.quantity)
        elif item.responsibility == "source_selection" and item.quantity in {
            "data_selection",
            "rate_law_selection",
            "numerical_quantity_selection",
        }:
            inputs.add("rate_law_selection" if item.quantity == "data_selection" else item.quantity)
        elif item.responsibility in {"external_models", "unsupported_inputs"}:
            inputs.add(item.quantity)
    return tuple(sorted(inputs)), tuple(sorted(transforms))


def coefficient_availability_verdict(status: str, dataset_statuses: Iterable[str]) -> str:
    """Availability in supplied records, without judging channel occurrence.

    Rejected/inapplicable records can rule out their use. Conflicting records
    remain unresolved; they do not establish a coefficient's unavailability.
    """
    if status == "coefficient":
        return "pass"
    if status == "not_applicable":
        return "not_applicable"
    offered = tuple(dataset_statuses)
    if offered and all(item in {"invalid", "out_of_range"} for item in offered):
        return "fail"
    return "unknown"


def participant_support_verdict(verdicts: Iterable[str]) -> str:
    """Aggregate the saved named state claims, preserving their individual scope."""
    values = tuple(verdicts)
    if "fail" in values:
        return "fail"
    return "unknown" if "unknown" in values else "pass"


@dataclass(frozen=True, order=True)
class ScientificRecordReference:
    target: str
    quantity: str
    record_id: str
    record_ref: str


@dataclass(frozen=True)
class Assessment:
    verdict: str  # pass | fail | unknown | not_applicable
    basis: tuple[str, ...] = ()
    message: str = ""
    proposition: str = ""
    scope: str = ""
    requirements: tuple[Requirement, ...] = ()
    # References to saved state assessments, not duplicate conclusions.
    dependencies: tuple[tuple[str, str], ...] = ()
    record_inputs: tuple[ScientificRecordReference, ...] = ()

    def __post_init__(self) -> None:
        # References identify a basis, not the number of independent records.
        # The complete declarations remain in evidence; public basis is unique.
        object.__setattr__(self, "basis", tuple(dict.fromkeys(self.basis)))
        if not isinstance(self.scope, str):
            raise ValueError("assessment.scope must be a string")
        if any(not isinstance(item, Requirement) for item in self.requirements):
            raise ValueError("assessment.requirements must contain Requirement records")
        object.__setattr__(self, "requirements", tuple(dict.fromkeys(self.requirements)))
        if any(
            len(item) != 2 or any(not isinstance(value, str) or not value for value in item)
            for item in self.dependencies
        ):
            raise ValueError("assessment.dependencies must identify a state and assessment")
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies))))


@dataclass(frozen=True)
class ThermochemicalCalculation:
    """Availability of one calculated quantity, independent of an energy claim.

    ``computed`` supplies a finite nominal value at the retained conditions.
    Other states retain the concrete prerequisites or an applicability limit.
    Source qualification and calculation applicability never establish channel
    occurrence, uncertainty propagation, or a reversible elementary mechanism.
    """

    status: str
    value: float | None
    unit: str
    reason: str
    requirements: tuple[Requirement, ...] = ()
    conditions: dict[str, float] = field(default_factory=dict)
    inputs: tuple[dict, ...] = ()
    operation: str = ""
    alternatives: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "computed",
            "needs_input",
            "unavailable",
            "out_of_range",
            "not_applicable",
        }:
            raise ValueError("unknown thermochemical calculation status")
        if (self.status == "computed") != (self.value is not None):
            raise ValueError("only computed thermochemical quantities may have a value")
        if self.value is not None and (isinstance(self.value, bool) or not isfinite(self.value)):
            raise ValueError("thermochemical calculation value must be finite")
        if not isinstance(self.unit, str) or not self.unit:
            raise ValueError("thermochemical calculation unit must be nonempty")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("thermochemical calculation reason must be nonempty")
        if any(not isinstance(item, Requirement) for item in self.requirements):
            raise ValueError("thermochemical calculation requirements must be typed")
        if any(
            not isinstance(name, str) or not name or isinstance(value, bool) or not isfinite(value)
            for name, value in self.conditions.items()
        ):
            raise ValueError("thermochemical calculation conditions must be finite quantities")
        object.__setattr__(self, "requirements", tuple(dict.fromkeys(self.requirements)))
        if any(not isinstance(item, dict) for item in self.inputs):
            raise ValueError("calculation inputs must reference scientific records")
