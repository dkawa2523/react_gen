"""Canonical schema-5 results and disposable CSV views of the same conclusions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from reactgen import outcomes, yamlio
from reactgen.case import Case, Conditions
from reactgen.chemistry import parse_state_id, reaction_declaration_matches, reaction_family
from reactgen.evidence import ReactionEvidence, molecular_equation
from reactgen.model import (
    VERIFIED_STRUCTURE_BASIS,
    EquationKey,
    ReactionCandidate,
    Requirement,
    Term,
    canonical_state_label,
    coefficient_availability_verdict,
    numerical_requirement_fields,
    participant_support_verdict,
    reaction_id,
    state_excitation,
    state_lifetime_class,
    validate_stoichiometric_terms,
)
from reactgen.pathway import PATHWAY_POLICY_FORMAT, analyze_pathways, validate_saved_pathway_graph
from reactgen.pipeline import AnalysisResult
from reactgen.presentation import (
    CalculationRecordIndex,
    calculation_record_index,
    calculation_source,
    calculation_source_offers,
    reaction_equation,
    requirement_summary,
    saved_requirement_summary,
    state_name,
)
from reactgen.reaction_tables import (
    csv_text,
    judgment_tables,
    reaction_table,
    state_judgment_stem,
    state_judgment_tables,
    state_table,
)
from reactgen.records import (
    calculation_record_reference,
    normalized_dataset_target,
    normalized_source,
    scientific_datasets_equivalent,
    scientific_method,
    selectable_state_record_id,
    validate_numerical_targets,
)
from reactgen.registry import molecular_identity_state, read_molecular_identity
from reactgen.selection import DataSelection
from reactgen.structure import (
    physical_equation_key,
    saved_structure_alias_matches,
    saved_supply_structure_matches,
)

PUBLIC_FILES = ("result.yaml", "states.csv", "reactions.csv")
FOCUSED_VIEW_FORMAT = 10
JUDGMENT_PATH = re.compile(r"judgments/[a-z][a-z0-9_-]*[.]csv")
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
    """Project validated analysis values and check their saved references."""
    payload, views = _document_views(result)
    _validated_views(payload, views)
    return payload


def _document_views(result: AnalysisResult) -> tuple[dict, dict[str, str]]:
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
        item["evidence"].pop("selection", None)
        item["evidence"].pop("target", None)
        for group in ("records", "related_records"):
            for saved, record in zip(
                item["evidence"][group],
                getattr(result.evaluation.state_evidence[state.id], group),
                strict=True,
            ):
                saved["record_id"] = selectable_state_record_id(record)
                if record.molecular_identity is None:
                    saved.pop("molecular_identity", None)
        item["assessments"] = _assessment_payload(result.evaluation.state_assessments[state.id])
        states.append(item)
    reactions = []
    for reaction in sorted(result.candidates.reactions.values(), key=lambda item: item.id):
        item = _plain(asdict(reaction))
        item["reactants"] = [_plain(term._asdict()) for term in reaction.reactants]
        item["products"] = [_plain(term._asdict()) for term in reaction.products]
        item["equation"] = reaction.equation
        item["reaction_type"] = reaction.process.replace("_", " ")
        item["evidence"] = _reaction_evidence_payload(
            result.evaluation.reaction_evidence[reaction.id]
        )
        item["assessments"] = _assessment_payload(
            result.evaluation.reaction_assessments[reaction.id]
        )
        item["thermochemistry"] = _plain(result.evaluation.thermochemistry.get(reaction.id, {}))
        use = result.evaluation.data_use[reaction.id]
        saved_use = item["data_use"] = _plain(use)
        work = (use.requirements, *(assessment.requirements for assessment in use.datasets))
        for stored, requirements in zip((saved_use, *saved_use["datasets"]), work, strict=True):
            inputs, transforms = numerical_requirement_fields(requirements)
            stored.update(
                required_inputs=list(inputs),
                required_transforms=list(transforms),
            )
        item["thermochemical_calculations"] = _plain(
            result.evaluation.thermochemical_calculations.get(reaction.id, {})
        )
        reactions.append(item)
    outcomes.add_labels(states, reactions)
    output: dict[str, Any] = {
        "input": result.input,
        "metadata": result.metadata | {"helper_view_format": FOCUSED_VIEW_FORMAT},
        "summary": summary(states, reactions),
        "states": states,
        "reactions": reactions,
        "scientific_records": _calculation_records_payload(result),
        "helper_views": {},
    }
    if reference_ids := result.evaluation.calculation_reference_state_ids:
        output["metadata"]["calculation_reference_state_ids"] = list(reference_ids)
    output["pathways"] = analyze_pathways(
        states,
        reactions,
        seeds=result.metadata.get("supply_state_ids"),
        conditions=result.input.get("conditions", {}),
    )
    views = csv_views(output)
    output["helper_views"] = {name: _hash(content) for name, content in views.items()}
    return output, views


def _assessment_payload(assessments: dict) -> dict:
    payload = _plain(assessments)
    for assessment in payload.values():
        if not assessment["record_inputs"]:
            del assessment["record_inputs"]
    return payload


def _calculation_records_payload(result: AnalysisResult) -> dict:
    records = [
        (record.id, record.id, _plain(record, declaration=True))
        for record in result.evaluation.calculation_sources.values()
    ]
    records.extend(
        (
            record_id,
            target,
            _plain(record, declaration=True)
            | {"record_id": record_id, "calculation_target": target},
        )
        for target, references in result.evaluation.calculation_state_records.items()
        for record in references
        for record_id in (selectable_state_record_id(record),)
    )
    # Keep existing keys for unique portable IDs. Distinct sources/targets with
    # that ID are independent declarations and must survive the same archive.
    reserved = {record_id for record_id, _, _ in records}
    distinct = {
        (record_id, target, calculation_record_reference(record)): record
        for record_id, target, record in records
    }
    saved = {}
    for (record_id, target, ref), record in sorted(distinct.items()):
        key = record_id
        if key in saved:
            key = f"{target}/{ref}"
            while key in reserved or key in saved:
                key = f"~{key}"
        saved[key] = record
    return saved


def _reaction_evidence_payload(evidence: ReactionEvidence) -> dict:
    payload = _plain(evidence, declaration=True)
    if not evidence.structure_aliases:
        payload.pop("structure_aliases", None)
    for group in ("records", "related_records"):
        for record in payload[group]:
            if not record["molecular_identities"]:
                record.pop("molecular_identities")
    return payload


def summary(states: list[dict], reactions: list[dict]) -> dict:
    result = {
        "state_count": len(states),
        "reaction_count": len(reactions),
        "judgments": {
            subject: {
                layer: dict(
                    sorted(
                        Counter(
                            item["assessments"][layer]["verdict"]
                            for item in items
                            if layer in item["assessments"]
                        ).items()
                    )
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
    if (states or reactions) and all(
        "label" in result
        for item in (*states, *reactions)
        for result in (
            *item["assessments"].values(),
            *([item["data_use"]] if "data_use" in item else []),
        )
    ):
        result["coverage"] = outcomes.coverage(states, reactions)
    return result


def write(outdir: Path, result: AnalysisResult) -> dict:
    """Commit the validated canonical document and return its decoded content."""
    if outdir.exists() and not outdir.is_dir():
        raise OSError(f"output is not a directory: {outdir}")
    if any((outdir / name).exists() for name in ("states.yaml", "reactions.yaml", "selected.yaml")):
        raise ValueError(
            "schema-4 bundle present; use the migration tool and a new output directory"
        )
    payload, views = _document_views(result)
    return _publish(outdir, payload, views)


def _publish(outdir: Path, payload: dict, views: dict[str, str]) -> dict:
    """Validate the staged result before commit; CSV failure leaves it readable."""
    outdir.mkdir(parents=True, exist_ok=True)
    obsolete = _obsolete_companions(outdir, views)
    files = {
        "result.yaml": yamlio.dump(payload, sort_keys=False, allow_unicode=True),
        **views,
    }
    temporary: dict[str, Path] = {}
    committed = False
    try:
        for name, content in files.items():
            destination = outdir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary[name] = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # Validate the bytes that will become the sole scientific source.
        saved = _load_document(temporary["result.yaml"])
        if saved != payload:
            raise ValueError("staged result differs from the canonical document")
        _validated_views(saved, views)
        temporary["result.yaml"].replace(outdir / "result.yaml")
        committed = True
        for name in views:
            temporary[name].replace(outdir / name)
        for path in obsolete:
            path.unlink(missing_ok=True)
    except OSError as error:
        if committed:
            raise PartialOutputError(f"result.yaml saved; CSV views incomplete: {error}") from error
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
    return saved


def _obsolete_companions(directory: Path, views: dict[str, str]) -> tuple[Path, ...]:
    """Find superseded generated judgment tables identified by the last result."""
    previous = directory / "result.yaml"
    if not previous.is_file() or not (directory / "judgments").is_dir():
        return ()
    try:
        document = _load_document(previous)
    except (OSError, ValueError, yaml.YAMLError):
        return ()
    manifest = document.get("helper_views") if isinstance(document, dict) else None
    if not isinstance(manifest, dict):
        return ()
    return tuple(
        path
        for name, digest in manifest.items()
        if isinstance(name, str)
        and JUDGMENT_PATH.fullmatch(name)
        and name not in views
        and (path := directory / name).is_file()
        and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    )


def _result_path(path: Path) -> Path:
    return path / "result.yaml" if path.is_dir() else path


def _load_document(path: Path) -> Any:
    return yamlio.load(path.read_text(encoding="utf-8"))


def read(path: Path, *, verify_views: bool = False) -> dict:
    canonical = _result_path(path)
    payload = _load_document(canonical)
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


def rebuild_views(payload: dict | Path, directory: Path) -> None:
    """Regenerate the tables defined by the saved result's format."""
    document = _load_document(_result_path(payload)) if isinstance(payload, Path) else payload
    views = _validated_views(document)
    obsolete = _obsolete_companions(directory, views)
    write_tables(directory, views)
    for path in obsolete:
        path.unlink(missing_ok=True)


