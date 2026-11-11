"""Match a local snapshot onto canonical identities in an analysis result."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from reactgen import yamlio
from reactgen.chemistry import declared_state_target, parse_state_id, reaction_declaration_matches
from reactgen.evidence import (
    EvidenceCatalog,
    dataset_for_reaction,
    parse_equation,
    reaction_record_candidate,
    snapshot_reaction,
    snapshot_state_record,
)
from reactgen.export import read
from reactgen.model import (
    EquationKey,
    ReactionCandidate,
    StateCandidate,
    Term,
    bind_transformation_states,
)
from reactgen.records import (
    NumericDataset,
    ReactionRecord,
    bind_dataset_target,
    dataset_payload,
    dataset_target_declaration,
    normalized_dataset,
    normalized_reaction_record,
    numerical_record_id,
    reaction_has_numeric_declaration,
    reaction_record_payload,
    relocated_asset_payload,
    scientific_datasets_equivalent,
    scientific_reaction_content,
    scientific_record_key,
    scientific_state_content,
    snapshot_content,
    source_information,
    state_record_content,
    state_record_payload,
    validate_numerical_targets,
)
from reactgen.structure import physical_equation_key, physical_state_id


@dataclass
class Report:
    accepted: int = 0
    review: list[dict] = field(default_factory=list)
    pending_total: int = 0


@dataclass(frozen=True)
class BundleIndex:
    states: frozenset[str]
    state_spellings: dict[str, tuple[str, ...]]
    reactions: dict[str, ReactionCandidate]
    equations: dict[EquationKey, tuple[str, ...]]

    @classmethod
    def load(cls, directory: Path) -> BundleIndex:
        document = read(directory)
        states = frozenset(item["id"] for item in document["states"])
        state_spellings: dict[str, list[str]] = {}
        for identifier in sorted(states):
            state_spellings.setdefault(physical_state_id(identifier), []).append(identifier)
        equations: dict[EquationKey, list[str]] = {}
        reactions = {}
        for item in document["reactions"]:
            candidate = ReactionCandidate(
                str(item["id"]),
                _terms(item["reactants"]),
                _terms(item["products"]),
                str(item["family"]),
                str(item["process"]),
                "attested_only",
                "ingest target reference",
                0,
                item.get("third_body"),
                item.get("surface"),
                stabilization=item.get("stabilization"),
            )
            reactions[candidate.id] = candidate
            equations.setdefault(physical_equation_key(candidate.equation_key), []).append(
                candidate.id
            )
        return cls(
            states,
            {key: tuple(ids) for key, ids in state_spellings.items()},
            reactions,
            {key: tuple(sorted(ids)) for key, ids in equations.items()},
        )

    def state(self, written: str) -> str | None:
        if written in self.states:
            return written
        candidate = parse_state_id(written)
        if candidate is None:
            return None
        if candidate.id in self.states:
            return candidate.id
        matched = self.state_spellings.get(physical_state_id(candidate.id), ())
        return matched[0] if len(matched) == 1 else None


def ingest(
    snapshot_path: Path,
    bundle_path: Path,
    overlay_path: Path,
) -> Report:
    records, source, kind = snapshot_content(yamlio.load(snapshot_path.read_text(encoding="utf-8")))
    bundle = BundleIndex.load(bundle_path)
    overlay = _read(overlay_path, bundle)
    report = Report()
    queue_path = overlay_path.with_name("review_queue.yaml")
    if overlay_path.resolve() == queue_path.resolve():
        raise ValueError("overlay path must differ from its reserved review_queue.yaml")
    prior_queue = _read_queue(queue_path)
    accepted = []

    for index, record in enumerate(records):
        prior_accepted = report.accepted
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
        if report.accepted > prior_accepted:
            accepted.append(_queue_input(record, kind, source, snapshot_path))

    current_queue = [
        entry | _queue_input(entry["original_record"], kind, source, snapshot_path)
        for entry in report.review
    ]
    remaining = _merge_queue(prior_queue, current_queue, accepted)
    _write_outputs({overlay_path: overlay, queue_path: {"queue_version": 1, "review": remaining}})
    report.pending_total = len(remaining)
    return report


def _state_record(
    record: dict,
    index: int,
    bundle: BundleIndex,
    overlay: dict,
    source: dict,
    report: Report,
) -> None:
    written = str(record["species"])
    try:
        declared = declared_state_target(written, record)
    except ValueError:
        target = bundle.state(written)
        targets = (target,) if target is not None else ()
        report.review.append(
            _queued(record, index, targets, "state", "physical state declaration mismatch")
        )
        return
    if declared is None:
        report.review.append(_queued(record, index, (), "state", "no match"))
        return
    if declared.phase == "unknown":
        related = bundle.state(written)
        report.review.append(
            _queued(
                record, index, (related,) if related else (), "state", "physical phase unspecified"
            )
        )
        return
    target = bundle.state(declared.id)
    if target is None:
        related = bundle.state(written)
        report.review.append(
            _queued(
                record,
                index,
                (related,) if related else (),
                "state",
                "physical identity mismatch" if related else "no match",
            )
        )
        return
    bound = declared if target == declared.id else parse_state_id(target)
    if bound is None:
        raise ValueError(f"bundle state has an invalid target: {target}")
    offered = _state_payload(record, source, bound)
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


def _state_payload(record: dict, source: dict, target: StateCandidate) -> dict:
    """Normalize one complete scientific declaration without approving it."""
    normalized = snapshot_state_record(record, target, source)
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
    held = list(subjects.get(target) or [])
    subjects[target] = held
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
    candidate = bundle.reactions[target]
    if dataset is not None:
        if not reaction_declaration_matches(dataset.declared_target, candidate):
            # The matched target equation is the overlay reference; the author's
            # spelling remains in the dataset's original source declaration.
            dataset = replace(
                dataset, declared_target=dataset.declared_target | {"reaction": candidate.equation}
            )
        dataset = dataset_for_reaction(dataset, candidate)
    claim = _matched_reaction_claim(record, source, candidate, dataset)
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
    if dataset.asset is not None:
        payload = relocated_asset_payload(dataset.asset, snapshot_path.parent, overlay_path.parent)
        dataset = replace(dataset, asset=replace(dataset.asset, reference=str(payload["path"])))
    return dataset


def _matched_reaction_claim(
    record: dict,
    source: dict,
    target: ReactionCandidate,
    dataset: NumericDataset | None,
) -> ReactionRecord:
    quantities = (dataset,) if dataset is not None else ()
    claim = snapshot_reaction(record, source, datasets=quantities)
    if claim is not None and claim.equation_key == target.equation_key:
        return claim
    # The explicit bundle ID is a physical target reference. Keep the original
    # declaration separately from the physical context supplied by that reference.
    equation = target.equation_key
    states = tuple(
        parse_state_id(identifier)
        for identifier in sorted({term[0] for side in equation[2:] for term in side})
    )
    if any(state is None for state in states):
        raise ValueError(f"bundle reaction has an invalid state target: {target.id}")
    bound = tuple(state for state in states if state is not None)
    if claim is not None:
        by_physical_id = {physical_state_id(state.id): state.id for state in bound}
        aliases = {state.id: by_physical_id[physical_state_id(state.id)] for state in claim.states}
        return replace(
            claim,
            equation_key=equation,
            states=bound,
            transformation=bind_transformation_states(claim.transformation, aliases),
        )
    return normalized_reaction_record(
        record
        | {
            "type": record.get("type") or target.process,
            "family": record.get("family") or target.family,
            "stabilization": target.stabilization,
            "source_declaration": source_information(record, source)[1],
        },
        equation,
        bound,
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
        try:
            validate_numerical_targets(
                [(dataset.id, target)]
                + [
                    (numerical_record_id(item), identifier)
                    for identifier, entries in quantities.items()
                    for item in entries
                ]
            )
        except ValueError:
            return None, "numerical dataset ID is assigned to different physical targets"
        existing = [
            bind_dataset_target(normalized_dataset(item, base=base), identifier)
            for identifier, entries in quantities.items()
            for item in entries
            if numerical_record_id(item) == dataset.id
        ]
        if any(not scientific_datasets_equivalent(item, dataset) for item in existing):
            return None, "dataset id already exists"
    declaration = reaction_record_payload(claim)
    subjects = dict(staged.get("reaction_records") or {})
    staged["reaction_records"] = subjects
    claims = list(subjects.get(target) or [])
    subjects[target] = claims
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


def _terms(records: list[dict]) -> tuple[Term, ...]:
    return tuple(Term(str(item["species"]), float(item.get("n", 1.0))) for item in records)


def _explicit_target(record: dict, bundle: BundleIndex) -> tuple[str, ...]:
    identifier = str(record["reaction_id"])
    return (identifier,) if identifier in bundle.reactions else ()


def _equation_targets(record: dict, bundle: BundleIndex) -> tuple[str, ...]:
    parsed = parse_equation(str(record.get("reaction") or ""))
    targets = () if parsed is None else bundle.equations.get(physical_equation_key(parsed[0]), ())
    return tuple(
        target
        for target in targets
        if _matches_declared_channel(record, target=target, bundle=bundle)
    )


def _matches_declared_channel(record: dict, *, target: str, bundle: BundleIndex) -> bool:
    if record.get("reaction_target") not in {None, target}:
        return False
    candidate = bundle.reactions[target]
    if not reaction_declaration_matches(
        dataset_target_declaration(record), candidate, comparison=physical_equation_key
    ):
        return False
    stabilization = record.get("stabilization")
    if stabilization is None and candidate.process in {"attachment", "recombination"}:
        stabilization = "unspecified"
    return stabilization == candidate.stabilization


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


def _read(path: Path, bundle: BundleIndex) -> dict:
    if not path.is_file():
        return {}
    document = yamlio.load(path.read_text(encoding="utf-8"))
    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ValueError("overlay must be a mapping")
    catalog = EvidenceCatalog.from_overlay(document, path.parent)
    for identifier, datasets in catalog.overlay_datasets.items():
        if identifier in bundle.reactions:
            for dataset in datasets:
                dataset_for_reaction(dataset, bundle.reactions[identifier])
    return document


def _queue_input(record: dict, kind: str, source: dict, path: Path) -> dict:
    """Retain source context per input, without evaluating a scientific claim."""
    return {
        "original_record": deepcopy(record),
        "kind": kind,
        "source": deepcopy(source),
        "snapshot": str(path.resolve()),
    }


def _read_queue(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    document = yamlio.load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("review"), list):
        raise ValueError("review queue must contain a review list")
    version = document.get("queue_version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("unsupported review queue version")
    entries = []
    for item in document["review"]:
        if not isinstance(item, dict) or not isinstance(item.get("original_record"), dict):
            raise ValueError("review queue entries require original_record mappings")
        entry = deepcopy(item)
        for name in ("kind", "source", "snapshot"):
            if name not in entry:
                entry[name] = deepcopy(document.get(name))
        if entry["source"] is None:
            entry["source"] = {}
        if not isinstance(entry["source"], dict):
            raise ValueError("review queue source must be a mapping")
        entries.append(entry)
    return entries


def _queue_key(entry: dict, *, include_kind: bool = True) -> str:
    context = {name: entry[name] for name in ("source", "original_record")}
    if include_kind:
        context["kind"] = entry["kind"]
    return yamlio.dump(context, sort_keys=True, allow_unicode=True)


def _merge_queue(prior: list[dict], current: list[dict], accepted: list[dict]) -> list[dict]:
    """Resolve only the same accepted input; keep other source declarations intact."""
    accepted_keys = {_queue_key(entry) for entry in accepted}
    accepted_legacy = {
        (entry["snapshot"], _queue_key(entry, include_kind=False)) for entry in accepted
    }
    remaining = [
        entry
        for entry in prior
        if (
            (entry["snapshot"], _queue_key(entry, include_kind=False)) not in accepted_legacy
            if entry["kind"] is None
            else _queue_key(entry) not in accepted_keys
        )
    ]
    keyed = {_queue_key(entry): index for index, entry in enumerate(remaining)}
    legacy = {
        (entry["snapshot"], _queue_key(entry, include_kind=False)): index
        for index, entry in enumerate(remaining)
        if entry["kind"] is None
    }
    for entry in current:
        key = _queue_key(entry)
        existing = keyed.get(
            key, legacy.get((entry["snapshot"], _queue_key(entry, include_kind=False)))
        )
        if existing is None:
            keyed[key] = len(remaining)
            remaining.append(entry)
        else:
            keyed[key] = existing
            remaining[existing] = entry
    return remaining


def _write_outputs(payloads: dict[Path, dict]) -> None:
    """Commit overlay and its queue together, restoring both on ordinary IO failure."""
    token = uuid4().hex
    staged: list[tuple[Path, Path, Path | None]] = []
    committed: list[tuple[Path, Path, Path | None]] = []
    preserve_backup = False
    try:
        for path, payload in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not path.is_file():
                raise ValueError(f"ingest output is not a file: {path}")
            temporary = path.with_name(f".{path.name}.{token}.tmp")
            backup = path.with_name(f".{path.name}.{token}.backup") if path.is_file() else None
            staged.append((path, temporary, backup))
            temporary.write_text(
                yamlio.dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            if backup is not None:
                backup.write_bytes(path.read_bytes())
        try:
            for path, temporary, backup in staged:
                temporary.replace(path)
                committed.append((path, temporary, backup))
        except OSError as original:
            failures = _restore_outputs(committed)
            if failures:
                preserve_backup = True
                recovery = [str(backup) for _, _, backup in staged if backup is not None]
                raise OSError(
                    "ingest save failed and rollback was incomplete; recovery files: "
                    + ", ".join(recovery)
                ) from ExceptionGroup("ingest and rollback errors", [original, *failures])
            raise
    finally:
        for _, temporary, backup in staged:
            temporary.unlink(missing_ok=True)
            if backup is not None and not preserve_backup:
                backup.unlink(missing_ok=True)


def _restore_outputs(staged: list[tuple[Path, Path, Path | None]]) -> list[OSError]:
    failures = []
    for path, _, backup in reversed(staged):
        try:
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                # Copy to a restore file: a failed restore must leave its
                # backup available for recovery.
                restore = backup.with_suffix(".restore")
                try:
                    restore.write_bytes(backup.read_bytes())
                    restore.replace(path)
                finally:
                    restore.unlink(missing_ok=True)
        except OSError as error:
            failures.append(error)
    return failures
