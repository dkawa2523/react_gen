"""Match a local snapshot onto canonical identities in an analysis result."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path

from reactgen import yamlio
from reactgen.chemistry import parse_state_id
from reactgen.evidence import (
    EvidenceCatalog,
    parse_equation,
    reaction_record_candidate,
    snapshot_reaction,
    snapshot_state,
)
from reactgen.export import read
from reactgen.model import EquationKey, Term, canonical_family, canonical_process, side_key
from reactgen.records import (
    NumericDataset,
    ReactionRecord,
    dataset_payload,
    normalized_dataset,
    normalized_reaction_record,
    numerical_record_id,
    reaction_has_numeric_declaration,
    reaction_record_payload,
    scientific_dataset_content,
    scientific_reaction_content,
    scientific_record_key,
    scientific_state_content,
    source_information,
    state_record_content,
    state_record_payload,
    validate_snapshot,
)


@dataclass
class Report:
    accepted: int = 0
    review: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class BundleIndex:
    states: frozenset[str]
    reactions: frozenset[str]
    equations: dict[EquationKey, tuple[str, ...]]
    families: dict[str, str]
    processes: dict[str, str]
    reaction_equations: dict[str, EquationKey]
    state_details: dict[str, dict]
    stabilizations: dict[str, str | None]

    @classmethod
    def load(cls, directory: Path) -> BundleIndex:
        document = read(directory)
        states = frozenset(item["id"] for item in document["states"])
        equations: dict[EquationKey, list[str]] = {}
        reaction_ids = set()
        families = {}
        processes = {}
        reaction_equations = {}
        for item in document["reactions"]:
            reaction_id_ = str(item["id"])
            reaction_ids.add(reaction_id_)
            families[reaction_id_] = str(item["family"])
            processes[reaction_id_] = str(item["process"])
            key: EquationKey = (
                item.get("third_body"),
                item.get("surface"),
                _terms(item.get("reactants") or []),
                _terms(item.get("products") or []),
            )
            equations.setdefault(key, []).append(reaction_id_)
            reaction_equations[reaction_id_] = key
        return cls(
            states,
            frozenset(reaction_ids),
            {key: tuple(sorted(ids)) for key, ids in equations.items()},
            families,
            processes,
            reaction_equations,
            {item["id"]: item for item in document["states"]},
            {item["id"]: item.get("stabilization") for item in document["reactions"]},
        )

    def state(self, written: str) -> str | None:
        if written in self.states:
            return written
        candidate = parse_state_id(written)
        return candidate.id if candidate is not None and candidate.id in self.states else None


def ingest(
    snapshot_path: Path,
    bundle_path: Path,
    overlay_path: Path,
) -> Report:
    snapshot = validate_snapshot(yamlio.load(snapshot_path.read_text(encoding="utf-8")))
    bundle = BundleIndex.load(bundle_path)
    overlay = _read(overlay_path)
    report = Report()
    source_data = snapshot.get("source") or {}
    if not isinstance(source_data, dict):
        raise ValueError("snapshot.source must be a mapping")
    source = source_data
    kind = snapshot.get("kind", "rate_coefficient")

    for index, record in enumerate(snapshot.get("records") or []):
        if not isinstance(record, dict):
            raise ValueError(f"snapshot record {index} must be a mapping")
        if record.get("species"):
            _state_record(record, index, bundle, overlay, source, report)
        else:
            _reaction_record(
                record,
                index,
                kind,
                bundle,
                overlay,
                source,
                snapshot_path,
                overlay_path,
                report,
            )

    _write(overlay_path, overlay)
    _write(
        overlay_path.with_name("review_queue.yaml"),
        {"snapshot": str(snapshot_path.resolve()), "source": source, "review": report.review},
    )
    return report


def _state_record(
    record: dict,
    index: int,
    bundle: BundleIndex,
    overlay: dict,
    source: dict,
    report: Report,
) -> None:
    target = bundle.state(str(record["species"]))
    if target is None:
        report.review.append(_queued(record, index, (), "state", "no match"))
        return
    identity = bundle.state_details[target]
    if record.get("phase") in {None, "unknown"}:
        report.review.append(
            _queued(record, index, (target,), "state", "physical phase unspecified")
        )
        return
    if any(name in record and record[name] != identity[name] for name in ("phase", "structure")):
        report.review.append(
            _queued(record, index, (target,), "state", "physical identity mismatch")
        )
        return
    if "state" in record and (
        not isinstance(record["state"], dict)
        or any(identity["state"].get(name) != value for name, value in record["state"].items())
    ):
        report.review.append(
            _queued(record, index, (target,), "state", "physical state declaration mismatch")
        )
        return
    offered = _state_payload(record, source)
    if not offered:
        report.review.append(
            _queued(
                record,
                index,
                (target,),
                "state",
                "no property, thermo or explicit existence payload",
            )
        )
        return
    staged = _stage_state_payload(overlay, target, offered)
    if staged is None:
        report.review.append(
            _queued(
                record,
                index,
                (target,),
                "state",
                "scientific record ID already has different content",
            )
        )
        return
    overlay.clear()
    overlay.update(staged)
    report.accepted += 1


def _state_payload(record: dict, source: dict) -> dict:
    """Normalize one complete scientific declaration without approving it."""
    normalized = snapshot_state(record, source)
    if normalized is None:
        raise ValueError("matched snapshot state cannot be normalized")
    if (
        not normalized.properties
        and normalized.thermo is None
        and not any(
            name in record
            for name in (
                "existence",
                "existence_source",
                "members",
                "configuration",
                "term",
                "J",
                "parity",
                "degeneracy",
                "lifetime_s",
            )
        )
    ):
        return {}
    return state_record_payload(normalized)


def _stage_state_payload(overlay: dict, target: str, offered: dict) -> dict | None:
    """Append one independent declaration; a scientific ID never overwrites data."""
    staged = dict(overlay)
    subjects = dict(staged.get("state_records") or {})
    staged["state_records"] = subjects
    if not isinstance(subjects, dict):
        raise ValueError("overlay.state_records must be a mapping")
    held = list(subjects.get(target) or [])
    subjects[target] = held
    if not isinstance(held, list):
        raise ValueError(f"overlay.state_records.{target} must be a list")
    existing = [
        item
        for entries in subjects.values()
        for item in entries
        if scientific_record_key(item) == scientific_record_key(offered)
    ]
    if any(
        scientific_state_content(item) != scientific_state_content(offered) for item in existing
    ):
        return None
    if existing:
        offered = offered | {"record_id": min(str(item["record_id"]) for item in existing)}
    if not any(state_record_content(item) == state_record_content(offered) for item in existing):
        held.append(offered)
    return staged


def _reaction_record(
    record: dict,
    index: int,
    kind: str,
    bundle: BundleIndex,
    overlay: dict,
    source: dict,
    snapshot_path: Path,
    overlay_path: Path,
    report: Report,
) -> None:
    targets: tuple[str, ...]
    if record.get("reaction_id"):
        targets = _explicit_target(record, bundle)
        if targets and not _matches_declared_channel(record, target=targets[0], bundle=bundle):
            report.review.append(
                _queued(
                    record, index, targets, "reaction", "reaction ID contradicts declared channel"
                )
            )
            return
    else:
        targets = _equation_targets(record, bundle)
    if len(targets) != 1:
        reason = "no match" if not targets else "several matches"
        report.review.append(_queued(record, index, targets, "reaction", reason))
        return

    target = targets[0]
    if record.get("channel_scope") == "total":
        report.review.append(
            _queued(
                record,
                index,
                targets,
                "reaction",
                "total process cannot be assigned to a product-resolved channel",
            )
        )
        return
    dataset = _snapshot_dataset(record, source, kind, snapshot_path, overlay_path)
    claim = _matched_reaction_claim(record, source, target, bundle, dataset)
    if reaction_record_candidate(claim).id != target:
        report.review.append(
            _queued(
                record,
                index,
                targets,
                "reaction",
                "reaction process or physical target is not identified by the declaration",
            )
        )
        return
    staged, reason = _stage_reaction_payload(overlay, target, claim, dataset, overlay_path.parent)
    if staged is None:
        report.review.append(_queued(record, index, targets, "reaction", reason))
        return
    overlay.clear()
    overlay.update(staged)
    report.accepted += 1


def _snapshot_dataset(
    record: dict,
    source: dict,
    kind: str,
    snapshot_path: Path,
    overlay_path: Path,
) -> NumericDataset | None:
    """Read only explicitly stated quantities and relocate their asset reference."""
    if not reaction_has_numeric_declaration(record):
        return None
    dataset = normalized_dataset(
        record,
        base=snapshot_path.parent,
        default_kind=kind,
        default_source=source,
    )
    if dataset.asset is not None and dataset.asset.local_path is not None:
        reference = os.path.relpath(dataset.asset.local_path, overlay_path.parent).replace(
            "\\", "/"
        )
        dataset = replace(dataset, asset=replace(dataset.asset, reference=reference))
    return dataset


def _matched_reaction_claim(
    record: dict,
    source: dict,
    target: str,
    bundle: BundleIndex,
    dataset: NumericDataset | None,
) -> ReactionRecord:
    quantities = (dataset,) if dataset is not None else ()
    claim = snapshot_reaction(record, source, datasets=quantities)
    if claim is not None:
        return claim
    # The explicit bundle ID is a physical target reference. Keep the original
    # declaration separately from the physical context supplied by that reference.
    equation = bundle.reaction_equations[target]
    states = tuple(
        parse_state_id(identifier)
        for identifier in sorted({term[0] for side in equation[2:] for term in side})
    )
    if any(state is None for state in states):
        raise ValueError(f"bundle reaction has an invalid state target: {target}")
    return normalized_reaction_record(
        record
        | {
            "type": record.get("type") or bundle.processes[target],
            "family": record.get("family") or bundle.families[target],
            "stabilization": bundle.stabilizations[target],
            "source_declaration": source_information(record, source)[1],
        },
        equation,
        tuple(state for state in states if state is not None),
        source,
        datasets=quantities,
    )


def _stage_reaction_payload(
    overlay: dict,
    target: str,
    claim: ReactionRecord,
    dataset: NumericDataset | None,
    base: Path,
) -> tuple[dict | None, str]:
    entry = dataset_payload(dataset) if dataset is not None else None
    # Stage both declarations together. A numerical collision must not leave
    # only its channel claim behind, or conversely drop a qualified threshold.
    staged = dict(overlay)
    held: list[dict] = []
    existing: list[NumericDataset] = []
    if dataset is not None:
        quantities = dict(staged.get("datasets") or {})
        staged["datasets"] = quantities
        held = list(quantities.get(target) or [])
        quantities[target] = held
        existing = [
            normalized_dataset(item, base=base)
            for entries in quantities.values()
            for item in entries
            if numerical_record_id(item) == dataset.id
        ]
        if any(
            scientific_dataset_content(item) != scientific_dataset_content(dataset)
            for item in existing
        ):
            return None, "dataset id already exists"
    declaration = reaction_record_payload(claim)
    subjects = dict(staged.get("reaction_records") or {})
    staged["reaction_records"] = subjects
    if not isinstance(subjects, dict):
        raise ValueError("overlay.reaction_records must be a mapping")
    claims = list(subjects.get(target) or [])
    subjects[target] = claims
    if not isinstance(claims, list):
        raise ValueError(f"overlay.reaction_records.{target} must be a list")
    previous = [
        item
        for entries in subjects.values()
        for item in entries
        if item.get("id") == declaration["id"]
    ]
    if any(
        scientific_reaction_content(item) != scientific_reaction_content(declaration)
        for item in previous
    ):
        return None, "reaction record ID already has different content"
    if declaration not in previous:
        claims.append(declaration)
    # Preserve distinct acquisitions without overwriting their original declarations.
    if entry is not None and entry not in [dataset_payload(item) for item in existing]:
        held.append(entry)
    return staged, ""


def _terms(records: list[dict]) -> tuple[tuple[str, float], ...]:
    return side_key(
        tuple(Term(str(item["species"]), float(item.get("n", 1.0))) for item in records)
    )


def _explicit_target(record: dict, bundle: BundleIndex) -> tuple[str, ...]:
    identifier = str(record["reaction_id"])
    return (identifier,) if identifier in bundle.reactions else ()


def _equation_targets(record: dict, bundle: BundleIndex) -> tuple[str, ...]:
    parsed = parse_equation(str(record.get("reaction") or ""))
    targets = () if parsed is None else bundle.equations.get(parsed[0], ())
    return tuple(
        target
        for target in targets
        if _matches_declared_channel(record, target=target, bundle=bundle)
    )


def _matches_declared_channel(record: dict, *, target: str, bundle: BundleIndex) -> bool:
    equation = bundle.reaction_equations[target]
    if record.get("reaction"):
        parsed = parse_equation(str(record["reaction"]))
        if parsed is None or parsed[0] != equation:
            return False
    if record.get("family") and canonical_family(str(record["family"])) != bundle.families[target]:
        return False
    if record.get("type"):
        process = canonical_process(
            str(record["type"]),
            family=str(record.get("family") or ""),
            third_body=equation[0],
            surface=equation[1],
        )
        if process != bundle.processes[target]:
            return False
    stabilization = record.get("stabilization")
    if stabilization is None and bundle.processes[target] in {"attachment", "recombination"}:
        stabilization = "unspecified"
    if stabilization != bundle.stabilizations[target]:
        return False
    return not any(
        name in record and record[name] != equation[index]
        for index, name in enumerate(("third_body", "surface"))
    )


def _queued(
    record: dict,
    index: int,
    targets: tuple[str, ...],
    subject: str,
    reason: str,
) -> dict:
    return {
        "record": index,
        "subject": subject,
        "wrote": record.get("reaction") or record.get("reaction_id") or record.get("species"),
        "candidates": list(targets),
        "reason": reason,
        "original_record": deepcopy(record),
    }


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    document = yamlio.load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError("overlay must be a mapping")
    EvidenceCatalog.load(None, overlay=path)
    return document


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            yamlio.dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
