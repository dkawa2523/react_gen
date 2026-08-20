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

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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


def adopt(overlay: dict, registry_root: Path, dry_run: bool = False) -> Adoption:
    """Write every overlay value the registry does not already answer for."""

    report = Adoption()
    directory = Path(registry_root) / "species"
    properties = overlay.get("properties") or {}
    thermo = overlay.get("thermo") or {}

    for species_id in sorted(set(properties) | set(thermo)):
        path = _file(directory, species_id)
        if path is None:
            report.unplaced.append(species_id)
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        touched = _merge(
            document, properties.get(species_id) or {}, thermo.get(species_id), report, species_id
        )
        if touched and not dry_run:
            path.write_text(
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
    return report


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
