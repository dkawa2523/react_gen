"""Explicit propositions about candidate equations, evidence, and energy.

Numerical-data use is a separate result: unusable data never deny a reaction.
An energy value alone is not a positive feasibility judgement.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from math import fsum, isclose, isfinite
from typing import TypeVar, cast

from reactgen.balance import Balance, conservation, retained_nuclide_correspondence
from reactgen.case import Conditions
from reactgen.chemistry import (
    electron_partition_process,
    electron_state,
    merge,
    parse_equation,
    parse_state_id,
    subtract,
)
from reactgen.energy import (
    EnergyInput,
    EnergyRelation,
    EnergyRelations,
    endpoint_order_issue,
    ground_reference_state,
    physical_coefficients,
    signature,
)
from reactgen.evidence import (
    EvidenceCatalog,
    ReactionEvidence,
    StateEvidence,
    bound_molecular_participants,
    molecular_reference_id,
)
from reactgen.model import (
    ELECTRON,
    VERIFIED_STRUCTURE_BASIS,
    Assessment,
    CandidateSet,
    ReactionCandidate,
    Requirement,
    ScientificRecordReference,
    StateCandidate,
    StateKey,
    Term,
    ThermochemicalCalculation,
    bind_transformation_states,
    coefficient_availability_verdict,
    participant_support_verdict,
    validate_stoichiometric_terms,
)
from reactgen.numeric import DataUse, data_use
from reactgen.records import (
    REVIEWED_TIERS,
    TIER_RANK,
    FormationReference,
    Property,
    ReactionRecord,
    StateRecord,
    Thermo,
    calculation_record_reference,
    channel_energy_status,
    energy_declarations_agree,
    energy_properties_equivalent,
    property_energy_bounds,
    property_has_point_qualifier,
    qualified_channel_energy,
    reaction_energy_definition_compatible,
    review_scope_covers,
    scientific_reaction_content,
    selectable_state_record_id,
)
from reactgen.screening import (
    COLLISION_CONDITION_NOT_APPLICABLE,
    calculation_reason,
    collision_condition,
    relative_collision_energy,
    screening_calculations,
)
from reactgen.selection import DataSelection, QuantitySelection
from reactgen.structure import (
    StructureUnavailable,
    charge_target_correspondence,
    endpoint_structure_matches,
    physical_equation_key,
    physical_state_id,
    physical_state_key,
    resonant_charge_correspondence,
    structure_key,
    validate_graph_transformation,
)
from reactgen.thermo import (
    formation_delta,
    formation_reference,
    net_electron_coefficient,
    net_stoichiometry,
    reference_pressure,
    thermal_values,
    valid_thermo,
)
from reactgen.units import energy_eV

VERDICT_PASS = "pass"  # noqa: S105 - scientific verdict, not a credential
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_NA = "not_applicable"
StateQuantity = TypeVar("StateQuantity", Property, Thermo)


@dataclass
class Evaluation:
    state_assessments: dict[str, dict[str, Assessment]]
    reaction_assessments: dict[str, dict[str, Assessment]]
    state_evidence: dict[str, StateEvidence]
    reaction_evidence: dict[str, ReactionEvidence]
    energy_values: dict[str, dict[str, float]] = field(default_factory=dict)
    data_use: dict[str, DataUse] = field(default_factory=dict)
    thermochemical_calculations: dict[str, dict[str, ThermochemicalCalculation]] = field(
        default_factory=dict
    )
    calculation_sources: dict[str, ReactionRecord] = field(default_factory=dict)
    calculation_state_records: dict[str, tuple[StateRecord, ...]] = field(default_factory=dict)
    calculation_reference_state_ids: tuple[str, ...] = ()

    @property
    def thermochemistry(self) -> Mapping[str, dict[str, float]]:
        """Read view combining auxiliary energies with successful calculations."""
        return _ThermochemistryView(self.energy_values, self.thermochemical_calculations)


class _ThermochemistryView(Mapping[str, dict[str, float]]):
    """Project each reaction on access, without copying all reaction values."""

    def __init__(
        self,
        energies: dict[str, dict[str, float]],
        calculations: dict[str, dict[str, ThermochemicalCalculation]],
    ) -> None:
        self.energies, self.calculations = energies, calculations

    def __getitem__(self, key: str) -> dict[str, float]:
        values = _combined_thermal_values(
            self.energies.get(key, {}), self.calculations.get(key, {})
        )
        if not values:
            raise KeyError(key)
        return values

    def __iter__(self) -> Iterator[str]:
        return (
            key for key in sorted(self.energies.keys() | self.calculations.keys()) if self.get(key)
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)


def evaluate(
    candidates: CandidateSet,
    catalog: EvidenceCatalog,
    conditions: Conditions,
    selection: DataSelection | None = None,
) -> Evaluation:
    if selection is not None and not isinstance(selection, DataSelection):
        raise ValueError("selection must be a validated DataSelection")
    references = _screening_reference_states(candidates.states, catalog)
    if selection is not None:
        selection.validate_targets(
            candidates.states, candidates.reactions, reference_states=references
        )
    catalog.validate_targets(candidates)
    state_evidence = {
        state_id: replace(catalog.state(state), selection=selection, target=state_id)
        for state_id, state in candidates.states.items()
    }
    reference_evidence = {
        state_id: replace(catalog.state(state), selection=selection, target=state_id)
        for state_id, state in references.items()
    }
    energy_states = candidates.states | references
    energy_evidence = state_evidence | reference_evidence
    state_assessments = {
        state_id: _evaluate_state(state, energy_states, energy_evidence)
        for state_id, state in candidates.states.items()
    }
    identity_requirements = {
        state: tuple(
            item for item in claims["state"].requirements if item.responsibility == "identity"
        )
        for state, claims in state_assessments.items()
        if any(item.responsibility == "identity" for item in claims["state"].requirements)
    }
    reaction_evidence = {
        reaction_id: catalog.reaction(reaction)
        for reaction_id, reaction in candidates.reactions.items()
    }
    reaction_assessments = {}
    energy_values = {}
    calculations = {}
    numerical_use = {}
    screening_values = _screening_inputs(energy_evidence)
    alternative_values = _screening_inputs(energy_evidence, apply_selection=False)
    screening_issues = _screening_property_issues(
        energy_evidence, screening_values, alternative_values
    )
    screening_relations = _screening_relations(catalog, energy_states)
    for reaction_id, reaction in candidates.reactions.items():
        evidence = reaction_evidence[reaction_id]
        balance = _checked_balance(reaction, candidates)
        conservation_result = _conservation_assessment(reaction, balance)
        consistency = _consistency_assessment(reaction, candidates, balance)
        thermo, values, thermal_calculations = _evaluate_thermochemistry(
            reaction,
            candidates,
            state_evidence,
            evidence,
            conditions,
            screening_values,
            conservation=conservation_result,
            screening_property_issues=screening_issues,
        )
        kinetics, use = assess_kinetics(
            reaction, evidence, conditions, selection, conservation=conservation_result
        )
        if values:
            energy_values[reaction_id] = values
        calculations[reaction_id] = thermal_calculations
        level_transitions = _validated_level_transitions(reaction, candidates, consistency)
        screening, energy = screening_calculations(
            reaction,
            candidates,
            screening_values,
            screening_relations,
            conditions,
            selection,
            alternative_values,
            energy_states=energy_states,
            identity_requirements=identity_requirements,
            property_issues=screening_issues,
            state_assessments=state_assessments,
            level_transitions=level_transitions,
            conservation=conservation_result,
        )
        consistency = _directional_level_consistency(
            reaction, candidates, consistency, level_transitions, screening.get("level_gap_1_eV")
        )
        thermal_calculations.update(screening)
        numerical_use[reaction_id] = use
        reaction_assessments[reaction_id] = {
            "consistency": consistency,
            "state": assess_reaction_states(reaction, state_assessments),
            "thermochemistry": thermo,
            "reaction_evidence": assess_reaction_evidence(
                reaction,
                evidence,
                catalog.materials,
            ),
            "kinetics": kinetics,
            "conservation": conservation_result,
            "energy": energy,
        }
    requested_references = (
        reference_evidence.keys() & (selection.targets if selection else {}).keys()
    )
    reaction_sources, state_sources = _calculation_declarations(
        calculations,
        catalog.reaction_records,
        reference_evidence,
        state_assessments,
        requested_references,
    )
    return Evaluation(
        state_assessments,
        reaction_assessments,
        state_evidence,
        reaction_evidence,
        energy_values,
        numerical_use,
        calculations,
        reaction_sources,
        state_sources,
        tuple(sorted(state_sources.keys() | requested_references)),
    )


def _calculation_declarations(
    calculations: dict[str, dict[str, ThermochemicalCalculation]],
    reaction_records: tuple[ReactionRecord, ...],
    reference_evidence: dict[str, StateEvidence],
    state_assessments: dict[str, dict[str, Assessment]],
    requested_references: set[str],
) -> tuple[dict[str, ReactionRecord], dict[str, tuple[StateRecord, ...]]]:
    """Retain declarations needed to explain selected and alternative results."""
    used_records: dict[tuple[str, str], set[str]] = {}
    for claims in state_assessments.values():
        for assessment in claims.values():
            for source in assessment.record_inputs:
                used_records.setdefault((source.target, source.record_id), set()).add(
                    source.record_ref
                )
    for term in (
        term
        for collection in calculations.values()
        for calculation in collection.values()
        for term in (
            *calculation.inputs,
            *(
                entry
                for alternative in calculation.alternatives
                for entry in alternative.get("inputs", ())
            ),
        )
    ):
        if "record_ref" in term:
            source_key = term["target"], term["record_id"]
            used_records.setdefault(source_key, set()).add(term["record_ref"])
    reviewed_relations = {
        requirement.target
        for collection in calculations.values()
        for calculation in collection.values()
        for requirement in calculation.requirements
        if requirement.responsibility == "source_review" and requirement.quantity == "delta_e_eV"
    }
    reaction_sources: dict[str, ReactionRecord] = {}
    reserved_ids = {record.id for record in reaction_records}
    for reaction_record in reaction_records:
        cited_refs = used_records.get((reaction_record.id, reaction_record.id))
        if reaction_record.id in reviewed_relations or (
            cited_refs and calculation_record_reference(reaction_record) in cited_refs
        ):
            storage_key = reaction_record.id
            if storage_key in reaction_sources:
                storage_key = calculation_record_reference(reaction_record)
                while storage_key in reserved_ids:
                    storage_key = f"~{storage_key}"
            reaction_sources.setdefault(storage_key, reaction_record)
    state_sources = {
        state_id: records
        for state_id, evidence in reference_evidence.items()
        if evidence.match == "exact"
        and (
            records := tuple(
                record
                for record in evidence.records
                if state_id in requested_references
                or (
                    (refs := used_records.get((state_id, selectable_state_record_id(record))))
                    and calculation_record_reference(record) in refs
                )
            )
        )
    }
    return reaction_sources, state_sources


def _evaluate_state(
    state: StateCandidate,
    reference_states: Mapping[str, StateCandidate],
    evidence: dict[str, StateEvidence],
) -> dict[str, Assessment]:
    matched = evidence[state.id]
    binding = (
        _assess_anion_from_affinity(state, reference_states, evidence)
        if state.charge == -1 and state.state.kind == "ground"
        else None
    )
    support = _state_assessment(state, matched, binding)
    claims = {
        "consistency": assess_state_consistency(state),
        "state": support,
        "thermochemistry": assess_state_thermochemistry(state, matched),
    }
    if binding is not None and support.proposition != binding.proposition:
        claims["electron_binding"] = binding
    return claims


def assess_state_consistency(state: StateCandidate) -> Assessment:
    """Check the candidate representation; this does not identify a physical state."""
    return replace(
        _state_consistency(state),
        proposition="state_representation_consistency",
        scope=(
            "Composition and integer charge of this candidate and validation of any "
            "explicit SMILES. Physical identity and existence are undetermined."
        ),
    )


def _state_consistency(state: StateCandidate) -> Assessment:
    if state.id == ELECTRON:
        valid = not state.composition and state.charge == -1
        return Assessment(VERDICT_PASS if valid else VERDICT_FAIL, ("electron carrier",), "")
    if (
        not state.composition
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count <= 0
            for count in state.composition.values()
        )
        or isinstance(state.charge, bool)
        or not isinstance(state.charge, int)
    ):
        return Assessment(VERDICT_FAIL, ("formula",), "composition is empty or non-positive")
    basis: tuple[str, ...] = ("parsed formula", "integer charge")
    if state.structure and state.structure.startswith("smiles:"):
        try:
            structure_key(state)
        except StructureUnavailable as error:
            return Assessment(
                VERDICT_UNKNOWN,
                basis,
                str(error),
                requirements=(
                    Requirement("external_models", state.id, "structure_validation", str(error)),
                ),
            )
        except ValueError as error:
            return Assessment(VERDICT_FAIL, basis, str(error))
        basis += (VERIFIED_STRUCTURE_BASIS,)
    return Assessment(VERDICT_PASS, basis, "candidate representation is well formed")


def assess_state(
    state: StateCandidate,
    evidence: StateEvidence,
    candidates: CandidateSet,
    all_evidence: dict[str, StateEvidence] | None = None,
) -> Assessment:
    binding = (
        _assess_anion_from_affinity(state, candidates.states, all_evidence)
        if all_evidence is not None and state.charge == -1 and state.state.kind == "ground"
        else None
    )
    return _state_assessment(state, evidence, binding)


def _state_assessment(
    state: StateCandidate, evidence: StateEvidence, binding: Assessment | None
) -> Assessment:
    if state.state.kind == "composition":
        return Assessment(
            VERDICT_UNKNOWN,
            ("composition hypothesis",),
            "this nuclear inventory and charge do not identify an actual structure "
            "or internal state",
            proposition="state_identity_resolution",
            scope="The generated inventory hypothesis; not an observed or bound molecular state.",
            requirements=(
                Requirement(
                    "identity",
                    state.id,
                    "state_identity",
                    "identify an actual structure and state before assigning its existence "
                    "or state energy",
                ),
            ),
        )
    result = _assess_state_support(state, evidence, binding)
    if result.proposition == "ground_anion_electron_binding":
        return result
    return replace(
        result,
        proposition="state_existence_support",
        scope=(
            "Evidence supporting the represented state identity; its population, "
            "lifetime and reaction rates are undetermined."
        ),
    )


def _assess_state_support(
    state: StateCandidate,
    evidence: StateEvidence,
    binding: Assessment | None,
) -> Assessment:
    if state.id == ELECTRON:
        return Assessment(VERDICT_PASS, ("physical carrier",), "electron is explicitly represented")
    if evidence.match == "ambiguous":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "several identity records match this state",
            requirements=(
                Requirement(
                    "identity",
                    state.id,
                    "state_identity",
                    "disambiguate the matching phase, structure and physical state",
                ),
            ),
        )
    if evidence.match == "exact":
        recorded = _assess_exact_state(state, evidence)
        if (
            recorded.verdict == VERDICT_UNKNOWN
            and binding is not None
            and binding.verdict != VERDICT_UNKNOWN
            and all(
                not review_scope_covers(record.review_scope, "state_existence")
                or (record.existence in {"unknown", "transient"} and record.status != "conflicting")
                for record in evidence.records
            )
        ):
            # Unknown or short-lived declarations do not decide electron
            # binding. Retain its independent evidence, without overriding an
            # explicit bound, unbound, hypothetical, or conflicting assertion.
            return binding
        return recorded
    if evidence.match == "compatible":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "related state records exist but do not attest this candidate representation",
            requirements=(
                Requirement(
                    "identity",
                    state.id,
                    "state_identity",
                    "identify evidence for this exact phase, structure and physical state",
                ),
            ),
        )
    if "feed" in state.classes and state.state.kind == "ground":
        return Assessment(
            VERDICT_UNKNOWN,
            ("case input",),
            "input gas is a generation seed, not evidence that the state exists",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "state_existence",
                    (
                        "obtain existence evidence for this exact state; repeating the input "
                        "gas does not supply it"
                    ),
                ),
            ),
        )
    if binding is not None:
        return binding
    return Assessment(
        VERDICT_UNKNOWN,
        (),
        "no state record matches this candidate",
        requirements=(
            Requirement(
                "source_information",
                state.id,
                "state_existence",
                "obtain evidence supporting or excluding this exact state",
            ),
        ),
    )


def _assess_exact_state(state: StateCandidate, evidence: StateEvidence) -> Assessment:
    declarations = tuple(
        record for record in evidence.records if record.existence in {"confirmed", "unbound"}
    )
    reviewed = tuple(
        record
        for record in declarations
        if record.tier in REVIEWED_TIERS
        and review_scope_covers(record.review_scope, "state_existence")
    )
    declared_conflicts = tuple(
        record
        for record in evidence.records
        if record in reviewed
        or (record.status == "conflicting" and "state_existence" in record.review_scope)
    )
    if _state_existence_conflicts(declared_conflicts):
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "reviewed existence assertions conflict for this exact state identity",
            requirements=(
                Requirement(
                    "source_review",
                    state.id,
                    "state_existence",
                    (
                        "resolve the contradictory reviewed existence assertions for this exact"
                        " identity"
                    ),
                ),
            ),
        )
    qualified = [
        record for record in declarations if record.reviewed and record.existence_source is not None
    ]
    if qualified:
        excluded = qualified[0].existence == "unbound"
        return Assessment(
            VERDICT_FAIL if excluded else VERDICT_PASS,
            tuple(sorted({record.label for record in qualified})),
            "the source explicitly identifies this state as unbound"
            if excluded
            else "reviewed existence evidence supports this identity; population is undetermined",
        )
    if not declarations:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "short lifetime is declared; this alone does not establish or exclude a bound state"
            if any(record.existence == "transient" for record in evidence.records)
            else "no supporting or excluding existence assertion is supplied for this state",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "state_existence",
                    (
                        "obtain evidence supporting or excluding this exact state; numerical "
                        "properties, lifetime and hypothetical labels do not establish existence"
                    ),
                ),
            ),
        )
    requirements = []
    if any(record.existence_source is not None for record in declarations) or not any(
        record.reviewed for record in declarations
    ):
        requirements.append(
            Requirement(
                "source_review",
                state.id,
                "state_existence",
                "review the supplied existence assertion independently of numerical properties",
            )
        )
    if not any(record.existence_source is not None for record in declarations):
        requirements.append(
            Requirement(
                "source_information",
                state.id,
                "existence_source",
                "identify the evidence supporting the supplied existence assertion",
            )
        )
    return Assessment(
        VERDICT_UNKNOWN,
        evidence.sources,
        "the supplied existence assertions lack review or a supporting source",
        requirements=tuple(requirements),
    )


def _state_existence_conflicts(records: tuple[StateRecord, ...]) -> bool:
    """Conflicting existence evidence does not change the matched physical target."""
    if any(
        record.status == "conflicting"
        and review_scope_covers(record.review_scope, "state_existence")
        for record in records
    ):
        return True
    assertions = {
        record.existence
        for record in records
        if record.reviewed
        and record.existence_source
        and record.existence in {"confirmed", "unbound"}
    }
    return len(assertions) > 1


def _assess_anion_from_affinity(
    state: StateCandidate,
    states: Mapping[str, StateCandidate],
    evidence: dict[str, StateEvidence],
) -> Assessment:
    parent = ground_reference_state(state, states, 0)
    matched = evidence.get(parent.id) if parent is not None else None
    if parent is None:
        result = Assessment(
            VERDICT_UNKNOWN,
            (),
            "a unique corresponding neutral parent is missing",
            requirements=(
                Requirement(
                    "identity",
                    state.id,
                    "neutral_parent",
                    "identify a unique corresponding neutral ground state with the same "
                    "phase and structure",
                ),
            ),
        )
    else:
        result = (
            _electron_binding_support(matched)
            if matched is not None
            else Assessment(VERDICT_UNKNOWN, (), "no state record or electron affinity")
        )
        if result.verdict == VERDICT_UNKNOWN and not result.requirements:
            result = replace(
                result,
                requirements=_energy_requirements(parent.id, matched, "electron_affinity_eV"),
            )
    return replace(
        result,
        proposition="ground_anion_electron_binding",
        scope=(
            "Electron-detachment binding of the corresponding ground anion; "
            "lifetime, population, stabilization and occurrence are undetermined."
        ),
    )


def _electron_binding_support(evidence: StateEvidence) -> Assessment:
    """Judge electron detachment binding, not lifetime or stability to other reactions.

    A positive EA range supports binding; a negative range excludes it. Only
    the explicit ``unbound`` qualifier declares electron nonbinding. IUPAC's
    ``unstable`` and ``transient`` concern thermodynamic comparison and lifetime,
    respectively, and do not supply that declaration. A contradictory or
    unresolved numerical declaration never becomes a definite exclusion.
    """
    name = "electron_affinity_eV"
    offers = _property_offers(evidence, name) if evidence.match == "exact" else []
    properties = [prop for _, prop in offers]
    bounds, sources = _bounds_from_offers(offers)
    record_inputs: tuple[ScientificRecordReference, ...] = ()
    if evidence.target is not None:
        record_inputs = tuple(
            sorted(
                {
                    ScientificRecordReference(
                        evidence.target,
                        name,
                        selectable_state_record_id(record),
                        calculation_record_reference(record),
                    )
                    for record, _ in offers
                }
            )
        )
        sources = (*sources, *(item.record_id for item in record_inputs))

    def result(verdict: str, message: str) -> Assessment:
        return Assessment(verdict, sources, message, record_inputs=record_inputs)

    if not properties:
        return result(VERDICT_UNKNOWN, "no reviewed electron affinity declaration")
    if _property_declarations_conflict(name, properties):
        return result(VERDICT_UNKNOWN, "reviewed electron affinity declarations conflict")
    if any(_explicit_electron_nonbinding(prop) for prop in properties):
        if any(prop.value is not None for prop in properties) and (
            bounds is None or bounds[1] >= 0.0
        ):
            return result(
                VERDICT_UNKNOWN,
                "unbound declaration and electron affinity range do not establish "
                "a consistent electron nonbinding conclusion",
            )
        return result(VERDICT_FAIL, "reviewed evidence explicitly declares electron nonbinding")
    if bounds is not None and bounds[1] < 0.0:
        return result(VERDICT_FAIL, "negative electron affinity range excludes electron binding")
    if bounds is not None and bounds[0] > 0.0:
        return result(VERDICT_PASS, "positive electron affinity range supports electron binding")
    return result(VERDICT_UNKNOWN, "electron affinity evidence is inconclusive")


def _explicit_electron_nonbinding(prop: Property) -> bool:
    return _affinity_qualifier(prop) == "unbound"


def _affinity_qualifier(prop: Property) -> str | None:
    """Normalize interpreted EA words; retain unknown qualifiers as declared."""
    word = (prop.qualifier or "").strip().lower()
    if word == "unbound":
        return word
    return None if word in {"", "unstable", "transient"} else prop.qualifier


def assess_state_thermochemistry(
    state: StateCandidate,
    evidence: StateEvidence,
) -> Assessment:
    result = _state_thermochemistry(state, evidence)
    return replace(
        result,
        scope=(
            "Availability of a reviewed thermochemical representation; use at a "
            "particular temperature and physical existence are undetermined."
        ),
    )


def _state_thermochemistry(
    state: StateCandidate,
    evidence: StateEvidence,
) -> Assessment:
    """Report a non-conflicting reviewed representation, not its use at a given T."""
    proposition = "thermochemical_representation_availability"
    if state.id == ELECTRON:
        return Assessment(VERDICT_NA, ("zero reference convention",), "", proposition)
    if evidence.match != "exact":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            f"thermochemical quantity identity is not exact ({evidence.match})",
            proposition,
            requirements=(
                Requirement(
                    "source_information" if evidence.match == "none" else "identity",
                    state.id,
                    "thermochemical_representation"
                    if evidence.match == "none"
                    else "thermochemical_target",
                    (
                        "obtain a thermochemical representation for the exact phase, structure "
                        "and state"
                    ),
                ),
            ),
        )
    selected = _preferred_state(state.id, {state.id: evidence})
    conflicts = _thermochemical_conflicts(evidence)
    if selected is not None and _trusted_thermochemistry(selected):
        note = "a non-conflicting reviewed thermochemical representation is available"
        if conflicts:
            note += "; other thermochemical declarations conflict: " + ", ".join(conflicts)
        note += "; applicability at a specified temperature is undetermined"
        return Assessment(VERDICT_PASS, _thermochemistry_sources(selected), note, proposition)
    if conflicts:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "reviewed thermochemical declarations conflict: " + ", ".join(conflicts),
            proposition,
            requirements=tuple(
                Requirement(
                    "source_review",
                    state.id,
                    quantity,
                    "resolve the conflicting scientific declarations for this quantity",
                )
                for quantity in conflicts
            ),
        )
    selection_requirements = tuple(
        requirement
        for quantity in ("enthalpy_formation_eV", "thermochemical_model")
        for requirement in _state_selection_requirement(evidence, quantity)
    )
    if selection_requirements:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "the requested data selection excludes available thermochemical representations",
            proposition,
            requirements=selection_requirements,
        )
    useful = [
        record
        for record in evidence.records
        if evidence.match == "exact"
        and (record.thermo is not None or record.value("enthalpy_formation_eV") is not None)
    ]
    if not useful:
        return Assessment(
            VERDICT_UNKNOWN,
            (),
            "formation enthalpy or NASA coefficients are missing",
            proposition,
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "thermochemical_representation",
                    (
                        "supply a finite formation enthalpy or NASA7 representation for this "
                        "exact state"
                    ),
                ),
            ),
        )
    if (
        selected is not None
        and selected.thermo is not None
        and (selected.thermo.phase != state.phase)
    ):
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "the stated thermochemical model phase does not identify this state phase",
            proposition,
            requirements=(
                Requirement(
                    "identity" if state.phase == "unknown" else "source_review",
                    state.id,
                    "phase" if state.phase == "unknown" else "thermochemical_model.phase",
                    "identify the state phase or correct the model target; matching composition "
                    "does not make a gas model a representation of another phase",
                ),
            ),
        )
    return Assessment(
        VERDICT_UNKNOWN,
        tuple(record.label for record in useful),
        "thermochemical declarations are unreviewed, invalid, or not identified exactly",
        proposition,
        requirements=(
            Requirement(
                "source_review",
                state.id,
                "thermochemical_representation",
                (
                    "review or correct the supplied thermochemical declaration; its "
                    "numerical existence alone is insufficient"
                ),
            ),
        ),
    )


def _trusted_thermochemistry(record: StateRecord) -> bool:
    enthalpy = record.properties.get("enthalpy_formation_eV")
    return _qualified_thermal_representation(record) is not None or (
        enthalpy is not None
        and enthalpy.reviewed_for("enthalpy_formation_eV")
        and _eV_value(record, "enthalpy_formation_eV") is not None
    )


def _qualified_thermal_representation(record: StateRecord) -> Thermo | None:
    """Source/model shape and target phase, without a temperature-use decision."""
    thermo = record.thermo
    return (
        thermo
        if thermo is not None
        and thermo.reviewed_for("thermochemical_model")
        and valid_thermo(thermo)
        and thermo.phase == record.candidate.phase
        else None
    )


def _thermochemistry_sources(record: StateRecord) -> tuple[str, ...]:
    sources = set()
    if (prop := record.properties.get("enthalpy_formation_eV")) is not None and _eV_value(
        record, "enthalpy_formation_eV"
    ) is not None:
        sources.add(prop.source or record.label)
    if (thermo := _qualified_thermal_representation(record)) is not None:
        sources.add(thermo.source or record.label)
    return tuple(sorted(sources))


def assess_consistency(reaction: ReactionCandidate, candidates: CandidateSet) -> Assessment:
    """Check bookkeeping and the declared process pattern, not physical occurrence."""
    result = _consistency_assessment(reaction, candidates, _checked_balance(reaction, candidates))
    if reaction.process not in {
        *_DIRECTIONAL_ELECTRON_LEVELS,
        *_DIRECTIONAL_HEAVY_LEVELS,
        "penning_ionization",
    }:
        return result
    pairs = _validated_level_transitions(reaction, candidates, result)
    return _directional_level_consistency(reaction, candidates, result, pairs)


def _checked_balance(reaction: ReactionCandidate, candidates: CandidateSet) -> Balance | Assessment:
    try:
        validate_stoichiometric_terms(reaction.reactants)
        validate_stoichiometric_terms(reaction.products)
    except ValueError as error:
        return Assessment(VERDICT_FAIL, ("stoichiometry",), str(error))
    return conservation(reaction.reactants, reaction.products, candidates.states)


def _consistency_assessment(
    reaction: ReactionCandidate, candidates: CandidateSet, balance: Balance | Assessment
) -> Assessment:
    result = (
        balance
        if isinstance(balance, Assessment)
        else _equation_consistency(reaction, candidates, balance)
    )
    return replace(
        result,
        proposition="equation_consistency",
        scope=(
            "Element and charge accounting, participant family and defined process "
            "pattern; occurrence, activation and rates are undetermined."
        ),
    )


def _equation_consistency(
    reaction: ReactionCandidate, candidates: CandidateSet, result: Balance
) -> Assessment:
    if result.missing:
        return Assessment(
            VERDICT_FAIL,
            ("state index",),
            f"unknown states: {', '.join(result.missing)}",
        )
    family_problem = _family_problem(reaction, candidates)
    if family_problem is not None:
        return Assessment(VERDICT_FAIL, ("collision participants",), family_problem)
    if reaction.surface is None and not result.charge_conserved:
        return Assessment(
            VERDICT_FAIL,
            ("charge conservation",),
            f"charge {result.left_charge:+g} -> {result.right_charge:+g}; "
            f"difference {result.charge_difference:+g}",
        )
    if not result.elements_conserved and reaction.surface is None:
        return Assessment(
            VERDICT_FAIL,
            ("element conservation",),
            f"elements {result.left_elements} -> {result.right_elements}; "
            f"differences {result.element_differences}",
        )
    if result.isotope_conflicts and reaction.surface is None:
        return Assessment(
            VERDICT_FAIL,
            ("isotope conservation",),
            "explicit isotope labels cannot balance for " + ", ".join(result.isotope_conflicts),
        )
    pattern = _process_pattern(reaction, candidates)
    if pattern is False:
        return Assessment(
            VERDICT_FAIL,
            ("process equation pattern",),
            f"equation does not match the {reaction.process} participant/state pattern",
        )
    if not result.elements_conserved:
        return Assessment(
            VERDICT_UNKNOWN,
            (f"surface reservoir:{reaction.surface}",),
            "gas-phase element balance needs explicit surface stoichiometry",
            requirements=(
                Requirement(
                    "source_information",
                    reaction.id,
                    "surface_stoichiometry",
                    "specify the surface species and stoichiometry exchanged with the gas phase",
                ),
            ),
        )
    if pattern is None:
        return _unresolved_process_pattern(reaction, result.charge_conserved)
    return _consistent_result(reaction, result.charge_conserved)


_CHARGE_TRANSFER_PROCESSES = {
    "charge_exchange",
    "resonant_charge_exchange",
    "mutual_neutralization",
}
_GROUP_TRANSFER_PROCESSES = {"net_group_transfer", "ligand_transfer"}


def _unresolved_process_pattern(reaction: ReactionCandidate, charge_conserved: bool) -> Assessment:
    process = reaction.process
    if reaction.third_body is None and process in {
        *_CHARGE_TRANSFER_PROCESSES,
        *_GROUP_TRANSFER_PROCESSES,
        "net_group_exchange",
    }:
        if process == "resonant_charge_exchange":
            quantity = "resonant_charge_correspondence"
            message = "the ion and neutral cannot yet be identified as the same nuclear system"
        elif process in _GROUP_TRANSFER_PROCESSES:
            quantity = "group_transfer_correspondence"
            message = "the group transfer's per-particle nuclear correspondence is unresolved"
        elif process == "net_group_exchange":
            quantity = "group_exchange_correspondence"
            message = "the exchanged groups and retained nuclear inventories are unresolved"
        else:
            quantity = "charge_transfer_correspondence"
            message = "the charge transfer's per-particle nuclear correspondence is unresolved"
        requirement = Requirement(
            "identity",
            reaction.id,
            quantity,
            "resolve isotope and structure identity for the corresponding participants",
        )
    else:
        mapping_pending = (
            bool(reaction.transformation)
            and process in _HEAVY_FRAGMENTS
            and reaction.third_body is None
        )
        message = (
            "the declared fragmentation mapping could not be verified"
            if mapping_pending
            else f"process {process!r} has no defined equation pattern. "
            "Element and charge balance are accounted for. Process consistency is undetermined"
        )
        requirement = Requirement(
            "external_models",
            reaction.id,
            f"process_pattern:{process}",
            "verify the declared parent, fragments and collision partner with the "
            "structures and graph support needed for the mapping"
            if mapping_pending
            else "define the participant and state pattern for this physical process",
        )
    return Assessment(
        VERDICT_UNKNOWN,
        _balance_basis(reaction, charge_conserved),
        message,
        requirements=(requirement,),
    )


def _family_problem(reaction: ReactionCandidate, candidates: CandidateSet) -> str | None:
    """Check the declared carriers and reservoir, without inventing missing context."""
    for name in ("surface", "third_body"):
        value = getattr(reaction, name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return f"{name} must identify a nonempty reservoir or collision partner"
    if reaction.family == "surface" and reaction.surface is None:
        return "a surface process requires an explicit material reservoir"
    if reaction.surface is not None and reaction.family in {"electron", "ion", "neutral"}:
        return "an explicit surface reservoir contradicts the declared gas-collision family"
    if reaction.family in {"electron", "ion", "neutral"} and any(
        phase != "unknown" for phase in candidates.nongas_participants(reaction).values()
    ):
        return "a nongas participant contradicts the declared gas-collision family"
    electron = any(term.species == ELECTRON for term in reaction.reactants)
    charged = any(
        candidates.states[term.species].charge
        for term in reaction.reactants
        if term.species != ELECTRON
    )
    if reaction.family == "electron" and not electron:
        return "an electron process requires an incident electron"
    if reaction.family == "ion" and electron:
        return "an incident electron belongs to the electron family, not an ion collision family"
    if reaction.family == "ion" and not charged:
        return "an ion process requires a charged heavy reactant"
    if reaction.family == "neutral" and (electron or charged):
        return "a neutral process has a charged reactant"
    return None


def _balance_basis(reaction: ReactionCandidate, charge_conserved: bool) -> tuple[str, ...]:
    return (
        "element conservation",
        "charge conservation"
        if charge_conserved
        else f"surface charge reservoir:{reaction.surface}",
    )


def _consistent_result(reaction: ReactionCandidate, charge_conserved: bool) -> Assessment:
    basis = (*_balance_basis(reaction, charge_conserved), "process equation pattern")
    notes = "equation, family, and process agree; physical occurrence is undetermined"
    if reaction.surface is not None and not charge_conserved:
        notes = "gas charge changes under the explicit surface-reservoir convention"
    if reaction.process in _ELECTRON_CHARGE_CHANGES or reaction.process in {
        "charge_exchange",
        "collision_ionization",
        "collisional_detachment",
        "dissociative_charge_transfer",
        "mutual_neutralization",
        "penning_ionization",
    }:
        notes += ". The formula match leaves any unverified structures unresolved"
    if (
        reaction.process in {"attachment", "recombination", "association"}
        and not reaction.third_body
    ):
        notes += (
            "; energy stabilization is unspecified"
            if reaction.stabilization in {None, "unspecified"}
            else f"; stabilization convention:{reaction.stabilization}"
        )
    if reaction.process == "dissociation" and reaction.family in {"neutral", "ion"}:
        notes += "; activation mechanism and product energy partition are undetermined"
    return Assessment(VERDICT_PASS, basis, notes)


def _conservation_assessment(
    reaction: ReactionCandidate, result: Balance | Assessment
) -> Assessment:
    requirements: tuple[Requirement, ...] = ()
    if reaction.surface is not None:
        verdict, message = VERDICT_NA, "the gas-only balance excludes the material reservoir"
    elif isinstance(result, Assessment):
        verdict, message = result.verdict, result.message
    elif result.missing:
        verdict, message = VERDICT_UNKNOWN, "participant identities are missing"
    elif not result.elements_conserved or not result.charge_conserved:
        verdict = VERDICT_FAIL
        message = (
            f"element differences {result.element_differences}; "
            f"charge difference {result.charge_difference:g}"
        )
    elif result.isotope_conflicts:
        verdict = VERDICT_FAIL
        elements = ", ".join(result.isotope_conflicts)
        message = f"explicit isotope labels cannot balance for {elements}"
    elif result.isotope_unresolved:
        verdict = VERDICT_UNKNOWN
        elements = ", ".join(result.isotope_unresolved)
        message = f"element and charge balance hold; incomplete isotope identities for {elements}"
        requirements = (
            Requirement(
                "identity",
                reaction.id,
                "isotopic_composition",
                f"identify the isotope labels for {elements} in the unmatched participants",
            ),
        )
    else:
        verdict, message = VERDICT_PASS, "represented nuclear and charge inventories balance"
    return Assessment(
        verdict,
        ("declared reactant/product inventories",),
        message,
        proposition="element_charge_conservation",
        scope="Element and charge inventories, with explicit isotope identities when represented.",
        requirements=requirements,
    )


@dataclass(frozen=True)
class _Participants:
    left: list[StateCandidate]
    right: list[StateCandidate]
    left_n: float
    right_n: float
    left_e: float
    right_e: float
    same_composition: bool
    same_species: bool
    charge_redistributed: bool
    integer_molecularity: bool

    @property
    def one_parent(self) -> bool:
        return self.left_n == 1 and len(self.left) == 1

    @property
    def parent_sign(self) -> int:
        if not self.left or not self.left[0].charge:
            return 0
        return 1 if self.left[0].charge > 0 else -1

    @property
    def collision(self) -> bool:
        return self.integer_molecularity and self.left_e == self.right_e == 0 and self.left_n == 2


def _participants(reaction: ReactionCandidate, candidates: CandidateSet) -> _Participants:
    sides = []
    bags: list[dict[tuple, float]] = []
    charge_bags: list[dict[tuple, float]] = []
    for terms in (reaction.reactants, reaction.products):
        heavy = [term for term in terms if term.species != ELECTRON]
        expandable = sum(term.n for term in heavy) <= 5 and all(
            term.n in {1.0, 2.0, 3.0} for term in heavy
        )
        sides.append(
            [
                candidates.states[term.species]
                for term in heavy
                for _ in range(int(term.n) if expandable else 1)
            ]
        )
        bag: dict[tuple, float] = {}
        charge_bag: dict[tuple, float] = {}
        for term in terms:
            if term.species != ELECTRON:
                state = candidates.states[term.species]
                key = tuple(sorted(state.composition.items()))
                bag[key] = bag.get(key, 0.0) + term.n
                charge_key = (key, state.phase, state.structure, state.charge)
                charge_bag[charge_key] = charge_bag.get(charge_key, 0.0) + term.n
        bags.append(bag)
        charge_bags.append(charge_bag)
    return _Participants(
        sides[0],
        sides[1],
        sum(term.n for term in reaction.reactants if term.species != ELECTRON),
        sum(term.n for term in reaction.products if term.species != ELECTRON),
        sum(term.n for term in reaction.reactants if term.species == ELECTRON),
        sum(term.n for term in reaction.products if term.species == ELECTRON),
        bags[0] == bags[1],
        reaction.equation_key[2] == reaction.equation_key[3],
        charge_bags[0] != charge_bags[1],
        all(float(term.n).is_integer() for term in (*reaction.reactants, *reaction.products)),
    )


def _process_pattern(reaction: ReactionCandidate, candidates: CandidateSet) -> bool | None:
    """Check a pattern in its declared family, without inventing an inducer.

    True/False concerns a defined participant/state pattern. None means the
    family or inducing process has no applicable pattern. Formula shape alone
    does not establish an elementary mechanism, rate, spin, or stabilization.
    """
    if reaction.family not in {"electron", "ion", "neutral", "surface"}:
        return None
    participants = _participants(reaction, candidates)
    if reaction.process == "isotope_exchange" and (
        reaction.family != "neutral"
        or not participants.collision
        or participants.right_n != 2
        or any(term.n != 1 for term in (*reaction.reactants, *reaction.products))
    ):
        return False
    declared = _transformation_pattern(reaction, candidates, participants)
    if declared is False:
        return False
    ordinary = (
        True
        if reaction.process == "net_group_exchange" and declared is True
        else _participant_pattern(reaction, participants)
    )
    if (
        ordinary is True
        and declared is None
        and reaction.transformation
        and reaction.process
        in {
            *_HEAVY_FRAGMENTS,
            *_CHARGE_TRANSFER_PROCESSES,
            *_GROUP_TRANSFER_PROCESSES,
            "net_group_exchange",
        }
    ):
        return None
    # A role map supports state correspondence. A named direction or exact
    # resonance also requires the corresponding physical pattern.
    independent = reaction.process in {"excitation", "deexcitation", "resonant_charge_exchange"}
    pattern = declared if declared is True and ordinary is None and not independent else ordinary
    if (
        pattern is True
        and reaction.third_body is not None
        and reaction.process != "three_body_association"
    ):
        # An implicit collider changes molecularity. Existing binary patterns
        # do not establish that additional collision model; a contradiction
        # of the named process itself still remains False.
        return None
    return pattern


def _participant_pattern(reaction: ReactionCandidate, participants: _Participants) -> bool | None:
    process = reaction.process
    if process == "elastic":
        return (
            participants.integer_molecularity
            and participants.same_species
            and participants.left_n + participants.left_e == 2
        )
    if process.startswith("net_") or process in {"associative_detachment", "level_transfer"}:
        return _net_pattern(reaction, participants)
    if process in {
        "isotope_exchange",
        "radical_recombination",
        "radical_addition",
        "insertion",
        "substitution",
        "coordinate_addition",
    }:
        return None  # A formula pattern cannot establish a local graph edit.
    if process == "three_body_association":
        return (
            reaction.third_body is not None
            and reaction.surface is None
            and participants.left_n + participants.left_e == 2
            and participants.right_n + participants.right_e == 1
        )
    if process in {"surface_recombination", "surface_neutralization"}:
        return reaction.family == "surface" and reaction.surface is not None
    if reaction.family == "electron":
        electron_pattern = _electron_pattern(process, participants)
        if electron_pattern is not None:
            return electron_pattern and reaction.surface is None
        # A defined heavy-particle process can contradict this family, but an
        # unrecognized process is not made false merely for missing support.
        return _heavy_pattern(reaction, participants)
    if reaction.family in {"neutral", "ion"}:
        return _heavy_pattern(reaction, participants)
    return None


_DIRECTIONAL_ELECTRON_LEVELS = {"excitation": 1, "deexcitation": -1}


_ELECTRON_CHARGE_CHANGES = {
    "ionization": (2, 1, 0),
    "attachment": (0, -1, 0),
    "recombination": (0, -1, 1),
    "detachment": (2, 1, -1),
}


def _electron_pattern(process: str, p: _Participants) -> bool | None:
    if process in _ELECTRON_CHARGE_CHANGES:
        emitted, difference, sign = _ELECTRON_CHARGE_CHANGES[process]
        parent_sign_matches = p.parent_sign == sign or (
            process == "ionization" and p.parent_sign == 1
        )
        return (
            p.left_e == 1
            and p.right_e == emitted
            and p.one_parent
            and p.right_n == 1
            and len(p.right) == 1
            and parent_sign_matches
            and p.right[0].charge == p.left[0].charge + difference
            and _charge_change_target(p.left[0], p.right[0])
        )
    if process in {
        "dissociation",
        "dissociative_ionization",
        "dissociative_attachment",
        "dissociative_recombination",
        "dissociative_detachment",
        "ion_pair_formation",
    }:
        charges = (state.charge for state in p.right)
        return (
            p.left_e == 1
            and p.one_parent
            and p.right_n >= 2
            and p.right_e in {0, 1, 2}
            and electron_partition_process(p.left[0].charge, p.right_e, charges) == process
        )
    if process in _DIRECTIONAL_ELECTRON_LEVELS:
        valid = (
            p.left_e == p.right_e == 1
            and p.one_parent
            and p.right_n == 1
            and len(p.right) == 1
            and _internal_state_change(p.left[0], p.right[0])
        )
        if not valid:
            return False
        if p.left[0].state.kind != "ground" and p.right[0].state.kind != "ground":
            return True  # The signed gap determines the direction after endpoint reduction.
        return (
            p.right[0].state.kind != "ground"
            if process == "excitation"
            else p.left[0].state.kind != "ground"
        )
    return None


_HEAVY_FRAGMENTS = {
    "collision_induced_dissociation": "holding",
    "projectile_dissociation": "holding",
    "dissociation_with_level_transfer": "level_transfer",
    "dissociative_charge_transfer": "charge_transfer",
    "collisional_detachment": "detachment",
    "dissociative_detachment": "detachment",
}

_DIRECTIONAL_HEAVY_LEVELS = {
    "ion_induced_excitation": ("ion", 1),
    "ion_induced_deexcitation": ("ion", -1),
    "quenching": ("neutral", -1),
    "v_t_relaxation": ("neutral", -1),
}


def _heavy_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    process = reaction.process
    if process in {"dissociation", "association"}:
        return _heavy_combination_pattern(reaction, p)
    if process in {"charge_exchange", "resonant_charge_exchange"}:
        valid = (
            reaction.family == "ion"
            and p.collision
            and p.right_n == len(p.left) == len(p.right) == 2
            and p.integer_molecularity
            and p.same_composition
            and any(state.charge for state in p.left)
        )
        if process == "resonant_charge_exchange":
            if not (valid and p.same_species and any(state.charge == 0 for state in p.left)):
                return False
            return resonant_charge_correspondence(p.left[0], p.left[1])
        return _charge_redistribution(p) if valid and not p.same_species else False
    if process in _DIRECTIONAL_HEAVY_LEVELS:
        return bool(_state_transfer_roles(reaction, p))
    if process == "penning_ionization":
        return _collision_ionization_pattern(reaction, p)
    if process == "mutual_neutralization":
        valid = (
            reaction.family == "ion"
            and p.collision
            and p.right_n == len(p.left) == len(p.right) == 2
            and p.same_composition
            and sorted(state.charge for state in p.left) == [-1, 1]
            and all(state.charge == 0 for state in p.right)
        )
        return _charge_redistribution(p) if valid else False
    if process in _HEAVY_FRAGMENTS:
        return _collision_fragment_pattern(reaction, p)
    return _heavy_reactive_pattern(reaction, p)


def _heavy_reactive_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    process = reaction.process
    if process in {"ligand_transfer", "radical_abstraction"}:
        transfers = [
            (group, match)
            for group, charge, match in _inventory_transfers(
                p, require_partition_change=process != "radical_abstraction"
            )
            if charge == 0
        ]
        if process == "radical_abstraction":
            return None if any(group == {"H": 1} for group, _ in transfers) else False
        return _role_verdict(match for _, match in transfers)
    if process == "reactive_scattering":
        return p.collision and p.right_n >= 2 and not p.same_species
    if process in {"ionization", "collision_ionization"}:
        if process == "ionization" and p.left_e == 0 and p.left_n == 1:
            return None
        return _collision_ionization_pattern(reaction, p)
    if process == "associative_ionization":
        return p.left_e == 0 and p.left_n == 2 and p.right_e == 1 and p.right_n == 1
    return None


def _collision_ionization_pattern(
    reaction: ReactionCandidate, p: _Participants, declared: dict | None = None
) -> bool:
    return next(_collision_ionization_matches(reaction, p, declared), None) is not None


def _collision_ionization_matches(
    reaction: ReactionCandidate, p: _Participants, declared: dict | None = None
) -> Iterator[tuple[StateCandidate, StateCandidate, StateCandidate, StateCandidate]]:
    """Yield matched target, ion product, collider and collider product."""
    penning = reaction.process == "penning_ionization"
    if not (
        reaction.family in {"neutral", "ion"}
        and (not penning or reaction.family == "neutral")
        and p.left_e == 0
        and p.right_e == 1
        and p.left_n == p.right_n == len(p.left) == len(p.right) == 2
    ):
        return
    for target, collider in (p.left, p.left[::-1]):
        for product, counterpart in (p.right, p.right[::-1]):
            if (
                target.charge < 0
                or product.charge != target.charge + 1
                or not _charge_change_target(target, product)
                or not (
                    collider.key == counterpart.key
                    or _internal_state_change(
                        collider,
                        counterpart,
                        allow_missing_structure=penning and declared is None,
                    )
                )
                or (
                    penning
                    and (collider.state.manifold != "electronic" or collider.key == counterpart.key)
                )
            ):
                continue
            if declared is None:
                yield target, product, collider, counterpart
            elif declared.get("kind") == "penning":
                if (
                    declared.get("donor") == collider.id
                    and declared.get("donor_product") == counterpart.id
                    and declared.get("target") == target.id
                ):
                    yield target, product, collider, counterpart
            elif (
                declared.get("parent") == target.id
                and declared.get("product") == product.id
                and declared.get("collider") == collider.id
                and declared.get("collider_product", collider.id) == counterpart.id
            ):
                yield target, product, collider, counterpart


def _charge_redistribution(p: _Participants) -> bool | None:
    left, right = p.left
    options = [
        (charge_target_correspondence(left, a), charge_target_correspondence(right, b))
        for a, b in (p.right, p.right[::-1])
        if a.charge != left.charge and b.charge - right.charge == left.charge - a.charge
    ]
    if (True, True) in options:
        return True
    return None if any(False not in option for option in options) else False


def _heavy_combination_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    """Check one-parent fragmentation or two-entity association equations.

    These are deliberately minimum equation patterns, using IUPAC dissociation
    D01801 and association A00472 (A + B -> AB is also the example in 08184).
    Their agreement does not prove a microscopic single step or a stable
    product. Other collision- or photon-induced fragmentation, and higher
    molecularity association, need their own declared process/model.
    """
    if (
        reaction.family not in {"neutral", "ion"}
        or p.left_e != 0
        or p.right_e != 0
        or reaction.surface is not None
    ):
        return False
    if reaction.process == "dissociation":
        if not p.one_parent or reaction.third_body is not None:
            return None
        return p.right_n >= 2
    if p.left_n > 2 and p.right_n == 1:
        return None
    return p.collision and p.right_n == 1 and reaction.third_body is None


def _state_transfer_roles(reaction: ReactionCandidate, p: _Participants) -> set[tuple[str, str]]:
    process = reaction.process
    family, direction = _DIRECTIONAL_HEAVY_LEVELS[process]
    if reaction.family != family:
        return set()
    roles = set()
    for changes in _heavy_level_matches(p):
        if len(changes) != 1:
            continue
        ((initial, final),) = changes
        upper, lower = (initial, final) if direction < 0 else (final, initial)
        if upper.state.kind == "ground":
            continue
        if process == "v_t_relaxation" and (
            upper.state.manifold != "vibrational"
            or lower.state.manifold not in {"vibrational", "ground"}
        ):
            continue
        roles.add((initial.id, final.id))
    return roles


def _heavy_level_matches(
    p: _Participants,
) -> Iterator[tuple[tuple[StateCandidate, StateCandidate], ...]]:
    if not (
        p.integer_molecularity
        and p.collision
        and p.right_n == 2
        and len(p.left) == len(p.right) == 2
    ):
        return
    for right in (p.right, p.right[::-1]):
        changes = tuple((a, b) for a, b in zip(p.left, right, strict=True) if a.key != b.key)
        if all(_internal_state_change(a, b) for a, b in changes):
            yield changes


def _directional_level_consistency(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    consistency: Assessment,
    transitions: tuple[tuple[str, str], ...],
    gap: ThermochemicalCalculation | None = None,
) -> Assessment:
    if consistency.verdict != VERDICT_PASS:
        return consistency
    if reaction.process == "penning_ionization":
        # The donor must release internal energy (IUPAC Gold Book 12520).
        direction = -1
    elif reaction.family == "electron" and reaction.process in _DIRECTIONAL_ELECTRON_LEVELS:
        direction = _DIRECTIONAL_ELECTRON_LEVELS[reaction.process]
    elif reaction.process in _DIRECTIONAL_HEAVY_LEVELS:
        _, direction = _DIRECTIONAL_HEAVY_LEVELS[reaction.process]
    else:
        return consistency
    # IUPAC V06615 and Q05007 describe loss of excitation. The existing signed
    # state gap decides nominal direction independently of available collision energy.
    expected = "increase" if direction > 0 else "decrease"
    if gap is not None and gap.value is not None:
        supported = gap.value * direction > 0
        return replace(
            consistency,
            verdict=VERDICT_PASS if supported else VERDICT_FAIL,
            basis=(*consistency.basis, "calculation:level_gap_1_eV"),
            message=(
                f"equation pattern and nominal level gap ({gap.value:g} eV) support "
                f"the declared internal-energy {expected}. Physical occurrence is undetermined"
                if supported
                else f"nominal level gap ({gap.value:g} eV) contradicts the declared "
                f"internal-energy {expected}"
            ),
        )
    if len(transitions) == 1:
        initial, final = transitions[0]
        lower = candidates.states[initial if direction > 0 else final]
        if lower.state.kind == "ground":
            return consistency
    requirements = gap.requirements if gap is not None else ()
    if not requirements:
        requirement = (
            Requirement(
                "identity",
                reaction.id,
                "internal_level_correspondence",
                "identify the initial and final states of the same participant",
            )
            if len(transitions) != 1
            else Requirement(
                "source_information",
                reaction.id,
                "internal_level_gap",
                "provide the signed internal-energy gap between the represented levels",
            )
        )
        requirements = (requirement,)
    return replace(
        consistency,
        verdict=VERDICT_UNKNOWN,
        message=f"Equation pattern matches. The declared internal-energy {expected} is unresolved",
        requirements=requirements,
    )


def _role_verdict(matches: Iterator[bool | None]) -> bool | None:
    verdicts = set(matches)
    return True if True in verdicts else None if None in verdicts else False


def _inventory_transfers(
    p: _Participants, *, require_partition_change: bool = True
) -> Iterator[tuple[dict[str, int], int, bool | None]]:
    """Two conjugate inventory changes, without claiming a microscopic path."""
    if not _two_particle_products(p) or (require_partition_change and p.same_composition):
        return
    for donor, acceptor in (p.left, p.left[::-1]):
        for dproduct, aproduct in (p.right, p.right[::-1]):
            result = _group_transfer(donor, acceptor, dproduct, aproduct)
            if result is not None and result[2] is not False:
                yield result


def _two_particle_products(p: _Participants) -> bool:
    return p.collision and p.right_n == len(p.left) == len(p.right) == 2


def _group_transfer(
    donor: StateCandidate,
    acceptor: StateCandidate,
    donor_product: StateCandidate,
    acceptor_product: StateCandidate,
) -> tuple[dict[str, int], int, bool | None] | None:
    group = _positive_composition_difference(donor.composition, donor_product.composition)
    received = _positive_composition_difference(acceptor_product.composition, acceptor.composition)
    charge = donor.charge - donor_product.charge
    if group is None or received != group or acceptor_product.charge - acceptor.charge != charge:
        return None
    match = retained_nuclide_correspondence(
        (donor, donor_product, donor_product.composition),
        (acceptor, acceptor_product, acceptor.composition),
    )
    return group, charge, match


def _positive_composition_difference(
    whole: dict[str, int], part: dict[str, int]
) -> dict[str, int] | None:
    result = {element: whole.get(element, 0) - part.get(element, 0) for element in whole | part}
    return (
        {element: n for element, n in result.items() if n}
        if all(n >= 0 for n in result.values()) and any(result.values())
        else None
    )


def _collision_fragment_pattern(
    reaction: ReactionCandidate, p: _Participants, declared: dict | None = None
) -> bool | None:
    mode = _HEAVY_FRAGMENTS.get(reaction.process)
    if (
        mode is None
        or not p.integer_molecularity
        or reaction.family not in {"ion", "neutral"}
        or (mode in {"detachment", "charge_transfer"} and reaction.family != "ion")
        or p.left_n != 2
        or len(p.left) != 2
        or p.right_n != len(p.right)
        or p.left_e != 0
    ):
        return False
    outgoing = 1 if mode == "detachment" else 0
    intact_detachment = reaction.process == "collisional_detachment"
    if p.right_e != outgoing or (p.right_n != 2 if intact_detachment else p.right_n < 3):
        return False
    if declared is not None:
        count = declared.get("outgoing_electrons", outgoing)
        if type(count) is not int or count != outgoing:
            return False
    graph = declared if declared is not None and declared.get("kind") == "graph_edit" else None
    matches = _collision_fragment_matches(p, mode, declared)
    if graph is None:
        return next(matches, None) is not None
    if mode not in {"holding", "level_transfer"}:
        return False
    # The collider's exit is validated by the role match. Only the declared
    # parent participates in this bond edit, so the collider needs no graph.
    replays = {
        validate_graph_transformation((parent,), tuple(fragments), graph, process="dissociation")
        for parent, fragments in matches
    }
    return True if True in replays else (None if None in replays else False)


def _collision_fragment_matches(
    p: _Participants, mode: str, declared: dict | None
) -> Iterator[tuple[StateCandidate, list[StateCandidate]]]:
    for parent, collider in (p.left, p.left[::-1]):
        for index, counterpart in enumerate(p.right):
            fragments = p.right[:index] + p.right[index + 1 :]
            if declared is not None and not _fragment_roles(
                declared, parent, collider, counterpart, fragments
            ):
                continue
            if _fragment_exit(fragments, parent, collider, counterpart, mode):
                yield parent, fragments


def _fragment_roles(
    declared: dict,
    parent: StateCandidate,
    collider: StateCandidate,
    counterpart: StateCandidate,
    fragments: list[StateCandidate],
) -> bool:
    if declared.get("parent") != parent.id or declared.get("collider") != collider.id:
        return False
    if declared.get("kind") == "detachment":
        return (
            len(fragments) == 1
            and declared.get("product") == fragments[0].id
            and counterpart.key == collider.key
        )
    ids = declared.get("fragments")
    return (
        declared.get("collider_product") == counterpart.id
        and isinstance(ids, list)
        and len(ids) in {2, 3}
        and all(isinstance(item, str) for item in ids)
        and sorted(ids) == sorted(fragment.id for fragment in fragments)
    )


def _fragment_exit(
    fragments: list[StateCandidate],
    parent: StateCandidate,
    collider: StateCandidate,
    counterpart: StateCandidate,
    mode: str,
) -> bool:
    same_collider = (
        _charge_change_target(collider, counterpart)
        if mode == "charge_transfer"
        else _same_nuclei(collider, counterpart)
    )
    if not same_collider:
        return False
    composition: dict[str, int] = {}
    for fragment in fragments:
        if fragment.phase != parent.phase:
            return False
        for element, n in fragment.composition.items():
            composition[element] = composition.get(element, 0) + n
    if composition != parent.composition:
        return False
    charge_change = sum(fragment.charge for fragment in fragments) - parent.charge
    if mode == "charge_transfer":
        return counterpart.charge != collider.charge and (
            charge_change == collider.charge - counterpart.charge
        )
    if mode == "level_transfer":
        return charge_change == 0 and _internal_state_change(collider, counterpart)
    if counterpart.key != collider.key:
        return False
    if mode == "detachment":
        return (
            parent.charge < 0
            and charge_change == 1
            and (len(fragments) != 1 or _charge_change_target(parent, fragments[0]))
        )
    return charge_change == 0


def _charge_change_target(initial: StateCandidate, final: StateCandidate) -> bool:
    """Test the formula pattern without assuming unknown isotope identity."""
    return charge_target_correspondence(initial, final) is not False


def _same_nuclei(
    left: StateCandidate, right: StateCandidate, *, allow_missing_structure: bool = False
) -> bool:
    return (
        left.composition == right.composition
        and left.phase == right.phase
        and (
            physical_state_key(left)[-1] == physical_state_key(right)[-1]
            or (allow_missing_structure and None in {left.structure, right.structure})
        )
    )


def _internal_state_change(
    initial: StateCandidate, final: StateCandidate, *, allow_missing_structure: bool = False
) -> bool:
    return (
        _same_nuclei(initial, final, allow_missing_structure=allow_missing_structure)
        and initial.charge == final.charge
        and initial.state != final.state
        and "composition" not in {initial.state.kind, final.state.kind}
    )


def _net_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    process = reaction.process
    if process == "net_group_transfer":
        return _role_verdict(match for _, _, match in _inventory_transfers(p))
    if process == "net_group_exchange":
        return _exchange_pattern(p)
    if process == "net_association_loss":
        return p.collision and p.right_n == 2 and not p.same_composition
    if process == "net_association":
        return p.collision and p.right_n == 1
    if process == "associative_detachment":
        return (
            p.left_e == 0
            and p.right_e == 1
            and p.left_n == 2
            and p.right_n == 1
            and any(state.charge < 0 for state in p.left)
        )
    if process == "level_transfer":
        if reaction.family == "electron":
            return (
                p.left_e == p.right_e == 1
                and p.one_parent
                and p.right_n == len(p.right) == 1
                and _internal_state_change(p.left[0], p.right[0])
            )
        valid = next(_heavy_level_matches(p), None) is not None
        # A state exchange can have the same initial and final inventories.
        # Only a role map distinguishes it from unchanged internal states.
        return None if valid and p.same_species else valid
    return None


def _transformation_pattern(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    participants: _Participants,
    declared: dict | None = None,
) -> bool | None:
    if declared is None:
        declared = reaction.transformation
    if not declared:
        return None
    if declared.get("kind") == "alternatives":
        alternatives = declared.get("alternatives")
        if not isinstance(alternatives, list):
            return False
        answers = [
            _transformation_pattern(reaction, candidates, participants, item)
            for item in alternatives
            if isinstance(item, dict)
        ]
        return True if True in answers else (None if None in answers else False)
    return _declared_transform_pattern(reaction, candidates, participants, declared)


def _declared_transform_pattern(
    reaction: ReactionCandidate, candidates: CandidateSet, p: _Participants, declared: dict
) -> bool | None:
    kind = declared.get("kind")
    if (
        (kind is not None and not isinstance(kind, str))
        or (reaction.process == "isotope_exchange" and kind != "graph_edit")
        or reaction.process not in _INVENTORY_MAP_PROCESSES.get(kind or "", (reaction.process,))
    ):
        return False
    if kind == "group_transfer":
        return _mapped_transfer(declared, reaction, candidates, p)
    if kind == "group_exchange":
        return _mapped_exchange(declared, p, candidates)
    if kind == "charge_transfer":
        return _mapped_charge_transfer(declared, reaction, candidates)
    if kind in {"collision_partition", "detachment"} or (
        kind == "graph_edit" and reaction.process in _HEAVY_FRAGMENTS
    ):
        return _collision_fragment_pattern(reaction, p, declared)
    if kind in {"collision_ionization", "penning"}:
        return reaction.process in {
            "collision_ionization",
            "ionization",
            "penning_ionization",
        } and _collision_ionization_pattern(reaction, p, declared)
    if kind in {"level_transition", "two_level_transition"}:
        return _mapped_level_pattern(declared, reaction, candidates, p)
    if kind == "graph_edit":
        # A graph edit only checks the cut. Electron partition rules check the charge class.
        process = (
            "dissociation"
            if reaction.family == "electron" and reaction.process == "ion_pair_formation"
            else reaction.process
        )
        return validate_graph_transformation(
            tuple(p.left), tuple(p.right), declared, process=process
        )
    if not _transformation_references(reaction, declared):
        return False
    return None


_INVENTORY_MAP_PROCESSES = {
    "charge_transfer": _CHARGE_TRANSFER_PROCESSES,
    "group_transfer": _GROUP_TRANSFER_PROCESSES,
    "group_exchange": {"net_group_exchange"},
}


def _transformation_references(reaction: ReactionCandidate, declared: dict) -> bool:
    for keys, terms in (
        (("parent", "collider", "initial", "donor", "acceptor"), reaction.reactants),
        (("collider_product", "final", "product", "fragments"), reaction.products),
    ):
        present = {term.species for term in terms}
        for key in keys:
            if key not in declared:
                continue
            references = declared[key] if isinstance(declared[key], list) else [declared[key]]
            if any(not isinstance(item, str) or item not in present for item in references):
                return False
    return True


def _mapped_charge_transfer(
    declared: dict, reaction: ReactionCandidate, candidates: CandidateSet
) -> bool | None:
    partners, products = declared.get("partners"), declared.get("partner_products")
    if (
        not isinstance(partners, list)
        or not isinstance(products, list)
        or len(partners) != 2
        or len(products) != 2
    ):
        return False
    if any(
        not isinstance(key, str) or key not in candidates.states for key in [*partners, *products]
    ):
        return False
    if set(partners) != {term.species for term in reaction.reactants} or set(products) != {
        term.species for term in reaction.products
    }:
        return False
    a, b, ap, bp = [candidates.states[key] for key in [*partners, *products]]
    if ap.charge == a.charge or ap.charge - a.charge != b.charge - bp.charge:
        return False
    if ap.charge - a.charge != declared.get("charge_change"):
        return False
    matches = (charge_target_correspondence(a, ap), charge_target_correspondence(b, bp))
    return False if False in matches else None if None in matches else True


def _mapped_level_pattern(
    declared: dict, reaction: ReactionCandidate, candidates: CandidateSet, p: _Participants
) -> bool:
    if reaction.process not in {
        "level_transfer",
        "excitation",
        "deexcitation",
        *_DIRECTIONAL_HEAVY_LEVELS,
    }:
        return False
    pairs = _declared_level_transitions(declared)
    if not pairs or any(
        initial not in candidates.states or final not in candidates.states
        for initial, final in pairs
    ):
        return False
    if reaction.process in _DIRECTIONAL_HEAVY_LEVELS and (
        len(pairs) != 1 or pairs[0] not in _state_transfer_roles(reaction, p)
    ):
        return False
    left, right = zip(*pairs, strict=True)
    collider = declared.get("collider")
    if collider is not None:
        if not isinstance(collider, str) or len(pairs) != 1:
            return False
        left, right = (*left, collider), (*right, collider)
    return (
        p.left_n == len(left)
        and p.right_n == len(right)
        and sorted(left) == sorted(state.id for state in p.left)
        and sorted(right) == sorted(state.id for state in p.right)
        and all(
            _internal_state_change(candidates.states[initial], candidates.states[final])
            for initial, final in pairs
        )
    )


def _declared_level_transitions(declared: dict) -> tuple[tuple[str, str], ...]:
    kind = declared.get("kind")
    if not isinstance(kind, str):
        return ()
    if kind == "two_level_transition":
        initial, final = declared.get("initial"), declared.get("final")
        if (
            isinstance(initial, list)
            and isinstance(final, list)
            and len(initial) == len(final) == 2
            and all(isinstance(item, str) for item in (*initial, *final))
        ):
            return tuple(sorted(zip(initial, final, strict=True)))
        return ()
    keys = {
        "level_transition": ("initial", "final"),
        "collision_partition": ("collider", "collider_product"),
        "graph_edit": ("collider", "collider_product"),
        "collision_ionization": ("collider", "collider_product"),
        "penning": ("donor", "donor_product"),
    }.get(kind)
    if keys is None:
        return ()
    initial, final = (declared.get(key) for key in keys)
    if isinstance(initial, str) and isinstance(final, str) and initial != final:
        return ((initial, final),)
    return ()


def _validated_level_options(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    participants: _Participants,
    declared: dict,
) -> set[tuple[tuple[str, str], ...]]:
    if declared.get("kind") == "alternatives":
        alternatives = declared.get("alternatives")
        if not isinstance(alternatives, list):
            return set()
        return {
            pairs
            for item in alternatives
            if isinstance(item, dict)
            for pairs in _validated_level_options(reaction, candidates, participants, item)
        }
    pairs = _declared_level_transitions(declared)
    if pairs and _transformation_pattern(reaction, candidates, participants, declared) is True:
        return {pairs}
    return set()


def _validated_level_transitions(
    reaction: ReactionCandidate, candidates: CandidateSet, consistency: Assessment
) -> tuple[tuple[str, str], ...]:
    """Project role pairs from an equation check without deciding gap signs."""
    if consistency.verdict == VERDICT_FAIL or reaction.process not in {
        "level_transfer",
        "excitation",
        "deexcitation",
        "dissociation_with_level_transfer",
        "ionization",
        "collision_ionization",
        "penning_ionization",
        *_DIRECTIONAL_HEAVY_LEVELS,
    }:
        return ()
    if reaction.transformation:
        options = _validated_level_options(
            reaction, candidates, _participants(reaction, candidates), reaction.transformation
        )
        if options:
            return next(iter(options)) if len(options) == 1 else ()
    if consistency.verdict == VERDICT_PASS and reaction.family in {"ion", "neutral"}:
        return _unmapped_heavy_level_transitions(reaction, candidates)
    if reaction.family == "electron" and reaction.process in {
        "level_transfer",
        "excitation",
        "deexcitation",
    }:
        # The equation pattern has checked the unique target on each side.
        initial = next(term.species for term in reaction.reactants if term.species != ELECTRON)
        final = next(term.species for term in reaction.products if term.species != ELECTRON)
        return ((initial, final),)
    return ()


def _unmapped_heavy_level_transitions(
    reaction: ReactionCandidate, candidates: CandidateSet
) -> tuple[tuple[str, str], ...]:
    participants = _participants(reaction, candidates)
    if reaction.process == "penning_ionization":
        matches = {
            (initial.id, final.id)
            for _, _, initial, final in _collision_ionization_matches(reaction, participants)
        }
        if len(matches) == 1:
            ((initial, final),) = matches
            # A formula hypothesis can allow a missing structure. A gap requires the same species.
            if _same_nuclei(candidates.states[initial], candidates.states[final]):
                return ((initial, final),)
    elif reaction.process in _DIRECTIONAL_HEAVY_LEVELS:
        named_roles = _state_transfer_roles(reaction, participants)
        return tuple(named_roles) if len(named_roles) == 1 else ()
    elif reaction.process == "level_transfer":
        roles = {
            tuple(sorted((initial.id, final.id) for initial, final in changes))
            for changes in _heavy_level_matches(participants)
        }
        return next(iter(roles)) if len(roles) == 1 else ()
    return ()


def _mapped_transfer(
    declared: dict, reaction: ReactionCandidate, candidates: CandidateSet, p: _Participants
) -> bool | None:
    if not _two_particle_products(p) or p.same_composition:
        return False
    keys = ("donor", "acceptor", "donor_product", "acceptor_product")
    if any(
        not isinstance(declared.get(key), str) or declared[key] not in candidates.states
        for key in keys
    ):
        return False
    donor, acceptor, dproduct, aproduct = [candidates.states[declared[key]] for key in keys]
    if sorted((donor.id, acceptor.id)) != sorted(state.id for state in p.left) or sorted(
        (dproduct.id, aproduct.id)
    ) != sorted(state.id for state in p.right):
        return False
    group = declared.get("group")
    charge = declared.get("group_charge")
    if not _valid_group(group) or type(charge) is not int:
        return False
    if reaction.process == "ligand_transfer" and charge != 0:
        return False
    result = _group_transfer(donor, acceptor, dproduct, aproduct)
    return result[2] if result is not None and result[:2] == (group, charge) else False


def _mapped_exchange(declared: dict, p: _Participants, candidates: CandidateSet) -> bool | None:
    partners, groups = declared.get("partners"), declared.get("groups")
    if (
        not isinstance(partners, list)
        or len(partners) != 2
        or not isinstance(groups, list)
        or len(groups) != 2
    ):
        return False
    if any(not _valid_group(group) for group in groups) or any(
        not isinstance(key, str) or key not in candidates.states for key in partners
    ):
        return False
    if sorted(partners) != sorted(state.id for state in p.left):
        return False
    products = declared.get("partner_products")
    if "partner_products" in declared and (
        not isinstance(products, list)
        or any(not isinstance(key, str) for key in products)
        or sorted(products) != sorted(state.id for state in p.right)
        or len(products) != 2
    ):
        return False
    left, right = (candidates.states[key] for key in partners)
    exits = (
        (candidates.states[products[0]], candidates.states[products[1]])
        if products is not None
        else None
    )
    return _exchange_pattern(p, (left, right), (groups[0], groups[1]), exits)


def _exchange_pattern(
    p: _Participants,
    partners: tuple[StateCandidate, StateCandidate] | None = None,
    groups: tuple[dict[str, int], dict[str, int]] | None = None,
    partner_products: tuple[StateCandidate, StateCandidate] | None = None,
) -> bool | None:
    """Check two retained elemental cores and two nonempty exchanged groups."""
    if not _two_particle_products(p) or p.same_composition:
        return False
    left, right = partners or (p.left[0], p.left[1])
    matches = []
    exits = (partner_products,) if partner_products is not None else (p.right, p.right[::-1])
    for left_product, right_product in exits:
        if (left.charge, right.charge) != (left_product.charge, right_product.charge):
            continue
        exchanged = groups or _inferred_exchange_groups(left, right, left_product, right_product)
        if exchanged is None:
            continue
        outgoing, incoming = exchanged
        left_core = _positive_composition_difference(left.composition, outgoing)
        right_core = _positive_composition_difference(right.composition, incoming)
        if (
            left_core
            and right_core
            and merge(left_core, incoming) == left_product.composition
            and merge(right_core, outgoing) == right_product.composition
        ):
            match = retained_nuclide_correspondence(
                (left, left_product, left_core), (right, right_product, right_core)
            )
            # An unmapped equation gives only one minimal elemental witness.
            # Other overlapping groups could move a label instead of retaining it.
            matches.append(None if match is False and groups is None else match)
    return _role_verdict(iter(matches))


def _inferred_exchange_groups(
    left: StateCandidate,
    right: StateCandidate,
    left_product: StateCandidate,
    right_product: StateCandidate,
) -> tuple[dict[str, int], dict[str, int]] | None:
    outgoing = dict(Counter(left.composition) - Counter(left_product.composition))
    incoming = dict(Counter(right.composition) - Counter(right_product.composition))
    if outgoing and incoming:
        return outgoing, incoming
    # An atom of the same element may appear in both groups and cancel in the
    # net changes. Both particles must still retain a nonempty inventory.
    left_core = subtract(left.composition, outgoing)
    right_core = subtract(right.composition, incoming)
    shared = left_core.keys() & right_core.keys()
    if not shared or min(sum(left_core.values()), sum(right_core.values())) < 2:
        return None
    common = {min(shared): 1}
    return merge(outgoing, common), merge(incoming, common)


def _valid_group(group: object) -> bool:
    return (
        isinstance(group, dict)
        and bool(group)
        and all(isinstance(key, str) and type(n) is int and n > 0 for key, n in group.items())
    )


def assess_reaction_states(
    reaction: ReactionCandidate,
    state_assessments: dict[str, dict[str, Assessment]],
) -> Assessment:
    """Aggregate the named participant claims, retaining their distinct propositions.

    A bound anion supported by EA and an observed state supported by an
    existence assertion are different claims. Their aggregate says only that
    the participant claims pass; it does not promote EA to an observation.
    """
    participants = tuple(
        sorted(
            {
                term.species
                for term in (*reaction.reactants, *reaction.products)
                if term.species != ELECTRON
            }
        )
    )
    verdicts = [state_assessments[state_id]["state"] for state_id in participants]
    proposition = "participant_state_support"
    scope = (
        "Aggregate of the named participant state claims; electron binding is "
        "not observational existence, population or channel occurrence."
    )
    dependencies = tuple((state_id, "state") for state_id in participants)
    aggregate = participant_support_verdict(item.verdict for item in verdicts)
    failed = [item for item in verdicts if item.verdict == VERDICT_FAIL]
    if aggregate == VERDICT_FAIL:
        return Assessment(
            VERDICT_FAIL,
            tuple(item for value in failed for item in value.basis),
            (
                "at least one participant fails its named state claim; see the "
                "referenced state assessments"
            ),
            proposition=proposition,
            scope=scope,
            dependencies=dependencies,
        )
    unknown = [item for item in verdicts if item.verdict == VERDICT_UNKNOWN]
    if aggregate == VERDICT_UNKNOWN:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(sorted({item for value in unknown for item in value.basis})),
            (
                "at least one participant has an unresolved named state claim; see the "
                "referenced state assessments"
            ),
            proposition=proposition,
            scope=scope,
            dependencies=dependencies,
        )
    return Assessment(
        VERDICT_PASS,
        ("reactant and product State assessments",),
        "all named participant state claims are supported within their individual scopes",
        proposition=proposition,
        scope=scope,
        dependencies=dependencies,
    )


def assess_thermochemistry(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    state_evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
    conditions: Conditions,
) -> tuple[Assessment, dict[str, float]]:
    """Return the energy proposition and available values for existing API callers.

    Analysis additionally saves the independent calculation results returned
    by ``_evaluate_thermochemistry``. Missing calculation inputs are not missing
    evidence for the energy proposition.
    """
    result, energy_values, calculations = _evaluate_thermochemistry(
        reaction,
        candidates,
        state_evidence,
        reaction_evidence,
        conditions,
        conservation=_conservation_assessment(reaction, _checked_balance(reaction, candidates)),
    )
    return result, _combined_thermal_values(energy_values, calculations)


def _evaluate_thermochemistry(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    state_evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
    conditions: Conditions,
    screening_values: dict[tuple[str, str], tuple[EnergyInput, ...]] | None = None,
    *,
    conservation: Assessment,
    screening_property_issues: dict[tuple[str, str], tuple[Requirement, ...]] | None = None,
) -> tuple[Assessment, dict[str, float], dict[str, ThermochemicalCalculation]]:
    proposition = {
        "elastic": "elastic_internal_energy_identity",
        "ionization": "ionization_threshold_lower_bound",
        "penning_ionization": "penning_energy_requirement",
        "attachment": "ground_anion_electron_binding",
        "charge_exchange": "charge_transfer_energy_defect_consistency",
        "resonant_charge_exchange": "charge_transfer_energy_defect_consistency",
    }.get(reaction.process, "reaction_energy_relation")
    if conservation.verdict == VERDICT_FAIL:
        reason = "reaction thermochemistry requires a conserved equation"
        return (
            Assessment(
                VERDICT_NA,
                ("assessment:conservation",),
                reason,
                proposition=proposition,
                scope="Thermochemistry of conserved reaction equations.",
            ),
            {},
            {
                quantity: ThermochemicalCalculation("not_applicable", None, unit, reason)
                for quantity, unit in (
                    ("delta_h_eV", "eV"),
                    ("delta_g_eV", "eV"),
                    ("equilibrium_constant_number_density", "m^(-3*delta_nu)"),
                )
            },
        )
    species, sources = _thermo_records(reaction, state_evidence, conditions.gas_temperature_K)
    calculations = _thermal_calculations(
        reaction, candidates, state_evidence, species, conditions, sources
    )
    source_values, source_conflicts = _source_energy_values(reaction, candidates, reaction_evidence)
    result, values = _assess_energy_relation(
        reaction,
        candidates,
        state_evidence,
        reaction_evidence,
        conditions,
        any(item.value is not None for item in calculations.values()),
        source_values,
        source_conflicts,
        screening_values,
        screening_property_issues,
    )
    conflicts = tuple(
        sorted(
            set(_reaction_energy_conflicts(reaction, candidates, state_evidence) + source_conflicts)
        )
    )
    if conflicts:
        result = replace(
            result,
            message=result.message
            + "; conflicting declarations or invalid values excluded from quantities: "
            + ", ".join(conflicts),
        )
    requirements = result.requirements
    if result.verdict == VERDICT_UNKNOWN and not requirements:
        requirements = _relation_requirements(
            reaction, candidates, state_evidence, reaction_evidence
        )
    scope = result.scope or {
        "elastic": (
            "Identity of participant internal energies; translational energy "
            "transfer, probability and occurrence are undetermined."
        ),
        "ionization": (
            "Consistency of a declared threshold with the ground-parent ionization "
            "lower bound; rates and occurrence are undetermined."
        ),
        "penning_ionization": (
            "Declared excitation, ionization and specified collision-energy budget;"
            " probabilities and occurrence are undetermined."
        ),
        "attachment": (
            "Electron binding of the corresponding ground anion; stabilization, "
            "rate and occurrence are undetermined."
        ),
        "charge_exchange": (
            "Consistency of comparable products-minus-reactants internal-energy "
            "defects; rates and occurrence are undetermined."
        ),
        "resonant_charge_exchange": (
            "Consistency of comparable products-minus-reactants internal-energy "
            "defects; rates and occurrence are undetermined."
        ),
    }.get(
        reaction.process,
        (
            "No implemented energy relation for this process; calculated enthalpy, "
            "Gibbs energy or equilibrium constants alone do not establish "
            "occurrence."
        ),
    )
    return (
        replace(result, proposition=proposition, scope=scope, requirements=requirements),
        values,
        calculations,
    )


def _energy_requirements(
    state_id: str,
    evidence: StateEvidence | None,
    name: str,
    *,
    electron_term_required: bool = False,
) -> tuple[Requirement, ...]:
    """Explain the actual boundary preventing consumption of this quantity."""
    if evidence is None or evidence.match == "none":
        return (
            Requirement(
                "source_information",
                state_id,
                name,
                "obtain a qualified energy declaration for this exact state",
            ),
        )
    if evidence.match != "exact":
        return (
            Requirement(
                "identity", state_id, name, "identify the exact target of this energy declaration"
            ),
        )
    supplied = [
        (record, record.properties[name])
        for record in evidence.records
        if name in record.properties
        and (
            record.properties[name].value is not None
            or bool((record.properties[name].qualifier or "").strip())
        )
    ]
    if not supplied:
        placeholder = any(name in record.properties for record in evidence.records)
        return (
            Requirement(
                "source_information",
                state_id,
                f"{name}.value" if placeholder else name,
                "supply a numerical value; an empty placeholder is not a scientific declaration"
                if placeholder
                else "obtain a sourced value with its physical definition "
                "and uncertainty information",
            ),
        )
    eligible = [
        (record, prop)
        for record, prop in supplied
        if record.status not in {"rejected", "conflicting"}
    ]
    if not eligible:
        return (
            Requirement(
                "source_review",
                state_id,
                f"{name}.record_status",
                (
                    "resolve the rejected or conflicting record qualification before "
                    "consuming its quantity"
                ),
            ),
        )
    reviewed = [(record, prop) for record, prop in eligible if prop.reviewed_for(name)]
    if not reviewed:
        return (
            Requirement(
                "source_review",
                state_id,
                name,
                "review this energy quantity independently of state existence or another quantity",
            ),
        )
    context = _energy_context_requirement(state_id, reviewed, name)
    if context:
        return context
    choices = _property_choices(evidence, name, electron_term_required=electron_term_required)
    selection_requirements = _state_selection_requirement(
        evidence, name, electron_term_required=electron_term_required
    )
    if selection_requirements:
        return selection_requirements
    if _property_declarations_conflict(
        name,
        choices,
        charge=evidence.records[0].candidate.charge if evidence.records else None,
        electron_term_required=electron_term_required,
    ):
        quantity = name
        if (
            name == "enthalpy_formation_eV"
            and electron_term_required
            and not _property_declarations_conflict(
                name,
                choices,
                charge=evidence.records[0].candidate.charge if evidence.records else None,
            )
        ):
            quantity = "formation_reference.electron_enthalpy_eV"
        return (
            Requirement(
                "source_review",
                state_id,
                quantity,
                f"resolve conflicting declarations of {quantity}",
            ),
        )
    return _energy_numeric_requirement(state_id, choices, name)


def _energy_context_requirement(
    state_id: str,
    declarations: list[tuple[StateRecord, Property]],
    name: str,
) -> tuple[Requirement, ...]:
    issues = {
        _state_energy_incompatibility(prop, name, record.candidate) for record, prop in declarations
    }
    if None in issues:
        return ()
    reasons = {
        "model": (
            "the current gas-phase ground-state energy relation does not cover this "
            "phase or state; changing a quantity definition cannot supply that model"
        ),
        "definition": (
            "supply a compatible atomic or adiabatic definition; a vertical or "
            "unspecified molecular value does not decide this ground-state relation"
        ),
        "qualifier": (
            "review the qualified energy declaration or obtain usable numerical bounds; "
            "an unsupported limit or annotation cannot be consumed as a point value"
        ),
        "relation": (
            "the declared related state does not match the actual charge/ground counterpart; "
            "resolve this target relationship before using the quantity"
        ),
        "value": "a ground-state ionization energy must be positive; verify the declared quantity",
    }
    responsibilities = {
        "model": "external_models",
        "definition": "source_information",
        "qualifier": "source_review",
        "relation": "identity",
        "value": "source_review",
    }
    return tuple(
        Requirement(responsibilities[issue], state_id, f"{name}.{issue}", reasons[issue])
        for issue in sorted(item for item in issues if item is not None)
    )


def _energy_numeric_requirement(
    state_id: str,
    choices: list[Property],
    name: str,
) -> tuple[Requirement, ...]:
    numerical = [prop for prop in choices if prop.value is not None]
    if not numerical:
        return (
            Requirement(
                "source_information",
                state_id,
                f"{name}.value",
                (
                    "supply a numerical value; a qualitative annotation alone does not "
                    "decide the energy relation"
                ),
            ),
        )
    if any(prop.value is not None and not isfinite(prop.value) for prop in numerical):
        return (
            Requirement(
                "source_review",
                state_id,
                f"{name}.value",
                "correct the nonfinite numerical declaration before evaluating this relation",
            ),
        )
    if any(
        prop.value is not None and energy_eV(prop.value, prop.unit) is None for prop in numerical
    ):
        return (
            Requirement(
                "source_information",
                state_id,
                f"{name}.unit",
                "state a supported energy unit so this declared value can be converted",
            ),
        )
    if any(property_energy_bounds(prop) is None for prop in numerical):
        return (
            Requirement(
                "source_review",
                state_id,
                f"{name}.uncertainty",
                (
                    "provide valid numerical uncertainty ranges; invalid or qualitative "
                    "ranges cannot be consumed"
                ),
            ),
        )
    return (
        Requirement(
            "source_information",
            state_id,
            f"{name}.uncertainty",
            (
                "obtain declaration ranges that resolve the energy relation; an "
                "overlapping or marginal declaration is inconclusive"
            ),
        ),
    )


def _ionization_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    states: dict[str, StateEvidence],
    evidence: ReactionEvidence,
) -> tuple[Requirement, ...]:
    target = _ionization_parent(reaction, candidates)
    if target is None:
        return (
            Requirement(
                "external_models",
                reaction.id,
                "ionization_energy_relation",
                (
                    "the current ground-parent gas-phase lower-bound relation does not cover "
                    "these actual reactants, product phase, structure or charge change"
                ),
            ),
        )
    requirements: list[Requirement] = []
    parent_id = target.id
    parent = _preferred_state(parent_id, states)
    if parent is None or _eV_value(parent, "ionization_energy_eV") is None:
        requirements.extend(
            _energy_requirements(parent_id, states.get(parent_id), "ionization_energy_eV")
        )
    choices = _reaction_energy_choices(evidence, "threshold_eV")
    if not choices or any(
        prop.value is None or energy_eV(prop.value, prop.unit) is None for _, prop in choices
    ):
        requirements.extend(_channel_energy_requirements(reaction.id, evidence, "threshold_eV"))
    if not requirements:
        requirements.append(
            Requirement(
                "source_review",
                reaction.id,
                "threshold_eV",
                (
                    "resolve conflicting, invalid or uncertainty-overlapping threshold and "
                    "ionization declarations"
                ),
            )
        )
    return tuple(requirements)


def _channel_energy_requirements(
    reaction_id: str,
    evidence: ReactionEvidence,
    quantity: str,
) -> tuple[Requirement, ...]:
    supplied = [
        (record, record.energy_properties[quantity])
        for record in evidence.exact_records
        if quantity in record.energy_properties
    ]
    if not supplied:
        return (
            Requirement(
                "source_information",
                reaction_id,
                quantity,
                "obtain an independently qualified energy declaration for this exact channel",
            ),
        )
    active = [
        (record, prop)
        for record, prop in supplied
        if record.status not in {"rejected", "conflicting"}
    ]
    if not active:
        return (
            Requirement(
                "source_review",
                reaction_id,
                f"{quantity}.record_status",
                (
                    "resolve the rejected or conflicting source record before consuming its"
                    " channel energy"
                ),
            ),
        )
    reviewed = [prop for _, prop in active if prop.reviewed_for(quantity)]
    if not reviewed:
        return (
            Requirement(
                "source_review",
                reaction_id,
                quantity,
                (
                    "review the channel energy independently of the channel assertion or "
                    "rate coefficient"
                ),
            ),
        )
    eligible = [prop for prop in reviewed if reaction_energy_definition_compatible(prop, quantity)]
    if not eligible:
        field = (
            "qualifier"
            if any(prop.qualifier and prop.qualifier.strip() for prop in reviewed)
            else "definition"
        )
        return (
            Requirement(
                "source_information",
                reaction_id,
                f"{quantity}.{field}",
                (
                    "supply a channel energy with a definition and numerical bounds "
                    "compatible with this implemented relation"
                ),
            ),
        )
    return _energy_numeric_requirement(reaction_id, eligible, quantity)


def _relation_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    states: dict[str, StateEvidence],
    evidence: ReactionEvidence,
) -> tuple[Requirement, ...]:
    if reaction.process == "ionization":
        return _ionization_requirements(reaction, candidates, states, evidence)
    if reaction.process == "attachment":
        parents = [term.species for term in reaction.reactants if term.species != ELECTRON]
        if len(parents) == 1 and _process_pattern(reaction, candidates) is True:
            return _energy_requirements(parents[0], states.get(parents[0]), "electron_affinity_eV")
        return (
            Requirement(
                "external_models",
                reaction.id,
                "attachment_energy_relation",
                (
                    "the ground-parent electron-binding relation does not cover the actual "
                    "participants"
                ),
            ),
        )
    if reaction.process in {"charge_exchange", "resonant_charge_exchange"}:
        return _charge_transfer_requirements(reaction, candidates, states, evidence)
    if reaction.process == "elastic":
        return (
            Requirement(
                "source_review",
                reaction.id,
                "elastic_internal_energy",
                (
                    "resolve inconsistent or invalid internal-energy declarations for the "
                    "unchanged states"
                ),
            ),
        )
    return ()


def _charge_transfer_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    states: dict[str, StateEvidence],
    evidence: ReactionEvidence,
) -> tuple[Requirement, ...]:
    _, model_requirements = _charge_transfer_inputs(reaction, candidates)
    if model_requirements:
        return model_requirements
    requirements: list[Requirement] = []
    for state_id, names in _relation_energy_quantities(reaction, candidates).items():
        for name in sorted(names):
            record = _preferred_state(state_id, states)
            if record is None or _eV_value(record, name) is None:
                requirements.extend(_energy_requirements(state_id, states.get(state_id), name))
    choices = _reaction_energy_choices(evidence, "delta_e_eV")
    if not choices or any(
        prop.value is None or energy_eV(prop.value, prop.unit) is None for _, prop in choices
    ):
        requirements.extend(_channel_energy_requirements(reaction.id, evidence, "delta_e_eV"))
    return tuple(requirements) or (
        Requirement(
            "source_review",
            reaction.id,
            "delta_e_eV",
            "resolve inconsistent or uncertainty-overlapping energy-defect declarations",
        ),
    )


def _assess_energy_relation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    state_evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
    conditions: Conditions,
    has_calculated_values: bool,
    source_values: dict[str, float],
    source_conflicts: tuple[str, ...],
    screening_values: dict[tuple[str, str], tuple[EnergyInput, ...]] | None,
    screening_property_issues: dict[tuple[str, str], tuple[Requirement, ...]] | None,
) -> tuple[Assessment, dict[str, float]]:
    """Check comparable energy relations; values alone do not prove occurrence."""
    values = dict(source_values)
    identity = _identity_energy(reaction, candidates, state_evidence)
    if identity is not None:
        values[identity[0]] = identity[1]
    if reaction.process == "penning_ionization":
        penning, available = _penning_energy_relation(
            reaction,
            candidates,
            state_evidence,
            conditions,
            screening_values,
            screening_property_issues,
        )
        values.update(available)
        return penning, values
    feasibility = _energy_feasibility(reaction, candidates, state_evidence)
    if feasibility is not None:
        name, value, conclusion = feasibility
        if value is not None:
            values[name] = value
        if conclusion is not None:
            return conclusion, values
    relation = _checked_energy_relation(
        reaction, candidates, values, reaction_evidence, state_evidence, source_conflicts
    )
    if relation is not None:
        return relation, values
    requirements = _relation_requirements(reaction, candidates, state_evidence, reaction_evidence)
    note = (
        "energy relation is undetermined"
        if requirements
        else f"no applicable declaration comparison for process {reaction.process!r}"
    )
    if requirements:
        note += "; " + "; ".join(dict.fromkeys(item.reason for item in requirements if item.reason))
    if values or has_calculated_values:
        note += "; available calculated or declared values are retained independently"
    return Assessment(
        VERDICT_UNKNOWN if requirements else VERDICT_NA,
        reaction_evidence.sources,
        note,
        requirements=requirements,
    ), values


def _calculation_values(
    calculations: dict[str, ThermochemicalCalculation],
) -> dict[str, float]:
    """Project successful calculations into the historical flat value view."""
    values: dict[str, float] = {}
    for quantity, calculation in calculations.items():
        if calculation.value is not None:
            values[quantity] = calculation.value
            values.update(calculation.conditions)
    return values


def _combined_thermal_values(
    energy_values: dict[str, float],
    calculations: dict[str, ThermochemicalCalculation],
) -> dict[str, float]:
    values = _calculation_values(calculations)
    if values.keys() & energy_values.keys():
        raise ValueError("auxiliary energy values cannot overwrite thermochemical calculations")
    return energy_values | values


def _thermal_calculations(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    species: dict[str, StateRecord],
    conditions: Conditions,
    sources: dict[tuple[str, str], StateRecord],
) -> dict[str, ThermochemicalCalculation]:
    """Calculate three distinct quantities from one selected participant view.

    Formation references and finite-temperature NASA models are independent
    inputs. Their applicability never determines an energy relation verdict.
    """
    enthalpy = _formation_calculation(reaction, candidates, evidence, species)
    gibbs, constant = _nasa_calculations(reaction, candidates, evidence, species, conditions)
    if enthalpy.value is not None:
        enthalpy = replace(
            enthalpy,
            inputs=_thermal_input_trace(reaction, sources, "enthalpy_formation_eV"),
            operation="formation_enthalpy_difference",
        )
    if gibbs.value is not None:
        gibbs = replace(
            gibbs,
            inputs=_thermal_input_trace(reaction, sources, "thermochemical_model"),
            operation="NASA7_standard_gibbs_difference",
        )
    if constant.value is not None:
        constant = replace(
            constant,
            inputs=({"calculation": "delta_g_eV", "coefficient": 1.0},),
            operation="number_density_equilibrium_from_standard_gibbs",
        )
    return {
        "delta_h_eV": enthalpy,
        "delta_g_eV": gibbs,
        "equilibrium_constant_number_density": constant,
    }


def _thermal_input_trace(
    reaction: ReactionCandidate,
    sources: dict[tuple[str, str], StateRecord],
    quantity: str,
) -> tuple[dict, ...]:
    inputs = []
    for state, coefficient in net_stoichiometry(reaction).items():
        if state == ELECTRON:
            inputs.append(
                {"constant": "retained_electron_enthalpy_convention", "coefficient": coefficient}
            )
        elif (record := sources.get((state, quantity))) is not None:
            inputs.append(
                {
                    "record_id": selectable_state_record_id(record),
                    "record_ref": calculation_record_reference(record),
                    "target": state,
                    "quantity": quantity,
                    "coefficient": coefficient,
                }
            )
    return tuple(inputs)


def _surface_thermal_requirement(reaction: ReactionCandidate) -> tuple[Requirement, ...]:
    return (
        Requirement(
            "external_models",
            reaction.id,
            "surface_thermochemical_balance",
            "an energy balance including the surface reservoir is not implemented; "
            "gas participant values alone do not give the surface reaction thermochemistry",
        ),
    )


def _formation_calculation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    species: dict[str, StateRecord],
) -> ThermochemicalCalculation:
    if reaction.surface is not None:
        requirements = _surface_thermal_requirement(reaction)
        return ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
    contributors = set(net_stoichiometry(reaction)) - {ELECTRON}
    electron_required = net_electron_coefficient(reaction) != 0.0
    missing = tuple(
        requirement
        for state_id in sorted(contributors)
        if state_id not in species or _eV_value(species[state_id], "enthalpy_formation_eV") is None
        for requirement in _energy_requirements(
            state_id,
            evidence.get(state_id),
            "enthalpy_formation_eV",
            electron_term_required=electron_required,
        )
    )
    if missing:
        return ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(missing), missing
        )
    reference = formation_reference(reaction, species)
    if reference is None and net_stoichiometry(reaction):
        requirements = _formation_reference_requirements(reaction, candidates, species)
        return ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
    value = formation_delta(reaction, species)
    if value is None:
        requirements = (
            Requirement(
                "external_models",
                reaction.id,
                "formation_enthalpy_numerical_range",
                "the formation enthalpy arithmetic cannot represent a finite difference "
                "for these declarations",
            ),
        )
        return ThermochemicalCalculation(
            "unavailable", None, "eV", calculation_reason(requirements), requirements
        )
    reference_conditions: dict[str, float] = {}
    if reference is not None:
        if reference.temperature_K is not None:
            reference_conditions["delta_h_reference_temperature_K"] = reference.temperature_K
        if reference.standard_pressure_Pa is not None:
            reference_conditions["delta_h_standard_pressure_Pa"] = reference.standard_pressure_Pa
    return ThermochemicalCalculation(
        "computed",
        value,
        "eV",
        (
            "products-minus-reactants formation enthalpy at the retained common reference; "
            if reference is not None
            else "identical represented states cancel at any common formation reference; "
        )
        + "this nominal difference does not establish an appearance threshold, "
        "uncertainty propagation, or channel occurrence",
        conditions=reference_conditions,
    )


def _formation_reference_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    species: dict[str, StateRecord],
) -> tuple[Requirement, ...]:
    requirements: list[Requirement] = []
    electron_required = net_electron_coefficient(reaction) != 0.0
    references = []
    charged = []
    for state_id in sorted(set(net_stoichiometry(reaction)) - {ELECTRON}):
        state = candidates.states[state_id]
        prop = species[state_id].properties["enthalpy_formation_eV"]
        reference = prop.formation_reference
        requirements.extend(
            _formation_reference_fields(state, reference, electron_required=electron_required)
        )
        if reference is not None:
            references.append((state_id, reference))
            if state.charge:
                charged.append((state_id, reference))
    for name in ("temperature_K", "basis", "standard_pressure_Pa", "electron_convention"):
        compared = charged if name == "electron_convention" else references
        if name == "electron_convention":
            compared = [(state_id, ref) for state_id, ref in compared if ref.temperature_K != 0]
        if len({getattr(ref, name) for _, ref in compared}) > 1:
            requirements.extend(
                Requirement(
                    "source_review",
                    state_id,
                    f"enthalpy_formation_eV.formation_reference.{name}",
                    f"formation values do not share {name}; use a stated common reference "
                    "or a supported conversion instead of subtracting unlike references",
                )
                for state_id, _ in compared
            )
    if electron_required:
        compared = [
            (state_id, ref)
            for state_id, ref in charged
            if ref.temperature_K != 0 and ref.electron_convention == "ion"
        ]
        if len({ref.electron_enthalpy_eV for _, ref in compared}) > 1:
            requirements.extend(
                Requirement(
                    "source_review",
                    state_id,
                    "formation_reference.electron_enthalpy_eV",
                    "formation_reference.electron_enthalpy_eV declarations conflict for "
                    "the consumed free-electron term",
                )
                for state_id, _ in compared
            )
    return tuple(dict.fromkeys(requirements)) or (
        Requirement(
            "source_information",
            reaction.id,
            "formation_reference",
            "a compatible common formation reference and applicable electron term are required",
        ),
    )


def _formation_reference_fields(
    state: StateCandidate,
    reference: FormationReference | None,
    *,
    electron_required: bool,
) -> tuple[Requirement, ...]:
    requirements = []
    if state.phase == "unknown":
        requirements.append(
            Requirement(
                "identity", state.id, "phase", "identify the phase of this formation quantity"
            )
        )
    if reference is None:
        return (
            *requirements,
            Requirement(
                "source_information",
                state.id,
                "enthalpy_formation_eV.formation_reference",
                "state the formation reference temperature, elemental basis, pressure "
                "and applicable electron convention for this quantity",
            ),
        )
    fields = ["temperature_K", "basis", "standard_pressure_Pa"]
    if state.charge and reference.temperature_K != 0:
        fields.append("electron_convention")
        if electron_required and reference.electron_convention == "ion":
            fields.append("electron_enthalpy_eV")
    requirements.extend(
        Requirement(
            "source_information",
            state.id,
            f"enthalpy_formation_eV.formation_reference.{name}",
            f"state {name} in this formation reference before subtracting values",
        )
        for name in fields
        if getattr(reference, name) is None
    )
    return tuple(requirements)


def _nasa_calculations(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    species: dict[str, StateRecord],
    conditions: Conditions,
) -> tuple[ThermochemicalCalculation, ThermochemicalCalculation]:
    coefficients = net_stoichiometry(reaction)
    density_power = fsum(coefficients.values())
    constant_unit = "dimensionless" if density_power == 0 else f"m{-3 * density_power:g}"
    if reaction.surface is None and any(
        term.species == ELECTRON for term in (*reaction.reactants, *reaction.products)
    ):
        reason = "standard NASA7 thermal gas ground-state calculations exclude electron channels"
        return (
            ThermochemicalCalculation("unavailable", None, "eV", reason),
            ThermochemicalCalculation("unavailable", None, constant_unit, reason),
        )
    requirements = _nasa_requirements(
        reaction, candidates, evidence, species, temperature_K=conditions.gas_temperature_K
    )
    if not coefficients and not requirements:
        # Each standard-state contribution and the density exponent cancel.
        # No model coefficients or arbitrary temperature are consumed.
        return (
            ThermochemicalCalculation(
                "computed",
                0.0,
                "eV",
                "the same represented thermal gas ground states cancel, giving zero "
                "standard Gibbs difference independently of temperature and reference pressure; "
                "state existence and channel occurrence are undetermined",
            ),
            ThermochemicalCalculation(
                "computed",
                1.0,
                "dimensionless",
                "the cancelling standard Gibbs difference and zero density exponent "
                "give an equilibrium ratio of one without temperature or reference pressure; "
                "a reverse channel and its kinetics are undetermined",
                conditions={"equilibrium_constant_density_power": 0.0},
            ),
        )
    temperature = conditions.gas_temperature_K
    calculation_conditions = {} if temperature is None else {"temperature_K": temperature}
    pressure = reference_pressure(reaction, species)
    if pressure is not None:
        calculation_conditions["standard_pressure_Pa"] = pressure
    constant_conditions = calculation_conditions | {
        "equilibrium_constant_density_power": density_power
    }
    status = "unavailable"
    if not requirements:
        if temperature is None:
            status = "needs_input"
            requirements = (
                Requirement(
                    "user_inputs",
                    reaction.id,
                    "gas_temperature_K",
                    "specify gas_temperature_K to evaluate the retained thermal NASA7 models",
                ),
            )
        else:
            requirements = tuple(
                Requirement(
                    "source_information",
                    state_id,
                    "thermochemical_model.temperature_range",
                    f"the NASA7 range [{record.thermo.t_min:g}, {record.thermo.t_max:g}] K "
                    f"does not cover the specified {temperature:g} K; obtain a model for "
                    "the actual temperature rather than extrapolating",
                )
                for state_id, record in sorted(species.items())
                if record.thermo is not None
                and not record.thermo.t_min <= temperature <= record.thermo.t_max
            )
            if requirements:
                status = "out_of_range"
    if requirements:
        reason = calculation_reason(requirements)
        return (
            ThermochemicalCalculation(
                status, None, "eV", reason, requirements, calculation_conditions
            ),
            ThermochemicalCalculation(
                status, None, constant_unit, reason, requirements, constant_conditions
            ),
        )
    # The missing-temperature branch above returned its typed prerequisite.
    gibbs, constant = thermal_values(reaction, species, cast(float, temperature))
    results = []
    for quantity, value, unit, declared_conditions, reason in (
        (
            "delta_g_eV",
            gibbs,
            "eV",
            calculation_conditions,
            "NASA7 standard Gibbs reaction energy for thermal gas ground states at the "
            "retained temperature and reference; channel occurrence and kinetics are undetermined",
        ),
        (
            "equilibrium_constant_number_density",
            constant,
            constant_unit,
            constant_conditions,
            "number-density equilibrium ratio from the retained thermal gas models; "
            "this does not establish a reversible channel or a reverse rate coefficient",
        ),
    ):
        if value is not None:
            results.append(
                ThermochemicalCalculation(
                    "computed", value, unit, reason, conditions=declared_conditions
                )
            )
        else:
            requirements = (
                Requirement(
                    "external_models",
                    reaction.id,
                    f"{quantity}.numerical_range",
                    f"the thermal arithmetic cannot represent a finite {quantity} for "
                    "these declarations; the physical quantity is not thereby disproved",
                ),
            )
            results.append(
                ThermochemicalCalculation(
                    "unavailable",
                    None,
                    unit,
                    calculation_reason(requirements),
                    requirements,
                    declared_conditions,
                )
            )
    return results[0], results[1]


def _nasa_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    species: dict[str, StateRecord],
    *,
    temperature_K: float | None = None,
) -> tuple[Requirement, ...]:
    if reaction.surface is not None:
        return _surface_thermal_requirement(reaction)
    requirements: list[Requirement] = []
    contributors = net_stoichiometry(reaction)
    targets = tuple(contributors) or tuple(
        sorted({term.species for term in (*reaction.reactants, *reaction.products)})
    )
    for state_id in targets:
        state = candidates.states[state_id]
        if state.phase != "gas" or state.state.kind != "ground":
            requirements.append(
                Requirement(
                    "identity" if state.phase == "unknown" else "external_models",
                    state_id,
                    "phase" if state.phase == "unknown" else "thermal_state_model",
                    "the implemented NASA7 calculation requires an identified thermal "
                    "gas ground state; a different phase or excited population needs its own model",
                )
            )
            continue
        if not contributors:
            continue
        matched = evidence.get(state_id)
        if matched is None or matched.match != "exact":
            requirements.append(
                Requirement(
                    "source_information"
                    if matched is None or matched.match == "none"
                    else "identity",
                    state_id,
                    "thermochemical_model",
                    "obtain a thermal model for the exact phase, structure and state",
                )
            )
            continue
        record = species.get(state_id)
        if record is None or record.thermo is None:
            requirements.extend(
                _missing_thermal_model_requirements(matched, state_id, temperature_K)
            )
            continue
        thermo = record.thermo
        if not valid_thermo(thermo):
            missing = [
                name for name in ("phase", "standard_pressure_Pa") if getattr(thermo, name) is None
            ]
            requirements.extend(
                Requirement(
                    "source_information" if missing else "source_review",
                    state_id,
                    f"thermochemical_model.{name}",
                    f"state {name} for the NASA7 model"
                    if missing
                    else "correct the NASA7 coefficients, temperature domain "
                    "or gas-phase reference",
                )
                for name in (missing or ["representation"])
            )
    if (
        not requirements
        and net_stoichiometry(reaction)
        and reference_pressure(reaction, species) is None
    ):
        requirements.extend(
            Requirement(
                "source_review",
                state_id,
                "thermochemical_model.standard_pressure_Pa",
                "NASA7 participants do not share a standard pressure; use an explicit "
                "common reference instead of silently mixing standard states",
            )
            for state_id in net_stoichiometry(reaction)
        )
    return tuple(dict.fromkeys(requirements))


def _missing_thermal_model_requirements(
    evidence: StateEvidence, state_id: str, temperature_K: float | None
) -> tuple[Requirement, ...]:
    selection_requirements = _state_selection_requirement(
        evidence, "thermochemical_model", temperature_K=temperature_K
    )
    if selection_requirements:
        return selection_requirements
    offered = [item.thermo for item in evidence.records if item.thermo is not None]
    conflicting = len({_thermo_physical_key(item) for item in _thermo_choices(evidence)}) > 1
    return (
        Requirement(
            "source_review" if offered else "source_information",
            state_id,
            "NASA7" if conflicting else "thermochemical_model",
            "resolve conflicting NASA7 declarations for this state"
            if conflicting
            else "review or correct this thermal model independently of state existence"
            if offered
            else "obtain a qualified NASA7 model for this thermal gas ground state",
        ),
    )


def _source_energy_values(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: ReactionEvidence,
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Return usable declarations and the quantities excluded by disagreement.

    A relation decides which quantities it needs. A threshold disagreement
    must not invalidate a delta-E comparison, or the reverse.
    """
    values = {}
    conflicts = []
    for attribute, name in (("threshold_eV", "threshold_eV"), ("delta_e_eV", "source_delta_e_eV")):
        if _reaction_claim_conflicts(evidence, attribute):
            conflicts.append(name)
            continue
        properties = [
            prop
            for _, prop in _reaction_energy_choices(evidence, attribute)
            if prop.value is not None
        ]
        declared = {
            energy_eV(prop.value, prop.unit) for prop in properties if prop.value is not None
        }
        if None in declared:
            conflicts.append(name)
            continue
        finite = {value for value in declared if value is not None}
        choices = {value for value in finite if isfinite(value)}
        if len(choices) != len(finite) or not energy_declarations_agree(properties):
            conflicts.append(name)
        elif choices:
            value = min(choices)
            if attribute == "delta_e_eV" and endpoint_order_issue(
                physical_coefficients(net_stoichiometry(reaction), candidates.states),
                value,
            ):
                conflicts.append(name)
                continue
            values[name] = value
    return values, tuple(conflicts)


