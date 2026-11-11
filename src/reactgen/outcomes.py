"""Labels and coverage projected from saved verdicts and assigned prerequisites.

No evidence is evaluated here. A failed proposition takes precedence over its
unresolved dependencies; excluding a numerical record does not reject a reaction.
Counts describe candidates within the saved generation scope, not a mechanism.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

from reactgen.model import coefficient_availability_verdict

CAUSES = {
    "source_information": "data_missing",
    "investigation": "data_missing",
    "user_inputs": "input_missing",
    "source_review": "review_required",
    "source_selection": "selection_required",
    "identity": "identity_unresolved",
    "external_models": "model_unsupported",
    "transforms": "model_unsupported",
    "unsupported_inputs": "interface_unsupported",
}


def _causes(record: dict) -> set[str]:
    return {
        CAUSES[item["responsibility"]]
        for item in record.get("requirements", [])
        if item["responsibility"] in CAUSES
    }


def _unresolved(causes: set[str]) -> dict:
    return {
        "label": next(iter(causes)) if len(causes) == 1 else "unresolved",
        "blocking_causes": sorted(causes),
    }


def numerical_outcome(record: dict, *, coefficient_exclusions: bool = True) -> dict:
    """Native availability, coefficient use, or calculation; never occurrence."""
    status = record["status"]
    native_statuses = tuple(item["status"] for item in record.get("datasets", []))
    if (
        coefficient_exclusions
        and status == "unavailable"
        and coefficient_availability_verdict(status, native_statuses) == "fail"
    ):
        return {
            "label": "out_of_range"
            if all(item == "out_of_range" for item in native_statuses)
            else "excluded",
            "blocking_causes": [],
        }
    labels = {
        "valid": "available",
        "coefficient": "available",
        "computed": "computed",
        "invalid": "excluded",
        "out_of_range": "out_of_range",
        "conflict": "conflicting_data",
        "not_applicable": "not_applicable",
    }
    if status in labels:
        return {"label": labels[status], "blocking_causes": []}
    return _unresolved(_causes(record))


def assessment_outcome(
    assessment: dict,
    states: dict,
    numerical: dict | None = None,
    *,
    coefficient_exclusions: bool = True,
) -> dict:
    """Follow declared dependencies only for an unresolved named proposition."""
    verdict = assessment["verdict"]
    if verdict != "unknown":
        label = {"pass": "satisfied", "fail": "not_satisfied", "not_applicable": "not_applicable"}
        return {"label": label[verdict], "blocking_causes": []}
    causes = _causes(assessment)
    for state_id, name in assessment.get("dependencies", []):
        dependency = states[state_id]["assessments"][name]
        if dependency["verdict"] == "unknown":
            causes.update(_causes(dependency))
    if numerical is not None and assessment.get("proposition") == "rate_coefficient_availability":
        projected = numerical_outcome(numerical, coefficient_exclusions=coefficient_exclusions)
        causes.update(projected["blocking_causes"])
        if projected["label"] == "conflicting_data":
            causes.add("review_required")
    return _unresolved(causes)


def add_labels(
    states: list[dict], reactions: list[dict], *, coefficient_exclusions: bool = True
) -> None:
    """Attach reproducible labels when creating a new canonical result."""
    for record, outcome, _ in _label_projections(states, reactions, coefficient_exclusions):
        record.update(outcome)


def validate_labels(
    states: list[dict], reactions: list[dict], *, coefficient_exclusions: bool = True
) -> None:
    """Check projections without reinterpreting evidence or changing old results."""
    for record, expected, target in _label_projections(states, reactions, coefficient_exclusions):
        if any(record.get(name) != value for name, value in expected.items()):
            raise ValueError(f"outcome label contradicts saved verdict or prerequisites: {target}")


def _label_projections(
    states: list[dict], reactions: list[dict], coefficient_exclusions: bool
) -> Iterator[tuple[dict, dict, str]]:
    index = {state["id"]: state for state in states}
    for item in (*states, *reactions):
        for name, record in item["assessments"].items():
            yield (
                record,
                assessment_outcome(
                    record,
                    index,
                    item.get("data_use"),
                    coefficient_exclusions=coefficient_exclusions,
                ),
                f"{item['id']}.{name}",
            )
    for reaction in reactions:
        for record in (
            reaction["data_use"],
            *reaction["data_use"]["datasets"],
            *reaction.get("thermochemical_calculations", {}).values(),
        ):
            yield (
                record,
                numerical_outcome(record, coefficient_exclusions=coefficient_exclusions),
                reaction["id"],
            )


def _coverage(records: list[dict]) -> dict:
    labels = Counter(record["label"] for record in records)
    total = len(records)
    applicable = total - labels["not_applicable"]
    missing = sum("data_missing" in record["blocking_causes"] for record in records)
    return {
        "total": total,
        "applicable": applicable,
        "by_label": dict(sorted(labels.items())),
        "data_missing": missing,
        "data_missing_fraction": missing / applicable if applicable else None,
        "unresolved_by_cause": dict(
            sorted(
                Counter(cause for record in records for cause in record["blocking_causes"]).items()
            )
        ),
    }


def coverage(states: list[dict], reactions: list[dict]) -> dict:
    """Separate denominators for propositions, coefficients and calculations.

    Causes may overlap within one unresolved result. Each data-missing result
    counts once, and a rejected proposition never contributes to that count.
    """
    judgments: dict[str, dict[str, dict]] = {}
    targets = {}
    for subject, items in (("states", states), ("reactions", reactions)):
        judgments[subject] = {}
        targets[subject] = {
            "total": len(items),
            "with_data_missing_judgment": sum(
                any(
                    "data_missing" in result["blocking_causes"]
                    for result in item["assessments"].values()
                )
                for item in items
            ),
        }
        for domain in sorted({name for item in items for name in item["assessments"]}):
            records = [
                item["assessments"][domain] for item in items if domain in item["assessments"]
            ]
            judgments[subject][domain] = _coverage(records) | {
                "by_proposition": {
                    name: _coverage([record for record in records if record["proposition"] == name])
                    for name in sorted({record["proposition"] for record in records})
                }
            }
    quantities = sorted(
        {name for item in reactions for name in item.get("thermochemical_calculations", {})}
    )
    native: dict[str, list[dict]] = {}
    for reaction in reactions:
        for record in reaction["data_use"]["datasets"]:
            kind = record.get("kind") or "unknown_quantity"
            observable = record.get("observable") or "unspecified"
            key = f"{kind}/{observable}"
            native.setdefault(key, []).append(record)
    return {
        "judgments": judgments,
        "targets": targets,
        "coefficient_use": _coverage([item["data_use"] for item in reactions]),
        "native_quantities": {name: _coverage(records) for name, records in sorted(native.items())},
        "thermochemical_calculations": {
            quantity: _coverage(
                [
                    item["thermochemical_calculations"][quantity]
                    for item in reactions
                    if quantity in item.get("thermochemical_calculations", {})
                ]
            )
            for quantity in quantities
        },
        "interpretation": (
            "Each denominator counts results in the named domain within the saved candidate scope; "
            "not_applicable is excluded from applicable. Data-missing fractions count unresolved "
            "results requiring source information, not rejected propositions, input, review, "
            "identity, selection or model work alone. Multiple causes can overlap. Domain counts "
            "are not added as independent work or mechanism completeness."
        ),
    }
