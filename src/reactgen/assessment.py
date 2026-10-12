"""Explicit propositions about candidate equations, evidence, and energy.

Numerical-data use is a separate result: unusable data never deny a reaction.
An energy value alone is not a positive feasibility judgement.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isclose, isfinite

from reactgen.balance import conservation
from reactgen.case import Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import (
    ELECTRON,
    Assessment,
    CandidateSet,
    ReactionCandidate,
    Requirement,
    StateCandidate,
)
from reactgen.numeric import DataUse, data_use
from reactgen.records import (
    TIER_RANK,
    Property,
    ReactionRecord,
    StateRecord,
    Thermo,
    channel_energy_status,
    energy_declarations_agree,
    energy_properties_equivalent,
    property_energy_bounds,
    qualified_channel_energy,
    reaction_energy_definition_compatible,
    review_scope_covers,
    scientific_reaction_content,
)
from reactgen.selection import DataSelection
from reactgen.thermo import (
    equilibrium_constant,
    formation_delta,
    formation_reference,
    gibbs_energy_eV,
    net_electron_coefficient,
    reference_pressure,
    valid_thermo,
)
from reactgen.units import energy_eV

VERDICT_PASS = "pass"  # noqa: S105 - scientific verdict, not a credential
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_NA = "not_applicable"


@dataclass
class Evaluation:
    state_assessments: dict[str, dict[str, Assessment]]
    reaction_assessments: dict[str, dict[str, Assessment]]
    state_evidence: dict[str, StateEvidence]
    reaction_evidence: dict[str, ReactionEvidence]
    thermochemistry: dict[str, dict[str, float]] = field(default_factory=dict)
    data_use: dict[str, DataUse] = field(default_factory=dict)


def evaluate(
    candidates: CandidateSet,
    catalog: EvidenceCatalog,
    conditions: Conditions,
    selection: DataSelection | None = None,
) -> Evaluation:
    state_evidence = {
        state_id: catalog.state(state) for state_id, state in candidates.states.items()
    }
    state_assessments = {
        state_id: {
            "consistency": assess_state_consistency(state),
            "state": assess_state(
                state,
                state_evidence[state_id],
                candidates,
                state_evidence,
            ),
            "thermochemistry": assess_state_thermochemistry(state, state_evidence[state_id]),
        }
        for state_id, state in candidates.states.items()
    }

    reaction_evidence = {
        reaction_id: catalog.reaction(reaction)
        for reaction_id, reaction in candidates.reactions.items()
    }
    reaction_assessments = {}
    thermochemistry = {}
    numerical_use = {}
    for reaction_id, reaction in candidates.reactions.items():
        evidence = reaction_evidence[reaction_id]
        thermo, values = assess_thermochemistry(
            reaction,
            candidates,
            state_evidence,
            evidence,
            conditions,
        )
        kinetics, use = assess_kinetics(reaction, evidence, conditions, selection)
        if values:
            thermochemistry[reaction_id] = values
        numerical_use[reaction_id] = use
        reaction_assessments[reaction_id] = {
            "consistency": assess_consistency(reaction, candidates),
            "state": assess_reaction_states(reaction, state_assessments),
            "thermochemistry": thermo,
            "reaction_evidence": assess_reaction_evidence(
                reaction,
                evidence,
                catalog.materials,
            ),
            "kinetics": kinetics,
        }
    return Evaluation(
        state_assessments,
        reaction_assessments,
        state_evidence,
        reaction_evidence,
        thermochemistry,
        numerical_use,
    )


def assess_state_consistency(state: StateCandidate) -> Assessment:
    """Check the candidate representation; this does not identify a physical state."""
    return replace(
        _state_consistency(state),
        proposition="state_representation_consistency",
        scope=(
            "Composition and integer charge of this candidate; physical identity "
            "and existence are undetermined."
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
    return Assessment(
        VERDICT_PASS,
        ("parsed formula", "integer charge"),
        "candidate representation is well formed",
    )


def assess_state(
    state: StateCandidate,
    evidence: StateEvidence,
    candidates: CandidateSet,
    all_evidence: dict[str, StateEvidence] | None = None,
) -> Assessment:
    result = _assess_state_support(state, evidence, candidates, all_evidence)
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
    candidates: CandidateSet,
    all_evidence: dict[str, StateEvidence] | None,
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
            and state.charge == -1
            and state.state.kind == "ground"
            and all_evidence is not None
            and all(
                not review_scope_covers(record.review_scope, "state_existence")
                or (record.existence in {"unknown", "transient"} and record.status != "conflicting")
                for record in evidence.records
            )
        ):
            # Unknown or short-lived declarations do not decide electron
            # binding. Retain its independent evidence, without overriding an
            # explicit bound, unbound, hypothetical, or conflicting assertion.
            binding = _assess_anion_from_affinity(state, candidates, all_evidence)
            if binding.verdict != VERDICT_UNKNOWN:
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
    if state.charge == -1 and state.state.kind == "ground" and all_evidence is not None:
        return _assess_anion_from_affinity(state, candidates, all_evidence)
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
    if _state_existence_conflicts(evidence.records):
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
    record = next(
        (
            record
            for record in evidence.records
            if record.reviewed
            and record.existence_source is not None
            and record.existence in {"confirmed", "unbound"}
        ),
        evidence.preferred,
    )
    if record is None:
        return Assessment(
            VERDICT_UNKNOWN,
            (),
            "no state evidence",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "state_existence",
                    "obtain an existence assertion for this exact state",
                ),
            ),
        )
    if not record.reviewed:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "no reviewed existence assertion qualifies this state identity",
            requirements=(
                Requirement(
                    "source_review",
                    state.id,
                    "state_existence",
                    (
                        "review the existence assertion for this exact identity independently "
                        "of its numerical properties"
                    ),
                ),
            ),
        )
    existence = record.existence.lower()
    if record.existence_source is None:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "existence assertion has no stated supporting source",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "existence_source",
                    "identify the evidence supporting the existence assertion",
                ),
            ),
        )
    if existence == "unbound":
        return Assessment(
            VERDICT_FAIL,
            evidence.sources,
            "the source explicitly identifies this state as unbound",
        )
    if existence == "transient":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "short lifetime is declared; this alone does not establish or exclude a bound state",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "state_existence",
                    (
                        "obtain existence or binding evidence; lifetime alone cannot establish "
                        "or exclude a bound state"
                    ),
                ),
            ),
        )
    if existence in {"unknown", "hypothetical"}:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "the state record does not establish a bound state",
            requirements=(
                Requirement(
                    "source_information",
                    state.id,
                    "state_existence",
                    (
                        "obtain existence evidence supporting or excluding this hypothetical or"
                        " unresolved state"
                    ),
                ),
            ),
        )
    return Assessment(
        VERDICT_PASS,
        evidence.sources,
        "reviewed existence evidence supports this identity; population is undetermined",
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
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> Assessment:
    result = _affinity_binding_support(state, candidates, evidence)
    parent = _corresponding_ground_state(state, 0, candidates)
    requirements = result.requirements
    if parent is None:
        requirements = (
            Requirement(
                "identity",
                state.id,
                "neutral_parent",
                (
                    "identify a unique corresponding neutral ground state with the same "
                    "phase and structure"
                ),
            ),
        )
    elif result.verdict == VERDICT_UNKNOWN and not requirements:
        requirements = _energy_requirements(
            parent.id, evidence.get(parent.id), "electron_affinity_eV"
        )
    return replace(
        result,
        proposition="ground_anion_electron_binding",
        scope=(
            "Electron-detachment binding of the corresponding ground anion; "
            "lifetime, population, stabilization and occurrence are undetermined."
        ),
        requirements=requirements,
    )


def _affinity_binding_support(
    state: StateCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> Assessment:
    neutral = _corresponding_ground_state(state, 0, candidates)
    if neutral is None:
        return Assessment(VERDICT_UNKNOWN, (), "a unique corresponding neutral parent is missing")
    matched = evidence.get(neutral.id)
    if matched is None:
        return Assessment(VERDICT_UNKNOWN, (), "no state record or electron affinity")
    return _electron_binding_support(matched)


def _electron_binding_support(evidence: StateEvidence) -> Assessment:
    """Judge electron detachment binding, not lifetime or stability to other reactions.

    A positive EA range supports binding; a negative range excludes it. Only
    the explicit ``unbound`` qualifier declares electron nonbinding. IUPAC's
    ``unstable`` and ``transient`` concern thermodynamic comparison and lifetime,
    respectively, and do not supply that declaration. A contradictory or
    unresolved numerical declaration never becomes a definite exclusion.
    """
    name = "electron_affinity_eV"
    properties = _property_choices(evidence, name) if evidence.match == "exact" else []
    bounds, sources = _energy_property_bounds(evidence, name)
    if not properties:
        return Assessment(VERDICT_UNKNOWN, sources, "no reviewed electron affinity declaration")
    if _property_declarations_conflict(name, properties):
        return Assessment(
            VERDICT_UNKNOWN, sources, "reviewed electron affinity declarations conflict"
        )
    if any(_explicit_electron_nonbinding(prop) for prop in properties):
        if any(prop.value is not None for prop in properties) and (
            bounds is None or bounds[1] >= 0.0
        ):
            return Assessment(
                VERDICT_UNKNOWN,
                sources,
                "unbound declaration and electron affinity range do not establish "
                "a consistent electron nonbinding conclusion",
            )
        return Assessment(
            VERDICT_FAIL, sources, "reviewed evidence explicitly declares electron nonbinding"
        )
    if bounds is not None and bounds[1] < 0.0:
        return Assessment(
            VERDICT_FAIL, sources, "negative electron affinity range excludes electron binding"
        )
    if bounds is not None and bounds[0] > 0.0:
        return Assessment(
            VERDICT_PASS, sources, "positive electron affinity range supports electron binding"
        )
    return Assessment(VERDICT_UNKNOWN, sources, "electron affinity evidence is inconclusive")


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
    return (
        record.thermo is not None
        and record.thermo.reviewed_for("thermochemical_model")
        and valid_thermo(record.thermo)
    ) or (
        enthalpy is not None
        and enthalpy.reviewed_for("enthalpy_formation_eV")
        and _eV_value(record, "enthalpy_formation_eV") is not None
    )


def _thermochemistry_sources(record: StateRecord) -> tuple[str, ...]:
    sources = set()
    if (prop := record.properties.get("enthalpy_formation_eV")) is not None and _eV_value(
        record, "enthalpy_formation_eV"
    ) is not None:
        sources.add(prop.source or record.label)
    if (
        record.thermo is not None
        and record.thermo.reviewed_for("thermochemical_model")
        and valid_thermo(record.thermo)
    ):
        sources.add(record.thermo.source or record.label)
    return tuple(sorted(sources))


def assess_consistency(reaction: ReactionCandidate, candidates: CandidateSet) -> Assessment:
    """Check bookkeeping and the declared process pattern, not physical occurrence."""
    result = _equation_consistency(reaction, candidates)
    return replace(
        result,
        proposition="equation_consistency",
        scope=(
            "Element and charge accounting, participant family and defined process "
            "pattern; occurrence, activation and rates are undetermined."
        ),
    )


def _equation_consistency(reaction: ReactionCandidate, candidates: CandidateSet) -> Assessment:
    terms = (*reaction.reactants, *reaction.products)
    if any(not isfinite(term.n) or term.n <= 0 for term in terms):
        return Assessment(VERDICT_FAIL, ("stoichiometry",), "all coefficients must be positive")
    result = conservation(reaction.reactants, reaction.products, candidates.states)
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
            f"charge {result.left_charge:+g} -> {result.right_charge:+g}",
        )
    if not result.elements_conserved and reaction.surface is None:
        return Assessment(
            VERDICT_FAIL,
            ("element conservation",),
            f"elements {result.left_elements} -> {result.right_elements}",
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
        return Assessment(
            VERDICT_UNKNOWN,
            _balance_basis(reaction, result.charge_conserved),
            f"process {reaction.process!r} has no defined equation pattern; "
            "element/charge balance is accounted for, but process consistency is undetermined",
            requirements=(
                Requirement(
                    "external_models",
                    reaction.id,
                    f"process_pattern:{reaction.process}",
                    "define the participant and state pattern for this physical process",
                ),
            ),
        )
    return _consistent_result(reaction, result.charge_conserved)


def _family_problem(reaction: ReactionCandidate, candidates: CandidateSet) -> str | None:
    electron = any(term.species == ELECTRON for term in reaction.reactants)
    charged = any(
        candidates.states[term.species].charge
        for term in reaction.reactants
        if term.species != ELECTRON
    )
    if reaction.family == "electron" and not electron:
        return "an electron process requires an incident electron"
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

    @property
    def one_parent(self) -> bool:
        return self.left_n == 1 and len(self.left) == 1

    @property
    def same_parent(self) -> bool:
        return (
            self.one_parent
            and self.right_n == 1
            and len(self.right) == 1
            and self.left[0].composition == self.right[0].composition
            and self.left[0].phase == self.right[0].phase
            and self.left[0].structure == self.right[0].structure
        )

    @property
    def parent_sign(self) -> int:
        if not self.left or not self.left[0].charge:
            return 0
        return 1 if self.left[0].charge > 0 else -1

    @property
    def collision(self) -> bool:
        return self.left_e == self.right_e == 0 and self.left_n == 2


def _participants(reaction: ReactionCandidate, candidates: CandidateSet) -> _Participants:
    sides = []
    bags: list[dict[tuple, float]] = []
    charge_bags: list[dict[tuple, float]] = []
    for terms in (reaction.reactants, reaction.products):
        sides.append(
            [candidates.states[term.species] for term in terms if term.species != ELECTRON]
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
    process = reaction.process
    if process == "elastic":
        return participants.same_species
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


def _electron_pattern(process: str, p: _Participants) -> bool | None:
    charged = {
        "ionization": (2, 1, 0),
        "attachment": (0, -1, 0),
        "recombination": (0, -1, 1),
        "detachment": (2, 1, -1),
    }
    if process in charged:
        emitted, difference, sign = charged[process]
        parent_sign_matches = p.parent_sign == sign or (
            process == "ionization" and p.parent_sign == 1
        )
        return (
            p.left_e == 1
            and p.right_e == emitted
            and p.same_parent
            and parent_sign_matches
            and p.right[0].charge == p.left[0].charge + difference
        )
    dissociative = {
        "dissociation": (1, 0),
        "dissociative_ionization": (2, 0),
        "dissociative_attachment": (0, 0),
        "dissociative_recombination": (0, 1),
        "dissociative_detachment": (2, -1),
    }
    if process in dissociative:
        emitted, sign = dissociative[process]
        parent_sign_matches = p.parent_sign == sign or (
            process == "dissociative_ionization" and p.parent_sign == 1
        )
        return (
            p.left_e == 1
            and p.right_e == emitted
            and p.one_parent
            and p.right_n >= 2
            and parent_sign_matches
        )
    if process in {"excitation", "deexcitation"}:
        valid = (
            p.left_e == p.right_e == 1
            and p.same_parent
            and p.left[0].charge == p.right[0].charge
            and p.left[0].id != p.right[0].id
        )
        if not valid:
            return False
        return (
            p.right[0].state.kind != "ground"
            if process == "excitation"
            else p.left[0].state.kind != "ground"
        )
    return None


def _heavy_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    process = reaction.process
    if process in {"dissociation", "association"}:
        return _heavy_combination_pattern(reaction, p)
    if process in {"charge_exchange", "resonant_charge_exchange"}:
        valid = (
            reaction.family == "ion"
            and p.collision
            and p.right_n == 2
            and p.same_composition
            and any(state.charge for state in p.left)
        )
        if process == "resonant_charge_exchange":
            return (
                valid
                and p.same_species
                and any(state.charge == 0 for state in p.left)
                and all(state.composition == p.left[0].composition for state in p.left)
            )
        return valid and not p.same_species and p.charge_redistributed
    if process in {
        "ion_induced_excitation",
        "ion_induced_deexcitation",
        "quenching",
        "v_t_relaxation",
    }:
        return _state_transfer_pattern(reaction, p)
    if process == "penning_ionization":
        return (
            reaction.family == "neutral"
            and p.left_e == 0
            and p.right_e == 1
            and p.left_n == p.right_n == 2
            and p.same_composition
            and any(state.state.manifold == "electronic" for state in p.left)
            and any(state.charge > 0 for state in p.right)
        )
    if process == "mutual_neutralization":
        return (
            reaction.family == "ion"
            and p.collision
            and any(state.charge > 0 for state in p.left)
            and any(state.charge < 0 for state in p.left)
            and all(state.charge == 0 for state in p.right)
        )
    if process == "collisional_detachment":
        return (
            reaction.family == "ion"
            and p.left_e == 0
            and p.right_e == 1
            and p.left_n == 2
            and any(state.charge < 0 for state in p.left)
        )
    if process in {
        "collision_induced_dissociation",
        "projectile_dissociation",
        "dissociative_charge_transfer",
    }:
        return (
            reaction.family == "ion"
            and p.collision
            and p.right_n >= 3
            and any(state.charge for state in p.left)
        )
    if process in {"ligand_transfer", "reactive_scattering", "radical_abstraction"}:
        return p.collision and p.right_n >= 2 and not p.same_species
    return None


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


def _state_transfer_pattern(reaction: ReactionCandidate, p: _Participants) -> bool | None:
    process = reaction.process
    expected_family = "ion" if process.startswith("ion_") else "neutral"
    if not (
        reaction.family == expected_family
        and p.collision
        and p.right_n == 2
        and p.same_composition
        and not p.charge_redistributed
        and not p.same_species
    ):
        return False
    source, target = (p.right, p.left) if process == "ion_induced_excitation" else (p.left, p.right)
    transfers = [
        (state, other)
        for state in source
        if state.state.kind != "ground"
        and (process != "v_t_relaxation" or state.state.kind == "vibrational")
        for other in target
        if (
            other.composition == state.composition
            and other.charge == state.charge
            and other.phase == state.phase
            and other.structure == state.structure
            and other.key != state.key
        )
    ]
    if not transfers:
        return False
    if any(other.state.kind == "ground" for _, other in transfers):
        return True
    # The current template recognizes ground/end-state transfers. A different
    # resolved level or lumped term may be a legitimate lower state, but its
    # energy ordering is not established by this equation-pattern check.
    return None


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
    failed = [item for item in verdicts if item.verdict == VERDICT_FAIL]
    if failed:
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
    if unknown:
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
    source_values, source_conflicts = _source_energy_values(reaction_evidence)
    result, values = _assess_energy_relation(
        reaction,
        candidates,
        state_evidence,
        reaction_evidence,
        conditions,
        source_values,
        source_conflicts,
    )
    proposition = {
        "elastic": "elastic_internal_energy_identity",
        "ionization": "ionization_threshold_lower_bound",
        "penning_ionization": "penning_energy_requirement",
        "attachment": "ground_anion_electron_binding",
        "charge_exchange": "charge_transfer_energy_defect_consistency",
        "resonant_charge_exchange": "charge_transfer_energy_defect_consistency",
    }.get(reaction.process, "reaction_energy_relation")
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
    species = _thermo_records(reaction, state_evidence)
    if _formation_quality(reaction, species) and formation_reference(reaction, species) is None:
        result = replace(
            result,
            message=result.message
            + "; formation delta-H is undetermined: compatible reference temperature, "
            "elemental basis, pressure and applicable electron convention/enthalpy are required",
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
    return replace(result, proposition=proposition, scope=scope, requirements=requirements), values


def _energy_requirements(
    state_id: str,
    evidence: StateEvidence | None,
    name: str,
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
    ]
    if not supplied:
        return (
            Requirement(
                "source_information",
                state_id,
                name,
                "obtain a sourced value with its physical definition and uncertainty information",
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
    choices = _property_choices(evidence, name)
    if _property_declarations_conflict(name, choices):
        return (
            Requirement(
                "source_review",
                state_id,
                name,
                "resolve conflicting declarations of this same energy quantity",
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
    }
    responsibilities = {
        "model": "external_models",
        "definition": "source_information",
        "qualifier": "source_review",
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
    return (
        Requirement(
            "external_models",
            reaction.id,
            f"energy_relation:{reaction.process}",
            (
                "implement an energy relation for this process; an enthalpy or Gibbs "
                "value alone does not decide channel occurrence"
            ),
        ),
    )


def _assess_energy_relation(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    state_evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
    conditions: Conditions,
    source_values: dict[str, float],
    source_conflicts: tuple[str, ...],
) -> tuple[Assessment, dict[str, float]]:
    """Check comparable energy relations; values alone do not prove occurrence."""
    species = _thermo_records(reaction, state_evidence)
    values = _calculated_energy_values(reaction, species, conditions)
    values.update(source_values)
    identity = _identity_energy(reaction, candidates, state_evidence)
    if identity is not None:
        values[identity[0]] = identity[1]
    if reaction.process == "penning_ionization":
        penning, available = _penning_energy_relation(
            reaction, candidates, state_evidence, conditions
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
    unimplemented = any(
        item.responsibility == "external_models"
        and item.quantity == f"energy_relation:{reaction.process}"
        for item in requirements
    )
    note = (
        f"no implemented energy relation for process {reaction.process!r}"
        if unimplemented
        else "energy relation is undetermined"
    )
    note += "; " + "; ".join(dict.fromkeys(item.reason for item in requirements if item.reason))
    if values:
        note += "; available calculated or declared values are retained independently"
    return Assessment(
        VERDICT_UNKNOWN, reaction_evidence.sources, note, requirements=requirements
    ), values


def _calculated_energy_values(
    reaction: ReactionCandidate,
    species: dict[str, StateRecord],
    conditions: Conditions,
) -> dict[str, float]:
    delta_h = formation_delta(reaction, species)
    values = _available_value("delta_h_eV", delta_h, _formation_quality(reaction, species))
    if "delta_h_eV" in values:
        reference = formation_reference(reaction, species)
        if reference is not None and reference.temperature_K is not None:
            values["delta_h_reference_temperature_K"] = reference.temperature_K
            if reference.standard_pressure_Pa is not None:
                values["delta_h_standard_pressure_Pa"] = reference.standard_pressure_Pa
    delta_g, gibbs_values = _gibbs_values(reaction, species, conditions)
    if delta_g is None or not _gibbs_quality(reaction, species):
        return values
    values.update(gibbs_values)
    if conditions.gas_temperature_K is None or reaction.surface is not None:
        return values
    constant = equilibrium_constant(reaction, species, conditions.gas_temperature_K)
    pressure = reference_pressure(reaction, species)
    if constant is not None and pressure is not None:
        values["equilibrium_constant_number_density"] = constant
        values["equilibrium_constant_density_power"] = sum(
            term.n for term in reaction.products
        ) - sum(term.n for term in reaction.reactants)
        values["standard_pressure_Pa"] = pressure
    return values


def _source_energy_values(
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
            values[name] = min(choices)
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
            abs(values.get(name, 0.0)) > 1e-9
            for name in ("delta_h_eV", "threshold_eV", "source_delta_e_eV")
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
    reactants = [candidates.states[term.species] for term in reaction.reactants]
    ion = next((state for state in reactants if state.charge), None)
    target = next((state for state in reactants if not state.charge), None)
    if ion is None or target is None:
        return None, (), False
    donor = _corresponding_ground_state(ion, 0, candidates)
    if donor is None:
        return None, (), False
    if donor.key == target.key:
        return (0.0, 0.0), ("identical physical states",), True
    name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
    first, first_sources = _energy_property_bounds(evidence[donor.id], name)
    second, second_sources = _energy_property_bounds(evidence[target.id], name)
    sources = tuple(sorted(set(first_sources + second_sources)))
    uncertainty_known = all(
        prop.uncertainty is not None
        for state in (donor, target)
        for prop in _property_choices(evidence[state.id], name)
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
    choices = _property_choices(evidence, name) if evidence.match == "exact" else []
    properties = [
        (record, prop)
        for record in evidence.records
        if evidence.match == "exact"
        and record.status not in {"rejected", "conflicting"}
        and (prop := record.properties.get(name)) is not None
        and prop.reviewed_for(name)
        and prop in choices
    ]
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


def _gibbs_values(
    reaction: ReactionCandidate,
    species: dict[str, StateRecord],
    conditions: Conditions,
) -> tuple[float | None, dict[str, float]]:
    temperature = conditions.gas_temperature_K
    if temperature is None:
        return (None, {})
    delta_g = gibbs_energy_eV(reaction, species, temperature)
    return (
        (None, {})
        if delta_g is None
        else (delta_g, {"delta_g_eV": delta_g, "temperature_K": temperature})
    )


def _available_value(name: str, value: float | None, ready: bool) -> dict[str, float]:
    return {name: value} if ready and value is not None else {}


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
        return Assessment(VERDICT_FAIL, (), "attested origin has no recoverable source")
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
) -> tuple[Assessment, DataUse]:
    use = data_use(reaction, evidence, conditions, selection)
    if use.status == "coefficient":
        verdict = VERDICT_PASS
    elif use.datasets and all(item.status in {"invalid", "out_of_range"} for item in use.datasets):
        verdict = VERDICT_FAIL
    else:
        verdict = VERDICT_UNKNOWN
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
            "A usable rate coefficient under supplied conditions; probability or "
            "curve availability is reported separately in data_use and does not "
            "establish channel occurrence."
        ),
    ), use


def _thermo_records(
    reaction: ReactionCandidate,
    evidence: dict[str, StateEvidence],
) -> dict[str, StateRecord]:
    """Select properties only for participants in this energy balance."""
    electron_term_required = net_electron_coefficient(reaction) != 0
    return {
        state_id: record
        for state_id in sorted({term.species for term in (*reaction.reactants, *reaction.products)})
        if (
            record := _preferred_state(
                state_id, evidence, electron_term_required=electron_term_required
            )
        )
        is not None
    }


def _formation_quality(
    reaction: ReactionCandidate,
    species: dict[str, StateRecord],
) -> bool:
    return all(
        term.species == ELECTRON
        or (
            term.species in species
            and (prop := species[term.species].properties.get("enthalpy_formation_eV")) is not None
            and prop.reviewed_for("enthalpy_formation_eV")
            and _eV_value(species[term.species], "enthalpy_formation_eV") is not None
        )
        for term in (*reaction.reactants, *reaction.products)
    )


def _gibbs_quality(
    reaction: ReactionCandidate,
    species: dict[str, StateRecord],
) -> bool:
    for term in (*reaction.reactants, *reaction.products):
        if term.species == ELECTRON or term.species not in species:
            return False
        thermo = species[term.species].thermo
        if thermo is None or not thermo.reviewed_for("thermochemical_model"):
            return False
    return True


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
    The electron process pattern verifies whole-species stoichiometry and
    charge increment as well as phase and structure preservation.
    """
    if reaction.process != "ionization" or _process_pattern(reaction, candidates) is not True:
        return None
    parent = next(
        candidates.states[term.species] for term in reaction.reactants if term.species != ELECTRON
    )
    return parent if parent.phase == "gas" and parent.state.kind == "ground" else None


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
    if _process_pattern(reaction, candidates) is not True:
        return None
    reactants = [candidates.states[term.species] for term in reaction.reactants]
    participants = [
        candidates.states[term.species]
        for term in (*reaction.reactants, *reaction.products)
        if term.species != ELECTRON
    ]
    if any(state.state.kind != "ground" for state in participants):
        return None
    ion = next((state for state in reactants if state.charge), None)
    target = next((state for state in reactants if state.charge == 0), None)
    if ion is None or target is None:
        return None
    if abs(ion.charge) != 1:
        return None
    donor_state = _corresponding_ground_state(ion, 0, candidates)
    acceptor_state = _corresponding_ground_state(target, 0, candidates)
    charged_product = _corresponding_ground_state(target, ion.charge, candidates)
    if donor_state is None or acceptor_state is None or charged_product is None:
        return None
    expected_products = tuple(sorted(((donor_state.id, 1.0), (charged_product.id, 1.0))))
    if (
        any(term.n != 1 for term in reaction.reactants)
        or reaction.equation_key[3] != expected_products
    ):
        return None
    if donor_state.key == acceptor_state.key:
        return ("charge_transfer_energy_defect_eV", 0.0, None)
    donor = _preferred_state(donor_state.id, evidence)
    acceptor = _preferred_state(acceptor_state.id, evidence)
    if donor is None or acceptor is None:
        return None
    property_name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
    return _charge_transfer_declared_defect(reaction, donor, acceptor, property_name)


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
    # A gas temperature is not a maximum relative collision energy. It cannot
    # turn an internal-energy deficit into an unconditional hard prohibition.
    collision = conditions.value_of("collision_energy")
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
        ), values
    relationship = f"Penning declared available-energy range [{lower:.15g}, {upper:.15g}] eV"
    has_uncertainty = all(
        prop.uncertainty is not None
        for state_id, name in (
            (excited_id, "excitation_energy_eV"),
            (target_id, "ionization_energy_eV"),
        )
        for prop in _property_choices(evidence[state_id], name)
    )
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
        ), values
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
        ), values
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
    ), values


