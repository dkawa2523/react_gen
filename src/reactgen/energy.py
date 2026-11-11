"""State-energy differences from qualified endpoints and a few closed cycles.

Inputs have already passed quantity/source selection. This module adds and
subtracts their physical relationships; it never approves a source or infers
reaction probability. NIST ion thermochemistry defines adiabatic IE/EA and
distinguishes thermochemical limits from appearance energies and barriers:
https://webbook.nist.gov/chemistry/ion/
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from math import fsum, isclose

from reactgen.model import (
    DIRECT_STATE_RELATION,
    ELECTRON,
    REVERSED_STATE_RELATION,
    Requirement,
    StateCandidate,
    StateKey,
    state_excitation,
)
from reactgen.records import FormationReference
from reactgen.structure import endpoint_structure_matches, physical_state_id, physical_state_key

EnergyVector = tuple[tuple[StateKey, float], ...]


@dataclass(frozen=True)
class EnergyInput:
    record_id: str
    record_ref: str
    target: str
    quantity: str
    value: float
    source_value: float
    source_unit: str | None
    definition: str | None = None
    reference: FormationReference | None = None
    related_state: str | None = None
    method: str = "unknown"
    provider: str | None = None
    collection: str | None = None

    def term(self, coefficient: float) -> dict:
        result = {
            "record_id": self.record_id,
            "record_ref": self.record_ref,
            "target": self.target,
            "quantity": self.quantity,
            "coefficient": coefficient,
            "value_amu" if self.quantity == "mass_amu" else "value_eV": self.value,
            "source_value": self.source_value,
            "source_unit": self.source_unit,
            "definition": self.definition,
            "method": self.method,
            "provider": self.provider,
            "collection": self.collection,
        }
        if self.related_state is not None:
            result["related_state"] = self.related_state
        return result


@dataclass(frozen=True)
class EnergyRelation:
    """A declared products-minus-reactants quantity for specific states."""

    coefficients: EnergyVector
    energy: EnergyInput


@dataclass(frozen=True)
class EnergyDifference:
    value: float
    operation: str
    inputs: tuple[dict, ...] = ()
    conditions: dict[str, float] = field(default_factory=dict)


def physical_coefficients(
    contributors: dict[str, float], states: Mapping[str, StateCandidate]
) -> dict[StateKey, float]:
    """Cancel identical physical states before looking up energy relations."""
    terms: dict[StateKey, list[float]] = defaultdict(list)
    for state_id, coefficient in contributors.items():
        if state_id != ELECTRON:
            terms[physical_state_key(states[state_id])].append(coefficient)
    return {key: value for key, parts in terms.items() if (value := fsum(parts)) != 0}


def endpoint_order_issue(vector: dict[StateKey, float], value: float) -> str | None:
    """Check a signed difference with a known ordering of two resolved gas states.

    Bound nonnegative ground charge stages increase in energy toward ionization
    (NIST ASD GSIE definition). This does not order resonances, negative ions,
    different isomers, or a sum that also changes other states.
    https://physics.nist.gov/PhysRefData/ASD/Html/iehelp.html
    """
    if len(vector) != 2:
        return None
    lower, higher = sorted(vector, key=lambda key: (key[1], key[2] != "ground"))
    if (
        lower[0] != higher[0]
        or lower[5] != higher[5]
        or lower[5] != "gas"
        or lower[4] != "resolved"
        or higher[4] != "resolved"
        or vector[lower] != -vector[higher]
        or not endpoint_structure_matches(lower, higher)
    ):
        return None
    increase = value if vector[higher] > 0 else -value
    if lower[2] == higher[2] == "ground" and 0 <= lower[1] < higher[1] and increase <= 0:
        return "a higher ground ionization stage must lie above the lower stage"
    if (
        lower[1] == higher[1]
        and lower[2] == "ground"
        and higher[2] != "resonant"
        and state_excitation(higher[2], higher[3]) in {"electronic", "vibrational", "rotational"}
        and increase < 0
    ):
        return "the signed difference places a resolved excited level below its own ground state"
    return None


def admissible_differences(
    vector: dict[StateKey, float],
    proposals: list[EnergyDifference],
    requirements: list[Requirement] | None = None,
) -> list[EnergyDifference]:
    """Keep derived and direct differences subject to the same endpoint ordering."""
    accepted = []
    for proposal in proposals:
        issue = endpoint_order_issue(vector, proposal.value)
        if issue is None:
            accepted.append(proposal)
        elif requirements is not None:
            requirements.extend(
                Requirement("source_review", term["target"], term["quantity"], issue)
                for term in proposal.inputs
                if "record_id" in term
            )
    return accepted


def signature(coefficients: dict[StateKey, float]) -> EnergyVector:
    return tuple(sorted(coefficients.items(), key=lambda item: repr(item[0])))


def _reverse(vector: EnergyVector) -> EnergyVector:
    return tuple((state, -n) for state, n in vector)


class EnergyRelations:
    """Index qualified signed endpoint differences for one analysis."""

    def __init__(
        self,
        relations: Iterable[EnergyRelation],
        *,
        rejected: Iterable[tuple[EnergyVector, Requirement]] = (),
    ) -> None:
        self._rejected: dict[EnergyVector, list[Requirement]] = defaultdict(list)
        for vector, requirement in rejected:
            self._rejected[vector].append(requirement)
            self._rejected[_reverse(vector)].append(requirement)
        self._signed: dict[EnergyVector, list[tuple[EnergyInput, float]]] = defaultdict(list)
        for relation in relations:
            self._signed[relation.coefficients].append((relation.energy, 1.0))
            self._signed[_reverse(relation.coefficients)].append((relation.energy, -1.0))
        self._fragments = {
            vector: {state for state, n in vector if n > 0}
            for vector in self._signed
            if _is_dissociation(vector)
        }

    def difference(
        self, coefficients: dict[StateKey, float], requirements: list[Requirement] | None = None
    ) -> list[EnergyDifference]:
        """Use one exact relation or two cuts with a shared fragment."""
        if not coefficients:
            return [EnergyDifference(0.0, "identical_state_cancellation")]
        vector = signature(coefficients)
        results = [
            EnergyDifference(
                sign * source.value,
                DIRECT_STATE_RELATION if sign == 1 else REVERSED_STATE_RELATION,
                (source.term(sign),),
            )
            for source, sign in self._signed.get(vector, ())
        ]
        # Orient each input toward dissociation, regardless of how the source
        # writes it. Look up the other cut from the exact signed remainder.
        for cut, fragments in self._fragments.items():
            remainder = coefficients.copy()
            for state, n in cut:
                remainder[state] = remainder.get(state, 0.0) - n
            other = signature({state: -n for state, n in remainder.items() if n})
            if fragments.isdisjoint(self._fragments.get(other, ())):
                continue
            results.extend(
                EnergyDifference(
                    sign * source.value - other_sign * other_source.value,
                    "two_dissociation_transfer_cycle",
                    (source.term(sign), other_source.term(-other_sign)),
                )
                for source, sign in self._signed[cut]
                for other_source, other_sign in self._signed[other]
            )
        if requirements is not None:
            requirements.extend(
                sorted(self._rejected.get(vector, ()), key=lambda item: item.target)
            )
        return results


def _is_dissociation(coefficients: EnergyVector) -> bool:
    return [n for _, n in coefficients if n < 0] == [-1] and sum(
        n for _, n in coefficients if n > 0
    ) in {2, 3}


def formation_differences(
    contributors: dict[str, float],
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    *,
    operation: str = "zero_K_formation_difference",
    requirements: list[Requirement] | None = None,
) -> list[EnergyDifference]:
    """Compare state formation values at one explicitly shared zero-K basis."""
    if not contributors:
        return [EnergyDifference(0.0, "identical_state_cancellation")]
    bases: dict[str, dict[str, list[EnergyInput]]] = defaultdict(lambda: defaultdict(list))
    for state in contributors:
        if (
            states[state].phase != "gas"
            or states[state].state.resolution != "resolved"
            or states[state].state.kind == "composition"
        ):
            return []
        for item in values.get((state, "enthalpy_formation_eV"), ()):
            ref = item.reference
            if ref is not None and ref.temperature_K == 0 and ref.basis:
                bases[ref.basis][state].append(item)
    results = []
    for basis, offers_by_state in sorted(bases.items()):
        if set(offers_by_state) != set(contributors):
            continue
        if disagreements := [
            state for state, offers in offers_by_state.items() if not _agree(offers)
        ]:
            if requirements is not None:
                requirements.extend(
                    Requirement(
                        "source_selection",
                        state,
                        "enthalpy_formation_eV",
                        f"qualified 0 K formation values disagree for {state} on basis {basis}",
                    )
                    for state in disagreements
                )
            continue
        selected = {state: offers_by_state[state][0] for state in contributors}
        results.append(
            EnergyDifference(
                fsum(contributors[state] * item.value for state, item in selected.items()),
                operation,
                tuple(selected[state].term(n) for state, n in contributors.items()),
                {"reference_temperature_K": 0.0},
            )
        )
    return results


def level_differences(
    initial: str,
    final: str,
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
    requirements: list[Requirement] | None = None,
) -> list[EnergyDifference]:
    """Signed gap for a validated pair of internal states of one species."""
    return _endpoint_differences(
        {initial: -1.0, final: 1.0}, states, values, relations, requirements
    )


def complete_level_differences(
    coefficients: dict[str, float],
    changes: tuple[tuple[str, str, str, float], ...],
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
) -> list[EnergyDifference]:
    """Add validated level gaps to one independently evaluated endpoint remainder.

    Each change supplies its initial state, final state, calculation reference,
    and chosen signed gap. Subtraction fixes the remainder without searching
    for possible splits or using the event calculation as one of its inputs.
    """
    if not coefficients or not changes:
        return []
    remainder = coefficients.copy()
    for initial, final, _, _ in changes:
        remainder[initial] = remainder.get(initial, 0.0) + 1
        remainder[final] = remainder.get(final, 0.0) - 1
    remainder = {state: n for state, n in remainder.items() if n}
    gaps = tuple(value for _, _, _, value in changes)
    references = tuple(
        {"calculation": calculation, "coefficient": 1.0} for _, _, calculation, _ in changes
    )
    return [
        EnergyDifference(
            fsum((*gaps, residual.value)),
            "level_gaps_plus_remaining_endpoints",
            (*references, *residual.inputs),
            residual.conditions,
        )
        for residual in _endpoint_differences(remainder, states, values, relations)
    ]


def _endpoint_differences(
    contributors: dict[str, float],
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
    requirements: list[Requirement] | None = None,
) -> list[EnergyDifference]:
    if not contributors:
        return [EnergyDifference(0.0, "identical_state_cancellation")]
    if any(
        state.state.kind == "composition"
        or state.state.resolution != "resolved"
        or state.phase != "gas"
        for state in (states[state_id] for state_id in contributors)
    ):
        return []
    vector = physical_coefficients(contributors, states)
    return admissible_differences(
        vector,
        relations.difference(vector, requirements)
        + formation_differences(contributors, states, values, requirements=requirements)
        + reduced_differences(contributors, states, values, relations, requirements),
        requirements,
    )


def reduced_differences(
    contributors: dict[str, float],
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
    requirements: list[Requirement] | None = None,
) -> list[EnergyDifference]:
    """Combine resolved level offsets and charge-stage differences on a common basis."""
    ground_terms: dict[str, list[float]] = defaultdict(list)
    inputs: list[dict] = []
    for state_id, n in contributors.items():
        level = _ground_level(states[state_id], states, values, requirements)
        if level is None:
            return []
        ground, offset = level
        ground_terms[ground.id].append(n)
        if offset is not None:
            inputs.append(offset.term(n))

    # Within one spectrum, level offsets use the ground of that charge stage.
    # Reduce adjacent charge stages from the outside in so a shared ground
    # cancels before it would require an IE/EA to go one stage closer to neutral.
    neutral: dict[StateKey, list[float]] = defaultdict(list)
    neutral_ids: dict[StateKey, str] = {}
    while ground_terms:
        ground_id = max(ground_terms, key=lambda item: (abs(states[item].charge), item))
        n = fsum(ground_terms.pop(ground_id))
        if not n:
            continue
        ground = states[ground_id]
        if ground.charge == 0:
            key = physical_state_key(ground)
            neutral_ids[key] = ground.id
            neutral[key].append(n)
            continue
        step = _ground_charge_step(ground, states, values, requirements)
        if step is None:
            return []
        reference, offset, sign = step
        ground_terms[reference.id].append(n)
        inputs.append(offset.term(n * sign))
    if not inputs:
        # Without a charge or level offset this is the original endpoint
        # calculation, already evaluated by the caller.
        return []
    vector = {key: v for key, parts in neutral.items() if (v := fsum(parts))}
    offsets = fsum(item["coefficient"] * item["value_eV"] for item in inputs)
    bases = relations.difference(vector)
    if vector:
        bases.extend(
            formation_differences(
                {neutral_ids[key]: n for key, n in vector.items()},
                states,
                values,
                operation="neutral_zero_K_formation_difference",
                requirements=requirements,
            )
        )
    return [
        EnergyDifference(
            base.value + offsets,
            "adiabatic_charge_level_cycle:" + base.operation,
            (*base.inputs, *inputs),
            base.conditions,
        )
        for base in bases
    ]


def _ground_level(
    state: StateCandidate,
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    requirements: list[Requirement] | None,
) -> tuple[StateCandidate, EnergyInput | None] | None:
    if state.phase != "gas" or state.state.resolution != "resolved":
        return None
    if state.state.kind == "ground":
        return state, None
    ground = ground_reference_state(state, states, state.charge)
    if ground is None:
        return None
    excitation = _offset(values, state.id, "excitation_energy_eV", ground.id, requirements)
    return (ground, excitation) if excitation is not None else None


def _ground_charge_step(
    ground: StateCandidate,
    states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    requirements: list[Requirement] | None,
) -> tuple[StateCandidate, EnergyInput, float] | None:
    """One bound charge step on the same gas-phase nuclear/structure identity.

    NIST ASD specifies the ground ion obtained by removing one electron from
    each initial atom or ion. With the free-electron zero, E(q+1)-E(q) is IE(q).
    https://physics.nist.gov/PhysRefData/ASD/Html/iehelp.html
    """
    if ground.charge < -1:
        return None
    reference = ground_reference_state(ground, states, max(0, ground.charge - 1))
    if reference is None:
        return None
    quantity, sign = (
        ("ionization_energy_eV", 1.0) if ground.charge > 0 else ("electron_affinity_eV", -1.0)
    )
    offset = _offset(values, reference.id, quantity, ground.id, requirements)
    return (reference, offset, sign) if offset is not None else None


def _offset(
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    state_id: str,
    quantity: str,
    related_id: str,
    requirements: list[Requirement] | None,
) -> EnergyInput | None:
    offered = values.get((state_id, quantity), ())
    related_key = physical_state_id(related_id)
    compatible = tuple(
        item
        for item in offered
        if item.related_state is None or physical_state_id(item.related_state) == related_key
    )
    if compatible and _agree(compatible):
        offset = compatible[0]
        if quantity != "electron_affinity_eV" or offset.value > 0:
            return offset
        return None  # A nonpositive EA cannot supply a bound endpoint.
    if requirements is not None:
        if compatible:
            need = Requirement(
                "source_selection",
                state_id,
                quantity,
                f"qualified values for {state_id} relative to {related_id} disagree",
            )
        else:
            definition = {
                "ionization_energy_eV": "an adiabatic ionization energy",
                "electron_affinity_eV": "an adiabatic electron affinity for a bound anion",
                "excitation_energy_eV": "a resolved level offset",
            }[quantity]
            need = Requirement(
                "source_information",
                state_id,
                quantity,
                f"the endpoint reduction needs {definition} for {state_id} "
                f"relative to {related_id}",
            )
        requirements.append(need)
    return None


def ground_reference_state(
    state: StateCandidate, states: Mapping[str, StateCandidate], charge: int
) -> StateCandidate | None:
    """Find the unique resolved ground reference at the requested charge stage."""
    key = physical_state_key(state)
    options = [
        other
        for other in states.values()
        if other.composition == state.composition
        and other.phase == state.phase
        and other.charge == charge
        and other.state.kind == "ground"
        and other.state.resolution == "resolved"
        and endpoint_structure_matches(key, physical_state_key(other))
    ]
    return options[0] if len(options) == 1 else None


def _agree(values: list[EnergyInput] | tuple[EnergyInput, ...]) -> bool:
    return all(
        isclose(item.value, values[0].value, rel_tol=1e-10, abs_tol=1e-12) for item in values
    )