def _reaction_energy_choices(
    evidence: ReactionEvidence,
    quantity: str,
) -> list[tuple[ReactionRecord, Property]]:
    """The nested quantity has its own qualification, independent of channel review."""
    return [
        (record, prop)
        for record in evidence.exact_records
        if (prop := qualified_channel_energy(record, quantity)) is not None
    ]


def _reaction_claim_conflicts(evidence: ReactionEvidence, claim: str) -> bool:
    """A record-ID collision or stated conflict affects only its reviewed claims.

    Acquisition-only changes compare equal through the common scientific
    declaration view. Other source records remain separate; review of a
    coefficient or threshold never becomes a channel assertion.
    """
    identifiers = {
        record.id
        for record in evidence.exact_records
        if _reaction_claim_reviewed(record, claim)
        or (
            _reaction_claim_explicit_conflict(record, claim)
            and _reaction_claim_relevant(record, claim)
        )
    }
    qualified = [
        record
        for record in (*evidence.records, *evidence.related_records)
        if record.id in identifiers and _reaction_claim_relevant(record, claim)
    ]
    if any(_reaction_claim_explicit_conflict(record, claim) for record in qualified):
        return True
    declared: dict[str, ReactionRecord] = {}
    for record in qualified:
        if record.id in declared and not _reaction_claims_equal(declared[record.id], record, claim):
            return True
        declared[record.id] = record
    return False