def _penning_ground_products(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
) -> tuple[str, str] | None:
    heavy = [term for term in reaction.reactants if term.species != ELECTRON]
    products = [term for term in reaction.products if term.species != ELECTRON]
    if (
        len(heavy) != 2
        or len(products) != 2
        or any(term.n != 1 for term in (*heavy, *products))
        or any(term.species == ELECTRON for term in reaction.reactants)
        or sum(term.n for term in reaction.products if term.species == ELECTRON) != 1
        or reaction.surface is not None
    ):
        return None
    donors = [
        candidates.states[term.species]
        for term in heavy
        if candidates.states[term.species].state.manifold == "electronic"
    ]
    targets = [
        candidates.states[term.species]
        for term in heavy
        if candidates.states[term.species].state.kind == "ground"
    ]
    if len(donors) != 1 or len(targets) != 1:
        return None
    donor, target = donors[0], targets[0]
    if (
        donor.charge != 0
        or target.charge != 0
        or donor.phase != "gas"
        or target.phase != "gas"
        or donor.state.resolution == "lumped"
    ):
        return None
    for parent, charge in ((donor, 0), (target, 1)):
        if not any(
            (product := candidates.states[term.species]).composition == parent.composition
            and product.phase == parent.phase
            and product.structure == parent.structure
            and product.charge == charge
            and product.state.kind == "ground"
            for term in products
        ):
            return None
    return donor.id, target.id


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
) -> StateRecord | None:
    if state_id is None:
        return None
    matched = evidence.get(state_id)
    if matched is None or matched.match != "exact" or matched.preferred is None:
        return None
    properties: dict[str, Property] = {}
    names = {name for record in matched.records for name in record.properties}
    for name in names:
        compared = _property_choices(matched, name, electron_term_required=electron_term_required)
        if not compared or _property_declarations_conflict(
            name,
            compared,
            charge=matched.preferred.candidate.charge,
            electron_term_required=electron_term_required,
        ):
            continue
        properties[name] = min(
            compared, key=lambda prop: (TIER_RANK.get(prop.tier, 5), prop.source or "", repr(prop))
        )
    thermos = _thermo_choices(matched)
    thermo = (
        min(thermos, key=lambda item: (TIER_RANK.get(item.tier, 5), item.source or ""))
        if thermos and len({_thermo_physical_key(item) for item in thermos}) == 1
        else None
    )
    # This is an aggregate, not one raw declaration. Its selected energy
    # Property must not inherit a different source's legacy scalar.
    return replace(matched.preferred, properties=properties, thermo=thermo, energy_eV=None)


