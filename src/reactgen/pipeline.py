"""One candidate and evidence analysis; every view derives from this result."""

from __future__ import annotations

from dataclasses import dataclass

from reactgen import __version__
from reactgen.assessment import Evaluation, evaluate
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.generate import candidates
from reactgen.model import CandidateSet


@dataclass
class AnalysisResult:
    candidates: CandidateSet
    evaluation: Evaluation
    input: dict
    metadata: dict


def analyze(case: Case, catalog: EvidenceCatalog) -> AnalysisResult:
    """Investigate bounded candidates; this does not construct a predictive solver."""
    mechanical = candidates(case.gases, case.limits)
    combined = catalog.with_attested(mechanical, case.surfaces)
    evaluation = evaluate(combined, catalog, case.conditions, case.data_selection)
    metadata = {
        "schema_version": 5,
        "generator_version": __version__,
        "evidence_snapshot_hash": catalog.fingerprint,
        "generation": {
            "complete": combined.complete,
            "completion": combined.completion,
            "stop_reason": combined.stop_reason,
            "limits": combined.limits,
            "scope": (
                "Bounded composition grammar for input gases; electronic/vibrational "
                "templates and ion ligand-transfer partners are limited to input "
                "ground states. Source-attested channels are added without a second "
                "mechanical closure. Completion describes this scope, not all chemistry."
            ),
        },
        "judgment_scope": {
            "consistency": "Equation, conservation and declared process pattern are consistent.",
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
            "kinetics": "A qualified numerical dataset applies under the supplied conditions.",
        },
    }
    return AnalysisResult(combined, evaluation, case.document(), metadata)