def _reaction_claims_equal(first: ReactionRecord, second: ReactionRecord, claim: str) -> bool:
    left, right = _reaction_claim_content(first, claim), _reaction_claim_content(second, claim)
    if claim in {"threshold_eV", "delta_e_eV"}:
        first_quantity, second_quantity = (
            first.energy_properties.get(claim),
            second.energy_properties.get(claim),
        )
        if (
            first_quantity is None
            or second_quantity is None
            or not energy_properties_equivalent(first_quantity, second_quantity)
        ):
            return False
        # Compare the consumed quantity in common units, retaining every raw
        # declaration in evidence. Other channel and lifecycle content still
        # fixes the target and eligibility of that same source-record ID.
        left.pop("energy_property", None)
        right.pop("energy_property", None)
    return left == right


def _reaction_claim_reviewed(record: ReactionRecord, claim: str) -> bool:
    if claim in {"threshold_eV", "delta_e_eV"}:
        return qualified_channel_energy(record, claim) is not None
    return record.reviewed_for(claim)


def _reaction_claim_relevant(record: ReactionRecord, claim: str) -> bool:
    if claim in {"threshold_eV", "delta_e_eV"}:
        prop = record.energy_properties.get(claim)
        return (
            prop is not None
            and channel_energy_status(record, claim) != "rejected"
            and review_scope_covers(prop.review_scope, claim)
            and reaction_energy_definition_compatible(prop, claim)
        )
    return review_scope_covers(record.review_scope, claim)


