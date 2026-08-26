"""The single generate -> evidence -> assess -> select flow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from reactgen import __version__
from reactgen.assessment import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNKNOWN,
    Evaluation,
    evaluate,
)
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.generate import candidates
from reactgen.model import ELECTRON, Assessment, CandidateSet, ReactionCandidate

POLICIES = (
    "review",
    "chemistry_candidate",
    "acquisition",
    "exploratory_simulation",
    "strict_simulation",
    "energy_balance",
    "resolved_state_model",
)


@dataclass(frozen=True)
class Selection:
    policy: str
    state_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    excluded_states: dict[str, str]
    excluded_reactions: dict[str, str]
    readiness: Readiness


@dataclass(frozen=True)
class Readiness:
    candidate_complete: bool
    evidence_ready: bool
    kinetic_data_ready: bool
    direct_rate_ready: bool
    energy_source_ready: bool
    reverse_rate_ready: bool
    required_transforms: tuple[str, ...] = ()


@dataclass
class PipelineResult:
    candidates: CandidateSet
    evaluation: Evaluation
    selection: Selection
    metadata: dict


def run(
    case: Case,
    catalog: EvidenceCatalog,
    policy: str = "review",
) -> PipelineResult:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy}; known: {list(POLICIES)}")
    mechanical = candidates(case.gases, case.limits)
    combined = catalog.with_attested(mechanical, case.surfaces)
    evaluation = evaluate(combined, catalog, case.conditions)
    selection = select(combined, evaluation, policy)
    metadata = {
        "schema_version": 4,
        "generator_version": __version__,
        "case": case.name,
        "case_digest": _case_digest(case),
        "evidence_snapshot_hash": catalog.fingerprint,
        "complete": combined.complete,
        "stop_reason": combined.stop_reason,
        "limits": combined.limits,
        "counts": {
            "states": len(combined.states),
            "reactions": len(combined.reactions),
            "mechanical_states": sum(
                state.origin == "mechanical" for state in combined.states.values()
            ),
            "mechanical_reactions": sum(
                reaction.origin == "mechanical" for reaction in combined.reactions.values()
            ),
        },
    }
    return PipelineResult(combined, evaluation, selection, metadata)


def select(
    candidates: CandidateSet,
    evaluation: Evaluation,
    policy: str,
) -> Selection:
    selected = []
    excluded_reactions = {}
    for reaction in sorted(candidates.reactions.values(), key=lambda item: item.id):
        keep, reason = _reaction_selected(reaction, evaluation, candidates, policy)
        if keep:
            selected.append(reaction.id)
        else:
            excluded_reactions[reaction.id] = reason

    if policy == "exploratory_simulation":
        selected = _one_state_resolution(
            selected,
            candidates,
            evaluation,
            excluded_reactions,
        )

    if policy == "review":
        state_ids = tuple(sorted(candidates.states))
    else:
        used = {
            term.species
            for reaction_id in selected
            for term in (
                *candidates.reactions[reaction_id].reactants,
                *candidates.reactions[reaction_id].products,
            )
        }
        used.add(ELECTRON)
        state_ids = tuple(sorted(used & candidates.states.keys()))

    excluded_states = {
        state_id: _state_exclusion(state_id, evaluation)
        for state_id in sorted(set(candidates.states) - set(state_ids))
    }
    return Selection(
        policy,
        state_ids,
        tuple(selected),
        excluded_states,
        excluded_reactions,
        _readiness(tuple(selected), candidates, evaluation),
    )


def _one_state_resolution(
    selected: list[str],
    candidates: CandidateSet,
    evaluation: Evaluation,
    excluded: dict[str, str],
) -> list[str]:
    """Keep one internal-state resolution per composition in simulation output."""

    groups: dict[tuple, dict[str, set[str]]] = {}
    for state in candidates.states.values():
        if state.state.kind in {"ground", "electron"}:
            continue
        key = (
            tuple(sorted(state.composition.items())),
            state.charge,
            state.state.manifold,
        )
        groups.setdefault(key, {}).setdefault(state.state.resolution, set()).add(state.id)

    kept = list(selected)
    for resolutions in groups.values():
        lumped = resolutions.get("lumped", set())
        resolved = resolutions.get("resolved", set())
        if not lumped or not resolved:
            continue
        chosen, rejected = _preferred_resolution(
            kept,
            lumped,
            resolved,
            candidates,
            evaluation,
        )
        if chosen == "lumped":
            rejected = resolved
        for reaction_id_ in list(kept):
            reaction = candidates.reactions[reaction_id_]
            participants = {term.species for term in (*reaction.reactants, *reaction.products)}
            if participants & rejected:
                kept.remove(reaction_id_)
                excluded[reaction_id_] = f"state: {chosen} resolution selected"
    return kept


def _preferred_resolution(
    selected: list[str],
    lumped: set[str],
    resolved: set[str],
    candidates: CandidateSet,
    evaluation: Evaluation,
) -> tuple[str, set[str]]:
    scores = {"lumped": 0, "resolved": 0}
    for reaction_id_ in selected:
        reaction = candidates.reactions[reaction_id_]
        participants = {term.species for term in (*reaction.reactants, *reaction.products)}
        if evaluation.reaction_assessments[reaction_id_]["kinetics"].verdict != VERDICT_PASS:
            continue
        scores["lumped"] += bool(participants & lumped)
        scores["resolved"] += bool(participants & resolved)
    chosen = "resolved" if scores["resolved"] >= scores["lumped"] else "lumped"
    return (chosen, lumped if chosen == "resolved" else resolved)


def _reaction_selected(
    reaction: ReactionCandidate,
    evaluation: Evaluation,
    candidates: CandidateSet,
    policy: str,
) -> tuple[bool, str]:
    assessed = evaluation.reaction_assessments[reaction.id]
    if policy == "review":
        return (True, "")
    if policy == "exploratory_simulation":
        if assessed["consistency"].verdict == VERDICT_FAIL:
            return (False, _reason("consistency", VERDICT_FAIL))
        if assessed["state"].verdict == VERDICT_FAIL:
            return (False, _reason("state", VERDICT_FAIL))
        if assessed["thermochemistry"].verdict == VERDICT_FAIL:
            return (False, _reason("thermochemistry", VERDICT_FAIL))
        return _exploratory_selected(reaction, assessed, evaluation)
    if assessed["consistency"].verdict != VERDICT_PASS:
        return (False, _reason("consistency", assessed["consistency"].verdict))
    if policy == "chemistry_candidate":
        return (True, "")
    if policy == "acquisition":
        return _acquisition_selected(assessed)
    if assessed["state"].verdict == VERDICT_FAIL:
        return (False, _reason("state", VERDICT_FAIL))
    return _strict_selected(reaction, assessed, evaluation, candidates, policy)


def _acquisition_selected(assessed: dict[str, Assessment]) -> tuple[bool, str]:
    failed = next(
        (
            name
            for name in ("state", "thermochemistry", "reaction_evidence", "kinetics")
            if assessed[name].verdict == VERDICT_FAIL
        ),
        None,
    )
    if failed is not None:
        return (False, _reason(failed, VERDICT_FAIL))
    unknown = next(
        (
            name
            for name in ("state", "thermochemistry", "reaction_evidence", "kinetics")
            if assessed[name].verdict == VERDICT_UNKNOWN
        ),
        None,
    )
    return (unknown is not None, "" if unknown is not None else "no acquisition gap")


def _exploratory_selected(
    reaction: ReactionCandidate,
    assessed,
    evaluation: Evaluation,
) -> tuple[bool, str]:
    kinetics = assessed["kinetics"].verdict
    keep = kinetics == VERDICT_PASS or (
        reaction.id in evaluation.estimated_kinetics and kinetics != VERDICT_FAIL
    )
    return (keep, "" if keep else _reason("kinetics", kinetics))


def _strict_selected(
    reaction: ReactionCandidate,
    assessed,
    evaluation: Evaluation,
    candidates: CandidateSet,
    policy: str,
) -> tuple[bool, str]:
    if assessed["thermochemistry"].verdict == VERDICT_FAIL:
        return (False, _reason("thermochemistry", VERDICT_FAIL))
    for layer in ("state", "reaction_evidence", "kinetics"):
        if assessed[layer].verdict != VERDICT_PASS:
            return (False, _reason(layer, assessed[layer].verdict))
    if reaction.id in evaluation.estimated_kinetics:
        return (False, "kinetics: estimated")
    if (
        policy == "energy_balance"
        and not evaluation.thermo_capabilities[reaction.id].reaction_enthalpy_ready
    ):
        return (
            False,
            "thermochemistry: reaction enthalpy unavailable",
        )
    if policy == "resolved_state_model":
        unresolved = [
            term.species
            for term in (*reaction.reactants, *reaction.products)
            if term.species != ELECTRON
            and candidates.states[term.species].state.resolution != "resolved"
        ]
        if unresolved:
            return (False, f"state: lumped {sorted(set(unresolved))}")
    return (True, "")


def _reason(layer: str, verdict: str) -> str:
    return f"{layer}: {verdict}"


def _state_exclusion(state_id: str, evaluation: Evaluation) -> str:
    assessed = evaluation.state_assessments[state_id]
    for layer in ("consistency", "state"):
        if assessed[layer].verdict == VERDICT_FAIL:
            return _reason(layer, VERDICT_FAIL)
    return "not used by selected reactions"


def _readiness(
    selected: tuple[str, ...],
    candidates: CandidateSet,
    evaluation: Evaluation,
) -> Readiness:
    if not selected:
        return Readiness(candidates.complete, False, False, False, False, False)
    assessments = [evaluation.reaction_assessments[reaction_id] for reaction_id in selected]
    kinetics = [evaluation.kinetics_capabilities[reaction_id] for reaction_id in selected]
    thermochemistry = [evaluation.thermo_capabilities[reaction_id] for reaction_id in selected]
    evidence_ready = all(
        all(
            assessed[layer].verdict == VERDICT_PASS
            for layer in ("consistency", "state", "reaction_evidence", "kinetics")
        )
        for assessed in assessments
    )
    return Readiness(
        candidate_complete=candidates.complete,
        evidence_ready=evidence_ready,
        kinetic_data_ready=all(
            item.cross_section_ready or item.direct_rate_ready for item in kinetics
        ),
        direct_rate_ready=all(item.direct_rate_ready for item in kinetics),
        energy_source_ready=all(item.reaction_enthalpy_ready for item in thermochemistry),
        reverse_rate_ready=all(item.reverse_rate_ready for item in thermochemistry),
        required_transforms=tuple(
            sorted({name for item in kinetics for name in item.required_transforms})
        ),
    )


def _case_digest(case: Case) -> str:
    payload = json.dumps(asdict(case), sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(payload.encode()).hexdigest()
