"""Compact next-work summaries derived only from saved conclusions.

Groups share a subject, named proposition, saved outcome and work responsibility;
they do not declare their targets scientifically equivalent. Detailed saved
reasons and target identities remain available with ``detail=True``.
"""

from __future__ import annotations

from collections import Counter

from reactgen.presentation import reaction_equation, requirement_summary, state_name

RESPONSIBILITIES = {
    "user_inputs": "Supply the listed accepted physical input fields.",
    "source_information": (
        "Acquire the missing source declaration; physical input does not fill it."
    ),
    "source_review": "Review or repair the source record; selection does not approve it.",
    "identity": "Identify the stated physical target; a formula alone does not supply it.",
    "source_selection": "Choose among the applicable sources using data_selection.",
    "external_models": (
        "The named physical relation or model is unsupported; scalar input is insufficient."
    ),
    "transforms": "This conversion is not performed by the current coefficient workflow.",
    "unsupported_inputs": "The required quantity is not accepted by the current input interface.",
    "investigation": "Investigate evidence for this proposition; missing support is not a denial.",
    "failed_proposition": "Inspect the failed proposition; it does not reject every candidate use.",
    "excluded_data": (
        "This record is excluded under the saved conditions; it does not deny the reaction."
    ),
}


def build(document: dict, *, detail: bool = False) -> dict:
    """Summarize existing findings without reassessing evidence or opening assets."""
    names = {state["id"]: state_name(state) for state in document["states"]}
    labels = dict(names)
    for reaction in document["reactions"]:
        label = reaction_equation(reaction, names)
        labels[reaction["id"]] = label
        for dataset in reaction["data_use"]["datasets"]:
            labels.setdefault(dataset["dataset_id"], label)
    items = []
    for subject in ("states", "reactions"):
        for candidate in sorted(document[subject], key=lambda item: item["id"]):
            label = (
                names[candidate["id"]]
                if subject == "states"
                else reaction_equation(candidate, names)
            )
            target = {"subject": subject[:-1], "id": candidate["id"], "target": label}
            items.extend(_assessment_items(candidate, target))
            if subject == "reactions":
                items.extend(_numerical_items(candidate, target))
    groups, details = _groups(items, detail=detail)
    tasks = _tasks(items)
    work = _work_groups(tasks, labels)
    output = {
        "summary": {
            "groups": len(groups),
            "findings": len(items),
            "known_prerequisites": len(tasks),
            "derived_findings": sum(bool(item.get("derived_from")) for item in items),
            "findings_without_prerequisites": sum(
                not item.get("prerequisites") and not item.get("derived_from") for item in items
            ),
            "by_responsibility": dict(
                sorted(Counter(row["responsibility"] for row in items).items())
            ),
            "interpretation": (
                "Findings include individual saved propositions and dataset exclusions. "
                "Known prerequisites count distinct target/quantity/work combinations; "
                "derived findings are not counted again as work. Groups do not imply "
                "a common cause or that one task resolves every affected conclusion. "
                "They do not establish mechanism completeness or predictive ability. "
                "Use --detail for every target and its saved reason."
            ),
        },
        "input": document["input"],
        "work": work,
        "responsibilities": {
            name: explanation
            for name, explanation in RESPONSIBILITIES.items()
            if any(group["responsibility"] == name for group in groups)
        },
        "needs": groups,
        "generation": document["metadata"]["generation"],
    }
    if detail:
        output["details"] = details
        output["work_details"] = list(tasks.values())
    return output


def _assessment_items(candidate: dict, target: dict) -> list[dict]:
    items = []
    for name, judgment in sorted(candidate["assessments"].items()):
        if judgment["verdict"] not in {"unknown", "fail"}:
            continue
        base = target | {
            "judgment": name,
            "proposition": judgment.get("proposition", ""),
            "status": judgment["verdict"],
            "responsibility": "failed_proposition"
            if judgment["verdict"] == "fail"
            else "investigation",
            "reason": judgment["message"],
            "requirements": (),
        }
        prerequisites = judgment.get("requirements", []) if judgment["verdict"] == "unknown" else []
        dependencies = judgment.get("dependencies", [])
        if dependencies:
            base["derived_from"] = [
                {"subject": "state", "id": state, "judgment": layer}
                for state, layer in dependencies
            ]
        if (
            target["subject"] == "reaction"
            and name == "kinetics"
            and judgment.get("proposition") == "rate_coefficient_availability"
        ):
            base["derived_from"] = [
                {"subject": "reaction", "id": target["id"], "judgment": "data_use"}
            ]
        if not prerequisites:
            items.append(base)
            continue
        for responsibility in sorted({item["responsibility"] for item in prerequisites}):
            selected = [item for item in prerequisites if item["responsibility"] == responsibility]
            items.append(
                base
                | {
                    "responsibility": responsibility,
                    "requirements": tuple(sorted({item["quantity"] for item in selected})),
                    "prerequisites": selected,
                }
            )
    return items


