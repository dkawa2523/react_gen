"""Explicitly persist an overlay without upgrading its scientific quality.

Existing values and qualified negative evidence are retained. Each written
value keeps its source and quality; adopting a file is not scientific review.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reactgen import yamlio
from reactgen.evidence import (
    EvidenceCatalog,
    registry_reaction_candidate,
    registry_state_candidate,
    snapshot_reaction,
)
from reactgen.records import (
    NumericDataset,
    dataset_payload,
    normalized_dataset,
    reaction_record_payload,
    scientific_dataset_content,
    scientific_reaction_content,
    scientific_record_key,
    scientific_state_content,
    state_record_content,
    state_record_payload,
)
from reactgen.registry import Registry


class AdoptionRecoveryError(OSError):
    """Adoption and rollback failed; retained recovery files are named in the error."""


@dataclass
class Adoption:
    """What one pass over the registry wrote, kept, and could not place."""

    written: dict[str, list[str]] = field(default_factory=dict)
    kept: dict[str, list[str]] = field(default_factory=dict)
    unplaced: list[str] = field(default_factory=list)

    @property
    def values(self) -> int:
        return sum(len(names) for names in self.written.values())

    @property
    def held(self) -> int:
        return sum(len(names) for names in self.kept.values())


def adopt(overlay: Path, registry_root: Path, dry_run: bool = False) -> Adoption:
    """Prepare all changes before writing; restore originals on a save exception.

    File replacement prevents truncated files. Rollback covers ordinary I/O
    errors, not simultaneous readers/writers or process/power interruption.
    If restoring files also fails, backups are retained and the error names
    their location. Scientific quality is preserved, never approved here.
    """

    report = Adoption()
    root = Path(registry_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"registry directory not found: {root}")
    overlay_path = Path(overlay)
    overlay_data: dict = yamlio.load(overlay_path.read_text(encoding="utf-8")) or {}
    if not isinstance(overlay_data, dict):
        raise ValueError("overlay must be a mapping")
    # Parse all typed declarations before any writes. This validates format,
    # not scientific approval; missing assets are checked when placing data.
    catalog = EvidenceCatalog.load(None, overlay=overlay_path)
    registry = Registry.load(root)
    documents: dict[Path, dict] = {}
    assets: dict[Path, bytes] = {}
    _prepare_species(overlay_data, catalog, root, registry, report, documents)
    _prepare_reaction_records(overlay_data, root, registry, report, documents)
    _prepare_datasets(
        overlay_data.get("datasets") or {},
        root,
        overlay_path.parent,
        registry,
        report,
        documents,
        assets,
    )
    changes = assets | {
        path: yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8")
        for path, document in documents.items()
    }
    for target in changes:
        if root not in target.resolve().parents:
            raise ValueError(f"adoption target is outside the Registry: {target}")
    if not dry_run:
        _commit_changes(root, changes)
    return report


def _prepare_species(
    overlay_data: dict,
    catalog: EvidenceCatalog,
    root: Path,
    registry: Registry,
    report: Adoption,
    documents: dict[Path, dict],
) -> None:
    """Store independent typed declarations, including legacy overlay inputs.

    Existing Registry declarations remain in their original fields. Incoming
    records are appended to the scientific record array rather than choosing
    a permanent representative value or overwriting an existence assertion.
    """
    directory = root / "species"
    state_targets: dict[tuple, list[str]] = {}
    for species in registry.species.values():
        state_targets.setdefault(registry_state_candidate(species).key, []).append(species.id)
    requested = set().union(
        *(
            set(overlay_data.get(name) or {})
            for name in ("states", "properties", "thermo", "state_records")
        )
    )
    offered_targets = {record.id for record in catalog.state_records}
    report.unplaced.extend(sorted(requested - offered_targets))
    all_existing = [
        state_record_payload(record)
        for species in registry.species.values()
        for record in species.records
    ]
    for incoming in catalog.state_records:
        candidate_id = incoming.id
        matches = state_targets.get(incoming.candidate.key, [])
        if len(matches) != 1:
            report.unplaced.append(candidate_id)
            continue
        path = _file(directory, matches[0])
        if path is None:
            report.unplaced.append(candidate_id)
            continue
        document = documents.get(path)
        if document is None:
            document = yamlio.load(path.read_text(encoding="utf-8")) or {}
        held = document.setdefault("records", [])
        if not isinstance(held, list):
            raise ValueError(f"{path}: scientific records must be a list")
        offered = state_record_payload(incoming)

        existing = [
            item
            for item in all_existing
            if scientific_record_key(item) == scientific_record_key(offered)
        ]
        if any(
            scientific_state_content(item) != scientific_state_content(offered) for item in existing
        ):
            raise ValueError(f"scientific record ID has different content: {incoming.record_id}")
        if existing:
            offered = offered | {"record_id": min(str(item["record_id"]) for item in existing)}
        if any(state_record_content(item) == state_record_content(offered) for item in existing):
            report.kept.setdefault(candidate_id, []).append(str(offered["record_id"]))
            continue
        held.append(offered)
        all_existing.append(offered)
        report.written.setdefault(candidate_id, []).append(str(offered["record_id"]))
        documents[path] = document


def _prepare_reaction_records(
    overlay_data: dict,
    root: Path,
    registry: Registry,
    report: Adoption,
    documents: dict[Path, dict],
) -> None:
    """Persist independently qualified claims without replacing their channel."""
    requested = overlay_data.get("reaction_records") or {}
    destinations = _reaction_destinations(root, registry)
    all_existing = [
        reaction_record_payload(record)
        for group in registry.channels.values()
        for reaction in group
        for record in reaction.records
    ]
    for candidate_id, records in sorted(requested.items()):
        location = destinations.get(candidate_id)
        if location is None:
            report.unplaced.append(candidate_id)
            continue
        path, index = location
        document = documents.get(path)
        if document is None:
            document = yamlio.load(path.read_text(encoding="utf-8")) or {}
        channel = document["channels"][index]
        held = channel.setdefault("records", [])
        if not isinstance(held, list):
            raise ValueError(f"{path}: channel scientific records must be a list")
        additions, kept = _reaction_record_additions(records, all_existing)
        if additions:
            held.extend(additions)
            all_existing.extend(additions)
            report.written.setdefault(candidate_id, []).extend(item["id"] for item in additions)
            documents[path] = document
        if kept:
            report.kept.setdefault(candidate_id, []).extend(kept)


def _reaction_record_additions(
    records: list[dict], held: list[dict]
) -> tuple[list[dict], list[str]]:
    """Validate same-ID science before preserving distinct acquisition declarations."""
    previous: dict[str, list[dict]] = {}
    for item in held:
        previous.setdefault(item["id"], []).append(item)
    additions, kept = [], []
    for item in records:
        incoming = snapshot_reaction(item, origin="overlay", datasets=(), preserved_record_id=True)
        if incoming is None:
            raise ValueError("invalid reaction record declaration")
        offered = reaction_record_payload(incoming)
        existing = previous.get(incoming.id, [])
        if any(
            scientific_reaction_content(record) != scientific_reaction_content(offered)
            for record in existing
        ):
            raise ValueError(f"reaction record ID has different content: {incoming.id}")
        if offered in existing:
            kept.append(incoming.id)
        else:
            additions.append(offered)
            previous.setdefault(incoming.id, []).append(offered)
    return additions, kept


def _prepare_datasets(
    datasets: dict,
    root: Path,
    overlay_base: Path,
    registry: Registry,
    report: Adoption,
    documents: dict[Path, dict],
    assets: dict[Path, bytes],
) -> None:
    destinations = _reaction_destinations(root, registry)
    all_existing = [
        dataset
        for group in registry.channels.values()
        for reaction in group
        for dataset in reaction.datasets
    ]
    for candidate_id, records in sorted(datasets.items()):
        # Equivalent physical channels may have several independent source
        # records. The stable container ID only decides where to persist data;
        # it neither chooses a scientific source nor changes evaluation.
        location = destinations.get(candidate_id)
        if location is None:
            report.unplaced.append(candidate_id)
            continue
        path, index = location
        document = documents.get(path)
        if document is None:
            document = yamlio.load(path.read_text(encoding="utf-8")) or {}
        channel = document["channels"][index]
        held = channel.setdefault("data", {}).setdefault("datasets", [])
        additions, kept = _dataset_additions(records, all_existing, overlay_base, root, assets)
        if additions:
            held.extend(additions)
            written = report.written.setdefault(candidate_id, [])
            written.extend(str(item["id"]) for item in additions)
            documents[path] = document
        if kept:
            report.kept.setdefault(candidate_id, []).extend(kept)


def _dataset_additions(
    records: list[dict],
    held: list[NumericDataset],
    overlay_base: Path,
    root: Path,
    assets: dict[Path, bytes],
) -> tuple[list[dict], list[str]]:
    """An existing numerical ID can be repeated, never silently replaced."""
    existing: dict[str, list[NumericDataset]] = {}
    for dataset in held:
        existing.setdefault(dataset.id, []).append(dataset)
    additions = []
    kept = []
    for item in records:
        normalized = normalized_dataset(item, base=overlay_base)
        dataset_id = normalized.id
        previous = existing.get(dataset_id, [])
        if previous:
            if any(
                scientific_dataset_content(item) != scientific_dataset_content(normalized)
                for item in previous
            ):
                raise ValueError(f"dataset ID has different content: {dataset_id}")
            if any(
                _dataset_storage_content(normalized) == _dataset_storage_content(item)
                for item in previous
            ):
                kept.append(str(dataset_id))
                continue
        # An agreeing scientific declaration with a distinct acquisition is
        # persisted alongside the originals rather than overwritten.
        additions.append(_registry_dataset(normalized, root, assets))
        existing.setdefault(dataset_id, []).append(normalized)
        held.append(normalized)
    return additions, kept


def _dataset_storage_content(dataset: NumericDataset) -> dict:
    """Keep original declarations/acquisitions; ignore only a verified copy's path."""
    content = dataset_payload(dataset)
    if dataset.asset is not None and dataset.asset.read_bytes(False) is not None:
        content["asset"].pop("path", None)
    return content


