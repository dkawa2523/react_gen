"""Endpoint screening over already qualified scientific inputs.

Source retrieval, source review and quantity selection remain in assessment.
This module owns endpoint arithmetic choices, collision-condition applicability
and the named energy-conservation proposition. Values never establish a rate,
mechanism, lifetime or the simultaneous feasibility of a multi-event pathway.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from math import fsum, isclose, isfinite
from typing import cast

from reactgen.case import CollisionPair, Conditions
from reactgen.energy import (
    EnergyDifference,
    EnergyInput,
    EnergyRelations,
    admissible_differences,
    complete_level_differences,
    endpoint_order_issue,
    formation_differences,
    level_differences,
    physical_coefficients,
    reduced_differences,
)
from reactgen.model import (
    ELECTRON,
    EXACT_STATE_RELATION_OPERATIONS,
    Assessment,
    CandidateSet,
    ReactionCandidate,
    Requirement,
    StateCandidate,
    StateKey,
    ThermochemicalCalculation,
    binary_collision_partners,
    side_key,
)
from reactgen.selection import DataSelection, QuantitySelection
from reactgen.thermo import net_stoichiometry

VERDICT_PASS = "pass"  # noqa: S105 - scientific verdict, not a credential
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_NA = "not_applicable"
COLLISION_CONDITION_NOT_APPLICABLE = "no specified projectile/target pair applies to this channel"


def calculation_reason(requirements: tuple[Requirement, ...]) -> str:
    return "; ".join(dict.fromkeys(item.reason for item in requirements))


def screening_calculations(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
    conditions: Conditions,
    selection: DataSelection | None,
    alternative_values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    *,
    energy_states: Mapping[str, StateCandidate],
    conservation: Assessment,
    identity_requirements: dict[str, tuple[Requirement, ...]],
    property_issues: dict[tuple[str, str], tuple[Requirement, ...]],
    state_assessments: dict[str, dict[str, Assessment]],
    level_transitions: tuple[tuple[str, str], ...],
) -> tuple[dict[str, ThermochemicalCalculation], Assessment]:
    if outside_scope := _screening_scope(reaction, candidates, conservation):
        return {}, outside_scope
    selected = collision_condition(reaction, conditions)
    relative, collision_inputs, collision_requirements = (
        relative_collision_energy(
            reaction, candidates.states, values, *selected, property_issues=property_issues
        )
        if selected is not None and binary_collision_partners(reaction.reactants) is not None
        else (None, (), ())
    )
    collision_context = {} if relative is None else {"relative_collision_energy_eV": relative}
    net = net_stoichiometry(reaction)
    coefficients = {state: n for state, n in net.items() if state != ELECTRON}
    shared_transition = None
    if len(level_transitions) == 1:
        initial, final = level_transitions[0]
        shared_transition = (initial, final) if coefficients == {initial: -1, final: 1} else None
    calculations = _level_calculations(
        level_transitions if shared_transition is None else (),
        candidates,
        energy_states,
        values,
        relations,
        identity_requirements,
        alternative_values,
        property_issues,
    )
    if requirements := _isotope_requirements(reaction, conservation):
        unavailable = ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
        calculations.update(
            state_energy_difference_eV=unavailable,
            collision_energy_margin_eV=replace(
                unavailable, conditions=collision_context, inputs=collision_inputs
            ),
        )
        if shared_transition is not None:
            calculations["level_gap_1_eV"] = _level_gap_result(
                *shared_transition, unavailable, event_equivalent=True
            )
        return calculations, _budget_result(VERDICT_UNKNOWN, unavailable.reason, requirements)
    participants = tuple(coefficients)
    vector = physical_coefficients(coefficients, energy_states)
    unresolved = any(_unresolved_energy_state(state, candidates) for state in participants)
    cycle_requirements: list[Requirement] = []
    direct = [] if unresolved else relations.difference(vector, cycle_requirements)
    policy = selection.for_quantity("delta_e_eV", reaction.id) if selection else None
    derived = (
        []
        if unresolved
        else formation_differences(
            coefficients, energy_states, values, requirements=cycle_requirements
        )
    )
    if not unresolved:
        derived.extend(
            reduced_differences(coefficients, energy_states, values, relations, cycle_requirements)
        )
        derived.extend(
            complete_level_differences(
                coefficients,
                _computed_level_changes(level_transitions, calculations),
                energy_states,
                values,
                relations,
            )
        )
        derived = admissible_differences(vector, derived, cycle_requirements)
    proposals, constrained = _selected_direct_differences(direct, policy)
    if not constrained:
        proposals.extend(derived)
    difference = _state_difference_calculation(
        reaction.id,
        participants,
        candidates,
        proposals,
        identity_requirements,
        values,
        _explain_property_issues(cycle_requirements, property_issues),
    )
    if constrained and not proposals:
        rejected = tuple(
            item
            for item in cycle_requirements
            if policy is not None
            and item.target == policy.record
            and item.responsibility == "source_review"
        )
        requirements = rejected or (
            Requirement(
                "source_selection",
                reaction.id,
                "delta_e_eV",
                "the requested direct-energy records do not supply an applicable state difference; "
                "inspect the selected record target, definition and review status",
            ),
        )
        difference = ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
    alternatives = _difference_alternatives(
        difference, [*direct, *derived], alternative_values, vector
    )
    if alternatives:
        difference = replace(difference, alternatives=alternatives)
    energy, margin = _collision_budget(
        reaction, difference, selected is not None, relative, collision_requirements
    )
    energy = _bound_endpoint_applicability(
        energy, reaction, coefficients, candidates, state_assessments
    )
    calculations.update(
        state_energy_difference_eV=difference,
        collision_energy_margin_eV=replace(
            margin, conditions=collision_context, inputs=(*margin.inputs, *collision_inputs)
        ),
    )
    if shared_transition is not None:
        calculations["level_gap_1_eV"] = _level_gap_result(
            *shared_transition, difference, event_equivalent=True
        )
    calculations.update(
        _proton_transfer_calculations(reaction, net, candidates, values, alternative_values)
    )
    return calculations, energy


def _screening_scope(
    reaction: ReactionCandidate, candidates: CandidateSet, conservation: Assessment
) -> Assessment | None:
    if reaction.surface is not None or reaction.family == "surface":
        return Assessment(
            VERDICT_NA,
            (),
            "gas-state endpoint screening does not include a surface reservoir",
            proposition="collision_energy_necessary_condition",
            scope="Gas collisions only.",
        )
    if conservation.verdict == VERDICT_FAIL:
        return Assessment(
            VERDICT_NA,
            ("assessment:conservation",),
            "a collision energy budget requires a conserved reaction equation",
            proposition="collision_energy_necessary_condition",
            scope="Conserved gas-phase collision equations.",
        )
    non_gas = candidates.nongas_participants(reaction)
    if any(phase != "unknown" for phase in non_gas.values()):
        return Assessment(
            VERDICT_NA,
            (),
            "the represented reaction includes a nongas reactant or product",
            proposition="collision_energy_necessary_condition",
            scope="Gas collisions only.",
        )
    if non_gas:
        reason = "identify participant phases before screening the event"
        return Assessment(
            VERDICT_UNKNOWN,
            (),
            reason,
            proposition="collision_energy_necessary_condition",
            scope="Gas collisions only.",
            requirements=tuple(
                Requirement("identity", state, "phase", reason) for state in sorted(non_gas)
            ),
        )
    return None


def _level_calculations(
    transitions: tuple[tuple[str, str], ...],
    candidates: CandidateSet,
    energy_states: Mapping[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    relations: EnergyRelations,
    identities: dict[str, tuple[Requirement, ...]],
    alternative_values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    property_issues: dict[tuple[str, str], tuple[Requirement, ...]],
) -> dict[str, ThermochemicalCalculation]:
    calculations = {}
    for number, (initial, final) in enumerate(sorted(transitions), start=1):
        cycle_requirements: list[Requirement] = []
        proposals = level_differences(
            initial, final, energy_states, values, relations, cycle_requirements
        )
        gap = _state_difference_calculation(
            f"{initial} → {final}",
            (initial, final),
            candidates,
            proposals,
            identities,
            values,
            _explain_property_issues(cycle_requirements, property_issues),
            quantity="internal_level_gap",
        )
        calculations[f"level_gap_{number}_eV"] = _level_gap_result(
            initial,
            final,
            replace(
                gap,
                alternatives=_difference_alternatives(
                    gap,
                    proposals,
                    alternative_values,
                    physical_coefficients({initial: -1.0, final: 1.0}, energy_states),
                ),
            ),
        )
    return calculations


def _computed_level_changes(
    transitions: tuple[tuple[str, str], ...],
    calculations: dict[str, ThermochemicalCalculation],
) -> tuple[tuple[str, str, str, float], ...]:
    changes = []
    for number, (initial, final) in enumerate(sorted(transitions), start=1):
        name = f"level_gap_{number}_eV"
        gap = calculations.get(name)
        if gap is None or gap.value is None:
            return ()
        changes.append((initial, final, name, gap.value))
    return tuple(changes)


def _level_gap_result(
    initial: str,
    final: str,
    gap: ThermochemicalCalculation,
    *,
    event_equivalent: bool = False,
) -> ThermochemicalCalculation:
    if gap.value is None:
        reason = gap.reason
    else:
        direction = "upward" if gap.value > 0 else "downward" if gap.value < 0 else "equal energy"
        reason = f"nominal single-particle internal energy gap ({direction})"
    if event_equivalent:
        # This pair is the entire uncancelled event. Keep the selected result
        # and trace its sources and alternatives through the event calculation.
        gap = replace(
            gap,
            inputs=({"calculation": "state_energy_difference_eV", "coefficient": 1.0},),
            operation="single_level_event_difference",
            alternatives=(),
        )
    return replace(
        gap,
        reason=f"For {initial} → {final}, {reason}",
        inputs=({"operation": "level_state_pair", "initial": initial, "final": final}, *gap.inputs),
    )


def _unresolved_energy_state(state_id: str, candidates: CandidateSet) -> bool:
    state = candidates.states[state_id].state
    return state.kind == "composition" or state.resolution != "resolved"


def _difference_alternatives(
    result: ThermochemicalCalculation,
    proposals: list[EnergyDifference],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    vector: dict[StateKey, float] | None = None,
) -> tuple[dict, ...]:
    output: list[dict] = [
        {
            "value": item.value,
            "unit": "eV",
            "operation": item.operation,
            "inputs": item.inputs,
            "conditions": item.conditions,
        }
        for item in proposals
        if item.inputs != result.inputs or item.value != result.value
    ]
    if result.value is not None:
        output.extend(_substituted_inputs(result, values))
    if vector:
        output = [item for item in output if endpoint_order_issue(vector, item["value"]) is None]
    unique = {repr(item): item for item in output}
    return tuple(unique.values())


def _substituted_inputs(
    result: ThermochemicalCalculation,
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
) -> list[dict]:
    alternatives = []
    for index, term in enumerate(result.inputs):
        target, quantity = term.get("target"), term.get("quantity")
        if not isinstance(target, str) or not isinstance(quantity, str):
            continue
        original = next(
            (
                item
                for item in values.get((target, quantity), ())
                if item.record_ref == term.get("record_ref")
            ),
            None,
        )
        if original is None:
            continue
        for other in values.get((target, quantity), ()):
            if other.record_ref == original.record_ref or not _same_energy_input(original, other):
                continue
            reference = other.reference
            if reference is not None and reference.temperature_K != result.conditions.get(
                "reference_temperature_K", 0
            ):
                continue
            coefficient = term["coefficient"]
            substituted = other.term(coefficient)
            alternatives.append(
                {
                    "value": cast(float, result.value)
                    + coefficient * (other.value - term["value_eV"]),
                    "unit": "eV",
                    "operation": "alternative_qualified_input",
                    "inputs": (*result.inputs[:index], substituted, *result.inputs[index + 1 :]),
                    "conditions": result.conditions,
                }
            )
    return alternatives


def _same_energy_input(left: EnergyInput, right: EnergyInput) -> bool:
    if left.definition != right.definition or left.related_state != right.related_state:
        return False
    if left.quantity != "enthalpy_formation_eV":
        return True
    a, b = left.reference, right.reference
    return (
        a is not None
        and b is not None
        and a.temperature_K == b.temperature_K == 0
        and (a.basis == b.basis)
    )


def _unresolved_nuclides(transformation: dict) -> bool:
    if transformation.get("unresolved_nuclides") is True:
        return True
    if transformation.get("kind") == "alternatives":
        alternatives = transformation.get("alternatives", [])
        return bool(alternatives) and all(_unresolved_nuclides(item) for item in alternatives)
    return False


def _isotope_requirements(
    reaction: ReactionCandidate, conservation: Assessment
) -> tuple[Requirement, ...]:
    if conservation.verdict == VERDICT_UNKNOWN:
        requirements = tuple(
            item
            for item in conservation.requirements
            if item.responsibility == "identity" and item.quantity == "isotopic_composition"
        )
        if requirements:
            return requirements
    if _unresolved_nuclides(reaction.transformation):
        return (
            Requirement(
                "external_models",
                reaction.id,
                "nuclide_resolved_transformation",
                "this inventory projection does not retain the explicit isotope labels; "
                "use a mapped nuclide-preserving transformation before applying state energies",
            ),
        )
    return ()


def _selected_direct_differences(
    differences: list[EnergyDifference], policy: QuantitySelection | None
) -> tuple[list[EnergyDifference], bool]:
    # Exact endpoint cancellation has no source to select.
    if policy is None or any(
        item.operation == "identical_state_cancellation" for item in differences
    ):
        return differences, False
    direct = [item for item in differences if item.operation in EXACT_STATE_RELATION_OPERATIONS]

    def axes(item: EnergyDifference) -> tuple[str, str | None, str | None]:
        source = item.inputs[0]
        return source.get("method", "unknown"), source.get("provider"), source.get("collection")

    if policy.record is not None:
        selected = [
            item
            for item in direct
            if policy.record in {item.inputs[0]["record_id"], item.inputs[0]["record_ref"]}
        ]
        if any(not policy.allows(*axes(item)) for item in selected):
            raise ValueError(
                f"data_selection delta_e_eV: record {policy.record!r} contradicts only restrictions"
            )
        return selected, True

    allowed = [item for item in direct if policy.allows(*axes(item))]
    if policy.mode == "only":
        return allowed, True
    if not allowed:
        return differences, False
    rank = min(policy.rank(*axes(item)) for item in allowed)
    # An empty preference or a fallback on every requested axis supplies no
    # reason to discard independently derived differences.
    if rank == policy.rank("", None, None):
        return differences, False
    selected = [item for item in allowed if policy.rank(*axes(item)) == rank]
    return selected, True


def _state_difference_calculation(
    target: str,
    participants: tuple[str, ...],
    candidates: CandidateSet,
    proposals: list[EnergyDifference],
    identities: dict[str, tuple[Requirement, ...]],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    cycle_requirements: list[Requirement],
    *,
    quantity: str = "delta_e_eV",
) -> ThermochemicalCalculation:
    if not proposals:
        requirements = _state_difference_requirements(
            target, participants, candidates, identities, values, cycle_requirements, quantity
        )
        return ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
    if not all(
        isclose(item.value, proposals[0].value, rel_tol=1e-9, abs_tol=1e-10) for item in proposals
    ):
        conflict = (
            Requirement(
                "source_selection",
                target,
                quantity,
                "complete endpoint/cycle alternatives disagree; inspect retained inputs "
                "and select the applicable records rather than averaging",
            ),
        )
        return ThermochemicalCalculation(
            "unavailable",
            None,
            "eV",
            "conflicting compatible alternatives: " + ", ".join(f"{x.value:g}" for x in proposals),
            conflict,
            inputs=tuple(term for item in proposals for term in item.inputs),
            operation="alternative_comparison",
        )
    selected = proposals[0]
    return ThermochemicalCalculation(
        "computed",
        selected.value,
        "eV",
        "nominal products-minus-reactants endpoint energy for the represented states; "
        "not an activation barrier, resonance position, appearance energy or occurrence proof",
        conditions=selected.conditions,
        inputs=selected.inputs,
        operation=selected.operation,
    )


def _explain_property_issues(
    requirements: list[Requirement], issues: dict[tuple[str, str], tuple[Requirement, ...]]
) -> list[Requirement]:
    explained: list[Requirement] = []
    for item in requirements:
        known = (
            issues.get((item.target, item.quantity))
            if item.responsibility == "source_information"
            else None
        )
        explained.extend(known or (item,))
    return list(dict.fromkeys(explained))


def _state_difference_requirements(
    target: str,
    participants: tuple[str, ...],
    candidates: CandidateSet,
    identities: dict[str, tuple[Requirement, ...]],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    cycle_requirements: list[Requirement],
    quantity: str,
) -> tuple[Requirement, ...]:
    requirements: list[Requirement] = []
    for state in participants:
        if state in identities:
            requirements.extend(identities[state])
        elif _unresolved_energy_state(state, candidates):
            requirements.append(
                Requirement(
                    "identity",
                    state,
                    "state_energy_identity",
                    "resolve the actual internal state before using a collective or inventory "
                    "reference quantity as one collision's endpoint energy",
                )
            )
    if requirements:
        return tuple(requirements)

    direct = "a qualified 0 K products-minus-reactants relation for the specified endpoints"
    formations = "0 K formation energies for the net endpoints on one common reference basis"
    if cycle_requirements:
        selection = [
            item for item in cycle_requirements if item.responsibility == "source_selection"
        ]
        return tuple(
            replace(item, reason=f"{item.reason}. Alternatively use {direct} or {formations}")
            for item in selection or cycle_requirements
        )

    have_formations = participants and all(
        any(
            item.reference and item.reference.temperature_K == 0
            for item in values.get((state, "enthalpy_formation_eV"), ())
        )
        for state in participants
    )
    if have_formations:
        return (
            Requirement(
                "source_information",
                target,
                "enthalpy_formation_eV",
                "the offered formation energies lack a common 0 K reference basis. "
                f"Reconcile those references or obtain {direct}",
            ),
        )
    return (
        Requirement("source_information", target, quantity, f"obtain {direct} or {formations}"),
    )


def _collision_budget(
    reaction: ReactionCandidate,
    difference: ThermochemicalCalculation,
    condition_applies: bool,
    relative: float | None,
    requirements: tuple[Requirement, ...],
) -> tuple[Assessment, ThermochemicalCalculation]:
    if not condition_applies:
        reason = COLLISION_CONDITION_NOT_APPLICABLE
        return _budget_result(VERDICT_NA, reason), ThermochemicalCalculation(
            "unavailable", None, "eV", reason, operation="collision_condition_not_applicable"
        )
    capture = fsum(term.n for term in reaction.products) == 1
    if requirement := _collision_model_requirement(reaction, capture):
        return _unresolved_budget(requirement)
    if difference.value is None:
        return _unresolved_budget(*difference.requirements, reason=difference.reason)
    if capture and difference.value < 0:
        return _budget_result(
            VERDICT_FAIL,
            "an isolated fixed single product cannot receive positive residual COM energy",
        ), ThermochemicalCalculation(
            "unavailable", None, "eV", "the isolated single-product exit has no energy sink"
        )
    if relative is None and not requirements:
        requirements = (
            Requirement(
                "user_inputs",
                reaction.id,
                "collision_energy_eV",
                "supply collision_energy_eV and its frame to calculate the energy margin",
            ),
        )
        if difference.value <= 0 and not capture:
            return _budget_result(
                VERDICT_PASS,
                "the nominal endpoint difference is nonpositive; nonnegative incoming relative "
                "energy satisfies this necessary condition; barriers and dynamics are undetermined",
            ), ThermochemicalCalculation(
                "needs_input", None, "eV", "incoming relative energy is unspecified", requirements
            )
    if relative is None or requirements:
        return _unresolved_budget(*requirements)
    residual = relative - difference.value
    valid = isclose(residual, 0.0, abs_tol=1e-12) if capture else residual >= 0
    margin = ThermochemicalCalculation(
        "computed",
        residual,
        "eV",
        "nominal COM input minus the retained endpoint state difference; "
        "no probability, barrier or energy partition is calculated",
        inputs=({"calculation": "state_energy_difference_eV", "coefficient": -1.0},),
        operation="relative_energy_minus_state_difference",
    )
    return _budget_result(
        VERDICT_PASS if valid else VERDICT_FAIL,
        f"nominal residual COM energy {residual:g} eV; "
        + (
            "isolated fixed single-product exit requires zero"
            if capture
            else "exit requires nonnegative energy"
        ),
    ), margin


def _collision_model_requirement(reaction: ReactionCandidate, capture: bool) -> Requirement | None:
    if reaction.third_body is not None:
        return Requirement(
            "external_models",
            reaction.id,
            "third_body_collision_energy",
            "the third body's incoming energy and exchange are not specified by a "
            "binary relative collision energy",
        )
    if fsum(term.n for term in reaction.reactants) != 2 or any(
        term.n != int(term.n) for term in (*reaction.reactants, *reaction.products)
    ):
        return Requirement(
            "external_models",
            reaction.id,
            "binary_collision_event",
            "a single relative collision energy applies to an explicit two-particle "
            "integer event, not a scaled or generic net stoichiometric equation",
        )
    stabilization = reaction.stabilization
    if stabilization not in {None, "unspecified", "isolated"}:
        return Requirement(
            "external_models",
            reaction.id,
            "collision_stabilization_model",
            f"the declared {stabilization} stabilization requires an energy exchange model "
            "beyond the isolated two-body balance",
        )
    if capture and stabilization != "isolated":
        return Requirement(
            "source_information",
            reaction.id,
            "capture_energy_exchange",
            "identify the product internal state and the energy exchange of this capture",
        )
    return None


def _unresolved_budget(
    *requirements: Requirement, reason: str | None = None
) -> tuple[Assessment, ThermochemicalCalculation]:
    message = reason or calculation_reason(requirements)
    status = (
        "needs_input"
        if requirements and all(item.responsibility == "user_inputs" for item in requirements)
        else "unavailable"
    )
    return _budget_result(VERDICT_UNKNOWN, message, requirements), ThermochemicalCalculation(
        status, None, "eV", message, requirements
    )


def _bound_endpoint_applicability(
    result: Assessment,
    reaction: ReactionCandidate,
    coefficients: dict[str, float],
    candidates: CandidateSet,
    state_assessments: dict[str, dict[str, Assessment]],
) -> Assessment:
    if result.verdict != VERDICT_PASS:
        return result
    capture = fsum(term.n for term in reaction.products) == 1 and reaction.third_body is None
    requirements, dependencies = _bound_endpoint_assumptions(
        coefficients, candidates, state_assessments, capture
    )
    if not requirements:
        return result
    return replace(
        result,
        verdict=VERDICT_UNKNOWN,
        message=calculation_reason(requirements),
        requirements=requirements,
        dependencies=dependencies,
    )


def _bound_endpoint_assumptions(
    coefficients: dict[str, float],
    candidates: CandidateSet,
    state_assessments: dict[str, dict[str, Assessment]],
    capture: bool,
) -> tuple[tuple[Requirement, ...], tuple[tuple[str, str], ...]]:
    """Limit the fixed-bound endpoint model without asserting state existence.

    An independent formation or reaction energy is still a usable formal
    difference when a ground endpoint is electron-unbound. It cannot turn that
    endpoint into a bound asymptotic particle. Missing binding is required only
    for a fixed single-product anion capture, not for every collision involving
    an unobserved state or a canceled spectator. Transient/resonant states are
    not reinterpreted here as unbound ground states.

    NIST's ion-thermochemistry definition places a bound ground negative ion
    below its neutral-plus-zero-energy-electron limit:
    https://webbook.nist.gov/chemistry/ion/ .
    """
    requirements = []
    dependencies = []
    for state_id, coefficient in coefficients.items():
        state = candidates.states[state_id]
        if state.state.kind != "ground":
            continue
        claims = state_assessments.get(state_id, {})
        existence = claims.get("state")
        if (
            existence is not None
            and existence.proposition == "state_existence_support"
            and existence.verdict == VERDICT_FAIL
        ):
            requirements.append(
                Requirement(
                    "external_models",
                    state_id,
                    "bound_ground_state_endpoint",
                    "reviewed evidence identifies this ground-state endpoint as unbound; "
                    "a formal energy difference does not supply a fixed bound particle; "
                    "identify the actual resonance/continuum state and its energy exchange",
                )
            )
            dependencies.append((state_id, "state"))
            continue
        if state.charge != -1:
            continue
        binding_key = (
            "state"
            if existence is not None and existence.proposition == "ground_anion_electron_binding"
            else "electron_binding"
        )
        binding = claims.get(binding_key)
        fixed_capture_product = capture and coefficient > 0
        if binding is not None and binding.verdict == VERDICT_FAIL:
            requirements.append(
                Requirement(
                    "external_models",
                    state_id,
                    "bound_ground_anion_endpoint",
                    "reviewed electron-binding evidence excludes a bound ground anion; "
                    "retain the formal energy difference but identify the actual "
                    "resonance/continuum endpoint before applying this collision model",
                )
            )
            dependencies.append((state_id, binding_key))
        elif fixed_capture_product and (binding is None or binding.verdict != VERDICT_PASS):
            requirements.extend(
                binding.requirements
                if binding is not None and binding.requirements
                else (
                    Requirement(
                        "source_information",
                        state_id,
                        "ground_anion_electron_binding",
                        "establish electron binding of the fixed ground-anion capture product; "
                        "a formal energy value or an existence assertion alone does not decide it",
                    ),
                )
            )
            if binding is not None:
                dependencies.append((state_id, binding_key))
    return tuple(dict.fromkeys(requirements)), tuple(sorted(set(dependencies)))


def _budget_result(
    verdict: str, message: str, requirements: tuple[Requirement, ...] = ()
) -> Assessment:
    return Assessment(
        verdict,
        ("calculation:state_energy_difference_eV", "calculation:collision_energy_margin_eV"),
        message,
        proposition="collision_energy_necessary_condition",
        scope="Nominal endpoint energy conservation for these states and declared collision "
        "conditions only; not a guaranteed uncertainty bound or reaction occurrence.",
        requirements=requirements,
    )


def collision_condition(
    reaction: ReactionCandidate, conditions: Conditions
) -> tuple[CollisionPair | Conditions, str] | None:
    """Bind a condition to the exact represented entrance pair, or keep the scalar input."""
    if not conditions.collision_pairs:
        return (conditions, "conditions") if _matches_legacy_roles(reaction, conditions) else None
    key = binary_collision_partners(reaction.reactants)
    if key is None:
        return None
    binding = conditions.collision_pair_index.get(key)
    if binding is None:
        return None
    index, pair = binding
    return pair, f"conditions.collision_pairs[{index}]"


def relative_collision_energy(
    reaction: ReactionCandidate,
    states: dict[str, StateCandidate],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    conditions: CollisionPair | Conditions,
    input_prefix: str,
    *,
    property_issues: dict[tuple[str, str], tuple[Requirement, ...]] | None = None,
) -> tuple[float | None, tuple[dict, ...], tuple[Requirement, ...]]:
    """Retain the matched input and resolve its COM energy when possible."""
    projectile, target = conditions.projectile_state, conditions.target_state
    source, energy, frame = _collision_energy_input(reaction, conditions)
    energy_input: dict = {
        "projectile_state": projectile,
        "target_state": target,
        "target_at_rest": conditions.target_at_rest,
    }
    if energy is None:
        if projectile is None and target is None:
            return None, (), ()
        energy_input["input"] = input_prefix
        return None, (energy_input,), ()
    energy_input.update(
        input=f"{input_prefix}.{source}",
        energy_eV=energy,
        frame=frame,
        requested_projectile_state=projectile,
        requested_target_state=target,
    )
    if frame == "com":
        energy_input["coefficient"] = 1.0
        return energy, (energy_input,), ()
    if frame != "lab":
        return (
            None,
            (energy_input,),
            (
                Requirement(
                    "user_inputs",
                    reaction.id,
                    "collision_energy_frame",
                    "declare com or lab for collision_energy_eV before comparing energies",
                ),
            ),
        )

    roles, requirements = _laboratory_roles(reaction, states, conditions, source, input_prefix)
    if roles is None:
        return None, (energy_input,), requirements
    projectile, target = roles
    energy_input.update(projectile_state=projectile, target_state=target)
    if projectile == target:
        energy_input.update(coefficient=0.5, operation="equal_represented_mass_cancellation")
        return energy / 2, (energy_input,), ()

    mp, mt = (_mass_input(state, values) for state in (projectile, target))
    if mp is None or mt is None:
        return (
            None,
            (energy_input,),
            tuple(
                requirement
                for state, mass in ((projectile, mp), (target, mt))
                if mass is None
                for requirement in _mass_requirements(state, values, property_issues or {})
            ),
        )
    fraction = mt[0] / (mp[0] + mt[0])
    energy_input["coefficient"] = fraction
    return fraction * energy, (mp[1], mt[1], energy_input), ()


def _collision_energy_input(
    reaction: ReactionCandidate, conditions: CollisionPair | Conditions
) -> tuple[str, float | None, str | None]:
    if conditions.collision_energy_eV is not None:
        return (
            "collision_energy_eV",
            conditions.collision_energy_eV,
            conditions.collision_energy_frame,
        )
    if isinstance(conditions, Conditions):
        if reaction.family == "electron" and conditions.electron_energy_eV is not None:
            return "electron_energy_eV", conditions.electron_energy_eV, "lab"
        if reaction.family == "ion" and conditions.ion_energy_eV is not None:
            return "ion_energy_eV", conditions.ion_energy_eV, "lab"
    return "collision_energy_eV", None, None


def _laboratory_roles(
    reaction: ReactionCandidate,
    states: dict[str, StateCandidate],
    conditions: CollisionPair | Conditions,
    source: str,
    input_prefix: str,
) -> tuple[tuple[str, str] | None, tuple[Requirement, ...]]:
    projectile, target = conditions.projectile_state, conditions.target_state
    if source == "electron_energy_eV":
        reactants = dict(side_key(reaction.reactants))
        if ELECTRON not in reactants or projectile not in {None, ELECTRON}:
            return (
                None,
                (
                    Requirement(
                        "user_inputs",
                        reaction.id,
                        "projectile_state",
                        "electron_energy_eV requires an incident electron; use collision_energy_eV "
                        "for a different projectile",
                    ),
                ),
            )
        projectile = ELECTRON
        if reactants[ELECTRON] == 1:
            other = tuple(state for state in reactants if state != ELECTRON)
            if target == ELECTRON:
                return (
                    None,
                    (
                        Requirement(
                            "user_inputs",
                            reaction.id,
                            "target_state",
                            "the single incoming electron cannot be both projectile and target",
                        ),
                    ),
                )
            if target is None and len(other) == 1:
                (target,) = other
    elif (
        source == "ion_energy_eV"
        and projectile is not None
        and (projectile == ELECTRON or states[projectile].charge == 0)
    ):
        return (
            None,
            (
                Requirement(
                    "user_inputs",
                    reaction.id,
                    "projectile_state",
                    "ion_energy_eV requires an incident ion; use collision_energy_eV "
                    "for a different projectile",
                ),
            ),
        )

    if projectile is None or target is None or conditions.target_at_rest is not True:
        needed = (
            ("projectile_state", projectile is None, "identify the actual projectile"),
            ("target_state", target is None, "identify the actual target"),
            (
                "target_at_rest",
                conditions.target_at_rest is not True,
                "confirm a stationary target, or specify the relative COM energy directly",
            ),
        )
        return (
            None,
            tuple(
                Requirement(
                    "user_inputs", reaction.id, quantity, f"for {input_prefix}.{source}, {reason}"
                )
                for quantity, missing, reason in needed
                if missing
            ),
        )
    return (projectile, target), ()


def _matches_legacy_roles(reaction: ReactionCandidate, conditions: Conditions) -> bool:
    projectile, target = conditions.projectile_state, conditions.target_state
    roles = {state for state in (projectile, target) if state is not None}
    participants = {term.species for term in reaction.reactants}
    return roles.issubset(participants) and not (
        projectile is not None
        and projectile == target
        and sum(term.n for term in reaction.reactants if term.species == projectile) < 2
    )


def _mass_input(
    state_id: str, values: dict[tuple[str, str], tuple[EnergyInput, ...]]
) -> tuple[float, dict] | None:
    if state_id == ELECTRON:
        return 0.0005485799090441, {"constant": "electron_mass_u_CODATA2022"}
    available = values.get((state_id, "mass_amu"), ())
    if available and all(isclose(x.value, available[0].value) for x in available):
        return available[0].value, available[0].term(1.0)
    return None


def _mass_requirements(
    state: str,
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    property_issues: dict[tuple[str, str], tuple[Requirement, ...]],
) -> tuple[Requirement, ...]:
    key = (state, "mass_amu")
    if issues := property_issues.get(key):
        return issues
    if key in values:
        return (Requirement("source_selection", *key, "select a compatible nominal mass"),)
    return (Requirement("source_information", *key, "obtain a reviewed nominal mass"),)


def _proton_transfer_calculations(
    reaction: ReactionCandidate,
    net: dict[str, float],
    candidates: CandidateSet,
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    alternatives: dict[tuple[str, str], tuple[EnergyInput, ...]],
) -> dict[str, ThermochemicalCalculation]:
    if reaction.family not in {"ion", "neutral"}:
        return {}
    endpoints = _proton_transfer_endpoints(net, candidates)
    results = {}
    for quantity, output in (
        ("proton_affinity_eV", "proton_transfer_delta_h_eV"),
        ("gas_basicity_eV", "proton_transfer_delta_g_eV"),
    ):
        offered, missing = _proton_affinity_differences(
            reaction.id, endpoints, alternatives, quantity
        )
        if not offered and not missing:
            continue
        selected, selected_missing = _proton_affinity_differences(
            reaction.id, endpoints, values, quantity
        )
        result = _proton_affinity_calculation(
            reaction.id, quantity, selected, offered, selected_missing or missing
        )
        results[output] = replace(
            result, alternatives=_difference_alternatives(result, offered, {})
        )
    return results


def _proton_affinity_calculation(
    target: str,
    quantity: str,
    selected: list[EnergyDifference],
    offered: list[EnergyDifference],
    missing: tuple[Requirement, ...],
) -> ThermochemicalCalculation:
    first = selected[0] if selected else None
    if first is not None and all(
        item.conditions == first.conditions
        and isclose(item.value, first.value, rel_tol=1e-9, abs_tol=1e-10)
        for item in selected
    ):
        return ThermochemicalCalculation(
            "computed",
            first.value,
            "eV",
            "same-temperature conjugate-pair affinity difference; this finite-T quantity "
            "is not used in a single-collision energy budget",
            conditions=first.conditions,
            inputs=first.inputs,
            operation=first.operation,
        )
    if first is not None or offered:
        reason = (
            "complete affinity differences disagree or describe distinct reference conditions; "
            "select the applicable conjugate-pair records"
            if first is not None
            else "the requested selection supplies no complete conjugate-pair difference; "
            "inspect the retained alternative records and conditions"
        )
        missing = (Requirement("source_selection", target, quantity, reason),)
    return ThermochemicalCalculation(
        "unavailable", None, "eV", calculation_reason(missing), missing
    )


def _proton_transfer_endpoints(
    net: dict[str, float],
    candidates: CandidateSet,
) -> list[tuple[str, str, str, str]]:
    incoming = tuple(state for state, n in net.items() if n == -1)
    outgoing = tuple(state for state, n in net.items() if n == 1)
    if ELECTRON in net or len(net) != 4 or len(incoming) != 2 or len(outgoing) != 2:
        return []
    # Ordered (donor base, donor adduct, acceptor base, acceptor adduct).
    return [
        (base, donor, acceptor, adduct)
        for donor, acceptor in (incoming, incoming[::-1])
        for base, adduct in (outgoing, outgoing[::-1])
        if _proton_conjugate(base, donor, candidates)
        and _proton_conjugate(acceptor, adduct, candidates)
    ]


def _proton_affinity_differences(
    target: str,
    endpoints: list[tuple[str, str, str, str]],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    quantity: str,
) -> tuple[list[EnergyDifference], tuple[Requirement, ...]]:
    results = []
    missing = []
    for base, donor, acceptor, adduct in endpoints:
        donors = [item for item in values.get((base, quantity), ()) if item.related_state == donor]
        acceptors = [
            item for item in values.get((acceptor, quantity), ()) if item.related_state == adduct
        ]
        if donors and acceptors:
            for a in donors:
                for b in acceptors:
                    difference = _proton_affinity_difference(target, quantity, a, b)
                    if isinstance(difference, EnergyDifference):
                        results.append(difference)
                    else:
                        missing.append(difference)
        elif donors or acceptors:
            state, conjugate = (acceptor, adduct) if donors else (base, donor)
            missing.append(
                Requirement(
                    "source_information",
                    state,
                    quantity,
                    f"obtain a qualified {quantity} for the conjugate pair {state} / {conjugate}",
                )
            )
    return results, tuple(dict.fromkeys(missing))


def _proton_affinity_difference(
    target: str, quantity: str, donor: EnergyInput, acceptor: EnergyInput
) -> EnergyDifference | Requirement:
    a, b = donor.reference, acceptor.reference
    if a is None or b is None or a.temperature_K is None or a.temperature_K != b.temperature_K:
        return Requirement(
            "source_information",
            target,
            f"{quantity}.reference_temperature_K",
            "obtain both conjugate-pair affinities at a common reference temperature",
        )
    conditions = {"proton_transfer_delta_h_reference_temperature_K": a.temperature_K}
    operation = "proton_affinity_difference"
    if quantity == "gas_basicity_eV":
        if a.standard_pressure_Pa is None or a.standard_pressure_Pa != b.standard_pressure_Pa:
            return Requirement(
                "source_information",
                target,
                "gas_basicity_eV.standard_pressure_Pa",
                "gas basicities require a common declared standard pressure or an explicit "
                "standard-state conversion; PA and zero-K differences are independent",
            )
        conditions = {
            "proton_transfer_delta_g_reference_temperature_K": a.temperature_K,
            "proton_transfer_delta_g_standard_pressure_Pa": a.standard_pressure_Pa,
        }
        operation = "gas_basicity_difference"
    value = donor.value - acceptor.value
    if not isfinite(value):
        return Requirement(
            "source_information", target, quantity, "verify affinity values and their units"
        )
    return EnergyDifference(value, operation, (donor.term(1.0), acceptor.term(-1.0)), conditions)


def _proton_conjugate(base_id: str, adduct_id: str, candidates: CandidateSet) -> bool:
    base, adduct = candidates.states[base_id], candidates.states[adduct_id]
    expected = base.composition | {"H": base.composition.get("H", 0) + 1}
    return (
        adduct.composition == expected
        and adduct.charge == base.charge + 1
        and (base.phase == adduct.phase == "gas")
        and not _unresolved_energy_state(base_id, candidates)
        and not _unresolved_energy_state(adduct_id, candidates)
    )