def _reaction_claim_explicit_conflict(record: ReactionRecord, claim: str) -> bool:
    if claim in {"threshold_eV", "delta_e_eV"}:
        prop = record.energy_properties.get(claim)
        return (
            prop is not None
            and channel_energy_status(record, claim) == "conflicting"
            and review_scope_covers(prop.review_scope, claim)
        )
    return record.status == "conflicting"


def _reaction_claim_content(record: ReactionRecord, claim: str) -> dict:
    """Compare one reviewed claim, independently of other declared quantities.

    The common scientific view already separates independent numerical
    datasets. This projection compares the physical equation, qualifications,
    and retained conditions for one claim, omitting the other scalar energy.
    Unknown conditions and annotations still matter.
    """
    content = scientific_reaction_content(record)
    if any((state.structure or "").startswith("smiles:") for state in record.states):
        _compare_reaction_claim_graphs(record, content)
    if claim in {"threshold_eV", "delta_e_eV"}:
        # A channel assertion's quality or an independent energy is not part
        # of this quantity's qualification. Its own source declaration is
        # retained in the Property, while the physical channel fixes target.
        return {
            name: content.get(name)
            for name in (
                "id",
                "reaction",
                "family",
                "type",
                "channel_scope",
                "third_body",
                "surface",
                "stabilization",
            )
        } | {
            "energy_property": content.get("energy_properties", {}).get(claim),
            "record_stop": record.status if record.status in {"rejected", "conflicting"} else None,
        }
    omitted = set()
    if claim != "threshold_eV":
        omitted.add("threshold_eV")
    if claim != "delta_e_eV":
        omitted.update({"delta_e_eV", "deltaE_products_minus_reactants_eV"})
    for declaration in (content, content.get("source_declaration")):
        if not isinstance(declaration, dict):
            continue
        for name in omitted:
            declaration.pop(name, None)
        declaration.pop("energy_properties", None)
        if "review_scope" in declaration:
            declaration["review_scope"] = [claim]
    return content