def _reaction_destinations(root: Path, registry: Registry) -> dict[str, tuple[Path, int]]:
    """Choose a storage container for a physical target, without choosing its evidence."""
    locations = _reaction_locations(root / "reactions")
    targets: dict[str, list[str]] = {}
    for group in registry.channels.values():
        for reaction in group:
            candidate = registry_reaction_candidate(reaction, registry.species)
            if candidate is not None:
                targets.setdefault(candidate.id, []).append(reaction.id)
    return {target: locations[min(channels)] for target, channels in targets.items()}


def _reaction_locations(directory: Path) -> dict[str, tuple[Path, int]]:
    found = {}
    for path in sorted(directory.glob("*/*.yaml")):
        document = yamlio.load(path.read_text(encoding="utf-8")) or {}
        for index, channel in enumerate(document.get("channels") or []):
            found[str(channel.get("id"))] = (path, index)
    return found


def _commit_changes(root: Path, changes: dict[Path, bytes]) -> None:
    """Stage changed files and backups, replacing files with rollback on OSError."""

    if not changes:
        return
    staging = Path(tempfile.mkdtemp(prefix=".adopt-", dir=root.parent))
    committed: list[Path] = []
    created_dirs: list[Path] = []
    preserve_backup = False
    try:
        prepared, originals = _stage_changes(root, staging, changes)
        try:
            for target, prepared_file in prepared.items():
                _create_parents(target.parent, created_dirs)
                os.replace(prepared_file, target)
                committed.append(target)
        except OSError as original_error:
            failures = _restore_changes(staging, committed, originals, created_dirs)
            if failures:
                preserve_backup = True
                raise AdoptionRecoveryError(
                    f"adoption failed and rollback was incomplete; recovery files: {staging}"
                ) from ExceptionGroup("adoption and rollback errors", [original_error, *failures])
            raise
    finally:
        if not preserve_backup:
            if staging.resolve().parent != root.parent or not staging.name.startswith(".adopt-"):
                raise ValueError(f"refusing cleanup outside adoption staging directory: {staging}")
            shutil.rmtree(staging)


