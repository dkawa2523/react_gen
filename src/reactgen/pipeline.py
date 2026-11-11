"""One candidate and evidence analysis; every view derives from this result."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from reactgen import __version__
from reactgen.assessment import Evaluation, evaluate
from reactgen.case import Case
from reactgen.chemistry import formula_scope
from reactgen.evidence import EvidenceCatalog
from reactgen.generate import expand
from reactgen.model import CandidateSet, StateCandidate
from reactgen.naming import parse
from reactgen.structure import bind_physical_state, input_structure, physical_state_id


@dataclass
class AnalysisResult:
    candidates: CandidateSet
    evaluation: Evaluation
    input: dict
    metadata: dict


def analyze(case: Case, catalog: EvidenceCatalog) -> AnalysisResult:
    """Investigate bounded candidates; this does not construct a predictive solver."""
    supplied, gaps, structure_bindings = case.input_particles()
    structural_context = (*supplied, *(state for item in case.reactions for state in item.states))
    molecular_states = catalog.scoped_molecular_states(structural_context)
    case = replace(
        case,
        conditions=case.bound_conditions(supplied, molecular_states),
        reactions=case.bound_reactions(supplied, molecular_states),
    )
    for state in {state.id: state for item in case.reactions for state in item.states}.values():
        _, unavailable = input_structure(state, None)
        if unavailable:
            gap = {"target": state.id, "operation": "graph_input", "reason": unavailable}
            if gap not in gaps:
                gaps.append(gap)
    representatives: dict[str, StateCandidate] = {}
    for state in (*supplied, *(state for item in case.reactions for state in item.states)):
        representatives.setdefault(physical_state_id(state.id), state)
    projected = tuple(state for states in molecular_states.values() for state in states)
    for state in projected:
        representatives.setdefault(physical_state_id(state.id), state)
    combined = expand(
        supplied,
        case.limits,
        gaps,
        known_states=_known_states((*catalog.declared_states(), *projected), representatives),
        source_channels=tuple(
            catalog.attested_candidates(case.surfaces, representatives=representatives)
        ),
        requested=case.reactions,
    )
    evaluation = evaluate(combined, catalog, case.conditions, case.data_selection)
    scope = (
        "Bounded gas-state, charge, fragment and group/bond transformations; "
        "mechanical, source-added and reachable requested products share the worklist. "
        "Formula hypotheses remain distinct from identified structures and levels. "
        "Completion describes this finite grammar, not all chemistry."
    )
    if not case.limits.expand_unresolved_states:
        scope += (
            " Unresolved non-feed states remain inspectable and can enable declared channels; "
            "mechanical expansion uses resolved states and explicit gas supplies."
        )
    metadata = {
        "schema_version": 5,
        "generator_version": __version__,
        "evidence_snapshot_hash": catalog.fingerprint,
        "supply_state_ids": sorted(
            state.id for state in combined.states.values() if "feed" in state.classes
        ),
        "generation": {
            "complete": combined.complete,
            "completion": combined.completion,
            "stop_reason": combined.stop_reason,
            "trials": combined.trials,
            "gaps": combined.generation_gaps,
            "unexpanded": combined.unexpanded,
            "limits": combined.limits,
            "input_scope": {gas: formula_scope(parse(gas).composition) for gas in case.gases},
            "scope": scope,
        },
        "judgment_scope": {
            "conservation": "Element and charge accounting for the represented equation.",
            "consistency": "Equation, conservation and declared process pattern are consistent.",
            "energy": "The represented endpoints fit the specified collision energy budget.",
            "state": "The named existence or electron-binding proposition is evaluated. "
            "Binding support does not establish observed existence, lifetime or stability "
            "against other decay paths.",
            "reaction.state": "The named state propositions of the participants are combined; "
            "this does not establish an observed or complete reaction mechanism.",
            "thermochemistry": "Available qualified energy relations are mutually consistent.",
            "state.thermochemistry": "At least one nonconflicting qualified thermochemical "
            "representation is available; condition-specific use is not established.",
            "reaction.thermochemistry": "The named energy proposition is evaluated; "
            "calculated values alone do not establish occurrence.",
            "reaction_evidence": "Reviewed evidence supports this product-resolved channel.",
            "kinetics": "A usable reaction rate coefficient in the supplied evidence "
            "under supplied conditions; "
            "native quantity availability and conversion requirements are separate results.",
        },
    }
    if structure_bindings:
        metadata["input_structure_bindings"] = structure_bindings
    return AnalysisResult(combined, evaluation, case.document(), metadata)


def _known_states(
    declared: tuple[StateCandidate, ...], representatives: Mapping[str, StateCandidate]
) -> tuple[StateCandidate, ...]:
    """Use declared state identities without promoting their data or supplying them."""
    normalized: dict[str, StateCandidate] = {}
    for candidate in declared:
        state = bind_physical_state(candidate, representatives)
        normalized.setdefault(state.id, state)
    return tuple(normalized[key] for key in sorted(normalized))
