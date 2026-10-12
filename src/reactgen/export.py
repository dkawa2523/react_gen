"""Canonical schema-5 results and disposable CSV views of the same conclusions."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import tempfile
from collections import Counter
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from reactgen import yamlio
from reactgen.case import Case, Conditions
from reactgen.chemistry import parse_state_id
from reactgen.model import (
    CandidateState,
    ReactionCandidate,
    Term,
    canonical_state_label,
    reaction_id,
    state_excitation,
    state_lifetime_class,
)
from reactgen.pipeline import AnalysisResult
from reactgen.presentation import reaction_equation, requirement_summary, state_name
from reactgen.records import normalized_source, scientific_dataset_content, scientific_method
from reactgen.selection import DataSelection

PUBLIC_FILES = ("result.yaml", "states.csv", "reactions.csv")
VERDICTS = ("pass", "fail", "unknown", "not_applicable")
STATE_COLUMNS = (
    "state",
    "phase",
    "structure",
    "consistency_verdict",
    "state_verdict",
    "thermochemistry_verdict",
    "reason",
    "id",
)
STATE_JUDGMENTS = ("consistency", "state", "thermochemistry")
REACTION_JUDGMENTS = (*STATE_JUDGMENTS, "reaction_evidence", "kinetics")
REACTION_COLUMNS = (
    "equation",
    "process",
    "consistency_verdict",
    "state_verdict",
    "thermochemistry_verdict",
    "reaction_evidence_verdict",
    "kinetics_verdict",
    "delta_h_eV",
    "threshold_eV",
    "data_use",
    "value",
    "unit",
    "required_inputs",
    "required_transforms",
    "reason",
    "id",
)


class PartialOutputError(OSError):
    """The canonical result was committed but one or more CSV views were not."""


def document(result: AnalysisResult) -> dict:
    states = []
    for state in sorted(result.candidates.states.values(), key=lambda item: item.id):
        item = _plain(asdict(state))
        item["state_axes"] = {
            "excitation": state_excitation(state.state.kind, state.state.label),
            "lifetime_class": state_lifetime_class(state.state.kind, state.classes),
            "canonical_label": canonical_state_label(state.state.kind, state.state.label),
            "structure_scope": state.structure or "composition_only",
        }
        item["evidence"] = _plain(result.evaluation.state_evidence[state.id], declaration=True)
        item["assessments"] = _plain(result.evaluation.state_assessments[state.id])
        states.append(item)
    reactions = []
    for reaction in sorted(result.candidates.reactions.values(), key=lambda item: item.id):
        item = _plain(asdict(reaction))
        item["reactants"] = [_plain(term._asdict()) for term in reaction.reactants]
        item["products"] = [_plain(term._asdict()) for term in reaction.products]
        item["equation"] = reaction.equation
        item["reaction_type"] = reaction.process.replace("_", " ")
        item["evidence"] = _plain(
            result.evaluation.reaction_evidence[reaction.id], declaration=True
        )
        item["assessments"] = _plain(result.evaluation.reaction_assessments[reaction.id])
        item["thermochemistry"] = _plain(result.evaluation.thermochemistry.get(reaction.id, {}))
        item["data_use"] = _plain(result.evaluation.data_use[reaction.id])
        reactions.append(item)
    output = {
        "input": result.input,
        "metadata": result.metadata | {"helper_view_format": 3},
        "summary": summary(states, reactions),
        "states": states,
        "reactions": reactions,
        "helper_views": {},
    }
    output["helper_views"] = {name: _hash(content) for name, content in csv_views(output).items()}
    validate(output)
    return output


def summary(states: list[dict], reactions: list[dict]) -> dict:
    return {
        "state_count": len(states),
        "reaction_count": len(reactions),
        "judgments": {
            subject: {
                layer: dict(
                    sorted(Counter(item["assessments"][layer]["verdict"] for item in items).items())
                )
                for layer in sorted({name for item in items for name in item["assessments"]})
            }
            for subject, items in (("states", states), ("reactions", reactions))
        },
        "data_use": dict(sorted(Counter(item["data_use"]["status"] for item in reactions).items())),
        "interpretation": (
            "Conclusions apply to individual candidates and datasets within the declared "
            "generation scope. Missing support is unknown. These counts do not establish "
            "a complete mechanism, energy closure, or predictive simulation."
        ),
    }


def write(outdir: Path, result: AnalysisResult) -> None:
    """Commit one canonical document, then publish hash-checked auxiliary views."""
    if outdir.exists() and not outdir.is_dir():
        raise OSError(f"output is not a directory: {outdir}")
    if any((outdir / name).exists() for name in ("states.yaml", "reactions.yaml", "selected.yaml")):
        raise ValueError(
            "schema-4 bundle present; use the migration tool and a new output directory"
        )
    payload = document(result)
    _publish(outdir, payload)


def _publish(outdir: Path, payload: dict) -> None:
    """Publish an already validated result; CSV failure leaves a readable canonical file."""
    outdir.mkdir(parents=True, exist_ok=True)
    contents = csv_views(payload)
    files = {
        "result.yaml": yamlio.dump(payload, sort_keys=False, allow_unicode=True),
        **contents,
    }
    temporary: dict[str, Path] = {}
    committed = False
    try:
        for name, content in files.items():
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=outdir,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary[name] = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # Validate the bytes that will become the sole scientific source.
        validate(yamlio.load(temporary["result.yaml"].read_text(encoding="utf-8")))
        temporary["result.yaml"].replace(outdir / "result.yaml")
        committed = True
        for name in contents:
            temporary[name].replace(outdir / name)
    except OSError as error:
        if committed:
            raise PartialOutputError(f"result.yaml saved; CSV views incomplete: {error}") from error
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def read(path: Path, *, verify_views: bool = False) -> dict:
    canonical = path / "result.yaml" if path.is_dir() else path
    payload = yamlio.load(canonical.read_text(encoding="utf-8"))
    validate(payload)
    if verify_views and (stale := stale_views(payload, canonical.parent)):
        raise ValueError(
            f"stale or missing CSV views: {', '.join(stale)}; regenerate with rgen view --kind csv"
        )
    return payload


def stale_views(payload: dict, directory: Path) -> tuple[str, ...]:
    return tuple(
        name
        for name, expected in payload["helper_views"].items()
        if not (directory / name).is_file()
        or hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected
    )


def rebuild_views(payload: dict, directory: Path) -> None:
    """Regenerate disposable tables without changing saved judgments."""
    validate(payload)
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in csv_views(payload).items():
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=f".{name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        try:
            temporary.replace(directory / name)
        finally:
            temporary.unlink(missing_ok=True)


def csv_views(payload: dict) -> dict[str, str]:
    """Derive tables using the saved format, so historical hashes stay reproducible.

    Formats 1 and 2 retain historical CSV hashes. Format 3 also preserves the
    individual scope, prerequisites and dependencies, and numerical selection.
    No format evaluates scientific evidence.
    """
    version = payload.get("metadata", {}).get("helper_view_format", 3)
    # Documents with metadata but no format are historical; bare view inputs
    # use the current format (including empty tables).
    if "metadata" in payload and "helper_view_format" not in payload["metadata"]:
        version = 1
    names = {state["id"]: state_name(state) for state in payload["states"]}
    state_rows = [
        {
            "state": names[item["id"]],
            "phase": item["phase"],
            "structure": item["structure"] or "",
            **{f"{name}_verdict": value["verdict"] for name, value in item["assessments"].items()},
            "reason": " | ".join(
                f"{name}: {value['message']}"
                for name, value in item["assessments"].items()
                if value["message"]
            ),
            "id": item["id"],
        }
        for item in payload["states"]
    ]
    reaction_rows = [
        {
            "equation": reaction_equation(item, names),
            "process": item["process"],
            **{f"{name}_verdict": value["verdict"] for name, value in item["assessments"].items()},
            "delta_h_eV": item["thermochemistry"].get("delta_h_eV", ""),
            "threshold_eV": item["thermochemistry"].get("threshold_eV", ""),
            "data_use": item["data_use"]["status"],
            "value": item["data_use"]["value"],
            "unit": item["data_use"]["unit"],
            "required_inputs": ", ".join(item["data_use"]["required_inputs"]),
            "required_transforms": ", ".join(item["data_use"]["required_transforms"]),
            "reason": item["data_use"]["reason"],
            "id": item["id"],
        }
        for item in payload["reactions"]
    ]
    state_columns: tuple[str, ...] = STATE_COLUMNS
    reaction_columns: tuple[str, ...] = REACTION_COLUMNS
    if version in {2, 3}:
        scopes = payload.get("metadata", {}).get("judgment_scope", {})
        for row, item in zip(state_rows, payload["states"], strict=True):
            row.update(_judgment_details(item, STATE_JUDGMENTS, scopes, "state"))
        for row, item in zip(reaction_rows, payload["reactions"], strict=True):
            row.update(_judgment_details(item, REACTION_JUDGMENTS, scopes, "reaction"))
            row.update(
                {
                    name: item["thermochemistry"].get(name, "")
                    for name in ("delta_h_reference_temperature_K", "delta_h_standard_pressure_Pa")
                }
            )
            requirements = requirement_summary(
                item["data_use"]["required_inputs"], item["data_use"]["required_transforms"]
            )
            row.update({name: ", ".join(values) for name, values in requirements.items()})
        state_columns = (*STATE_COLUMNS[:-1], *_judgment_columns(STATE_JUDGMENTS), "id")
        reaction_columns = (
            *REACTION_COLUMNS[:-1],
            "delta_h_reference_temperature_K",
            "delta_h_standard_pressure_Pa",
            *_judgment_columns(REACTION_JUDGMENTS),
            *requirement_summary((), ()),
            "id",
        )
    if version == 3:
        _current_judgment_rows(state_rows, payload["states"], STATE_JUDGMENTS)
        _current_judgment_rows(reaction_rows, payload["reactions"], REACTION_JUDGMENTS)
        for row, item in zip(reaction_rows, payload["reactions"], strict=True):
            use = item["data_use"]
            row.update(
                dataset_id=use["dataset_id"] or "",
                quantity=use["kind"] or "",
                conditions=_cell(payload.get("input", {}).get("conditions", {})),
                data_selection=_cell(use.get("selection", {})),
                disagreements=_cell(use.get("disagreements", [])),
                thermochemical_values=_cell(item["thermochemistry"]),
            )
        state_columns = (*state_columns[:-1], *_prerequisite_columns(STATE_JUDGMENTS), "id")
        reaction_columns = (
            *reaction_columns[:-1],
            *_prerequisite_columns(REACTION_JUDGMENTS),
            "dataset_id",
            "quantity",
            "conditions",
            "data_selection",
            "disagreements",
            "thermochemical_values",
            "id",
        )
    return {
        "states.csv": _csv(state_rows, state_columns),
        "reactions.csv": _csv(reaction_rows, reaction_columns),
    }


def _judgment_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        f"{name}_{field}" for name in names for field in ("proposition", "scope", "reason")
    )


def _prerequisite_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{name}_{field}" for name in names for field in ("requirements", "dependencies"))


def _current_judgment_rows(rows: list[dict], items: list[dict], names: tuple[str, ...]) -> None:
    for row, item in zip(rows, items, strict=True):
        for name in names:
            assessment = item["assessments"][name]
            row[f"{name}_scope"] = assessment.get("scope", "")
            for field in ("requirements", "dependencies"):
                row[f"{name}_{field}"] = _cell(assessment.get(field, []))


def _cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _judgment_details(item: dict, names: tuple[str, ...], scopes: dict, subject: str) -> dict:
    details = {
        f"{name}_{field}": item["assessments"][name].get(source, "")
        for name in names
        for field, source in (("proposition", "proposition"), ("reason", "message"))
    }
    details.update(
        {f"{name}_scope": scopes.get(f"{subject}.{name}", scopes.get(name, "")) for name in names}
    )
    return details


def validate(payload: Any) -> None:
    schema = yamlio.load(Path(__file__).with_name("result.schema.yaml").read_text(encoding="utf-8"))
    error = next(Draft202012Validator(schema).iter_errors(payload), None)
    if error is not None:
        location = ".".join(map(str, error.absolute_path)) or "result"
        raise ValueError(f"{location}: {error.message}")
    _finite(payload)
    _validate_identities(payload)
    _validate_input_links(payload)
    _validate_data_uses(payload)
    _validate_assessments(payload)
    if payload["summary"] != summary(payload["states"], payload["reactions"]):
        raise ValueError("summary contradicts canonical candidates")
    if payload["metadata"]["generation"]["complete"] != all(
        payload["metadata"]["generation"]["completion"].values()
    ):
        raise ValueError("generation completion contradicts its scopes")
    if payload["helper_views"] != {
        name: _hash(content) for name, content in csv_views(payload).items()
    }:
        raise ValueError("helper view hashes do not match canonical content")


def _validate_assessments(payload: dict) -> None:
    """Validate stored meaning and references without recalculating judgments."""
    current = payload["metadata"].get("helper_view_format", 1) >= 3
    states = {item["id"]: item for item in payload["states"]}
    accepted = {field.name for field in fields(Conditions)}
    for item in (*payload["states"], *payload["reactions"]):
        for name, assessment in item["assessments"].items():
            if current and any(
                not assessment.get(field, "").strip() for field in ("proposition", "scope")
            ):
                raise ValueError(f"assessment meaning is missing: {item['id']}.{name}")
            for state_id, key in assessment.get("dependencies", []):
                if state_id not in states or key not in states[state_id]["assessments"]:
                    raise ValueError(f"assessment dependency is absent: {item['id']}.{name}")
            for requirement in assessment.get("requirements", []):
                if requirement["responsibility"] == "user_inputs":
                    field = requirement["quantity"].removeprefix("conditions.")
                    if field not in accepted:
                        raise ValueError(f"requirement is not an accepted input field: {field}")


def _validate_data_uses(payload: dict) -> None:
    requested = payload["input"].get("data_selection", {})
    for reaction in payload["reactions"]:
        use = reaction["data_use"]
        if use.get("selection", {}) != requested:
            raise ValueError(f"data_use selection contradicts analysis request: {reaction['id']}")
        assessed = {item["dataset_id"]: item for item in use["datasets"]}
        if len(assessed) != len(use["datasets"]):
            raise ValueError(f"duplicate data_use dataset IDs: {reaction['id']}")
        disagreements = use.get("disagreements", [])
        if any(
            identifier not in assessed
            or identifier == use["dataset_id"]
            or assessed[identifier]["status"] not in {"valid", "needs_input", "conflict"}
            for identifier in disagreements
        ):
            raise ValueError(f"data_use disagreement has no distinct dataset: {reaction['id']}")
        inputs, transforms = use["required_inputs"], use["required_transforms"]
        requirements = {
            "coefficient": not inputs and not transforms and use["value"] is not None,
            "needs_input": bool(inputs),
            "needs_transform": not inputs and bool(transforms),
            "unavailable": not inputs and not transforms,
            "conflict": True,
        }
        if not requirements[use["status"]]:
            raise ValueError(f"data_use status contradicts value or requirements: {reaction['id']}")
        _validate_data_selection(use, assessed, reaction["id"])
        _validate_selected_evidence(reaction, use, assessed)


def _evidence_datasets(reaction: dict) -> list[dict]:
    evidence = reaction["evidence"]
    offered = list(evidence.get("overlay_datasets", []))
    for record in evidence.get("records", []):
        offered.extend(record.get("datasets", []))
    if any(not isinstance(item, dict) for item in offered):
        raise ValueError(f"invalid numerical evidence records: {reaction['id']}")
    return offered


def _validate_selected_evidence(reaction: dict, use: dict, assessed: dict[str, dict]) -> None:
    selected_id = use["dataset_id"]
    if selected_id is None:
        return
    offered = _evidence_datasets(reaction)
    selected = [item for item in offered if item.get("id") == selected_id]
    if not selected or any(
        scientific_dataset_content(item) != scientific_dataset_content(selected[0])
        for item in selected
    ):
        raise ValueError(
            f"data_use selection has missing or conflicting evidence: {reaction['id']}"
        )
    if selected[0].get("kind") != use["kind"]:
        raise ValueError(f"data_use quantity contradicts selected evidence: {reaction['id']}")
    policy = DataSelection.from_document(use.get("selection", {})).for_quantity(use["kind"])
    if policy is not None:
        _validate_source_request(reaction["id"], selected[0], offered, assessed, policy)


def _validate_source_request(reaction_id, selected, offered, assessed, policy) -> None:
    if policy.record is not None and policy.record != selected["id"]:
        raise ValueError(f"data_use selection contradicts requested record: {reaction_id}")
    axes = _source_axes(selected)
    if not policy.allows(*axes):
        raise ValueError(f"data_use selection contradicts only restrictions: {reaction_id}")
    if policy.mode == "prefer" and policy.record is None:
        eligible = [
            item
            for item in offered
            if item.get("kind") == selected["kind"]
            and assessed.get(item.get("id"), {}).get("status") in {"valid", "needs_input"}
        ]
        best_rank = min(policy.rank(*_source_axes(item)) for item in eligible)
        if policy.rank(*axes) != best_rank:
            raise ValueError(f"data_use selection contradicts source priority: {reaction_id}")


def _source_axes(record: dict) -> tuple[str, str | None, str | None]:
    source = normalized_source(record.get("provenance"), record.get("source"))
    return scientific_method(record), source.provider, source.collection


def _validate_data_selection(use: dict, assessed: dict[str, dict], reaction_id: str) -> None:
    selected_id = use["dataset_id"]
    if selected_id is None:
        if (
            any(use[name] is not None for name in ("kind", "value", "unit"))
            or use["estimated"]
            or use["status"] in {"coefficient", "needs_transform"}
        ):
            raise ValueError(
                f"data_use has a value or usable status without selection: {reaction_id}"
            )
        return
    selected = assessed.get(selected_id)
    if selected is None or selected["status"] not in {"valid", "needs_input"}:
        raise ValueError(f"data_use selection has no applicable dataset assessment: {reaction_id}")
    if use["kind"] is None or not use["unit"]:
        raise ValueError(f"data_use selection is missing its quantity or unit: {reaction_id}")
    for name in ("value", "unit", "required_inputs", "required_transforms"):
        if use[name] != selected[name]:
            raise ValueError(f"data_use selection contradicts dataset {name}: {reaction_id}")
    expected_status = (
        "needs_input"
        if use["required_inputs"]
        else "needs_transform"
        if use["required_transforms"]
        else "coefficient"
    )
    if use["status"] != expected_status:
        raise ValueError(f"data_use selection contradicts status: {reaction_id}")
    if use["status"] == "coefficient" and use["kind"] != "rate_coefficient":
        raise ValueError(f"data_use coefficient does not describe a reaction rate: {reaction_id}")
    if use["kind"] == "sticking_coefficient" and use["value"] is not None and use["value"] > 1:
        raise ValueError(f"data_use sticking probability exceeds one: {reaction_id}")


def _validate_input_links(payload: dict) -> None:
    case = Case.from_document(payload["input"])
    if case.document() != payload["input"]:
        raise ValueError("saved input is not normalized")
    expected = {f"{gas}@ground" for gas in case.gases}
    actual = {
        state["id"]
        for state in payload["states"]
        if state["id"] != "e" and "input" in state["introduced_by"]
    }
    if actual != expected:
        raise ValueError("saved input contradicts generated input states")
    if payload["input"]["limits"] != payload["metadata"]["generation"]["limits"]:
        raise ValueError("saved input limits contradict generation limits")


def _validate_identities(payload: dict) -> None:
    states = {item["id"]: item for item in payload["states"]}
    if len(states) != len(payload["states"]):
        raise ValueError("duplicate state IDs")
    for state in states.values():
        parsed = parse_state_id(state["id"])
        expected_state = CandidateState(**state["state"])
        if (
            parsed is None
            or parsed.composition != state["composition"]
            or parsed.charge != state["charge"]
            or parsed.state != expected_state
            or parsed.phase != state["phase"]
            or parsed.structure != state["structure"]
        ):
            raise ValueError(f"state identity contradicts ID: {state['id']}")
    identifiers = set()
    for item in payload["reactions"]:
        if item["id"] in identifiers:
            raise ValueError(f"duplicate reaction ID: {item['id']}")
        identifiers.add(item["id"])
        reaction = ReactionCandidate(
            item["id"],
            tuple(Term(**term) for term in item["reactants"]),
            tuple(Term(**term) for term in item["products"]),
            item["family"],
            item["process"],
            item["origin"],
            item["generation_rule"],
            item["depth"],
            item["third_body"],
            item["surface"],
            tuple(item["kinetic_effects"]),
            item["stabilization"],
        )
        if reaction_id(reaction.key) != item["id"] or reaction.equation != item["equation"]:
            raise ValueError(f"reaction identity contradicts equation or ID: {item['id']}")
        if any(term.species not in states for term in (*reaction.reactants, *reaction.products)):
            raise ValueError(f"reaction refers to an absent state: {item['id']}")


def _plain(value: Any, *, declaration: bool = False) -> Any:
    # An invalid source declaration remains inspectable as text. Calculated
    # values still pass the strict finite-number check in validate().
    if declaration and isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value), declaration=declaration)
    if isinstance(value, dict):
        return {str(key): _plain(item, declaration=declaration) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return [_plain(item, declaration=declaration) for item in sorted(value)]
    if isinstance(value, list | tuple):
        return [_plain(item, declaration=declaration) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite numerical value in result")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _csv(rows: list[dict], columns: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