def _stage_changes(
    root: Path, staging: Path, changes: dict[Path, bytes]
) -> tuple[dict[Path, Path], dict[Path, bytes | None]]:
    prepared = {}
    originals = {}
    manifest = []
    for index, (target, content) in enumerate(sorted(changes.items())):
        prepared_file = staging / f"{index}.new"
        prepared_file.write_bytes(content)
        original = target.read_bytes() if target.is_file() else None
        if target.exists() and original is None:
            raise ValueError(f"adoption target is not a file: {target}")
        backup = f"{index}.original" if original is not None else None
        if backup:
            (staging / backup).write_bytes(original or b"")
        prepared[target] = prepared_file
        originals[target] = original
        manifest.append({"target": target.relative_to(root).as_posix(), "original": backup})
    (staging / "recovery.yaml").write_text(
        yaml.safe_dump({"registry": str(root), "files": manifest}), encoding="utf-8"
    )
    return prepared, originals


def _create_parents(directory: Path, created: list[Path]) -> None:
    missing = []
    while not directory.is_dir():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _restore_changes(
    staging: Path,
    committed: list[Path],
    originals: dict[Path, bytes | None],
    created_dirs: list[Path],
) -> list[OSError]:
    failures = []
    for index, target in enumerate(reversed(committed)):
        try:
            original = originals[target]
            if original is None:
                target.unlink()
            else:
                restore = staging / f"{index}.restore"
                restore.write_bytes(original)
                os.replace(restore, target)
        except OSError as error:
            failures.append(error)
    for directory in reversed(created_dirs):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError as error:
            failures.append(error)
    return failures