def _numerical_items(candidate: dict, target: dict) -> list[dict]:
    use = candidate["data_use"]
    items = []
    base = target | {
        "judgment": "data_use",
        "proposition": "coefficient_use_under_supplied_conditions",
        "status": use["status"],
        "reason": use["reason"],
    }
    requirements = requirement_summary(use["required_inputs"], use["required_transforms"])
    for responsibility, values in requirements.items():
        if values:
            items.append(
                base
                | {
                    "responsibility": responsibility,
                    "requirements": values,
                    "prerequisites": [
                        {
                            "responsibility": responsibility,
                            "target": use["dataset_id"] or target["id"],
                            "quantity": value,
                            "reason": use["reason"],
                        }
                        for value in values
                    ],
                }
            )
    if use["status"] != "coefficient" and (not items or use["status"] == "conflict"):
        items.append(
            base
            | {
                "responsibility": "source_review"
                if use["status"] == "conflict"
                else "investigation",
                "requirements": (),
            }
        )
    for dataset in use["datasets"]:
        if dataset["status"] in {"valid", "needs_input"}:
            continue
        responsibility = (
            "source_information"
            if dataset["status"] == "reference_only"
            else "excluded_data"
            if dataset["status"] == "out_of_range"
            else "source_review"
        )
        items.append(
            {
                "subject": "dataset",
                "reaction_id": target["id"],
                "id": dataset["dataset_id"],
                "target": target["target"],
                "judgment": "dataset",
                "proposition": "numerical_record_use_under_supplied_conditions",
                "status": dataset["status"],
                "responsibility": responsibility,
                "reason": dataset["reason"],
                "requirements": ("numerical_representation",)
                if dataset["status"] == "reference_only"
                else (),
                "prerequisites": [
                    {
                        "responsibility": responsibility,
                        "target": dataset["dataset_id"],
                        "quantity": "numerical_representation",
                        "reason": dataset["reason"],
                    }
                ]
                if dataset["status"] == "reference_only"
                else [],
            }
        )
    return items


def _tasks(items: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Deduplicate explicit prerequisites, never inferred causes of a message."""
    tasks: dict[tuple[str, str, str], dict] = {}
    for item in items:
        for requirement in item.get("prerequisites", []):
            key = (requirement["responsibility"], requirement["target"], requirement["quantity"])
            task = tasks.setdefault(
                key,
                {
                    "responsibility": key[0],
                    "target": key[1],
                    "quantity": key[2],
                    "reasons": [],
                    "affected": [],
                },
            )
            reason = requirement.get("reason", "")
            if reason and reason not in task["reasons"]:
                task["reasons"].append(reason)
            affected = {name: item[name] for name in ("subject", "id", "judgment", "proposition")}
            if affected not in task["affected"]:
                task["affected"].append(affected)
    _include_dependents(tasks, items)
    return dict(sorted(tasks.items()))


def _include_dependents(tasks: dict, items: list[dict]) -> None:
    references: dict[tuple, list[tuple]] = {}
    for item in items:
        key = (item["subject"], item["id"], item["judgment"])
        references.setdefault(key, []).extend(
            (req["responsibility"], req["target"], req["quantity"])
            for req in item.get("prerequisites", [])
        )
    for item in items:
        affected = {name: item[name] for name in ("subject", "id", "judgment", "proposition")}
        for reference in item.get("derived_from", []):
            key = (reference["subject"], reference["id"], reference["judgment"])
            for task_key in references.get(key, []):
                if affected not in tasks[task_key]["affected"]:
                    tasks[task_key]["affected"].append(affected)


def _work_groups(tasks: dict, names: dict[str, str]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for task in tasks.values():
        groups.setdefault((task["responsibility"], task["quantity"]), []).append(task)
    return [
        {
            "responsibility": key[0],
            "quantity": key[1],
            "target_tasks": len(members),
            "target_examples": [names.get(item["target"], item["target"]) for item in members[:3]],
            "affected_findings": sum(len(item["affected"]) for item in members),
        }
        for key, members in sorted(groups.items())
    ]


def _groups(items: list[dict], *, detail: bool) -> tuple[list[dict], list[dict]]:
    fields = ("responsibility", "subject", "judgment", "proposition", "status", "requirements")
    grouped: dict[tuple, list[dict]] = {}
    for item in items:
        grouped.setdefault(tuple(item[field] for field in fields), []).append(item)
    groups: list[dict] = []
    details: list[dict] = []
    for index, (key, members) in enumerate(sorted(grouped.items()), start=1):
        reasons = Counter(item["reason"] for item in members)
        examples = sorted(
            members, key=lambda item: (item["target"], item["id"], item.get("reaction_id", ""))
        )
        group = dict(zip(fields, key, strict=True))
        group["requirements"] = list(group["requirements"])
        group.update(
            group=index,
            count=len(members),
            reason_variants=len(reasons),
            reason_examples=[
                {"reason": reason, "count": count}
                for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[
                    :3
                ]
            ],
            target_examples=list(dict.fromkeys(item["target"] for item in examples))[:3],
        )
        groups.append(group)
        if detail:
            details.extend(
                item | {"group": index, "requirements": list(item["requirements"])}
                for item in examples
            )
    return groups, details