def write_tables(directory: Path, tables: dict[str, str]) -> None:
    for name, content in tables.items():
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def csv_views(payload: dict) -> dict[str, str]:
    """Derive only the tables defined by the saved helper format."""
    version = _csv_format(payload)
    if version < FOCUSED_VIEW_FORMAT:
        return _archived_csv_views(payload, version)
    return {
        "states.csv": state_table(payload),
        "reactions.csv": reaction_table(payload),
        **{f"judgments/{name}.csv": content for name, content in judgment_tables(payload).items()},
        **{
            f"judgments/{state_judgment_stem(name)}.csv": content
            for name, content in state_judgment_tables(payload).items()
        },
    }


def _archived_csv_views(payload: dict, version: int) -> dict[str, str]:
    """Preserve the byte representation of existing formats 1 through 9."""
    names = {state["id"]: state_name(state) for state in payload["states"]}
    state_rows = [
        {
            "state": names[item["id"]],
            "phase": item["phase"],
            "structure": item["structure"] or "",
            **{
                f"{name}_verdict": value["verdict"]
                for name, value in item["assessments"].items()
                if name in STATE_JUDGMENTS
            },
            "reason": " | ".join(
                f"{name}: {value['message']}"
                for name, value in (
                    sorted(item["assessments"].items())
                    if version >= 7
                    else item["assessments"].items()
                )
                if value["message"] and (version >= 7 or name in STATE_JUDGMENTS)
            ),
            "id": item["id"],
        }
        for item in payload["states"]
    ]
    reaction_rows = [
        {
            "equation": reaction_equation(item, names),
            "process": item["process"],
            **{
                f"{name}_verdict": value["verdict"]
                for name, value in item["assessments"].items()
                if version >= 7 or name in REACTION_JUDGMENTS
            },
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
    if version >= 2:
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
            requirements = (
                saved_requirement_summary(item["data_use"])
                if version >= 4
                else requirement_summary(
                    item["data_use"]["required_inputs"], item["data_use"]["required_transforms"]
                )
            )
            row.update(
                {
                    name: ", ".join(requirements.get(name, ()))
                    for name in requirement_summary((), ())
                }
            )
        state_columns = (*STATE_COLUMNS[:-1], *_judgment_columns(STATE_JUDGMENTS), "id")
        reaction_columns = (
            *REACTION_COLUMNS[:-1],
            "delta_h_reference_temperature_K",
            "delta_h_standard_pressure_Pa",
            *_judgment_columns(REACTION_JUDGMENTS),
            *requirement_summary((), ()),
            "id",
        )
    if version >= 3:
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
    if version >= 4:
        for row, item in zip(reaction_rows, payload["reactions"], strict=True):
            row.update(
                data_use_scope=item["data_use"].get("scope", ""),
                data_use_requirements=_cell(item["data_use"].get("requirements", [])),
                numerical_record_assessments=_cell(item["data_use"]["datasets"]),
                thermochemical_calculations=_cell(item.get("thermochemical_calculations", {})),
            )
        reaction_columns = (
            *reaction_columns[:-1],
            "data_use_scope",
            "data_use_requirements",
            "numerical_record_assessments",
            "thermochemical_calculations",
            "id",
        )
    if version >= 5:
        _label_rows(state_rows, payload["states"], STATE_JUDGMENTS)
        _label_rows(reaction_rows, payload["reactions"], REACTION_JUDGMENTS)
        state_columns = (*state_columns[:-1], *_label_columns(STATE_JUDGMENTS), "id")
        reaction_columns = (
            *reaction_columns[:-1],
            *_label_columns(REACTION_JUDGMENTS),
            "data_use_label",
            "data_use_blocking_causes",
            "id",
        )
    state_columns = _additional_judgment_rows(
        version, state_rows, payload["states"], state_columns, ("electron_binding",)
    )
    reaction_columns = _gas_judgment_rows(version, reaction_rows, payload, reaction_columns)
    return {
        "states.csv": csv_text(state_rows, state_columns),
        "reactions.csv": csv_text(reaction_rows, reaction_columns),
    }


def _gas_judgment_rows(version: int, rows: list[dict], payload: dict, columns: tuple) -> tuple:
    columns = _additional_judgment_rows(
        version, rows, payload["reactions"], columns, ("conservation", "energy")
    )
    if version < 7:
        return columns
    for row, item in zip(rows, payload["reactions"], strict=True):
        row["transformation"] = _cell(item.get("transformation", {}))
    return (*columns[:-1], "transformation", "id")


def _additional_judgment_rows(
    version: int, rows: list[dict], items: list[dict], columns: tuple, names: tuple[str, ...]
) -> tuple:
    """Project optional current judgments without changing historical CSVs."""
    if version < 7:
        return columns
    for row, item in zip(rows, items, strict=True):
        row.update(_judgment_details(item, names, {}, ""))
    _current_judgment_rows(rows, items, names)
    _label_rows(rows, items, names)
    return (
        *columns[:-1],
        *(f"{name}_verdict" for name in names),
        *_judgment_columns(names),
        *_prerequisite_columns(names),
        *_label_columns(names),
        "id",
    )


def _csv_format(payload: dict) -> int:
    # Missing format metadata denotes historical files. Bare view inputs use
    # current columns, including empty tables.
    return (
        payload["metadata"].get("helper_view_format", 1)
        if "metadata" in payload
        else PATHWAY_POLICY_FORMAT
    )


def _label_rows(rows: list[dict], items: list[dict], names: tuple[str, ...]) -> None:
    for row, item in zip(rows, items, strict=True):
        for name in names:
            for field in ("label", "blocking_causes"):
                value = (
                    item["assessments"]
                    .get(name, {})
                    .get(field, [] if field == "blocking_causes" else "")
                )
                row[f"{name}_{field}"] = _cell(value) if field == "blocking_causes" else value
        if "data_use" in item:
            row["data_use_label"] = item["data_use"]["label"]
            row["data_use_blocking_causes"] = _cell(item["data_use"]["blocking_causes"])


def _judgment_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        f"{name}_{field}" for name in names for field in ("proposition", "scope", "reason")
    )


def _label_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{name}_{field}" for name in names for field in ("label", "blocking_causes"))


def _prerequisite_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{name}_{field}" for name in names for field in ("requirements", "dependencies"))


def _current_judgment_rows(rows: list[dict], items: list[dict], names: tuple[str, ...]) -> None:
    for row, item in zip(rows, items, strict=True):
        for name in names:
            assessment = item["assessments"].get(name, {})
            row[f"{name}_scope"] = assessment.get("scope", "")
            for field in ("requirements", "dependencies"):
                row[f"{name}_{field}"] = _cell(assessment.get(field, []))


def _cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _judgment_details(item: dict, names: tuple[str, ...], scopes: dict, subject: str) -> dict:
    details = {
        f"{name}_{field}": item["assessments"].get(name, {}).get(source, "")
        for name in names
        for field, source in (("proposition", "proposition"), ("reason", "message"))
    }
    details.update(
        {f"{name}_scope": scopes.get(f"{subject}.{name}", scopes.get(name, "")) for name in names}
    )
    return details


def validate(payload: Any) -> None:
    _validated_views(payload)


def _validated_views(payload: Any, views: dict[str, str] | None = None) -> dict[str, str]:
    _validate_shape(payload)
    return _validate_saved_meaning(payload, views)


def _validate_shape(payload: Any) -> None:
    error = next(_result_validator().iter_errors(payload), None)
    if error is not None:
        location = ".".join(map(str, error.absolute_path)) or "result"
        raise ValueError(f"{location}: {error.message}")


@lru_cache(maxsize=1)
def _result_validator() -> Draft202012Validator:
    schema = yamlio.load(Path(__file__).with_name("result.schema.yaml").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _validate_saved_meaning(payload: dict, views: dict[str, str] | None) -> dict[str, str]:
    _finite(payload)
    _validate_identities(payload)
    case = _validate_input_links(payload)
    _validate_data_uses(payload, case.data_selection)
    _validate_assessments(payload)
    _validate_calculations(payload)
    _validate_calculation_references(payload, case.data_selection)
    _validate_pathways(payload)
    if payload["metadata"].get("helper_view_format", 1) >= 5:
        outcomes.validate_labels(
            payload["states"],
            payload["reactions"],
            coefficient_exclusions=payload["metadata"]["helper_view_format"] >= 6,
        )
        if "coverage" not in payload["summary"]:
            raise ValueError("current result requires coverage counts")
    if payload["summary"] != summary(payload["states"], payload["reactions"]):
        raise ValueError("summary contradicts canonical candidates")
    if payload["metadata"]["generation"]["complete"] != all(
        payload["metadata"]["generation"]["completion"].values()
    ):
        raise ValueError("generation completion contradicts its scopes")
    views = csv_views(payload) if views is None else views
    if payload["helper_views"] != {name: _hash(content) for name, content in views.items()}:
        raise ValueError("helper view hashes do not match canonical content")
    return views


def _validate_assessments(payload: dict) -> None:
    """Validate stored meaning and references without recalculating judgments."""
    current = payload["metadata"].get("helper_view_format", 1) >= 3
    states = {item["id"]: item for item in payload["states"]}
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
                _validate_requirement(requirement)
    if payload["metadata"].get("helper_view_format", 1) < 4:
        return
    for reaction in payload["reactions"]:
        _validate_coefficient_projection(reaction)
        _validate_participant_projection(reaction, states)


def _validate_coefficient_projection(reaction: dict) -> None:
    use = reaction["data_use"]
    kinetics = reaction["assessments"]["kinetics"]
    if kinetics["proposition"] != "rate_coefficient_availability":
        return
    expected = coefficient_availability_verdict(
        use["status"], (item["status"] for item in use["datasets"])
    )
    if kinetics["verdict"] != expected or kinetics["message"] != use["reason"]:
        raise ValueError(f"coefficient projection contradicts saved data_use: {reaction['id']}")
    if kinetics.get("requirements"):
        raise ValueError(f"coefficient projection duplicates numerical work: {reaction['id']}")


def _validate_participant_projection(reaction: dict, states: dict) -> None:
    claim = reaction["assessments"]["state"]
    if claim["proposition"] != "participant_state_support":
        return
    participants = {
        term["species"]
        for term in (*reaction["reactants"], *reaction["products"])
        if term["species"] != "e"
    }
    expected_refs = sorted([[name, "state"] for name in participants])
    if claim.get("dependencies", []) != expected_refs:
        raise ValueError(f"participant projection has different targets: {reaction['id']}")
    expected = participant_support_verdict(
        states[name]["assessments"]["state"]["verdict"] for name in participants
    )
    if claim["verdict"] != expected or claim.get("requirements"):
        raise ValueError(f"participant projection contradicts saved state claims: {reaction['id']}")


def _validate_requirement(requirement: dict) -> None:
    if requirement["responsibility"] == "user_inputs":
        name = requirement["quantity"].removeprefix("conditions.")
        if name not in Conditions.__dataclass_fields__:
            raise ValueError(f"requirement is not an accepted input field: {name}")


def _validate_numerical_requirements(record: dict, label: str) -> None:
    if not record.get("scope", "").strip() or "requirements" not in record:
        raise ValueError(f"numerical responsibility is missing: {label}")
    assigned = tuple(Requirement(**item) for item in record["requirements"])
    inputs, transforms = numerical_requirement_fields(assigned)
    if (
        list(inputs) != record["required_inputs"]
        or list(transforms) != record["required_transforms"]
    ):
        raise ValueError(f"numerical fields contradict saved responsibilities: {label}")
    for requirement in record["requirements"]:
        _validate_requirement(requirement)


def _validate_calculations(payload: dict) -> None:
    """Check saved arithmetic projections, without reopening or reapproving sources."""
    if payload["metadata"].get("helper_view_format", 1) < 4:
        return
    for reaction in payload["reactions"]:
        calculations = reaction.get("thermochemical_calculations", {})
        if (
            not {
                "delta_h_eV",
                "delta_g_eV",
                "equilibrium_constant_number_density",
            }
            <= calculations.keys()
        ):
            raise ValueError(f"calculation outcomes are missing: {reaction['id']}")
        for quantity, result in calculations.items():
            for requirement in result["requirements"]:
                _validate_requirement(requirement)
            computed = result["status"] == "computed"
            if computed:
                if result["value"] is None or result["requirements"]:
                    raise ValueError(f"computed quantity contradicts its prerequisites: {quantity}")
                expected = {quantity: result["value"], **result["conditions"]}
                if any(
                    reaction["thermochemistry"].get(key) != value for key, value in expected.items()
                ):
                    raise ValueError(f"thermal values contradict calculation outcome: {quantity}")
            elif result["value"] is not None or quantity in reaction["thermochemistry"]:
                raise ValueError(f"uncomputed quantity has a saved numerical value: {quantity}")


def _validate_pathways(payload: dict) -> None:
    """Check the derived graph against its saved inputs and judgments."""
    helper_format = payload["metadata"].get("helper_view_format", 1)
    if helper_format < 7:
        return
    saved = payload.get("pathways")
    if saved is None:
        raise ValueError("current result requires the saved pathway analysis")
    if saved["conditions"] != payload["input"]["conditions"]:
        raise ValueError("pathway conditions contradict the saved analysis input")
    if saved["seeds"] != payload["metadata"]["supply_state_ids"]:
        raise ValueError("pathway supply contradicts the saved analysis input")
    validate_saved_pathway_graph(
        payload["states"], payload["reactions"], saved, format_version=helper_format
    )


def _validate_calculation_references(payload: dict, selection: DataSelection) -> None:
    helper_format = payload["metadata"].get("helper_view_format", 1)
    if helper_format < 7:
        return
    exact_references = helper_format >= 9
    for record_id, record in payload.get("scientific_records", {}).items():
        if "calculation_target" in record:
            _validate_calculation_state_record(record_id, record, exact_references)
        elif not isinstance(record.get("id"), str) or (
            not exact_references and record_id != record["id"]
        ):
            raise ValueError(f"invalid calculation reaction record: {record_id}")
    records = calculation_record_index(payload)
    for subject in (*payload["states"], *payload["reactions"]):
        for assessment in subject["assessments"].values():
            for term in assessment.get("record_inputs", ()):
                _validate_assessment_record_input(records, term, selection)
    collision_inputs = {
        f"conditions.collision_pairs[{index}].collision_energy_eV": pair
        for index, pair in enumerate(payload["input"]["conditions"].get("collision_pairs", ()))
    }
    for reaction in payload["reactions"]:
        _validate_reaction_calculation_inputs(reaction, records, collision_inputs, exact_references)


def _validate_assessment_record_input(
    records: CalculationRecordIndex, term: dict, selection: DataSelection
) -> None:
    record = calculation_source(records, term)
    if record is None:
        raise ValueError("assessment refers to an absent scientific record, target or quantity")
    policy = selection.for_quantity(term["quantity"], term["target"])
    if policy is None:
        return
    quantity = record.get("properties", {}).get(term["quantity"], {})
    if (
        policy.record is not None and policy.record not in {term["record_id"], term["record_ref"]}
    ) or (not policy.allows(*_source_axes(quantity))):
        raise ValueError("assessment scientific record contradicts the saved selection")


def _validate_calculation_state_record(
    record_id: str, record: dict, exact_references: bool
) -> None:
    target, candidate = record["calculation_target"], record.get("candidate")
    if (
        not isinstance(record.get("record_id"), str)
        or (not exact_references and record_id != record["record_id"])
        or not isinstance(target, str)
        or not isinstance(candidate, dict)
    ):
        raise ValueError(f"invalid calculation state record: {record_id}")
    _validate_state_identity(candidate)
    if target != candidate["id"]:
        try:
            _validate_molecular_state_identity(record, target)
        except ValueError as error:
            raise ValueError(
                f"calculation state record contradicts its target: {record_id}"
            ) from error


def _validate_reaction_calculation_inputs(
    reaction: dict,
    records: CalculationRecordIndex,
    collision_inputs: dict[str, dict],
    exact_references: bool,
) -> None:
    calculations = reaction["thermochemical_calculations"]
    reactants = {item["species"] for item in reaction["reactants"]}
    products = {item["species"] for item in reaction["products"]}
    dependencies: dict[str, set[str]] = {}
    alternative_dependencies: list[tuple[str, str]] = []
    for name, calculation in calculations.items():
        dependencies[name] = _calculation_dependencies(
            calculation, records, reactants, products, collision_inputs, exact_references
        )
        for offer in calculation.get("alternatives", []):
            alternative_dependencies.extend(
                (name, dependency)
                for dependency in _calculation_dependencies(
                    offer, records, reactants, products, collision_inputs, exact_references
                )
            )
    if any(references - calculations.keys() for references in dependencies.values()) or any(
        dependency not in calculations for _, dependency in alternative_dependencies
    ):
        raise ValueError("calculation refers to an absent upstream calculation")
    if any(dependencies.values()):
        try:
            TopologicalSorter(dependencies).prepare()
        except CycleError as error:
            raise ValueError("cyclic calculation references") from error
    # Each alternative consumes saved calculations. Separate alternatives
    # are not chosen together when following the inputs of one offer.
    for name, dependency in alternative_dependencies:
        if _depends_on(dependencies, dependency, name):
            raise ValueError("cyclic calculation references in an alternative")


def _calculation_dependencies(
    calculation: dict,
    records: CalculationRecordIndex,
    reactants: set[str],
    products: set[str],
    collision_inputs: dict[str, dict],
    exact_references: bool,
) -> set[str]:
    dependencies = set()
    for term in calculation.get("inputs", []):
        if "record_id" in term or "record_ref" in term:
            fields = ("target", "record_id", "quantity")
            if not all(isinstance(term.get(field), str) for field in fields):
                raise ValueError("calculation scientific record reference is invalid")
            if exact_references or "record_ref" in term:
                resolved = (
                    isinstance(term.get("record_ref"), str)
                    and calculation_source(records, term) is not None
                )
            else:
                resolved = bool(calculation_source_offers(records, term))
            if not resolved:
                raise ValueError(
                    "calculation refers to an absent scientific record, target or quantity"
                )
        if "calculation" in term:
            dependencies.add(term["calculation"])
        source = term.get("input", "")
        if isinstance(source, str) and source.startswith("conditions.collision_pairs["):
            pair = collision_inputs.get(source)
            if pair is None or (
                term.get("frame"),
                term.get("projectile_state"),
                term.get("target_state"),
            ) != (pair["collision_energy_frame"], pair["projectile_state"], pair["target_state"]):
                raise ValueError("calculation refers to a different or absent collision condition")
        if term.get("operation") == "level_state_pair" and (
            term.get("initial") not in reactants or term.get("final") not in products
        ):
            raise ValueError("level gap refers to a state outside its reaction side")
    return dependencies


def _depends_on(dependencies: dict[str, set[str]], start: str, target: str) -> bool:
    pending = [start]
    seen = set()
    while pending:
        name = pending.pop()
        if name == target:
            return True
        if name not in seen:
            seen.add(name)
            pending.extend(dependencies[name])
    return False


def _validate_data_uses(payload: dict, selection: DataSelection) -> None:
    requested = payload["input"].get("data_selection", {})
    current = payload["metadata"].get("helper_view_format", 1) >= 4
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
        # Historical arrays also list unsupported models as "inputs". Current
        # typed work can explain an unavailable value without a missing scalar.
        unavailable_inputs = not inputs or (
            payload["metadata"].get("helper_view_format", 1) >= 6
            and set(inputs)
            <= {
                item["quantity"]
                for item in use.get("requirements", [])
                if item["responsibility"] in {"external_models", "unsupported_inputs"}
            }
        )
        requirements = {
            "coefficient": not inputs and not transforms and use["value"] is not None,
            "needs_input": bool(inputs),
            "needs_transform": not inputs and bool(transforms),
            "unavailable": unavailable_inputs and not transforms,
            "conflict": True,
            "not_applicable": not use.get("requirements")
            and use["dataset_id"] is None
            and reaction["assessments"].get("conservation", {}).get("verdict") == "fail",
        }
        if not requirements[use["status"]]:
            raise ValueError(f"data_use status contradicts value or requirements: {reaction['id']}")
        offered = _evidence_datasets(reaction) if current or use["dataset_id"] is not None else {}
        if current:
            _validate_numerical_evaluations(use, offered, reaction["id"])
        _validate_data_selection(use, assessed, reaction["id"], current=current)
        _validate_selected_evidence(
            reaction["id"], use, assessed, offered, selection, current=current
        )


def _evidence_datasets(reaction: dict) -> dict[str, list[dict]]:
    evidence = reaction["evidence"]
    offered = list(evidence.get("overlay_datasets", []))
    for record in evidence.get("records", []):
        offered.extend(record.get("datasets", []))
    by_id: dict[str, list[dict]] = {}
    for item in offered:
        if not isinstance(item, dict):
            raise ValueError(f"invalid numerical evidence records: {reaction['id']}")
        if isinstance(identifier := item.get("id"), str):
            if item.get("reaction_target") not in {
                None,
                reaction["id"],
            }:
                declaration = item.get("declared_target", {}).copy()
                if "reaction" in declaration:
                    declaration["reaction"] = reaction["equation"]
                if "reaction_id" in declaration:
                    declaration["reaction_id"] = reaction["id"]
                item = item | {"reaction_target": reaction["id"], "declared_target": declaration}
            by_id.setdefault(identifier, []).append(item)
    return by_id


def _validate_numerical_evaluations(
    use: dict, offered: dict[str, list[dict]], reaction_id: str
) -> None:
    """Validate native and coefficient-purpose results against their own declarations."""
    _validate_numerical_requirements(use, reaction_id)
    if use["status"] == "coefficient" and use["requirements"]:
        raise ValueError(f"coefficient has unresolved saved prerequisites: {reaction_id}")
    for assessment in use["datasets"]:
        records = offered.get(assessment["dataset_id"], [])
        if not records:
            raise ValueError(f"native quantity has no offered record: {assessment['dataset_id']}")
        if not (assessment["status"] == "conflict" and assessment["kind"] is None):
            labels = {(item.get("kind"), item.get("observable")) for item in records}
            if (assessment["kind"], assessment["observable"]) not in labels:
                raise ValueError(
                    f"native quantity labels contradict evidence: {assessment['dataset_id']}"
                )
        _validate_numerical_requirements(assessment, assessment["dataset_id"])
        _validate_native_quantity(assessment)


def _validate_native_quantity(result: dict) -> None:
    """Check evaluated quantity shape; raw scientific declarations stay in evidence."""
    value, kind = result["value"], result["kind"]
    if kind == "cross_section" and value is not None:
        raise ValueError(f"native curve is not a scalar point query: {result['dataset_id']}")
    if value is not None and (value < 0 or (kind == "sticking_coefficient" and value > 1)):
        raise ValueError(f"native quantity value is outside its domain: {result['dataset_id']}")
    if result["status"] == "valid" and (
        result["requirements"] or (kind != "cross_section" and value is None)
    ):
        raise ValueError(
            f"valid native quantity has unresolved work or no value: {result['dataset_id']}"
        )
    coefficient_work = {
        "electron_energy_distribution",
        "collision_energy_distribution",
        "surface_incident_flux_model",
        "eedf_integration",
        "energy_distribution_integration",
        "surface_flux_conversion",
    }
    if any(item["quantity"] in coefficient_work for item in result["requirements"]):
        raise ValueError(
            f"native quantity contains coefficient conversion work: {result['dataset_id']}"
        )


def _validate_selected_evidence(
    reaction_id: str,
    use: dict,
    assessed: dict[str, dict],
    offered: dict[str, list[dict]],
    selection: DataSelection,
    *,
    current: bool,
) -> None:
    selected_id = use["dataset_id"]
    if selected_id is None:
        return
    selected = offered.get(selected_id, [])
    if not selected or any(
        not scientific_datasets_equivalent(item, selected[0]) for item in selected
    ):
        raise ValueError(f"data_use selection has missing or conflicting evidence: {reaction_id}")
    if selected[0].get("kind") != use["kind"]:
        raise ValueError(f"data_use quantity contradicts selected evidence: {reaction_id}")
    if current and use["estimated"] != (selected[0].get("tier") == "estimated"):
        raise ValueError(
            f"data_use estimate annotation contradicts selected evidence: {reaction_id}"
        )
    policy = selection.for_quantity(use["kind"], reaction_id)
    if policy is not None:
        _validate_source_request(reaction_id, selected[0], offered, assessed, policy, current)


def _validate_source_request(
    reaction_id, selected, offered, assessed, policy, current=False
) -> None:
    if policy.record is not None and policy.record != selected["id"]:
        raise ValueError(f"data_use selection contradicts requested record: {reaction_id}")
    axes = _source_axes(selected)
    if not policy.allows(*axes):
        raise ValueError(f"data_use selection contradicts only restrictions: {reaction_id}")
    if policy.mode == "prefer" and policy.record is None:
        eligible = [
            item
            for group in offered.values()
            for item in group
            if item.get("kind") == selected["kind"]
            and assessed.get(item.get("id"), {}).get("status") in {"valid", "needs_input"}
            and (
                not current
                or all(
                    assessed[item["id"]].get(field) == assessed[selected["id"]].get(field)
                    for field in ("observable", "unit")
                )
            )
        ]
        best_rank = min(policy.rank(*_source_axes(item)) for item in eligible)
        if policy.rank(*axes) != best_rank:
            raise ValueError(f"data_use selection contradicts source priority: {reaction_id}")


def _source_axes(record: dict) -> tuple[str, str | None, str | None]:
    source = normalized_source(record.get("provenance"), record.get("source"))
    return scientific_method(record), source.provider, source.collection


def _validate_data_selection(
    use: dict, assessed: dict[str, dict], reaction_id: str, *, current: bool = False
) -> None:
    selected_id = use["dataset_id"]
    if selected_id is None:
        _validate_unselected_payload(use, reaction_id)
        return
    selected = assessed.get(selected_id)
    if selected is None or selected["status"] not in {"valid", "needs_input"}:
        raise ValueError(f"data_use selection has no applicable dataset assessment: {reaction_id}")
    if use["kind"] is None or not use["unit"]:
        raise ValueError(f"data_use selection is missing its quantity or unit: {reaction_id}")
    for name in (
        ("value", "unit")
        if current
        else ("value", "unit", "required_inputs", "required_transforms")
    ):
        if use[name] != selected[name]:
            raise ValueError(f"data_use selection contradicts dataset {name}: {reaction_id}")
    if current and any(item not in use["requirements"] for item in selected["requirements"]):
        raise ValueError(f"coefficient use drops native quantity prerequisites: {reaction_id}")
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


def _validate_unselected_payload(use: dict, reaction_id: str) -> None:
    if (
        any(use[name] is not None for name in ("kind", "value", "unit"))
        or use["estimated"]
        or use["status"] in {"coefficient", "needs_transform"}
    ):
        raise ValueError(f"data_use has a value or usable status without selection: {reaction_id}")


def _validate_input_links(payload: dict) -> Case:
    case = Case.from_document(payload["input"])
    reaction_ids = {reaction["id"] for reaction in payload["reactions"]}
    state_ids = {state["id"] for state in payload["states"]}
    case.data_selection.validate_targets(
        state_ids,
        reaction_ids,
        reference_states=_validate_reference_state_ids(payload, state_ids),
    )
    if any(item.candidate.id not in reaction_ids for item in case.reactions):
        raise ValueError("saved result is missing a requested reaction")
    normalized = case.document()
    if payload["metadata"].get("helper_view_format", 1) < 7:
        normalized = {key: normalized[key] for key in payload["input"]}
        for group in ("limits", "conditions"):
            normalized[group] = {
                key: value
                for key, value in normalized[group].items()
                if key in payload["input"][group]
            }
    if normalized != payload["input"]:
        raise ValueError("saved input is not normalized")
    expected = {f"{gas}@ground" for gas in case.gases}
    actual = {
        state["id"]
        for state in payload["states"]
        if state["id"] != "e" and "input" in state["introduced_by"]
    }
    if payload["metadata"].get("helper_view_format", 1) < 7 and actual != expected:
        raise ValueError("saved input contradicts generated input states")
    if payload["metadata"].get("helper_view_format", 1) >= 7:
        _validate_supply_links(payload, case)
    if payload["input"]["limits"] != payload["metadata"]["generation"]["limits"]:
        raise ValueError("saved input limits contradict generation limits")
    return case


def _validate_reference_state_ids(payload: dict, state_ids: set[str]) -> set[str]:
    references = set(payload["metadata"].get("calculation_reference_state_ids", ()))
    if references & state_ids:
        raise ValueError("calculation reference state duplicates a candidate state")
    for target in references:
        state = parse_state_id(target)
        if (
            state is None
            or state.id != target
            or state.phase != "gas"
            or state.state.kind != "ground"
            or state.state.resolution != "resolved"
            or not any(
                candidate["phase"] == "gas"
                and candidate["state"]["resolution"] == "resolved"
                and candidate["composition"] == state.composition
                and min(0, candidate["charge"]) <= state.charge <= max(0, candidate["charge"])
                for candidate in payload["states"]
            )
        ):
            raise ValueError(f"invalid calculation reference state: {target}")
    return references


def _validate_supply_links(payload: dict, case: Case) -> None:
    supplied = {item["id"]: item for item in payload["states"] if "feed" in item["classes"]}
    metadata = payload["metadata"]
    if sorted(supplied) != metadata["supply_state_ids"]:
        raise ValueError("saved supply metadata contradicts the feed states")
    expected = {f"{gas}@ground" for gas in case.gases} | set(case.supplies)
    unmatched = set(supplied)
    bindings = metadata.get("input_structure_bindings", {})
    older_binding = metadata.get("helper_view_format", 1) < 9
    if not older_binding and bindings.keys() != case.structures.keys():
        raise ValueError("saved structure bindings do not correspond to the input structures")
    for state_id in expected:
        state = parse_state_id(state_id)
        if state is None:
            raise ValueError("invalid saved supply state")
        mapped = case.structures.get(state_id)
        if mapped is None:
            matches = {state_id} & supplied.keys()
        elif older_binding:
            matches = {
                key
                for key in supplied
                if (saved := parse_state_id(key)) is not None
                and saved_supply_structure_matches(state, mapped, saved, recorded_verification=True)
            }
        else:
            binding = bindings[state_id]
            key = binding["state"]
            item = supplied.get(key)
            saved = parse_state_id(key) if item is not None else None
            recorded = item is not None and _recorded_feed_graph_verification(item)
            declarations = {mapped, binding["smiles"]}
            matches = (
                {key}
                if saved is not None
                and all(
                    saved_supply_structure_matches(
                        state,
                        declaration,
                        saved,
                        recorded_verification=recorded and declaration == binding["smiles"],
                    )
                    for declaration in declarations
                )
                else set()
            )
        if not matches:
            raise ValueError("saved supply does not correspond to the input particles")
        unmatched -= matches
    if unmatched:
        raise ValueError("saved supply contains particles absent from the input")


def _recorded_feed_graph_verification(state: dict) -> bool:
    claim = state["assessments"].get("consistency", {})
    return (
        claim.get("proposition") == "state_representation_consistency"
        and claim.get("verdict") == "pass"
        and VERIFIED_STRUCTURE_BASIS in claim.get("basis", ())
    )


def _validate_state_identity(state: dict) -> None:
    state_id = state.get("id")
    parsed = parse_state_id(state_id) if isinstance(state_id, str) else None
    if (
        parsed is None
        or parsed.composition != state.get("composition")
        or parsed.charge != state.get("charge")
        or asdict(parsed.state) != state.get("state")
        or parsed.phase != state.get("phase")
        or parsed.structure != state.get("structure")
    ):
        raise ValueError(f"state identity contradicts ID: {state_id}")


def _validate_identities(payload: dict) -> None:
    states = {item["id"]: item for item in payload["states"]}
    if len(states) != len(payload["states"]):
        raise ValueError("duplicate state IDs")
    for state in states.values():
        _validate_state_identity(state)
        if state["structure"] and state["evidence"]["match"] == "exact":
            for record in state["evidence"].get("records", []):
                if record["candidate"]["id"] != state["id"]:
                    _validate_molecular_state_identity(record, state["id"])
    identifiers = set()
    numerical_targets: list[tuple[str, str]] = []
    legacy_id_encoding = payload["metadata"].get("helper_view_format", 1) <= 5
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
            stabilization=item["stabilization"],
        )
        if reaction.equation != item["equation"] or not _saved_reaction_id_matches(
            reaction, item["id"], legacy_id_encoding
        ):
            raise ValueError(f"reaction identity contradicts equation or ID: {item['id']}")
        if any(term.species not in states for term in (*reaction.reactants, *reaction.products)):
            raise ValueError(f"reaction refers to an absent state: {item['id']}")
        numerical_targets.extend(_saved_numerical_targets(reaction, item["evidence"]))
    validate_numerical_targets(numerical_targets)


def _saved_reaction_id_matches(
    reaction: ReactionCandidate, identifier: str, legacy_encoding: bool
) -> bool:
    """Accept the historical storage hash without changing saved identities or judgments."""
    if reaction_id(reaction.key) == identifier:
        return True
    if not legacy_encoding:
        return False
    legacy_key = (
        reaction.family,
        reaction.process,
        reaction.third_body,
        reaction.surface,
        reaction.stabilization,
        _legacy_side_key(reaction.reactants),
        _legacy_side_key(reaction.products),
    )
    return reaction_id(legacy_key) == identifier


def _legacy_side_key(terms: tuple[Term, ...]) -> tuple[tuple[str, float], ...]:
    """Formats 1-5 used sequential binary-float sums when hashing raw duplicate terms."""
    totals: dict[str, float] = {}
    for term in terms:
        totals[term.species] = totals.get(term.species, 0.0) + term.n
    return tuple(sorted((name, count) for name, count in totals.items() if count))


def _saved_numerical_targets(reaction: ReactionCandidate, evidence: dict) -> list[tuple[str, str]]:
    offered = [
        (dataset, reaction, reaction.equation_key)
        for dataset in evidence.get("overlay_datasets", [])
    ]
    aliases = evidence.get("structure_aliases", {})
    if not isinstance(aliases, dict) or any(
        not isinstance(source, str)
        or not isinstance(target, str)
        or source == target
        or target in aliases
        or not saved_structure_alias_matches(source, target)
        for source, target in aliases.items()
    ):
        raise ValueError(f"invalid saved structure alias for reaction: {reaction.id}")
    for name in ("records", "related_records"):
        for record in evidence.get(name, []):
            target, equation = _saved_reaction_target(record, reaction, aliases)
            if name == "records" and target.key[:5] != reaction.key[:5]:
                raise ValueError(
                    f"saved reaction record contradicts its physical target: {record['id']}"
                )
            offered.extend((dataset, target, equation) for dataset in record.get("datasets", []))
    bindings = []
    for dataset, target, equation in offered:
        if not isinstance(dataset, dict) or not isinstance(dataset.get("id"), str):
            raise ValueError("saved numerical evidence requires a dataset ID")
        canonical = reaction_id(target.key)
        declared = dataset.get("reaction_target")
        if (declared is not None and declared != canonical) or not reaction_declaration_matches(
            normalized_dataset_target(dataset.get("declared_target", {})), target
        ):
            raise ValueError(
                f"saved numerical dataset contradicts physical target: {dataset['id']}"
            )
        key = (*target.key[:5], *physical_equation_key(equation, aliases)[2:])
        bindings.append((dataset["id"], reaction_id(key)))
    return bindings


def _saved_reaction_target(
    record: dict, enclosing: ReactionCandidate, aliases: dict[str, str]
) -> tuple[ReactionCandidate, EquationKey]:
    third_body, surface, reactants, products = record["equation_key"]
    validate_stoichiometric_terms(reactants)
    validate_stoichiometric_terms(products)
    target = ReactionCandidate(
        "",
        tuple(Term(*term) for term in reactants),
        tuple(Term(*term) for term in products),
        record.get("family") or reaction_family((third_body, surface, reactants, products)),
        record["process"],
        "attested_only",
        "saved evidence target",
        0,
        third_body,
        surface,
        stabilization=record.get("stabilization"),
    )
    declarations = record.get("molecular_identities", {})
    participants = {term.species for term in (*target.reactants, *target.products)}
    if not isinstance(declarations, dict) or (
        declarations and (record.get("origin") != "registry" or declarations.keys() - participants)
    ):
        raise ValueError(f"invalid saved molecular identity targets: {record['id']}")
    identities = {
        name: identity
        for name, declaration in declarations.items()
        if (identity := read_molecular_identity(declaration)) is not None
    }
    equation = molecular_equation(
        target.equation_key, identities, enclosing.equation_key, saved_aliases=aliases
    )
    if target.family != enclosing.family or physical_equation_key(
        equation, aliases
    ) != physical_equation_key(enclosing.equation_key, aliases):
        raise ValueError(f"saved reaction record contradicts its physical target: {record['id']}")
    # One raw Registry dataset can be used under both its nominal and its
    # cited explicit representation. Its stored target remains the raw one.
    return target, target.equation_key if identities else equation


def _validate_molecular_state_identity(record: dict, target: str) -> None:
    source = record["candidate"]["id"]
    identity = read_molecular_identity(record.get("molecular_identity"))
    if identity is None and saved_structure_alias_matches(source, target):
        return
    nominal = parse_state_id(source)
    explicit = (
        molecular_identity_state(nominal, identity, verify_graph=False)
        if nominal is not None and identity is not None
        else None
    )
    if (
        record.get("origin") != "registry"
        or explicit is None
        or not saved_structure_alias_matches(explicit.id, target)
    ):
        raise ValueError(f"invalid saved molecular state identity: {target}")


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
