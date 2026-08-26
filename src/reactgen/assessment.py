"""Five independent, four-valued judgements over candidates and evidence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import pairwise
from math import isfinite

from reactgen.balance import conservation
from reactgen.case import Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import ELECTRON, Assessment, CandidateSet, ReactionCandidate, StateCandidate
from reactgen.records import TIER_RANK, NumericDataset, ReactionRecord, StateRecord
from reactgen.thermo import formation_delta, gibbs_energy_eV

VERDICT_PASS = "pass"  # noqa: S105 - scientific verdict, not a credential
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_NA = "not_applicable"
TRUSTED_NUMERIC_TIERS = frozenset({"curated", "reviewed", "derived"})
THERMALLY_REVERSIBLE_PROCESSES = frozenset(
    {
        "charge_exchange",
        "resonant_charge_exchange",
        "ligand_transfer",
        "radical_abstraction",
        "reactive_scattering",
    }
)


@dataclass(frozen=True)
class ThermochemistryCapabilities:
    threshold_available: bool = False
    electron_energy_loss_ready: bool = False
    reaction_enthalpy_ready: bool = False
    equilibrium_constant_ready: bool = False
    reverse_rate_ready: bool = False


@dataclass(frozen=True)
class KineticsCapabilities:
    cross_section_ready: bool = False
    direct_rate_ready: bool = False
    usable_dataset_ids: tuple[str, ...] = ()
    usable_observables: tuple[str, ...] = ()
    required_transforms: tuple[str, ...] = ()
    estimated: bool = False


@dataclass
class Evaluation:
    state_assessments: dict[str, dict[str, Assessment]]
    reaction_assessments: dict[str, dict[str, Assessment]]
    state_evidence: dict[str, StateEvidence]
    reaction_evidence: dict[str, ReactionEvidence]
    thermochemistry: dict[str, dict[str, float]] = field(default_factory=dict)
    estimated_kinetics: set[str] = field(default_factory=set)
    thermo_capabilities: dict[str, ThermochemistryCapabilities] = field(default_factory=dict)
    kinetics_capabilities: dict[str, KineticsCapabilities] = field(default_factory=dict)


def evaluate(
    candidates: CandidateSet,
    catalog: EvidenceCatalog,
    conditions: Conditions,
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
    thermo_capabilities = {}
    kinetics_capabilities = {}
    estimated = set()
    for reaction_id, reaction in candidates.reactions.items():
        evidence = reaction_evidence[reaction_id]
        thermo, values, thermo_ready = assess_thermochemistry(
            reaction,
            candidates,
            state_evidence,
            evidence,
            conditions,
        )
        kinetics, kinetics_ready = assess_kinetics(reaction, evidence, conditions)
        thermo_ready = replace(
            thermo_ready,
            reverse_rate_ready=_reverse_rate_derivable(
                reaction,
                thermo_ready,
                kinetics_ready,
            ),
        )
        if values:
            thermochemistry[reaction_id] = values
        thermo_capabilities[reaction_id] = thermo_ready
        kinetics_capabilities[reaction_id] = kinetics_ready
        if kinetics_ready.estimated:
            estimated.add(reaction_id)
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
        estimated,
        thermo_capabilities,
        kinetics_capabilities,
    )


def assess_state_consistency(state: StateCandidate) -> Assessment:
    if state.id == ELECTRON:
        valid = not state.composition and state.charge == -1
        return Assessment(VERDICT_PASS if valid else VERDICT_FAIL, ("electron carrier",), "")
    if not state.composition or any(count <= 0 for count in state.composition.values()):
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
    if state.id == ELECTRON:
        return Assessment(VERDICT_PASS, ("physical carrier",), "electron is explicitly represented")
    if state.state.resolution == "lumped" and _resolved_alternative(state, candidates):
        return Assessment(
            VERDICT_UNKNOWN,
            ("candidate resolution",),
            "resolved alternatives exist; select one resolution before simulation",
        )
    if evidence.match == "ambiguous":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "several identity records match this state",
        )
    if evidence.match == "exact":
        return _assess_exact_state(state, evidence)
    if evidence.match == "compatible":
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "related state records exist but do not attest this candidate representation",
        )
    if "feed" in state.classes and state.state.kind == "ground":
        return Assessment(
            VERDICT_UNKNOWN,
            ("case input",),
            "input gas is a generation seed, not evidence that the state exists",
        )
    if state.charge == -1 and state.state.kind == "ground" and all_evidence is not None:
        return _assess_anion_from_affinity(state, candidates, all_evidence)
    return Assessment(VERDICT_UNKNOWN, (), "no state record matches this candidate")


def _assess_exact_state(state: StateCandidate, evidence: StateEvidence) -> Assessment:
    record = evidence.preferred
    if record is None:
        return Assessment(VERDICT_UNKNOWN, (), "no state evidence")
    if not record.reviewed:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            f"best state record quality is {record.tier}",
        )
    existence = record.existence.lower()
    if existence == "unbound":
        return Assessment(
            VERDICT_FAIL,
            evidence.sources,
            "the source explicitly identifies this state as unbound",
        )
    if existence == "transient" and state.state.kind == "ground":
        return Assessment(
            VERDICT_FAIL,
            evidence.sources,
            "a transient resonance is not a bound ground-state species",
        )
    if existence in {"unknown", "hypothetical"}:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "the state record does not establish a bound state",
        )
    if state.state.kind != "ground" and record.energy_eV is None:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "state identity is recorded but its energy is missing",
        )
    lifetime = record.lifetime_s or record.value("lifetime_s")
    if state.state.kind in {"metastable", "resonant"} and lifetime is None:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            "long-lived state is recorded but its lifetime is missing",
        )
    return Assessment(VERDICT_PASS, evidence.sources, "an exact reviewed state record exists")


def _assess_anion_from_affinity(
    state: StateCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> Assessment:
    neutral = next(
        (
            candidate
            for candidate in candidates.states.values()
            if candidate.composition == state.composition
            and candidate.charge == 0
            and candidate.state.kind == "ground"
        ),
        None,
    )
    matched = evidence.get(neutral.id) if neutral is not None else None
    record = matched.preferred if matched is not None and matched.match == "exact" else None
    if record is None:
        return Assessment(VERDICT_UNKNOWN, (), "no state record or electron affinity")
    affinity = record.properties.get("electron_affinity_eV")
    if affinity is None:
        return Assessment(VERDICT_UNKNOWN, (), "no state record or electron affinity")
    basis = (record.label,)
    qualifier = (affinity.qualifier or "").lower()
    excludes_bound_state = qualifier in {"unbound", "unstable", "transient"} or (
        affinity.value is not None and affinity.value < 0.0
    )
    trusted = affinity.tier in TRUSTED_NUMERIC_TIERS
    if excludes_bound_state and trusted:
        return Assessment(
            VERDICT_FAIL,
            basis,
            "electron affinity evidence excludes a bound parent anion",
        )
    if excludes_bound_state:
        return Assessment(
            VERDICT_UNKNOWN,
            basis,
            "unreviewed electron affinity suggests an unbound parent anion",
        )
    if affinity.value is not None and trusted:
        return Assessment(
            VERDICT_PASS,
            basis,
            "positive electron affinity supports a bound parent anion",
        )
    return Assessment(VERDICT_UNKNOWN, basis, "electron affinity evidence is inconclusive")


def assess_state_thermochemistry(
    state: StateCandidate,
    evidence: StateEvidence,
) -> Assessment:
    if state.id == ELECTRON:
        return Assessment(VERDICT_NA, ("zero reference convention",), "")
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
        )
    reviewed = [record for record in useful if _trusted_thermochemistry(record)]
    if not reviewed:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in useful),
            "thermochemical values are not reviewed",
        )
    preferred = min(reviewed, key=lambda item: item.label)
    return Assessment(
        VERDICT_PASS,
        (preferred.label,),
        "thermochemical representation is available",
    )


def _trusted_thermochemistry(record: StateRecord) -> bool:
    enthalpy = record.properties.get("enthalpy_formation_eV")
    return (record.thermo is not None and record.thermo.tier in TRUSTED_NUMERIC_TIERS) or (
        enthalpy is not None and enthalpy.tier in TRUSTED_NUMERIC_TIERS
    )


def assess_consistency(reaction: ReactionCandidate, candidates: CandidateSet) -> Assessment:
    terms = (*reaction.reactants, *reaction.products)
    if any(term.n <= 0 for term in terms):
        return Assessment(VERDICT_FAIL, ("stoichiometry",), "all coefficients must be positive")
    result = conservation(reaction.reactants, reaction.products, candidates.states)
    if result.missing:
        return Assessment(
            VERDICT_FAIL,
            ("state index",),
            f"unknown states: {', '.join(result.missing)}",
        )
    reactant_ids = {term.species for term in reaction.reactants}
    heavy_reactants = [
        candidates.states[term.species] for term in reaction.reactants if term.species != ELECTRON
    ]
    if reaction.family == "electron" and ELECTRON not in reactant_ids:
        return Assessment(
            VERDICT_FAIL,
            ("collision participants",),
            "an electron process requires an incident electron",
        )
    if reaction.family == "ion" and not any(state.charge for state in heavy_reactants):
        return Assessment(
            VERDICT_FAIL,
            ("collision participants",),
            "an ion process requires a charged heavy reactant",
        )
    if reaction.family == "neutral" and (
        ELECTRON in reactant_ids or any(state.charge for state in heavy_reactants)
    ):
        return Assessment(
            VERDICT_FAIL,
            ("collision participants",),
            "a neutral process has a charged reactant",
        )
    if reaction.process == "elastic" and reaction.equation_key[2] != reaction.equation_key[3]:
        return Assessment(
            VERDICT_FAIL,
            ("elastic channel",),
            "elastic scattering must preserve both participants",
        )
    if reaction.surface is None and not result.charge_conserved:
        return Assessment(
            VERDICT_FAIL,
            ("charge conservation",),
            f"charge {result.left_charge:+g} -> {result.right_charge:+g}",
        )
    if not result.elements_conserved:
        if reaction.surface is not None:
            return Assessment(
                VERDICT_UNKNOWN,
                (f"surface reservoir:{reaction.surface}",),
                "gas-phase element balance needs explicit surface stoichiometry",
            )
        return Assessment(
            VERDICT_FAIL,
            ("element conservation",),
            f"elements {result.left_elements} -> {result.right_elements}",
        )
    return Assessment(
        VERDICT_PASS,
        ("element conservation", "charge conservation"),
        "reaction is stoichiometrically and electrically consistent",
    )


def assess_reaction_states(
    reaction: ReactionCandidate,
    state_assessments: dict[str, dict[str, Assessment]],
) -> Assessment:
    verdicts = [
        state_assessments[term.species]["state"]
        for term in (*reaction.reactants, *reaction.products)
        if term.species != ELECTRON
    ]
    failed = [item for item in verdicts if item.verdict == VERDICT_FAIL]
    if failed:
        return Assessment(
            VERDICT_FAIL,
            tuple(item for value in failed for item in value.basis),
            "at least one non-electron reactant or product fails its State assessment",
        )
    unknown = [item for item in verdicts if item.verdict == VERDICT_UNKNOWN]
    if unknown:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(sorted({item for value in unknown for item in value.basis})),
            "at least one non-electron reactant or product has an unknown State assessment",
        )
    return Assessment(
        VERDICT_PASS,
        ("reactant and product State assessments",),
        "every non-electron reactant and product passes its State assessment",
    )


def assess_thermochemistry(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    state_evidence: dict[str, StateEvidence],
    reaction_evidence: ReactionEvidence,
    conditions: Conditions,
) -> tuple[Assessment, dict[str, float], ThermochemistryCapabilities]:
    species = _thermo_records(candidates, state_evidence)
    delta_h = formation_delta(reaction, species)
    enthalpy_ready = delta_h is not None and _formation_quality(reaction, species)
    values = _available_value("delta_h_eV", delta_h, enthalpy_ready)
    delta_g, gibbs_values = _gibbs_values(reaction, species, conditions)
    gibbs_ready = delta_g is not None and _gibbs_quality(reaction, species)
    if gibbs_ready:
        values.update(gibbs_values)

    source_records = tuple(
        record
        for record in _best_reaction_records(reaction_evidence.exact_records)
        if record.tier in {"curated", "reviewed", "derived"}
    )
    thresholds = {
        record.threshold_eV for record in source_records if record.threshold_eV is not None
    }
    energy_defects = {
        record.delta_e_eV for record in source_records if record.delta_e_eV is not None
    }
    if len(thresholds) == 1:
        values["threshold_eV"] = next(iter(thresholds))
    if len(energy_defects) == 1:
        values["source_delta_e_eV"] = next(iter(energy_defects))
    identity_energy = _identity_energy(reaction, candidates, state_evidence)
    if identity_energy is not None:
        name, value = identity_energy
        values[name] = value
    feasibility = _energy_feasibility(reaction, candidates, state_evidence)
    if feasibility is not None:
        feasible_name, feasible_value, failure, basis = feasibility
        if feasible_value is not None:
            values[feasible_name] = feasible_value

    feasibility_value = feasibility is not None and feasibility[1] is not None
    energy_known = bool(
        thresholds
        or energy_defects
        or identity_energy
        or feasibility_value
        or delta_h is not None
        or delta_g is not None
    )
    trusted_energy = bool(
        thresholds
        or energy_defects
        or identity_energy
        or feasibility_value
        or enthalpy_ready
        or gibbs_ready
    )
    capabilities = _thermochemistry_capabilities(
        reaction,
        enthalpy_ready,
        gibbs_ready,
        trusted_energy,
        bool(thresholds or identity_energy or feasibility_value),
    )
    if len(thresholds) > 1 or len(energy_defects) > 1:
        return (
            Assessment(
                VERDICT_UNKNOWN,
                reaction_evidence.sources,
                "thermochemical source values conflict",
            ),
            values,
            capabilities,
        )
    if feasibility is not None and failure:
        return (
            Assessment(VERDICT_FAIL, basis, failure),
            values,
            capabilities,
        )
    if values and trusted_energy:
        return (
            Assessment(
                VERDICT_PASS,
                tuple(
                    name
                    for name, present in (
                        ("formation thermochemistry", enthalpy_ready),
                        ("measured threshold", bool(thresholds)),
                        ("source energy defect", bool(energy_defects)),
                        ("ionization energy/electron affinity", identity_energy is not None),
                        ("process energy feasibility", feasibility_value),
                    )
                    if present
                ),
                "reaction energy or threshold is available",
            ),
            values,
            capabilities,
        )
    message = (
        "only unreviewed thermochemical values are available"
        if values and energy_known
        else "one or more reactant or product states lack compatible thermochemistry"
    )
    return (
        Assessment(
            VERDICT_UNKNOWN,
            (),
            message,
        ),
        {},
        capabilities,
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
    if reaction.surface is not None and reaction.surface not in materials:
        return Assessment(
            VERDICT_UNKNOWN,
            evidence.sources,
            f"surface material {reaction.surface} has no material record",
        )
    if any(record.reviewed for record in evidence.exact_records):
        return Assessment(
            VERDICT_PASS,
            tuple(record.label for record in evidence.exact_records if record.reviewed),
            "an exact state-resolved equation is listed",
        )
    if evidence.exact_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.exact_records),
            "matching equation records are not reviewed",
        )
    reviewed_datasets = tuple(
        dataset
        for dataset in evidence.overlay_datasets
        if dataset.reviewed and dataset.channel_scope == "product_resolved"
    )
    if reviewed_datasets:
        return Assessment(
            VERDICT_PASS,
            tuple(dataset.id for dataset in reviewed_datasets),
            "a reviewed dataset is bound to this canonical channel",
        )
    if evidence.overlay_datasets:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(dataset.id for dataset in evidence.overlay_datasets),
            "channel-bound datasets have not been reviewed",
        )
    if evidence.total_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.total_records),
            "only a related total-process record is available",
        )
    if evidence.related_records:
        return Assessment(
            VERDICT_UNKNOWN,
            tuple(record.label for record in evidence.related_records),
            "the equation is listed only for a different physical process",
        )
    if reaction.origin == "attested_only":
        return Assessment(VERDICT_FAIL, (), "attested origin has no recoverable source")
    return Assessment(VERDICT_UNKNOWN, (), "no source lists this exact equation")


def _thermochemistry_capabilities(
    reaction: ReactionCandidate,
    enthalpy_ready: bool,
    gibbs_ready: bool,
    energy_known: bool,
    threshold_ready: bool,
) -> ThermochemistryCapabilities:
    has_electron = any(
        term.species == ELECTRON for term in (*reaction.reactants, *reaction.products)
    )
    equilibrium_ready = gibbs_ready and not has_electron and reaction.surface is None
    return ThermochemistryCapabilities(
        threshold_available=threshold_ready,
        electron_energy_loss_ready=reaction.family == "electron" and energy_known,
        reaction_enthalpy_ready=enthalpy_ready,
        equilibrium_constant_ready=equilibrium_ready,
        reverse_rate_ready=False,
    )


def _reverse_rate_derivable(
    reaction: ReactionCandidate,
    thermochemistry: ThermochemistryCapabilities,
    kinetics: KineticsCapabilities,
) -> bool:
    """Conservative subset for which detailed balance needs no hidden convention."""

    if not thermochemistry.equilibrium_constant_ready or not kinetics.direct_rate_ready:
        return False
    if reaction.process not in THERMALLY_REVERSIBLE_PROCESSES:
        return False
    if reaction.third_body is not None or reaction.surface is not None:
        return False
    left_order = sum(term.n for term in reaction.reactants if term.species != ELECTRON)
    right_order = sum(term.n for term in reaction.products if term.species != ELECTRON)
    return abs(left_order - right_order) < 1e-12


def assess_kinetics(
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    conditions: Conditions,
) -> tuple[Assessment, KineticsCapabilities]:
    declared = list(evidence.datasets)
    usable = _best_datasets([dataset for dataset in declared if dataset.usable])
    estimated = bool(usable) and all(dataset.estimated for dataset in usable)
    empty = KineticsCapabilities(estimated=estimated)
    if not usable:
        return (
            Assessment(VERDICT_UNKNOWN, (), "no usable cross section or rate coefficient"),
            empty,
        )
    if _conflicting(usable):
        return (
            Assessment(
                VERDICT_UNKNOWN,
                tuple(dataset.id for dataset in usable),
                "usable numerical sources conflict",
            ),
            empty,
        )

    contracts = {dataset.id: _dataset_contract(dataset, reaction, evidence) for dataset in usable}
    compatible = [dataset for dataset in usable if contracts[dataset.id] == "pass"]
    if not compatible:
        verdict = (
            VERDICT_FAIL
            if all(value == "fail" for value in contracts.values())
            else VERDICT_UNKNOWN
        )
        return (
            Assessment(
                verdict,
                tuple(dataset.id for dataset in usable),
                "datasets lack a compatible unit, independent variable, or channel scope",
            ),
            empty,
        )

    applicability = {dataset.id: _applicability(dataset, conditions) for dataset in compatible}
    ready = [dataset for dataset in compatible if applicability[dataset.id] == "in_range"]
    transforms = _required_transforms(ready, reaction)
    capabilities = KineticsCapabilities(
        cross_section_ready=any(dataset.kind == "cross_section" for dataset in ready),
        direct_rate_ready=any(
            dataset.kind in {"rate_coefficient", "sticking_coefficient"} for dataset in ready
        ),
        usable_dataset_ids=tuple(dataset.id for dataset in ready),
        usable_observables=tuple(
            sorted({dataset.observable for dataset in ready if dataset.observable is not None})
        ),
        required_transforms=transforms,
        estimated=estimated,
    )
    if ready:
        return (
            Assessment(
                VERDICT_PASS,
                capabilities.usable_dataset_ids,
                "a compatible numerical dataset covers the case conditions",
            ),
            capabilities,
        )
    if all(value == "out_of_range" for value in applicability.values()):
        return (
            Assessment(
                VERDICT_FAIL,
                tuple(dataset.id for dataset in compatible),
                "available datasets are outside their declared range",
            ),
            capabilities,
        )
    return (
        Assessment(
            VERDICT_UNKNOWN,
            tuple(dataset.id for dataset in compatible),
            "numbers exist but their applicability is undeclared or undecidable",
        ),
        capabilities,
    )


def _resolved_alternative(state: StateCandidate, candidates: CandidateSet) -> bool:
    return any(
        other.id != state.id
        and other.composition == state.composition
        and other.charge == state.charge
        and other.state.manifold == state.state.manifold
        and other.state.resolution == "resolved"
        and other.state.kind != "ground"
        for other in candidates.states.values()
    )


def _thermo_records(
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> dict[str, StateRecord]:
    found = {}
    for state_id in candidates.states:
        matched = evidence[state_id]
        if matched.match == "exact" and matched.preferred is not None:
            found[state_id] = matched.preferred
    return found


def _formation_quality(
    reaction: ReactionCandidate,
    species: dict[str, StateRecord],
) -> bool:
    return all(
        term.species == ELECTRON
        or (
            term.species in species
            and (prop := species[term.species].properties.get("enthalpy_formation_eV")) is not None
            and prop.tier in TRUSTED_NUMERIC_TIERS
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
        if thermo is None or thermo.tier not in TRUSTED_NUMERIC_TIERS:
            return False
    return True


def _identity_energy(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float] | None:
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
    ]
    record = evidence[reactant_id].preferred
    if evidence[reactant_id].match != "exact" or record is None:
        return None
    if any(product.charge == reactant.charge + 1 for product in products):
        prop = record.properties.get("ionization_energy_eV")
        return (
            None
            if prop is None or prop.value is None or prop.tier not in TRUSTED_NUMERIC_TIERS
            else ("ionization_energy_eV", prop.value)
        )
    if any(product.charge == reactant.charge - 1 for product in products):
        prop = record.properties.get("electron_affinity_eV")
        return (
            None
            if prop is None or prop.value is None or prop.tier not in TRUSTED_NUMERIC_TIERS
            else ("electron_affinity_eV", prop.value)
        )
    return None


def _energy_feasibility(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, str | None, tuple[str, ...]] | None:
    """Decide only hard energy exclusions; endothermic plasma channels remain candidates."""

    if reaction.process == "attachment":
        return _attachment_feasibility(reaction, evidence)
    if reaction.process in {"charge_exchange", "resonant_charge_exchange"}:
        return _charge_transfer_feasibility(reaction, candidates, evidence)
    return (
        _penning_feasibility(reaction, candidates, evidence)
        if reaction.process == "penning_ionization"
        else None
    )


def _attachment_feasibility(
    reaction: ReactionCandidate,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, str | None, tuple[str, ...]] | None:
    parent = next(
        (term.species for term in reaction.reactants if term.species != ELECTRON),
        None,
    )
    record = _preferred_state(parent, evidence)
    if record is None:
        return None
    affinity = record.properties.get("electron_affinity_eV")
    if affinity is None or affinity.tier not in TRUSTED_NUMERIC_TIERS:
        return None
    qualifier = (affinity.qualifier or "").lower()
    unbound = qualifier in {"unbound", "unstable", "transient"}
    unbound = unbound or (affinity.value is not None and affinity.value < 0.0)
    failure = (
        "direct attachment cannot create the explicitly unbound parent anion" if unbound else None
    )
    return (
        "electron_affinity_eV",
        affinity.value,
        failure,
        (record.label,),
    )


def _charge_transfer_feasibility(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, str | None, tuple[str, ...]] | None:
    reactants = [candidates.states[term.species] for term in reaction.reactants]
    ion = next((state for state in reactants if state.charge), None)
    target = next((state for state in reactants if state.charge == 0), None)
    if ion is None or target is None:
        return None
    if ion.composition == target.composition:
        return ("charge_transfer_energy_defect_eV", 0.0, None, ("resonant identity",))
    donor = _ground_record(ion.composition, candidates, evidence)
    acceptor = _ground_record(target.composition, candidates, evidence)
    if donor is None or acceptor is None:
        return None
    property_name = "ionization_energy_eV" if ion.charge > 0 else "electron_affinity_eV"
    donor_energy = _eV_value(donor, property_name)
    acceptor_energy = _eV_value(acceptor, property_name)
    if donor_energy is None or acceptor_energy is None:
        return None
    defect = acceptor_energy - donor_energy if ion.charge > 0 else donor_energy - acceptor_energy
    return (
        "charge_transfer_energy_defect_eV",
        defect,
        None,
        (donor.label, acceptor.label),
    )


def _penning_feasibility(
    reaction: ReactionCandidate,
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> tuple[str, float | None, str | None, tuple[str, ...]] | None:
    heavy = [term.species for term in reaction.reactants if term.species != ELECTRON]
    excited_id = next(
        (state_id for state_id in heavy if candidates.states[state_id].state.kind != "ground"),
        None,
    )
    target_id = next(
        (
            state_id
            for state_id in heavy
            if state_id != excited_id
            and candidates.states[state_id].charge == 0
            and candidates.states[state_id].state.kind == "ground"
        ),
        None,
    )
    excited_record = _preferred_state(excited_id, evidence)
    if excited_record is None and excited_id is not None:
        # A generic reviewed manifold (for example Ar 4s) may bound the
        # feasibility of its metastable/resonant submanifolds.  It is not an
        # exact identity match and is therefore never adopted as that state's
        # thermochemical property, but it is valid for this hard exclusion.
        related = evidence.get(excited_id)
        if related is not None and related.match == "compatible":
            excited_record = related.preferred
    target_record = _preferred_state(target_id, evidence)
    if excited_record is None or target_record is None or excited_record.energy_eV is None:
        return None
    ionization = target_record.properties.get("ionization_energy_eV")
    if ionization is None or ionization.tier not in TRUSTED_NUMERIC_TIERS:
        return None
    if ionization.value is None or ionization.unit not in {None, "eV"}:
        return None
    available = excited_record.energy_eV - ionization.value
    failure = (
        "metastable energy is below the target ionization energy" if available < -1e-9 else None
    )
    return (
        "penning_available_energy_eV",
        available,
        failure,
        (excited_record.label, target_record.label),
    )


def _eV_value(record: StateRecord, name: str) -> float | None:
    value = record.properties.get(name)
    if (
        value is None
        or value.value is None
        or value.unit not in {None, "eV"}
        or value.tier not in TRUSTED_NUMERIC_TIERS
    ):
        return None
    return value.value


def _preferred_state(
    state_id: str | None,
    evidence: dict[str, StateEvidence],
) -> StateRecord | None:
    if state_id is None:
        return None
    matched = evidence.get(state_id)
    return (
        matched.preferred
        if matched is not None and matched.match == "exact" and matched.preferred is not None
        else None
    )


def _ground_record(
    composition: dict[str, int],
    candidates: CandidateSet,
    evidence: dict[str, StateEvidence],
) -> StateRecord | None:
    state = next(
        (
            candidate
            for candidate in candidates.states.values()
            if candidate.composition == composition
            and candidate.charge == 0
            and candidate.state.kind == "ground"
        ),
        None,
    )
    return _preferred_state(state.id if state else None, evidence)


def _dataset_contract(
    dataset: NumericDataset,
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
) -> str:
    if dataset.channel_scope != "product_resolved":
        return "fail"
    if dataset.status in {"rejected", "conflicting"}:
        return "fail"
    if dataset.tier == "imported":
        return "unknown"
    if dataset.kind not in {"cross_section", "rate_coefficient", "sticking_coefficient"}:
        return "fail"
    if dataset.asset is not None and not dataset.asset.integrity_ok:
        return "fail"
    if dataset.kind == "sticking_coefficient" and reaction.surface is None:
        return "fail"
    form = _form_contract(dataset, evidence)
    if form != "pass":
        return form
    unit = _unit_contract(dataset, reaction)
    if unit != "pass":
        return unit
    observable = _observable_compatibility(dataset, reaction)
    if observable != "pass":
        return observable
    return _independent_variable_contract(dataset)


def _observable_compatibility(
    dataset: NumericDataset,
    reaction: ReactionCandidate,
) -> str:
    """Keep numerical observables attached to the physical channel they describe."""

    observable = dataset.observable
    if observable is None:
        return "unknown"
    if dataset.kind == "rate_coefficient":
        return "pass" if observable == "reaction_rate" else "fail"
    if dataset.kind == "sticking_coefficient":
        return "pass" if observable == "sticking_probability" else "fail"
    if dataset.kind != "cross_section":
        return "fail"
    if reaction.process == "elastic":
        allowed = {"elastic", "momentum_transfer", "effective_momentum_transfer"}
    elif reaction.process == "resonant_charge_exchange":
        allowed = {"charge_exchange", "momentum_transfer"}
    else:
        allowed = {"reaction", reaction.process}
    return "pass" if observable in allowed else "fail"


def _independent_variable_contract(dataset: NumericDataset) -> str:
    if dataset.kind == "cross_section" and dataset.independent_variable not in {
        "collision_energy",
        "electron_energy",
        "ion_energy",
    }:
        return "unknown" if dataset.independent_variable is None else "fail"
    if dataset.form != "constant" and dataset.independent_variable is None:
        return "unknown"
    allowed = {
        None,
        "collision_energy",
        "electron_energy",
        "ion_energy",
        "gas_temperature",
        "electron_temperature",
        "ion_temperature",
        "reduced_field",
        "surface_temperature",
    }
    return "pass" if dataset.independent_variable in allowed else "fail"


def _form_contract(dataset: NumericDataset, evidence: ReactionEvidence) -> str:
    """Validate the numerical representation itself, not only its metadata."""

    if dataset.form == "constant":
        return _constant_contract(dataset)
    if dataset.form == "arrhenius":
        return _arrhenius_contract(dataset)
    if dataset.form != "table":
        return "unknown"
    return _table_contract(dataset, evidence)


def _constant_contract(dataset: NumericDataset) -> str:
    value = dataset.params.get("value")
    return "pass" if value is not None and isfinite(value) and value >= 0.0 else "fail"


def _arrhenius_contract(dataset: NumericDataset) -> str:
    pre_exponential = dataset.params.get("A")
    valid = pre_exponential is not None and isfinite(pre_exponential) and pre_exponential > 0.0
    return "pass" if valid and all(isfinite(value) for value in dataset.params.values()) else "fail"


def _table_contract(dataset: NumericDataset, evidence: ReactionEvidence) -> str:
    points = _table_points(dataset)
    if points is None or len(points) < 2:
        return "fail"
    coordinates = [point[0] for point in points]
    values = [point[1] for point in points]
    if any(not isfinite(value) for point in points for value in point):
        return "fail"
    if any(right <= left for left, right in pairwise(coordinates)):
        return "fail"
    if any(value < 0.0 for value in values):
        return "fail"
    validity = dataset.validity
    energy_axes = {"collision_energy", "electron_energy", "ion_energy"}
    same_axis = validity is not None and (
        validity.quantity == dataset.independent_variable
        or (validity.quantity in energy_axes and dataset.independent_variable in energy_axes)
    )
    if validity is not None and same_axis:
        if validity.minimum is not None and validity.minimum < coordinates[0] - 1e-12:
            return "fail"
        if validity.maximum is not None and validity.maximum > coordinates[-1] + 1e-12:
            return "fail"
    thresholds = [
        record.threshold_eV
        for record in _best_reaction_records(evidence.exact_records)
        if record.threshold_eV is not None
    ]
    if len(set(thresholds)) == 1 and dataset.independent_variable in energy_axes:
        threshold = thresholds[0]
        if any(x < threshold - 1e-9 and value > 0.0 for x, value in points):
            return "fail"
    return "pass"


def _table_points(dataset: NumericDataset) -> list[tuple[float, float]] | None:
    asset = dataset.asset
    if asset is None or asset.local_path is None:
        return None
    try:
        lines = asset.local_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return None
    points = []
    for line in lines:
        fields = line.replace(",", " ").split()
        if len(fields) < 2:
            continue
        try:
            points.append((float(fields[0]), float(fields[1])))
        except ValueError:
            continue
    return points


def _unit_contract(dataset: NumericDataset, reaction: ReactionCandidate) -> str:
    if not dataset.unit:
        return "unknown"
    unit = dataset.unit.lower().replace("^", "").replace(" ", "")
    if dataset.kind == "cross_section":
        return "pass" if unit in {"m2", "cm2"} else "fail"
    if dataset.kind == "sticking_coefficient":
        return "pass" if unit in {"1", "dimensionless"} else "fail"
    molecularity = sum(term.n for term in reaction.reactants) + bool(reaction.third_body)
    if abs(molecularity - round(molecularity)) > 1e-9:
        return "unknown"
    expected = {
        1: {"s-1", "1/s"},
        2: {"m3/s", "cm3/s"},
        3: {"m6/s", "cm6/s"},
    }.get(round(molecularity))
    return "unknown" if expected is None else ("pass" if unit in expected else "fail")


def _conflicting(datasets: list[NumericDataset]) -> bool:
    if any(dataset.status == "conflicting" for dataset in datasets):
        return True
    preferred = [dataset for dataset in datasets if dataset.preferred]
    compared = preferred if len(preferred) > 1 else datasets
    constants: dict[tuple, list[float]] = {}
    for dataset in compared:
        if dataset.form != "constant" or dataset.params.get("value") is None:
            continue
        key = (
            dataset.kind,
            dataset.observable,
            dataset.unit,
            dataset.independent_variable,
            _validity_key(dataset),
        )
        constants.setdefault(key, []).append(dataset.params["value"])
    return any(
        min(values) != 0.0 and max(values) / min(values) > 1.25
        for values in constants.values()
        if len(values) > 1 and min(values) >= 0.0
    )


def _best_datasets(datasets: list[NumericDataset]) -> list[NumericDataset]:
    if not datasets:
        return []
    best = min(TIER_RANK.get(dataset.tier, 5) for dataset in datasets)
    return [dataset for dataset in datasets if TIER_RANK.get(dataset.tier, 5) == best]


def _best_reaction_records(records: tuple[ReactionRecord, ...]) -> tuple[ReactionRecord, ...]:
    if not records:
        return ()
    best = min(TIER_RANK.get(record.tier, 5) for record in records)
    return tuple(record for record in records if TIER_RANK.get(record.tier, 5) == best)


def _required_transforms(
    datasets: list[NumericDataset],
    reaction: ReactionCandidate,
) -> tuple[str, ...]:
    found = set()
    if any(dataset.kind == "cross_section" for dataset in datasets):
        found.add(
            "eedf_integration"
            if reaction.family == "electron"
            else "energy_distribution_integration"
        )
    if any((dataset.unit or "").lower().replace(" ", "").startswith("cm") for dataset in datasets):
        found.add("unit_conversion_to_SI")
    return tuple(sorted(found))


def _validity_key(dataset: NumericDataset) -> tuple:
    value = dataset.validity
    return () if value is None else (value.quantity, value.minimum, value.maximum, value.unit)


def _applicability(dataset: NumericDataset, conditions: Conditions) -> str:
    if dataset.validity is None:
        directly_applicable = dataset.form == "constant" and dataset.independent_variable is None
        return "in_range" if directly_applicable else "unknown"
    if dataset.kind == "cross_section" and dataset.validity.quantity in {
        "collision_energy",
        "electron_energy",
        "ion_energy",
    }:
        return "in_range"
    covered = dataset.validity.covers(conditions.value_of(dataset.validity.quantity))
    if covered is None:
        return "unknown"
    return "in_range" if covered else "out_of_range"
