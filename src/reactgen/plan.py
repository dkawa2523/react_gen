"""Derive a compact acquisition backlog from unknown assessments."""

from __future__ import annotations

from reactgen.pipeline import PipelineResult


def build(result: PipelineResult) -> dict:
    needs: dict[str, dict[str, list[str]]] = {
        "state": {"states": [], "reactions": []},
        "thermochemistry": {"states": [], "reactions": []},
        "reaction_evidence": {"states": [], "reactions": []},
        "kinetics": {"states": [], "reactions": []},
    }
    for state_id, layers in result.evaluation.state_assessments.items():
        if any(value.verdict == "fail" for value in layers.values()):
            continue
        for layer in ("state", "thermochemistry"):
            if layers[layer].verdict == "unknown":
                needs[layer]["states"].append(state_id)
    for reaction_id, layers in result.evaluation.reaction_assessments.items():
        if any(value.verdict == "fail" for value in layers.values()):
            continue
        for layer in ("state", "thermochemistry", "reaction_evidence", "kinetics"):
            if layers[layer].verdict == "unknown":
                needs[layer]["reactions"].append(reaction_id)
    return {
        "case": result.metadata["case"],
        "complete": result.candidates.complete,
        "stop_reason": result.candidates.stop_reason,
        "needs": {
            layer: {subject: sorted(ids) for subject, ids in subjects.items() if ids}
            for layer, subjects in needs.items()
            if any(subjects.values())
        },
    }