def _property_choices(
    evidence: StateEvidence, name: str, *, electron_term_required: bool = False
) -> list[Property]:
    """Review this quantity, preserving unqualified declarations in raw evidence.

    Unqualified values cannot invalidate another quantity's qualified inputs.
    A rejected declaration contributes no usable numerical assertion.
    """
    choices = [
        prop
        for record in evidence.records
        if record.status not in {"rejected", "conflicting"}
        and (prop := record.properties.get(name)) is not None
        and prop.reviewed_for(name)
        and _state_energy_incompatibility(prop, name, record.candidate) is None
    ]
    if name == "enthalpy_formation_eV":
        charge = evidence.records[0].candidate.charge if evidence.records else 0
        referenced = [
            prop
            for prop in choices
            if prop.formation_reference is not None
            and prop.formation_reference.complete_for_charge(charge)
        ]
        choices = referenced or choices
        # A missing auxiliary electron term is not a reason to discard a
        # contradictory, fully referenced Hf value. Resolve Hf comparability
        # before selecting whole properties which supply the consumed term.
        if electron_term_required and not _property_declarations_conflict(
            name, choices, charge=charge
        ):
            completed = [
                prop
                for prop in choices
                if prop.formation_reference is not None
                and prop.formation_reference.complete_for_charge(
                    charge, electron_term_required=True
                )
            ]
            choices = completed or choices
    informative = [prop for prop in choices if prop.value is not None or prop.qualifier is not None]
    return informative or choices