def _compare_reaction_claim_graphs(record: ReactionRecord, content: dict) -> None:
    physical = physical_equation_key(record.equation_key)
    for declaration in (content, content.get("source_declaration")):
        if not isinstance(declaration, dict) or not isinstance(
            text := declaration.get("reaction"), str
        ):
            continue
        parsed = parse_equation(text)
        if parsed is None:
            continue
        (third_body, _, reactants, products), states = parsed
        if physical_equation_key((third_body, physical[1], reactants, products)) != physical:
            continue
        declaration["reaction"] = physical
        if isinstance(transformation := declaration.get("transformation"), dict):
            aliases = {state.id: physical_state_id(state.id) for state in states}
            declaration["transformation"] = bind_transformation_states(transformation, aliases)


def _checked_energy_relation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    values: dict[str, float],
    reaction_evidence: ReactionEvidence,
    state_evidence: dict[str, StateEvidence],
    source_conflicts: tuple[str, ...],
) -> Assessment | None:
    sources = reaction_evidence.sources
    if reaction.process == "ionization":
        if "threshold_eV" in source_conflicts:
            requirements = _ionization_requirements(
                reaction, candidates, state_evidence, reaction_evidence
            )
            return Assessment(
                VERDICT_UNKNOWN,
                sources,
                "declared ionization-energy relation is undetermined; "
                + "; ".join(dict.fromkeys(item.reason for item in requirements if item.reason)),
                requirements=requirements,
            )
        return _ionization_energy_relation(
            reaction, candidates, values, reaction_evidence, state_evidence
        )
    if reaction.process == "elastic":
        if _process_pattern(reaction, candidates) is not True:
            return Assessment(
                VERDICT_FAIL,
                ("elastic equation identity",),
                "elastic internal-energy identity requires unchanged participant states",
            )
        if source_conflicts:
            return Assessment(
                VERDICT_UNKNOWN,
                sources,
                "reviewed elastic internal-energy declarations are invalid or conflict",
            )
        changed = any(
            abs(values.get(name, 0.0)) > 1e-9 for name in ("threshold_eV", "source_delta_e_eV")
        )
        if changed:
            return Assessment(
                VERDICT_FAIL, sources, "elastic identity has a nonzero internal-energy change"
            )
        return Assessment(
            VERDICT_PASS,
            ("identical internal states",),
            "internal energy change is zero; translational energy transfer is undetermined",
        )
    if (
        reaction.process in {"charge_exchange", "resonant_charge_exchange"}
        and "source_delta_e_eV" in source_conflicts
    ):
        requirements = _relation_requirements(
            reaction, candidates, state_evidence, reaction_evidence
        )
        return Assessment(
            VERDICT_UNKNOWN,
            sources,
            "declared energy-defect relation is undetermined; "
            + "; ".join(dict.fromkeys(item.reason for item in requirements if item.reason)),
            requirements=requirements,
        )
    if "source_delta_e_eV" in values and "charge_transfer_energy_defect_eV" in values:
        return _charge_defect_consistency(reaction, candidates, state_evidence, reaction_evidence)
    return None


