from __future__ import annotations


def confidence(score: float, basis: list[str] | None = None) -> dict:
    """Build a simple review-priority confidence payload.

    This score is not a physical probability; it is only a compact way to rank
    inferred candidates for human review.
    """

    return {
        "score": max(0.0, min(1.0, float(score))),
        "basis": list(basis or []),
    }