def _state_energy_incompatibility(prop: Property, name: str, state: StateCandidate) -> str | None:
    """Identify why this declaration cannot supply the consumed energy quantity.

    NIST distinguishes vertical and adiabatic IE/EA. Only the applicable
    ground-state quantity decides binding or the ground ionization bound.
    Free numerical qualifiers are not numerical bounds: an upper limit may
    include negative EA or an IE below a proposed threshold. Known EA words
    retain their explicit electron-binding or lifetime meanings.
    https://webbook.nist.gov/chemistry/ion/
    """
    if name not in {"ionization_energy_eV", "electron_affinity_eV", "excitation_energy_eV"}:
        return None
    if name != "excitation_energy_eV" and (state.phase != "gas" or state.state.kind != "ground"):
        return "model"
    qualifier = (prop.qualifier or "").strip().lower()
    supported = {"", "unbound", "unstable", "transient"} if name == "electron_affinity_eV" else {""}
    if qualifier not in supported:
        return "qualifier"
    if name == "excitation_energy_eV":
        return None
    if (
        name == "electron_affinity_eV"
        and prop.value is None
        and _explicit_electron_nonbinding(prop)
    ):
        return None
    atom = sum(state.composition.values()) == 1
    if prop.definition == "atomic":
        return None if atom else "definition"
    if prop.definition == "adiabatic" or (prop.definition is None and atom):
        return None
    return "definition"


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
            (
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
            if (ref := prop.formation_reference) is not None
            else None
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


def _thermo_choices(evidence: StateEvidence) -> list[Thermo]:
    return [
        record.thermo
        for record in evidence.records
        if record.status not in {"rejected", "conflicting"}
        and record.thermo is not None
        and record.thermo.reviewed_for("thermochemical_model")
    ]


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
        charge = next(
            (
                candidates.states[state_id].charge
                for state_id in heavy_parents
                if candidates.states[state_id].charge
            ),
            0,
        )
        for state_id in participants - {ELECTRON}:
            if candidates.states[state_id].charge == 0:
                requested[state_id].add(
                    "ionization_energy_eV" if charge > 0 else "electron_affinity_eV"
                )
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
    electron_term_required = net_electron_coefficient(reaction) != 0
    for state_id, names in _relation_energy_quantities(reaction, candidates).items():
        matched = evidence.get(state_id)
        if matched is None or matched.match != "exact":
            continue
        names.update(_thermochemical_conflicts(matched))
        if electron_term_required:
            names.add("enthalpy_formation_eV")
        for name in names:
            compared = _property_choices(
                matched, name, electron_term_required=electron_term_required
            )
            if name == "NASA7" or _property_declarations_conflict(
                name,
                compared,
                charge=candidates.states[state_id].charge,
                electron_term_required=electron_term_required,
            ):
                quantity = name
                if name == "enthalpy_formation_eV" and not _property_declarations_conflict(
                    name, compared, charge=candidates.states[state_id].charge
                ):
                    quantity = "formation_reference.electron_enthalpy_eV"
                conflicts.append(f"{state_id}:{quantity}")
    return tuple(sorted(conflicts))


def _corresponding_ground_state(
    parent: StateCandidate,
    charge: int,
    candidates: CandidateSet,
) -> StateCandidate | None:
    """Find one ground identity with the parent's composition, phase, and structure.

    The requested charge changes only that identity axis. Multiple ground
    representations remain unresolved; insertion order never selects a parent.
    """
    matches = [
        candidate
        for candidate in candidates.states.values()
        if candidate.composition == parent.composition
        and candidate.charge == charge
        and candidate.state.kind == "ground"
        and candidate.phase == parent.phase
        and candidate.structure == parent.structure
    ]
    return matches[0] if len(matches) == 1 else None