def _charge_defect_consistency(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
) -> Assessment:
    declared = _reaction_energy_choices(reaction_evidence, "delta_e_eV")
    declared_ranges = [property_energy_bounds(prop) for _, prop in declared]
    derived, energy_sources, uncertainty_known = _charge_transfer_bounds(
        reaction, candidates, evidence
    )
    basis = tuple(
        sorted(
            set(energy_sources + tuple(prop.source or record.label for record, prop in declared))
        )
    )
    if derived is None or not declared_ranges or any(item is None for item in declared_ranges):
        missing: list[Requirement] = []
        if not declared_ranges or any(item is None for item in declared_ranges):
            missing.extend(
                _channel_energy_requirements(reaction.id, reaction_evidence, "delta_e_eV")
            )
        if derived is None:
            missing.extend(_charge_defect_input_requirements(reaction, candidates, evidence))
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "energy-defect consistency cannot use invalid or qualitative declaration ranges",
            requirements=tuple(missing),
        )
    ranges = [item for item in declared_ranges if item is not None]
    source = min(item[0] for item in ranges), max(item[1] for item in ranges)
    overlap = max(source[0], derived[0]) <= min(source[1], derived[1]) or isclose(
        max(source[0], derived[0]), min(source[1], derived[1]), rel_tol=1e-12, abs_tol=0.0
    )
    scope = (
        "Compatibility of declared internal-energy-defect ranges; overlap does not "
        "establish equal true values, statistical confidence, rate or occurrence."
    )
    if not uncertainty_known or any(prop.uncertainty is None for _, prop in declared):
        scope += (
            " Undeclared uncertainties permit a nominal consistency comparison only "
            "and are not zero errors."
        )
    return Assessment(
        VERDICT_PASS if overlap else VERDICT_FAIL,
        basis,
        f"declared defect [{source[0]:.15g}, {source[1]:.15g}] eV and "
        f"identity-derived defect [{derived[0]:.15g}, {derived[1]:.15g}] eV "
        + ("are compatible" if overlap else "are disjoint"),
        scope=scope,
    )


def _charge_defect_input_requirements(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[Requirement, ...]:
    _, model_requirements = _charge_transfer_inputs(reaction, candidates)
    if model_requirements:
        return model_requirements
    missing = tuple(
        requirement
        for state_id, names in _relation_energy_quantities(reaction, candidates).items()
        for name in sorted(names)
        if (matched := evidence.get(state_id)) is None
        or _energy_property_bounds(matched, name)[0] is None
        for requirement in _energy_requirements(state_id, evidence.get(state_id), name)
    )
    return missing or (
        Requirement(
            "external_models",
            reaction.id,
            "charge_transfer_energy_budget",
            "evaluate the declared energy-defect bounds with a numerical representation "
            "supporting these declarations",
        ),
    )


def _charge_transfer_bounds(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[tuple[float, float] | None, tuple[str, ...], bool]:
    pair, _ = _charge_transfer_inputs(reaction, candidates)
    if pair is None:
        return None, (), False
    ion, donor, target = pair
    if donor.key == target.key:
        return (0.0, 0.0), ("identical physical states",), True
    name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
    first, first_sources = _energy_property_bounds(
        evidence.get(donor.id, StateEvidence("none", ())), name
    )
    second, second_sources = _energy_property_bounds(
        evidence.get(target.id, StateEvidence("none", ())), name
    )
    sources = tuple(sorted(set(first_sources + second_sources)))
    uncertainty_known = all(
        prop.uncertainty is not None
        for state in (donor, target)
        for prop in _property_choices(evidence.get(state.id, StateEvidence("none", ())), name)
    )
    if first is None or second is None:
        return None, sources, uncertainty_known
    positive, negative = (second, first) if ion.charge > 0 else (first, second)
    bounds = positive[0] - negative[1], positive[1] - negative[0]
    return (
        (bounds if all(isfinite(value) for value in bounds) else None),
        sources,
        uncertainty_known,
    )


def _ionization_energy_relation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    values: dict[str, float],
    reaction_evidence: ReactionEvidence,
    state_evidence: dict[str, StateEvidence],
) -> Assessment | None:
    """Compare declarations, without treating uncertainty as an absolute physical bound.

    Declared intervals are compared on both sides when available. Missing
    uncertainty leaves only a nominal consistency check, never an invented
    zero measurement error or an absolute experimental bound.
    """
    # Ground-parent IE is a lower bound for appearance into the same ionic
    # composition, not an equality to an excited-product threshold.
    parent = _ionization_parent(reaction, candidates)
    if parent is None or "threshold_eV" not in values or "ionization_energy_eV" not in values:
        return None
    parent_id = parent.id
    bounds, ionization_sources = _ionization_bounds(state_evidence[parent_id])
    threshold_properties = _reaction_energy_choices(reaction_evidence, "threshold_eV")
    threshold_ranges = [property_energy_bounds(prop) for _, prop in threshold_properties]
    threshold_sources = tuple(prop.source or record.label for record, prop in threshold_properties)
    basis = tuple(sorted(set(threshold_sources + ionization_sources)))
    if bounds is None or not threshold_ranges or any(item is None for item in threshold_ranges):
        quantities = []
        if bounds is None:
            quantities.append(
                Requirement(
                    "source_review",
                    parent_id,
                    "ionization_energy_eV.uncertainty",
                    "provide valid, consistent ionization declaration ranges",
                )
            )
        if not threshold_ranges or any(item is None for item in threshold_ranges):
            quantities.append(
                Requirement(
                    "source_review",
                    reaction.id,
                    "threshold_eV.uncertainty",
                    "provide valid, consistent threshold declaration ranges",
                )
            )
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            (
                "threshold and IE cannot be compared because a declaration range is "
                "invalid or only qualitative; threshold measurement uncertainty is not "
                "evaluated"
            ),
            requirements=tuple(quantities),
        )
    lower, upper = bounds
    valid_threshold_ranges = [item for item in threshold_ranges if item is not None]
    threshold_lower = min(item[0] for item in valid_threshold_ranges)
    threshold_upper = max(item[1] for item in valid_threshold_ranges)
    threshold_uncertainty = all(prop.uncertainty is not None for _, prop in threshold_properties)
    ionization_uncertainty = all(
        prop.uncertainty is not None
        for prop in _property_choices(state_evidence[parent_id], "ionization_energy_eV")
    )
    threshold = (
        f"threshold declaration range [{threshold_lower:.15g}, {threshold_upper:.15g}] eV"
        if threshold_uncertainty
        else f"declared threshold point {values['threshold_eV']:.15g} eV"
    )
    relationship = f"{threshold} and IE declaration range [{lower:.15g}, {upper:.15g}] eV"
    scope = (
        (
            "Consistency over both declared uncertainty ranges; confidence, "
            "correlations, rate and occurrence are undetermined."
        )
        if threshold_uncertainty and ionization_uncertainty
        else (
            "Nominal declared-data consistency using the available ranges; "
            "undeclared measurement uncertainties are not zero errors, and rate and"
            " occurrence are undetermined."
        )
    )
    if any(prop.definition is None for _, prop in threshold_properties):
        scope += " Threshold definition beyond the exact-channel declaration is unspecified."
    notes = "; " + scope
    if not threshold_uncertainty:
        notes += "; threshold measurement uncertainty is not evaluated"
    if threshold_upper < lower and not isclose(threshold_upper, lower, rel_tol=1e-12, abs_tol=0.0):
        return Assessment(
            VERDICT_FAIL,
            basis,
            f"{relationship}: threshold is below the IE lower bound{notes}",
            scope=scope,
        )
    if threshold_lower >= upper:
        return Assessment(
            VERDICT_PASS,
            basis,
            f"{relationship}: threshold meets the IE lower bound throughout "
            f"the stated ranges{notes}",
            scope=scope,
        )
    return Assessment(
        VERDICT_UNKNOWN,
        basis,
        f"{relationship}: the lower-bound relation is unresolved within the "
        f"declared uncertainties or unit-conversion precision{notes}",
        scope=scope,
        requirements=tuple(
            Requirement(
                "source_information",
                target,
                f"{quantity}.uncertainty",
                (
                    "review or refine these declaration ranges to resolve the overlapping "
                    "threshold-versus-IE relation"
                ),
            )
            for target, quantity in (
                (reaction.id, "threshold_eV"),
                (parent_id, "ionization_energy_eV"),
            )
        ),
    )


def _ionization_bounds(
    evidence: StateEvidence,
) -> tuple[tuple[float, float] | None, tuple[str, ...]]:
    return _energy_property_bounds(evidence, "ionization_energy_eV")


def _energy_property_bounds(
    evidence: StateEvidence,
    name: str,
) -> tuple[tuple[float, float] | None, tuple[str, ...]]:
    """Convert declared ranges; their envelope is not a combined statistical error.

    All trusted declarations remain relevant when their uncertainties differ.
    Different central values, invalid ranges, and note-only uncertainty do not
    support an energy inequality. No uncertainty declares a point, not an
    invented error bar. Sources remain separate rather than being averaged.
    """
    properties = _property_offers(evidence, name) if evidence.match == "exact" else []
    return _bounds_from_offers(properties)


def _bounds_from_offers(
    properties: list[tuple[StateRecord, Property]],
) -> tuple[tuple[float, float] | None, tuple[str, ...]]:
    sources = tuple(sorted({prop.source or record.label for record, prop in properties}))
    ranges: list[tuple[float, float]] = []
    for _, prop in properties:
        bounds = property_energy_bounds(prop)
        if bounds is None:
            return None, sources
        ranges.append(bounds)
    if not energy_declarations_agree([prop for _, prop in properties]):
        return None, sources
    return (
        ((min(low for low, _ in ranges), max(high for _, high in ranges)), sources)
        if ranges
        else (None, sources)
    )


def assess_reaction_evidence(
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    materials: frozenset[str] = frozenset(),
) -> Assessment:
    result = _reaction_evidence_support(reaction, evidence, materials)
    return replace(
        result,
        proposition="channel_evidence_support",
        scope=(
            "Reviewed support for the exact state-resolved equation and process; "
            "occurrence under the supplied conditions and rate are undetermined."
        ),
    )


def _reaction_evidence_support(
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    materials: frozenset[str],
) -> Assessment:
    if reaction.surface is not None and reaction.surface not in materials:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            f"surface material {reaction.surface} has no material record",
            requirements=(
                Requirement(
                    "identity",
                    reaction.surface,
                    "surface_material",
                    "identify the material reservoir participating in this channel",
                ),
            ),
        )
    if _reaction_claim_conflicts(evidence, "channel_assertion"):
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "matching channel assertions have conflicting scientific declarations",
            requirements=(
                Requirement(
                    "source_review",
                    reaction.id,
                    "channel_assertion",
                    "resolve the contradictory exact channel assertions",
                ),
            ),
        )
    if evidence.reviewed:
        return Assessment(
            VERDICT_PASS,
            tuple(
                record.label
                for record in evidence.exact_records
                if record.reviewed_for("channel_assertion")
            ),
            "an exact state-resolved equation is listed",
        )
    if evidence.exact_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.exact_records),
            "matching equation records do not carry a reviewed channel assertion",
            requirements=(
                Requirement(
                    "source_review",
                    reaction.id,
                    "channel_assertion",
                    (
                        "review this exact state-resolved equation and process independently of"
                        " its coefficient or energies"
                    ),
                ),
            ),
        )
    if evidence.overlay_datasets:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(dataset.id for dataset in evidence.overlay_datasets),
            "channel-bound numerical datasets do not establish a reviewed channel assertion",
            requirements=(
                Requirement(
                    "source_information",
                    reaction.id,
                    "channel_assertion",
                    (
                        "obtain evidence for the exact equation and process; a channel-bound "
                        "numerical dataset is insufficient"
                    ),
                ),
            ),
        )
    if evidence.total_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.total_records),
            "only a related total-process record is available",
            requirements=(
                Requirement(
                    "source_information",
                    reaction.id,
                    "channel_assertion",
                    (
                        "obtain evidence for the actual products and state-resolved channel, "
                        "rather than a total process"
                    ),
                ),
            ),
        )
    if evidence.related_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.related_records),
            "the equation is listed only for a different physical process",
            requirements=(
                Requirement(
                    "source_information",
                    reaction.id,
                    "channel_assertion",
                    "obtain evidence for this actual physical process and exact equation",
                ),
            ),
        )
    if reaction.origin == "attested_only":
        return Assessment(
            VERDICT_UNKNOWN,
            (),
            "attested origin has no recoverable source for the channel assertion",
            requirements=(
                Requirement(
                    "source_information",
                    reaction.id,
                    "channel_assertion",
                    "recover evidence for this exact channel; missing provenance does not deny it",
                ),
            ),
        )
    return Assessment(
        VERDICT_UNKNOWN,
        (),
        "no source lists this exact equation",
        requirements=(
            Requirement(
                "source_information",
                reaction.id,
                "channel_assertion",
                "obtain evidence listing this exact state-resolved equation and process",
            ),
        ),
    )


