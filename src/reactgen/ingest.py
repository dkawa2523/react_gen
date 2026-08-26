"""Match a local snapshot onto the canonical ids in a generated bundle."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from reactgen.chemistry import parse_state_id
from reactgen.evidence import parse_equation
from reactgen.model import EquationKey, Term, canonical_family, canonical_process, side_key
from reactgen.records import dataset_payload, normalized_dataset


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

    @classmethod
    def load(cls, directory: Path) -> BundleIndex:
        states_path = directory / "states.yaml"
        reactions_path = directory / "reactions.yaml"
        if not states_path.is_file() or not reactions_path.is_file():
            raise ValueError(f"{directory}: states.yaml and reactions.yaml are required")
        states_doc = yaml.safe_load(states_path.read_text(encoding="utf-8")) or {}
        reactions_doc = yaml.safe_load(reactions_path.read_text(encoding="utf-8")) or {}
        states = frozenset(str(item["id"]) for item in states_doc.get("states") or [])
        equations: dict[EquationKey, list[str]] = {}
        reaction_ids = set()
        families = {}
        processes = {}
        for item in reactions_doc.get("reactions") or []:
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
        return cls(
            states,
            frozenset(reaction_ids),
            {key: tuple(sorted(ids)) for key, ids in equations.items()},
            families,
            processes,
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
    snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) or {}
    bundle = BundleIndex.load(bundle_path)
    overlay = _read(overlay_path)
    report = Report()
    source = dict(snapshot.get("source") or {})
    kind = snapshot.get("kind", "rate_coefficient")

    for index, record in enumerate(snapshot.get("records") or []):
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
    _write(overlay_path.with_name("review_queue.yaml"), {"review": report.review})
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
    if record.get("thermo"):
        destination = overlay.setdefault("thermo", {})
        key = target
        value = dict(record["thermo"])
        value.setdefault("status", record.get("status", "imported"))
    elif record.get("property"):
        destination = overlay.setdefault("properties", {}).setdefault(target, {})
        key = str(record["property"])
        value = {
            "value": record.get("value"),
            "unit": record.get("unit"),
            "source": (record.get("source") or source).get("citation") or source.get("source_id"),
            "evidence_tier": record.get("status", "imported"),
        }
    else:
        report.review.append(
            _queued(record, index, (target,), "state", "no property or thermo payload")
        )
        return
    existing = destination.get(key)
    if existing is not None and existing != value:
        report.review.append(
            _queued(record, index, (target,), "state", "overlay value already exists")
        )
        return
    destination[key] = value
    report.accepted += 1


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
        reaction_id_ = str(record["reaction_id"])
        targets = (reaction_id_,) if reaction_id_ in bundle.reactions else ()
    elif record.get("reaction"):
        parsed = parse_equation(str(record["reaction"]))
        targets = () if parsed is None else bundle.equations.get(parsed[0], ())
        if record.get("family"):
            family = canonical_family(str(record["family"]))
            targets = tuple(target for target in targets if bundle.families[target] == family)
        if record.get("type"):
            equation = parsed[0] if parsed is not None else (None, None, (), ())
            process = canonical_process(
                str(record["type"]),
                family=str(record.get("family") or ""),
                third_body=equation[0],
                surface=equation[1],
            )
            targets = tuple(target for target in targets if bundle.processes[target] == process)
    else:
        targets = ()
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
    dataset = normalized_dataset(
        record,
        base=snapshot_path.parent,
        default_id=f"{target}__{kind}_{index}",
        default_kind=kind,
        default_source=source,
    )
    if dataset.asset is not None and dataset.asset.local_path is not None:
        reference = os.path.relpath(dataset.asset.local_path, overlay_path.parent).replace(
            "\\", "/"
        )
        dataset = replace(dataset, asset=replace(dataset.asset, reference=reference))
    entry = dataset_payload(dataset)
    held = overlay.setdefault("datasets", {}).setdefault(target, [])
    existing = next((item for item in held if item.get("id") == entry["id"]), None)
    if existing is not None and existing != entry:
        report.review.append(
            _queued(record, index, targets, "reaction", "dataset id already exists")
        )
        return
    if existing is None:
        held.append(entry)
    report.accepted += 1


def _terms(records: list[dict]) -> tuple[tuple[str, float], ...]:
    return side_key(
        tuple(Term(str(item["species"]), float(item.get("n", 1.0))) for item in records)
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
    }


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
