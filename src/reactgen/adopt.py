"""Fold a reviewed overlay into the registry files it belongs to.

An overlay is a run-time merge: pass `--overlay` and the values appear, omit it
and they are gone. That is right while an import is under review and wrong once
it is settled, because every later run then has to remember the flag, and a
registry that answers differently depending on an argument is not a registry.

This writes the overlay's values into `registry/species/*.yaml`, keeping the
source line each one arrived with, so a reader can still see that a
polarizability came from `mendeleev` and a thermodynamic fit from `cantera`.

A value already in the registry is never replaced. Curation outranks
acquisition: someone read that number out of a paper and wrote it down, and an
automatic table has no standing to overrule them. Whatever is skipped for that
reason is reported rather than dropped silently.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reactgen.evidence import registry_reaction_candidate, registry_state_candidate
from reactgen.registry import Registry


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
    """Write every overlay value the registry does not already answer for."""

    report = Adoption()
    root = Path(registry_root)
    overlay_path = Path(overlay)
    overlay_data: dict = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    registry = Registry.load(root)
    directory = root / "species"
    state_targets = {
        registry_state_candidate(record).id: record.id for record in registry.species.values()
    }
    properties = overlay_data.get("properties") or {}
    thermo = overlay_data.get("thermo") or {}

    for candidate_id in sorted(set(properties) | set(thermo)):
        species_id = state_targets.get(candidate_id, candidate_id)
        path = _file(directory, species_id)
        if path is None:
            report.unplaced.append(candidate_id)
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        touched = _merge(
            document,
            properties.get(candidate_id) or {},
            thermo.get(candidate_id),
            report,
            candidate_id,
        )
        if touched and not dry_run:
            path.write_text(
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
    _adopt_datasets(
        overlay_data.get("datasets") or {},
        root,
        overlay_path.parent,
        registry,
        report,
        dry_run,
    )
    return report


def _adopt_datasets(
    datasets: dict,
    root: Path,
    overlay_base: Path,
    registry: Registry,
    report: Adoption,
    dry_run: bool,
) -> None:
    targets = {}
    for reaction in (reaction for group in registry.channels.values() for reaction in group):
        candidate = registry_reaction_candidate(reaction, registry.species)
        if candidate is not None:
            targets[candidate.id] = reaction.id
    locations = _reaction_locations(root / "reactions")
    for candidate_id, records in sorted(datasets.items()):
        registry_id = targets.get(candidate_id)
        location = locations.get(registry_id or "")
        if location is None:
            report.unplaced.append(candidate_id)
            continue
        path, index = location
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        channel = document["channels"][index]
        held = channel.setdefault("data", {}).setdefault("datasets", [])
        existing = {item.get("id") for item in held}
        additions = [
            _registry_dataset(item, overlay_base, root, dry_run)
            for item in records
            if item.get("id") not in existing
        ]
        kept = [str(item.get("id")) for item in records if item.get("id") in existing]
        if additions:
            held.extend(additions)
            written = report.written.setdefault(candidate_id, [])
            written.extend(str(item["id"]) for item in additions)
            if not dry_run:
                path.write_text(
                    yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
        if kept:
            report.kept.setdefault(candidate_id, []).extend(kept)


def _reaction_locations(directory: Path) -> dict[str, tuple[Path, int]]:
    found = {}
    for path in sorted(directory.glob("*/*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for index, channel in enumerate(document.get("channels") or []):
            found[str(channel.get("id"))] = (path, index)
    return found


def _registry_dataset(
    record: dict,
    overlay_base: Path,
    registry_root: Path,
    dry_run: bool,
) -> dict:
    asset = record.get("asset")
    asset_path = asset.get("path") if isinstance(asset, dict) else asset
    if asset_path:
        resolved = Path(str(asset_path))
        if not resolved.is_absolute():
            resolved = (overlay_base / resolved).resolve()
        if not resolved.is_file():
            raise ValueError(f"overlay asset not found: {resolved}")
        root = registry_root.resolve()
        if root not in resolved.parents:
            checksum = hashlib.sha256(resolved.read_bytes()).hexdigest()
            target = root / "assets" / "adopted" / f"{checksum[:16]}{resolved.suffix.lower()}"
            if not dry_run and not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resolved, target)
            resolved = target
        asset_path = os.path.relpath(resolved, root).replace("\\", "/")
    return {
        key: value
        for key, value in {
            "id": record.get("id"),
            "kind": record.get("kind"),
            "representation": record.get("form"),
            "unit": record.get("unit"),
            "independent_variable": record.get("independent_variable"),
            "observable": record.get("observable"),
            "channel_scope": record.get("channel_scope", "product_resolved"),
            "parameters": record.get("parameters") or {},
            "asset": {"path": asset_path} if asset_path else None,
            "validity": record.get("validity"),
            "uncertainty": record.get("uncertainty"),
            "source": record.get("source") or {},
            "status": record.get("status", "imported"),
            "preferred": bool(record.get("preferred")),
        }.items()
        if value not in (None, {}, [])
    }


def _merge(
    document: dict, values: dict, fit: dict | None, report: Adoption, species_id: str
) -> bool:
    held = document.setdefault("properties", {})
    touched = False
    for name, entry in sorted(values.items()):
        if entry.get("value") is None:
            continue
        if (held.get(name) or {}).get("value") is not None:
            report.kept.setdefault(species_id, []).append(name)
            continue
        held[name] = {k: v for k, v in entry.items() if v is not None}
        report.written.setdefault(species_id, []).append(name)
        touched = True
    if fit is not None:
        if document.get("thermo"):
            report.kept.setdefault(species_id, []).append("thermo")
        else:
            document["thermo"] = dict(fit)
            report.written.setdefault(species_id, []).append("thermo")
            touched = True
    return touched


def _file(directory: Path, species_id: str) -> Path | None:
    """The registry file for a species, matched on its declared id.

    A filename is not the identity -- `Ar+` cannot be a filename on Windows and
    is stored as `Ar_p.yaml` -- so the direct guess is tried first and the
    directory is read only when it misses.
    """

    direct = directory / f"{species_id}.yaml"
    if direct.is_file():
        return direct
    for path in sorted(directory.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if document.get("id") == species_id:
            return path
    return None