def assess_kinetics(
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    conditions: Conditions,
    selection: DataSelection | None = None,
    *,
    conservation: Assessment | None = None,
) -> tuple[Assessment, DataUse]:
    use = data_use(
        reaction,
        evidence,
        conditions,
        selection,
        equation_refuted=conservation is not None and conservation.verdict == VERDICT_FAIL,
    )
    verdict = coefficient_availability_verdict(use.status, (item.status for item in use.datasets))
    basis = (
        (use.dataset_id,)
        if use.dataset_id is not None
        else tuple(item.dataset_id for item in use.datasets)
    )
    return Assessment(
        verdict,
        basis,
        use.reason,
        "rate_coefficient_availability",
        (
            "A usable rate coefficient in the supplied evidence under supplied "
            "conditions; probability or "
            "curve availability is reported separately in data_use and does not "
            "establish channel occurrence."
        ),
    ), use


def _thermo_records(
    reaction: ReactionCandidate,
    evidence: dict[str, StateEvidence],
    temperature_K: float | None = None,
) -> tuple[dict[str, StateRecord], dict[tuple[str, str], StateRecord]]:
    """Select one quantity view and its actual inputs for the thermal difference."""
    electron_term_required = net_electron_coefficient(reaction) != 0
    sources: dict[tuple[str, str], StateRecord] = {}
    selected = {
        state_id: record
        for state_id in net_stoichiometry(reaction)
        if (
            record := _preferred_state(
                state_id,
                evidence,
                electron_term_required=electron_term_required,
                temperature_K=temperature_K,
                sources=sources,
            )
        )
        is not None
    }
    return selected, sources


def _identity_energy(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float] | None:
    if reaction.process == "ionization" and _ionization_parent(reaction, candidates) is None:
        return None
    heavy_reactants = [term.species for term in reaction.reactants if term.species != ELECTRON]
    if len(heavy_reactants) != 1:
        return None
    reactant_id = heavy_reactants[0]
    reactant = candidates.states[reactant_id]
    products = [
        candidates.states[term.species]
        for term in reaction.products
        if term.species != ELECTRON
        and candidates.states[term.species].composition == reactant.composition
        and candidates.states[term.species].phase == reactant.phase
        and candidates.states[term.species].structure == reactant.structure
    ]
    record = _preferred_state(reactant_id, evidence)
    if record is None or reactant.state.kind != "ground":
        return None
    if any(product.charge == reactant.charge + 1 for product in products):
        value = _eV_value(record, "ionization_energy_eV")
        return None if value is None else ("ionization_energy_eV", value)
    if any(product.charge == reactant.charge - 1 for product in products):
        value = _eV_value(record, "electron_affinity_eV")
        return None if value is None else ("electron_affinity_eV", value)
    return None


def _ionization_parent(
    reaction: ReactionCandidate, candidates: CandidateSet
) -> StateCandidate | None:
    """Resolve the actual gas-phase whole-species ionization relation.

    A corresponding ionic excitation can only raise the ground ionic energy;
    a different structure or phase has no such bound from this parent IE.
    The electron pattern checks the formula and charge change. The IE model
    also needs the product to share the parent's represented structure.
    """
    if (
        reaction.family != "electron"
        or reaction.process != "ionization"
        or _process_pattern(reaction, candidates) is not True
    ):
        return None
    parent = next(
        candidates.states[term.species] for term in reaction.reactants if term.species != ELECTRON
    )
    product = next(
        candidates.states[term.species] for term in reaction.products if term.species != ELECTRON
    )
    return (
        parent
        if parent.phase == "gas"
        and parent.state.kind == "ground"
        and parent.structure == product.structure
        else None
    )


def _energy_feasibility(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, Assessment | None] | None:
    """Check electron binding or a comparable defect, never channel occurrence."""

    if reaction.process == "attachment":
        # A mislabeled dissociative channel must not inherit parent-anion EA.
        parent = [
            candidates.states[term.species]
            for term in reaction.reactants
            if term.species != ELECTRON
        ]
        products = [
            candidates.states[term.species]
            for term in reaction.products
            if term.species != ELECTRON
        ]
        if (
            len(parent) == len(products) == 1
            and parent[0].composition == products[0].composition
            and parent[0].charge == 0
            and products[0].charge == -1
            and parent[0].state.kind == products[0].state.kind == "ground"
            and parent[0].phase == products[0].phase
            and parent[0].structure == products[0].structure
        ):
            return _attachment_feasibility(reaction, evidence)
        return None
    if reaction.process in {"charge_exchange", "resonant_charge_exchange"}:
        return _charge_transfer_feasibility(reaction, candidates, evidence)
    return None


def _attachment_feasibility(
    reaction: ReactionCandidate,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, Assessment | None] | None:
    parent = next(
        (term.species for term in reaction.reactants if term.species != ELECTRON),
        None,
    )
    if parent is None:
        return None
    record = _preferred_state(parent, evidence)
    matched = evidence.get(parent)
    if matched is None:
        return None
    binding = _electron_binding_support(matched)
    value = None if record is None else _eV_value(record, "electron_affinity_eV")
    if binding.verdict == VERDICT_FAIL:
        binding = replace(
            binding,
            message="direct attachment into the ground parent anion requires electron binding; "
            + binding.message,
        )
    if binding.verdict == VERDICT_PASS:
        binding = replace(
            binding,
            message=binding.message + "; stabilization, rate and occurrence are undetermined",
        )
    if binding.verdict == VERDICT_UNKNOWN:
        binding = replace(
            binding, requirements=_energy_requirements(parent, matched, "electron_affinity_eV")
        )
    return (
        "electron_affinity_eV",
        value,
        binding,
    )


def _charge_transfer_feasibility(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, Assessment | None] | None:
    pair, _ = _charge_transfer_inputs(reaction, candidates)
    if pair is None:
        return None
    ion, donor_state, acceptor_state = pair
    if donor_state.key == acceptor_state.key:
        return ("charge_transfer_energy_defect_eV", 0.0, None)
    donor = _preferred_state(donor_state.id, evidence)
    acceptor = _preferred_state(acceptor_state.id, evidence)
    if donor is None or acceptor is None:
        return None
    property_name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
    return _charge_transfer_declared_defect(reaction, donor, acceptor, property_name)


def _charge_transfer_inputs(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
) -> tuple[
    tuple[StateCandidate, StateCandidate, StateCandidate] | None,
    tuple[Requirement, ...],
]:
    """Resolve the gas-ground IE/EA defect model for the actual channel.

    Pattern agreement concerns the represented charge transfer, while this
    narrower correspondence fixes the states whose IE/EA may be subtracted.
    Scalar calculation, declaration ranges and prerequisite reporting consume
    this same result; no extra data can repair a different physical relation.
    """
    unsupported = (
        Requirement(
            "external_models",
            reaction.id,
            "charge_transfer_energy_relation",
            "the implemented IE/EA defect relation requires a singly charged gas "
            "ground ion, a gas ground neutral and their corresponding unchanged-structure "
            "ground products; these actual participants need another energy model",
        ),
    )
    participants = [
        candidates.states[term.species]
        for term in (*reaction.reactants, *reaction.products)
        if term.species != ELECTRON
    ]
    if (
        _process_pattern(reaction, candidates) is not True
        or reaction.surface is not None
        or any(state.state.kind != "ground" or state.phase != "gas" for state in participants)
        or any(term.n != 1 for term in (*reaction.reactants, *reaction.products))
    ):
        return None, unsupported
    reactants = [candidates.states[term.species] for term in reaction.reactants]
    ion = next((state for state in reactants if state.charge), None)
    target = next((state for state in reactants if state.charge == 0), None)
    if ion is None or target is None or abs(ion.charge) != 1:
        return None, unsupported
    resolved = []
    for parent, charge in ((ion, 0), (target, 0), (target, ion.charge)):
        found = ground_reference_state(parent, candidates.states, charge)
        if found is None:
            return None, (
                Requirement(
                    "identity",
                    parent.id,
                    "charge_transfer_ground_correspondence",
                    "identify a unique corresponding ground state with this composition, "
                    "phase and structure for the charge-transfer energy balance",
                ),
            )
        resolved.append(found)
    donor, acceptor, product = resolved
    expected_products = tuple(sorted(((donor.id, 1.0), (product.id, 1.0))))
    if reaction.equation_key[3] != expected_products:
        return None, unsupported
    return (ion, donor, acceptor), ()


def _charge_transfer_declared_defect(
    reaction: ReactionCandidate,
    donor: StateRecord,
    acceptor: StateRecord,
    property_name: str,
) -> tuple[str, float | None, Assessment | None] | None:
    donor_energy = _eV_value(donor, property_name)
    acceptor_energy = _eV_value(acceptor, property_name)
    if donor_energy is None or acceptor_energy is None:
        return None
    defect = (
        acceptor_energy - donor_energy
        if property_name == "ionization_energy_eV"
        else donor_energy - acceptor_energy
    )
    if not isfinite(defect):
        return (
            "charge_transfer_energy_defect_eV",
            None,
            Assessment(
                VERDICT_UNKNOWN,
                (donor.label, acceptor.label),
                "charge-transfer energy difference is not finite",
                requirements=(
                    Requirement(
                        "external_models",
                        reaction.id,
                        "charge_transfer_energy_budget",
                        "evaluate this energy difference with a numerical representation "
                        "supporting these declarations",
                    ),
                ),
            ),
        )
    return (
        "charge_transfer_energy_defect_eV",
        defect,
        None,
    )


def _penning_energy_relation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
    conditions: Conditions,
    screening_values: dict[tuple[str, str], tuple[EnergyInput, ...]] | None,
    screening_property_issues: dict[tuple[str, str], tuple[Requirement, ...]] | None,
) -> tuple[Assessment, dict[str, float]]:
    """Check N* + M -> N(ground) + M+(ground) + e energy declarations.

    The excitation-minus-IE relation applies only to those actual identities.
    Excited products, chemical rearrangement, and lumped populations require
    another energy model. IUPAC defines the unchanged-species transfer in
    https://goldbook.iupac.org/terms/view/12520 . Range differences use the
    envelope of independent declarations, without assuming error correlations.
    """
    pair = _penning_ground_products(reaction, candidates)
    if pair is None:
        return Assessment(
            VERDICT_UNKNOWN,
            (),
            "Penning excitation-minus-IE relation requires a resolved neutral donor, "
            "a neutral ground-state target, and their corresponding ground-state products",
            requirements=(
                Requirement(
                    "external_models",
                    reaction.id,
                    "penning_energy_relation",
                    (
                        "the current excitation-minus-IE model does not cover these actual "
                        "identities or state resolutions"
                    ),
                ),
            ),
        ), {}
    excited_id, target_id = pair
    excited_record = _preferred_state(excited_id, evidence)
    target_record = _preferred_state(target_id, evidence)
    excitation = (
        None if excited_record is None else _eV_value(excited_record, "excitation_energy_eV")
    )
    ionization = None if target_record is None else _eV_value(target_record, "ionization_energy_eV")
    excitation_bounds, excitation_sources = _energy_property_bounds(
        evidence.get(excited_id, StateEvidence("none", ())), "excitation_energy_eV"
    )
    ionization_bounds, ionization_sources = _energy_property_bounds(
        evidence.get(target_id, StateEvidence("none", ())), "ionization_energy_eV"
    )
    basis = tuple(sorted(set(excitation_sources + ionization_sources)))
    if excitation is None or ionization is None:
        missing = tuple(
            requirement
            for state_id, name, value in (
                (excited_id, "excitation_energy_eV", excitation),
                (target_id, "ionization_energy_eV", ionization),
            )
            if value is None
            for requirement in _energy_requirements(state_id, evidence.get(state_id), name)
        )
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "reviewed Penning energy evidence is missing",
            requirements=missing,
        ), {}
    available = excitation - ionization
    if not isfinite(available):
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "Penning energy difference is not finite",
            requirements=(
                Requirement(
                    "external_models",
                    reaction.id,
                    "penning_energy_budget",
                    (
                        "evaluate the energy difference with a numerical representation "
                        "supporting these declarations"
                    ),
                ),
            ),
        ), {}
    values = {"penning_available_energy_eV": available}
    if excitation_bounds is None or ionization_bounds is None:
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "Penning energy declarations have conflicting values or invalid or unspecified "
            "uncertainty ranges",
            requirements=tuple(
                Requirement(
                    "source_review",
                    state_id,
                    f"{name}.uncertainty",
                    "provide valid, consistent declaration ranges for this energy quantity",
                )
                for state_id, name, bounds in (
                    (excited_id, "excitation_energy_eV", excitation_bounds),
                    (target_id, "ionization_energy_eV", ionization_bounds),
                )
                if bounds is None
            ),
        ), values
    has_uncertainty = all(
        prop.uncertainty is not None
        for state_id, name in (
            (excited_id, "excitation_energy_eV"),
            (target_id, "ionization_energy_eV"),
        )
        for prop in _property_choices(evidence[state_id], name)
    )
    if screening_values is None:
        screening_values = _screening_inputs(evidence)
    if screening_property_issues is None:
        screening_property_issues = _screening_property_issues(
            evidence, screening_values, _screening_inputs(evidence, apply_selection=False)
        )
    return _penning_budget(
        reaction,
        candidates.states,
        conditions,
        screening_values,
        excitation_bounds,
        ionization_bounds,
        basis,
        has_uncertainty,
        screening_property_issues,
    ), values


def _penning_budget(
    reaction: ReactionCandidate,
    states: dict[str, StateCandidate],
    conditions: Conditions,
    screening_values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    excitation_bounds: tuple[float, float],
    ionization_bounds: tuple[float, float],
    basis: tuple[str, ...],
    has_uncertainty: bool,
    screening_property_issues: dict[tuple[str, str], tuple[Requirement, ...]],
) -> Assessment:
    selected = collision_condition(reaction, conditions)
    if selected is None:
        return Assessment(VERDICT_NA, basis, COLLISION_CONDITION_NOT_APPLICABLE)
    collision, _, collision_requirements = relative_collision_energy(
        reaction, states, screening_values, *selected, property_issues=screening_property_issues
    )
    # Nonnegative kinetic energy can only help the lower bound. A failed
    # conversion of a supplied condition cannot be treated as zero energy.
    if collision is None and collision_requirements:
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            calculation_reason(collision_requirements),
            requirements=collision_requirements,
        )
    kinetic = collision or 0.0
    lower = excitation_bounds[0] + kinetic - ionization_bounds[1]
    upper = excitation_bounds[1] + kinetic - ionization_bounds[0]
    if not isfinite(lower) or not isfinite(upper):
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "Penning energy budget is not finite",
            requirements=(
                Requirement(
                    "external_models",
                    reaction.id,
                    "penning_energy_budget",
                    (
                        "evaluate the energy budget with a numerical representation supporting "
                        "these declarations"
                    ),
                ),
            ),
        )
    relationship = f"Penning declared available-energy range [{lower:.15g}, {upper:.15g}] eV"
    scope = (
        "Declared energy consistency; confidence, correlations, collision-"
        "energy uncertainty, probability and occurrence are undetermined."
    )
    if not has_uncertainty:
        scope += (
            " Undeclared measurement uncertainties permit a nominal comparison only"
            " and are not zero errors."
        )
    note = "; " + scope
    if lower >= 0.0:
        return Assessment(
            VERDICT_PASS,
            basis,
            relationship + ": the energy requirement is met throughout that range" + note,
            scope=scope,
        )
    if (
        collision is not None
        and upper < 0.0
        and not isclose(
            excitation_bounds[1] + kinetic, ionization_bounds[0], rel_tol=1e-12, abs_tol=0.0
        )
    ):
        return Assessment(
            VERDICT_FAIL,
            basis,
            relationship + ": specified collision energy is below the Penning energy "
            "requirement throughout that range" + note,
            scope=scope,
        )
    return Assessment(
        VERDICT_UNKNOWN,
        basis,
        relationship
        + (
            ": collision energy is needed to test this internal-energy deficit"
            if upper < 0.0 and collision is None
            else ": the energy requirement is unresolved within uncertainty or unit-conversion "
            "precision"
        )
        + note,
        scope=scope,
        requirements=(
            Requirement(
                "user_inputs",
                reaction.id,
                "collision_energy_eV",
                "provide a specified collision energy to test this internal-energy deficit",
            )
            if upper < 0.0 and collision is None
            else Requirement(
                "source_information",
                reaction.id,
                "penning_energy_uncertainty",
                (
                    "obtain excitation and ionization ranges that resolve their overlapping"
                    " energy budget"
                ),
            ),
        ),
    )


def _penning_ground_products(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
) -> tuple[str, str] | None:
    participants = _participants(reaction, candidates)
    if (
        reaction.surface is not None
        or reaction.third_body is not None
        or (
            reaction.transformation
            and _transformation_pattern(reaction, candidates, participants) is not True
        )
    ):
        return None
    for target, ion, donor, ground in _collision_ionization_matches(reaction, participants):
        # Only this model reduces two exact ground correspondences to IE and
        # the donor's ground-relative excitation energy.
        if (
            target.charge == donor.charge == 0
            and target.state.kind == ion.state.kind == ground.state.kind == "ground"
            and all(
                state.phase == "gas" and state.state.resolution == "resolved"
                for state in (target, ion, donor, ground)
            )
            and endpoint_structure_matches(physical_state_key(target), physical_state_key(ion))
            and endpoint_structure_matches(physical_state_key(donor), physical_state_key(ground))
        ):
            return donor.id, target.id
    return None


def _eV_value(record: StateRecord, name: str) -> float | None:
    value = record.properties.get(name)
    if (
        value is None
        or value.value is None
        or not value.reviewed_for(name)
        or _state_energy_incompatibility(value, name, record.candidate) is not None
    ):
        return None
    return energy_eV(value.value, value.unit)


def _preferred_state(
    state_id: str | None,
    evidence: dict[str, StateEvidence],
    *,
    electron_term_required: bool = False,
    temperature_K: float | None = None,
    sources: dict[tuple[str, str], StateRecord] | None = None,
) -> StateRecord | None:
    if state_id is None:
        return None
    matched = evidence.get(state_id)
    if matched is None or matched.match != "exact" or matched.preferred is None:
        return None
    properties: dict[str, Property] = {}
    names = {name for record in matched.records for name in record.properties}
    if matched.selection is not None:
        names.update(
            name
            for name in set(matched.selection.quantities)
            | set(matched.selection.targets.get(state_id, {}))
            if name.endswith("_eV")
        )
    for name in names:
        offered = _property_offers(matched, name, electron_term_required=electron_term_required)
        compared = [prop for _, prop in offered]
        if not compared or _property_declarations_conflict(
            name,
            compared,
            charge=matched.preferred.candidate.charge,
            electron_term_required=electron_term_required,
        ):
            continue
        record, properties[name] = min(
            offered,
            key=lambda pair: (
                TIER_RANK.get(pair[1].tier, 5),
                pair[1].source or "",
                repr(pair[1]),
                pair[0].id,
                calculation_record_reference(pair[0]),
            ),
        )
        if sources is not None:
            sources[state_id, name] = record
    thermos = _thermo_offers(matched, temperature_K=temperature_K)
    thermo = None
    if thermos and len({_thermo_physical_key(item) for _, item in thermos}) == 1:
        record, thermo = min(
            thermos,
            key=lambda pair: (
                TIER_RANK.get(pair[1].tier, 5),
                pair[1].source or "",
                pair[0].id,
                calculation_record_reference(pair[0]),
            ),
        )
        if sources is not None:
            sources[state_id, "thermochemical_model"] = record
    # This is an aggregate, not one raw declaration. Its selected energy
    # Property must not inherit a different source's legacy scalar.
    return replace(matched.preferred, properties=properties, thermo=thermo, energy_eV=None)


def _reviewed_property_records(
    evidence: StateEvidence, name: str
) -> list[tuple[StateRecord, Property]]:
    return [
        (record, prop)
        for record in evidence.records
        if record.status not in {"rejected", "conflicting"}
        and (prop := record.properties.get(name)) is not None
        and prop.reviewed_for(name)
        and _state_energy_incompatibility(prop, name, record.candidate) is None
    ]


def _property_choices(
    evidence: StateEvidence, name: str, *, electron_term_required: bool = False
) -> list[Property]:
    return [
        prop
        for _, prop in _property_offers(
            evidence, name, electron_term_required=electron_term_required
        )
    ]