def _registry_dataset(
    dataset: NumericDataset,
    registry_root: Path,
    assets: dict[Path, bytes],
) -> dict:
    record = dataset_payload(dataset)
    asset = record.get("asset")
    preserved_asset = dict(asset) if isinstance(asset, dict) else {}
    asset_path = asset.get("path") if isinstance(asset, dict) else asset
    if asset_path:
        content = dataset.asset.read_bytes(False) if dataset.asset is not None else None
        if content is None or dataset.asset is None or dataset.asset.local_path is None:
            raise ValueError(
                f"overlay asset not found or differs from its recorded checksum: {asset_path}"
            )
        resolved = dataset.asset.local_path
        root = registry_root.resolve()
        if root not in resolved.parents:
            checksum = hashlib.sha256(content).hexdigest()
            target = root / "assets" / "adopted" / f"{checksum[:16]}{resolved.suffix.lower()}"
            if target.exists() and (not target.is_file() or target.read_bytes() != content):
                raise ValueError(f"adopted asset name conflicts with existing content: {target}")
            if not target.exists():
                assets[target] = content
            resolved = target
        asset_path = os.path.relpath(resolved, root).replace("\\", "/")
    return {
        key: value
        for key, value in {
            "id": record.get("id"),
            "kind": record.get("kind"),
            "representation": record.get("form") or record.get("representation"),
            "unit": record.get("unit"),
            "independent_variable": record.get("independent_variable"),
            "observable": record.get("observable"),
            "channel_scope": record.get("channel_scope", "product_resolved"),
            "parameters": record.get("parameters") or {},
            "asset": preserved_asset | {"path": asset_path} if asset_path else None,
            "validity": record.get("validity"),
            "uncertainty": record.get("uncertainty"),
            "source": record.get("source") or {},
            "provenance": record.get("provenance"),
            "source_declaration": record.get("source_declaration"),
            "method": record.get("method", "unknown"),
            "review_scope": record.get("review_scope"),
            "status": record.get("status", "imported"),
            "evidence_tier": record.get("evidence_tier")
            or record.get("tier")
            or record.get("quality"),
            "preferred": bool(record.get("preferred")),
            "reaction_order": record.get("reaction_order"),
            "parameter_units": record.get("parameter_units"),
            "reference_temperature_K": record.get("reference_temperature_K"),
        }.items()
        if value not in (None, {}, [])
    }


def _file(directory: Path, species_id: str) -> Path | None:
    """The registry file for a species, matched on its declared id.

    A filename is not the identity -- `Ar+` cannot be a filename on Windows and
    is stored as `Ar_p.yaml` -- so the direct guess is tried first and the
    directory is read only when it misses.
    """

    direct = directory / f"{species_id}.yaml"
    if direct.is_file() and direct.resolve().parent == directory.resolve():
        document = yamlio.load(direct.read_text(encoding="utf-8")) or {}
        if document.get("id") == species_id:
            return direct
    for path in sorted(directory.glob("*.yaml")):
        document = yamlio.load(path.read_text(encoding="utf-8")) or {}
        if document.get("id") == species_id:
            return path
    return None