def _property_offers(
    evidence: StateEvidence, name: str, *, electron_term_required: bool = False
) -> list[tuple[StateRecord, Property]]:
    """Apply qualification and selection to the original record-property pairs."""
    choices = _reviewed_property_records(evidence, name)
    policy = _state_quantity_policy(evidence, name)
    if policy is not None and (policy.record is not None or policy.mode == "only"):
        choices = _requested_state_records(evidence, name, policy, choices)
    if name == "enthalpy_formation_eV":
        charge = evidence.records[0].candidate.charge if evidence.records else 0
        referenced = [
            (record, prop)
            for record, prop in choices
            if prop.formation_reference is not None
            and prop.formation_reference.complete_for_charge(charge)
        ]
        choices = referenced or choices
        # An absent auxiliary electron term cannot hide a contradictory Hf value.
        if electron_term_required and not _property_declarations_conflict(
            name, [prop for _, prop in choices], charge=charge
        ):
            completed = [
                (record, prop)
                for record, prop in choices
                if prop.formation_reference is not None
                and prop.formation_reference.complete_for_charge(
                    charge, electron_term_required=True
                )
            ]
            choices = completed or choices
    informative = [
        (record, prop)
        for record, prop in choices
        if prop.value is not None or prop.qualifier is not None
    ]
    choices = informative or choices
    if policy is None or policy.record is not None:
        return choices
    usable = [
        (record, prop)
        for record, prop in choices
        if property_energy_bounds(prop) is not None
        or (name == "electron_affinity_eV" and _explicit_electron_nonbinding(prop))
    ]
    choices = usable or choices
    if policy.mode == "only":
        return choices
    groups: dict[tuple, list[tuple[StateRecord, Property]]] = {}
    for record, prop in choices:
        # Hf at different reference conditions is not a source alternative.
        # Prefer cannot choose a reference convention on behalf of the user.
        key = (
            (
                _formation_quantity_key(
                    prop, record.candidate.charge, electron_term_required=electron_term_required
                ),
            )
            if name == "enthalpy_formation_eV"
            else ()
        )
        groups.setdefault(key, []).append((record, prop))
    return [
        item
        for group in groups.values()
        for item in _requested_state_records(evidence, name, policy, group)
    ]


def _state_quantity_policy(evidence: StateEvidence, quantity: str) -> QuantitySelection | None:
    target = evidence.target or (evidence.records[0].candidate.id if evidence.records else None)
    return (
        evidence.selection.for_quantity(quantity, target)
        if evidence.selection is not None
        else None
    )


def _state_source_axes(value: Property | Thermo) -> tuple[str, str | None, str | None]:
    return value.method, value.provenance.provider, value.provenance.collection


def _requested_state_records(
    evidence: StateEvidence,
    quantity: str,
    policy: QuantitySelection,
    eligible: list[tuple[StateRecord, StateQuantity]],
) -> list[tuple[StateRecord, StateQuantity]]:
    """Rank already qualified alternatives; raw declarations remain untouched."""
    if policy.record is not None:
        offered = [
            record
            for record in evidence.records
            if calculation_record_reference(record) == policy.record
        ] or [
            record
            for record in evidence.records
            if selectable_state_record_id(record) == policy.record
        ]
        values = [
            record.thermo if quantity == "thermochemical_model" else record.properties.get(quantity)
            for record in offered
        ]
        if any(value is None for value in values):
            raise ValueError(
                f"data_selection {quantity}: record {policy.record!r} describes another quantity"
            )
        if any(
            value is not None and not policy.allows(*_state_source_axes(value)) for value in values
        ):
            raise ValueError(
                f"data_selection {quantity}: record {policy.record!r} contradicts only restrictions"
            )
        return [(record, value) for record, value in eligible if record in offered]
    allowed = [
        (record, value) for record, value in eligible if policy.allows(*_state_source_axes(value))
    ]
    if policy.mode == "only" or not allowed:
        return allowed
    best = min(policy.rank(*_state_source_axes(value)) for _, value in allowed)
    return [
        (record, value)
        for record, value in allowed
        if policy.rank(*_state_source_axes(value)) == best
    ]


def _formation_quantity_key(
    prop: Property, charge: int | None, *, electron_term_required: bool = False
) -> tuple | None:
    ref = prop.formation_reference
    if ref is None:
        return None
    return (
        ref.temperature_K,
        ref.basis,
        ref.standard_pressure_Pa,
        ref.electron_convention if ref.temperature_K != 0 and charge != 0 else None,
        ref.electron_enthalpy_eV
        if electron_term_required
        and ref.temperature_K != 0
        and charge != 0
        and ref.electron_convention == "ion"
        else 0.0,
    )


def _state_energy_incompatibility(prop: Property, name: str, state: StateCandidate) -> str | None:
    """Identify why this declaration cannot supply the consumed energy quantity.

    NIST distinguishes vertical and adiabatic IE/EA. Only the applicable
    ground-state quantity decides binding or the ground ionization bound.
    Free numerical qualifiers are not numerical bounds: an upper limit may
    include negative EA or an IE below a proposed threshold. Known EA words
    retain their explicit electron-binding or lifetime meanings.
    https://webbook.nist.gov/chemistry/ion/
    """
    if name == "enthalpy_formation_eV":
        return None if property_has_point_qualifier(prop) else "qualifier"
    if name not in {"ionization_energy_eV", "electron_affinity_eV", "excitation_energy_eV"}:
        return None
    if not _related_energy_target_matches(prop, name, state):
        return "relation"
    if name != "excitation_energy_eV" and (state.phase != "gas" or state.state.kind != "ground"):
        return "model"
    qualifier = (prop.qualifier or "").strip().lower()
    supported = {"", "unbound", "unstable", "transient"} if name == "electron_affinity_eV" else {""}
    if qualifier not in supported:
        return "qualifier"
    if name == "excitation_energy_eV":
        return None
    if name == "ionization_energy_eV" and prop.value is not None and prop.value <= 0:
        return "value"
    if (
        name == "electron_affinity_eV"
        and prop.value is None
        and _explicit_electron_nonbinding(prop)
    ):
        return None
    atom = sum(state.composition.values()) == 1
    compatible = prop.definition == "adiabatic" or (atom and prop.definition in {None, "atomic"})
    return None if compatible else "definition"


def _related_energy_target_matches(prop: Property, name: str, state: StateCandidate) -> bool:
    if prop.related_state is None:
        return True
    related = parse_state_id(prop.related_state)
    if related is None:
        return False
    charge = state.charge + {"ionization_energy_eV": 1, "electron_affinity_eV": -1}.get(name, 0)
    return (
        related.composition == state.composition
        and related.charge == charge
        and related.phase == state.phase
        and endpoint_structure_matches(physical_state_key(state), physical_state_key(related))
        and related.state.kind == "ground"
        and related.state.resolution == "resolved"
    )


def _property_declarations_conflict(
    name: str,
    properties: list[Property],
    *,
    charge: int | None = None,
    electron_term_required: bool = False,
) -> bool:
    """Exclude contradictory quantities without suppressing independent properties."""
    if name == "enthalpy_formation_eV":
        references = {
            _formation_quantity_key(prop, charge, electron_term_required=electron_term_required)
            for prop in properties
        }
        if len(references) > 1:
            return True
    if name.endswith("_eV"):
        disagree = not energy_declarations_agree(
            [prop for prop in properties if prop.value is not None]
        )
    else:
        values = {(prop.value, prop.unit) for prop in properties if prop.value is not None}
        disagree = len(values) > 1
    qualifiers = {
        qualifier
        for prop in properties
        if (
            qualifier := _affinity_qualifier(prop)
            if name == "electron_affinity_eV"
            else prop.qualifier
        )
        is not None
    }
    inconsistent_binding = (
        name == "electron_affinity_eV"
        and any(_explicit_electron_nonbinding(prop) for prop in properties)
        and any(
            (bounds := property_energy_bounds(prop)) is not None and bounds[0] > 0.0
            for prop in properties
        )
    )
    return disagree or len(qualifiers) > 1 or inconsistent_binding


def _thermo_choices(evidence: StateEvidence, *, temperature_K: float | None = None) -> list[Thermo]:
    return [thermo for _, thermo in _thermo_offers(evidence, temperature_K=temperature_K)]


def _thermo_offers(
    evidence: StateEvidence, *, temperature_K: float | None = None
) -> list[tuple[StateRecord, Thermo]]:
    declarations = [
        (record, record.thermo)
        for record in evidence.records
        if record.status not in {"rejected", "conflicting"}
        and record.thermo is not None
        and record.thermo.reviewed_for("thermochemical_model")
    ]
    policy = _state_quantity_policy(evidence, "thermochemical_model")
    if policy is None:
        return declarations
    if policy.record is not None:
        return _requested_state_records(evidence, "thermochemical_model", policy, declarations)
    if policy.mode == "only":
        declarations = _requested_state_records(
            evidence, "thermochemical_model", policy, declarations
        )
    applicable = [
        (record, thermo)
        for record, thermo in declarations
        if valid_thermo(thermo)
        and thermo.phase == record.candidate.phase
        and (temperature_K is None or thermo.t_min <= temperature_K <= thermo.t_max)
    ]
    declarations = applicable or declarations
    groups: dict[tuple, list[tuple[StateRecord, Thermo]]] = {}
    for record, thermo in declarations:
        key: tuple = (thermo.phase, thermo.standard_pressure_Pa)
        if temperature_K is None:
            key += (thermo.t_min, thermo.t_max)
        groups.setdefault(key, []).append((record, thermo))
    return [
        item
        for group in groups.values()
        for item in _requested_state_records(evidence, "thermochemical_model", policy, group)
    ]


def _state_selection_requirement(
    evidence: StateEvidence,
    quantity: str,
    *,
    temperature_K: float | None = None,
    electron_term_required: bool = False,
) -> tuple[Requirement, ...]:
    """An excluded qualified value needs selection, not invented source data."""
    if _state_quantity_policy(evidence, quantity) is None:
        return ()
    unrestricted = replace(evidence, selection=None)
    if quantity == "thermochemical_model":
        selected: list = _thermo_choices(evidence, temperature_K=temperature_K)
        offered: list = _thermo_choices(unrestricted, temperature_K=temperature_K)
    else:
        selected = _property_choices(
            evidence, quantity, electron_term_required=electron_term_required
        )
        offered = _property_choices(
            unrestricted, quantity, electron_term_required=electron_term_required
        )
    if selected or not offered:
        return ()
    target = evidence.records[0].candidate.id if evidence.records else ""
    return (
        Requirement(
            "source_selection",
            target,
            quantity,
            "choose an eligible record or relax data_selection; qualified declarations "
            "are present but excluded by the requested record or only restrictions",
        ),
    )


def _thermo_physical_key(thermo: Thermo) -> tuple:
    """NASA7 equality concerns its model and reference domain, not its citation."""
    return (
        thermo.low,
        thermo.high,
        thermo.t_min,
        thermo.t_mid,
        thermo.t_max,
        thermo.phase,
        thermo.standard_pressure_Pa,
    )


def _thermochemical_conflicts(evidence: StateEvidence) -> tuple[str, ...]:
    if evidence.match != "exact":
        return ()
    conflicts = []
    if _property_declarations_conflict(
        "enthalpy_formation_eV",
        _property_choices(evidence, "enthalpy_formation_eV"),
        charge=evidence.records[0].candidate.charge if evidence.records else None,
    ):
        conflicts.append("enthalpy_formation_eV")
    if len({_thermo_physical_key(item) for item in _thermo_choices(evidence)}) > 1:
        conflicts.append("NASA7")
    return tuple(conflicts)


def _relation_energy_quantities(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
) -> dict[str, set[str]]:
    participants = {term.species for term in (*reaction.reactants, *reaction.products)}
    requested: dict[str, set[str]] = {state_id: set() for state_id in participants}
    heavy_parents = [term.species for term in reaction.reactants if term.species != ELECTRON]
    if reaction.process in {"ionization", "attachment"} and len(heavy_parents) == 1:
        requested[heavy_parents[0]].add(
            "ionization_energy_eV" if reaction.process == "ionization" else "electron_affinity_eV"
        )
    if reaction.process in {"charge_exchange", "resonant_charge_exchange"}:
        charge_inputs, _ = _charge_transfer_inputs(reaction, candidates)
        if charge_inputs is not None:
            ion, donor, target = charge_inputs
            name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
            for state in (donor, target):
                requested.setdefault(state.id, set()).add(name)
    if reaction.process == "penning_ionization":
        pair = _penning_ground_products(reaction, candidates)
        if pair is not None:
            requested[pair[0]].add("excitation_energy_eV")
            requested[pair[1]].add("ionization_energy_eV")
    return requested


def _reaction_energy_conflicts(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, ...]:
    """Explain conflicting input quantities without denying independent relations."""
    conflicts = []
    for state_id, names in _relation_energy_quantities(reaction, candidates).items():
        matched = evidence.get(state_id)
        if matched is None or matched.match != "exact":
            continue
        for name in names:
            compared = _property_choices(matched, name)
            if _property_declarations_conflict(
                name,
                compared,
                charge=candidates.states[state_id].charge,
            ):
                conflicts.append(f"{state_id}:{name}")
    return tuple(sorted(conflicts))


_SCREENING_QUANTITIES = (
    "enthalpy_formation_eV",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "excitation_energy_eV",
    "proton_affinity_eV",
    "gas_basicity_eV",
    "mass_amu",
)


def _screening_reference_states(
    states: Mapping[str, StateCandidate], catalog: EvidenceCatalog
) -> dict[str, StateCandidate]:
    """Resolve catalog ground references for the charge/level cycles independently of search."""
    participants: dict[tuple[tuple[str, int], ...], list[StateKey]] = {}
    for state in states.values():
        if state.phase == "gas" and state.state.resolution == "resolved":
            key = physical_state_key(state)
            participants.setdefault(key[0], []).append(key)
    represented = {key for group in participants.values() for key in group}
    references: dict[str, StateCandidate] = {}
    for state in catalog.declared_states(structural_context=states.values()):
        if (
            state.id in states
            or state.phase != "gas"
            or state.state.kind != "ground"
            or state.state.resolution != "resolved"
        ):
            continue
        key = physical_state_key(state)
        if key in represented or not any(
            min(0, participant[1]) <= state.charge <= max(0, participant[1])
            and endpoint_structure_matches(participant, key)
            for participant in participants.get(key[0], ())
        ):
            continue
        if assess_state_consistency(state).verdict == VERDICT_PASS:
            references[state.id] = state
            represented.add(key)
    return references


def _screening_inputs(
    evidence: dict[str, StateEvidence],
    *,
    apply_selection: bool = True,
) -> dict[tuple[str, str], tuple[EnergyInput, ...]]:
    """Keep selected input identities instead of losing them in a composite state."""
    output = {}
    for state_id, matched in evidence.items():
        if matched.match != "exact":
            continue
        for quantity in _SCREENING_QUANTITIES:
            choices = _screening_property_inputs(state_id, matched, quantity, apply_selection)
            if choices:
                output[state_id, quantity] = tuple(choices)
    return output


def _screening_property_issues(
    evidence: dict[str, StateEvidence],
    values: dict[tuple[str, str], tuple[EnergyInput, ...]],
    unrestricted: dict[tuple[str, str], tuple[EnergyInput, ...]],
) -> dict[tuple[str, str], tuple[Requirement, ...]]:
    """Keep qualification failures for offered quantities alongside usable inputs."""
    issues = {}
    for state_id, matched in evidence.items():
        offered = {name for record in matched.records for name in record.properties}
        for quantity in _SCREENING_QUANTITIES:
            key = (state_id, quantity)
            if quantity not in offered or key in values:
                continue
            if quantity == "mass_amu":
                issues[key] = _mass_property_issues(matched, key, unrestricted)
            else:
                issues[key] = _energy_requirements(state_id, matched, quantity)
    return issues


def _mass_property_issues(
    evidence: StateEvidence,
    key: tuple[str, str],
    unrestricted: dict[tuple[str, str], tuple[EnergyInput, ...]],
) -> tuple[Requirement, ...]:
    if key in unrestricted:
        return (
            Requirement(
                "source_selection", *key, "choose a qualified nominal mass or relax data_selection"
            ),
        )
    if evidence.match != "exact":
        return (Requirement("identity", *key, "identify the exact state of the mass declaration"),)
    if any(
        (prop := record.properties.get("mass_amu")) is not None and prop.value is not None
        for record in evidence.records
    ):
        return (
            Requirement(
                "source_review", *key, "review the qualification and unit of the nominal mass"
            ),
        )
    return ()


def _screening_property_inputs(
    state_id: str, evidence: StateEvidence, quantity: str, apply_selection: bool
) -> list[EnergyInput]:
    if quantity == "electron_affinity_eV":
        affinities = _property_choices(evidence, quantity)
        if _property_declarations_conflict(quantity, affinities) or any(
            _explicit_electron_nonbinding(prop) for prop in affinities
        ):
            return []
    declarations = [
        (record, prop)
        for record, prop in _reviewed_property_records(evidence, quantity)
        if property_has_point_qualifier(prop)
        and prop.value is not None
        and _screening_value(prop, quantity) is not None
    ]
    groups: dict[tuple, list[tuple[StateRecord, Property]]] = {}
    for record, prop in declarations:
        ref = prop.formation_reference
        # Zero-K internal differences do not depend on an arbitrary standard p.
        key = (
            ref.temperature_K if ref else None,
            ref.basis if ref else None,
            prop.definition,
            molecular_reference_id(record, state_id, prop.related_state),
            ref.standard_pressure_Pa if ref is not None and quantity == "gas_basicity_eV" else None,
        )
        groups.setdefault(key, []).append((record, prop))
    policy = _state_quantity_policy(evidence, quantity) if apply_selection else None
    selected = []
    for group in groups.values():
        offered = _requested_state_records(evidence, quantity, policy, group) if policy else group
        if apply_selection and offered and energy_declarations_agree([prop for _, prop in offered]):
            offered = [
                min(
                    offered,
                    key=lambda pair: (
                        TIER_RANK.get(pair[1].tier, 5),
                        pair[0].id,
                        calculation_record_reference(pair[0]),
                    ),
                )
            ]
        selected.extend(offered)
    return [
        EnergyInput(
            selectable_state_record_id(record),
            calculation_record_reference(record),
            state_id,
            quantity,
            cast(float, _screening_value(prop, quantity)),
            cast(float, prop.value),
            prop.unit,
            prop.definition,
            prop.formation_reference,
            molecular_reference_id(record, state_id, prop.related_state),
            prop.method,
            prop.provenance.provider,
            prop.provenance.collection,
        )
        for record, prop in selected
    ]


def _screening_value(prop: Property, quantity: str) -> float | None:
    if prop.value is None:
        return None
    if quantity == "mass_amu":
        return prop.value if prop.unit in {"u", "amu", "Da"} and prop.value > 0 else None
    return energy_eV(prop.value, prop.unit)


def _screening_relations(
    catalog: EvidenceCatalog, states: Mapping[str, StateCandidate]
) -> EnergyRelations:
    relations = []
    rejected = []
    representatives = {
        physical_state_id(state.id): state
        for state in states.values()
        if (state.structure or "").startswith("smiles:")
    }
    for record in catalog.reaction_records:
        prop = qualified_channel_energy(record, "delta_e_eV")
        if not _usable_state_relation(record, prop):
            continue
        prop = cast(Property, prop)
        original = {state.id: state for state in record.states}
        bound = bound_molecular_participants(record, representatives)
        views = (original, original | bound) if bound else (original,)
        value = cast(float, energy_eV(cast(float, prop.value), prop.unit))
        source = EnergyInput(
            record.id,
            calculation_record_reference(record),
            record.id,
            "delta_e_eV",
            value,
            cast(float, prop.value),
            prop.unit,
            prop.definition,
            prop.formation_reference,
            method=prop.method,
            provider=prop.provenance.provider,
            collection=prop.provenance.collection,
        )
        for view in views:
            if (vector := _screening_relation_vector(record, view)) is None:
                continue
            if issue := endpoint_order_issue(vector, value):
                rejected.append(
                    (
                        signature(vector),
                        Requirement("source_review", record.id, "delta_e_eV", issue),
                    )
                )
            else:
                relations.append(EnergyRelation(signature(vector), source))
    return EnergyRelations(
        sorted(
            relations, key=lambda relation: (relation.energy.record_id, relation.energy.record_ref)
        ),
        rejected=rejected,
    )


def _screening_relation_vector(
    record: ReactionRecord, states: dict[str, StateCandidate]
) -> dict[StateKey, float] | None:
    left, right = record.equation_key[2:]
    explicit_electrons = any(state_id == ELECTRON for state_id, _ in (*left, *right))
    if explicit_electrons:
        states = states | {ELECTRON: electron_state()}
    balance = conservation(
        tuple(Term(*term) for term in left),
        tuple(Term(*term) for term in right),
        states,
    )
    # A pure state-energy relation can omit zero-reference free electrons.
    # A declared event, or an explicit electron equation, must balance them.
    require_charge = explicit_electrons or record.channel_scope != "energy_relation"
    if (
        not balance.elements_conserved
        or balance.isotope_conflicts
        or balance.isotope_unresolved
        or (require_charge and not balance.charge_conserved)
    ):
        return None
    coefficients: dict[StateKey, list[float]] = {}
    for side, sign in ((left, -1.0), (right, 1.0)):
        for state_id, n in side:
            if state_id != ELECTRON:
                key = physical_state_key(states[state_id])
                coefficients.setdefault(key, []).append(sign * n)
    return {key: v for key, xs in coefficients.items() if (v := fsum(xs))}


def _usable_state_relation(record: ReactionRecord, prop: Property | None) -> bool:
    if prop is None or prop.value is None or prop.definition != "products_minus_reactants":
        return False
    if prop.formation_reference is not None and prop.formation_reference.temperature_K != 0:
        return False
    state_ids = {state.id for state in record.states} | {ELECTRON}
    if any(key not in state_ids for side in record.equation_key[2:] for key, _ in side):
        return False
    return (
        record.equation_key[1] is None
        and energy_eV(prop.value, prop.unit) is not None
        and all(
            state.id == ELECTRON
            or (
                state.phase == "gas"
                and state.state.resolution == "resolved"
                and state.state.kind != "composition"
            )
            for state in record.states
        )
    )
