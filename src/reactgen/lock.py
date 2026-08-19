"""Pin the exact data a run used, so the run can be repeated.

Acquisition may be automated and may reach the network; generation may not.
The lock file is the seam between them: whatever a tool fetched and a reviewer
accepted is recorded here by id and checksum, and a later ``generate`` can
prove it read the same bytes.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from reactgen.case import Case
from reactgen.model import Network
from reactgen.registry import Registry


def build(case: Case, network: Network, registry: Registry) -> dict:
    entries = []
    for reaction in network.reactions:
        for dataset in reaction.datasets:
            if not dataset.usable:
                continue
            path = registry.asset_path(dataset.asset)
            entries.append(
                {
                    "dataset_id": dataset.id,
                    "reaction_id": reaction.id,
                    "kind": dataset.kind,
                    "form": dataset.form,
                    "asset": dataset.asset,
                    "sha256": _digest(path),
                    "source": dataset.source.get("source_id") or dataset.source.get("source_type"),
                    "status": dataset.status,
                }
            )
    return {
        "case": case.name,
        "gases": list(case.gases),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "registry": str(registry.root),
        "registry_digest": digest_registry(registry),
        "datasets": sorted(entries, key=lambda item: item["dataset_id"]),
    }


def mechanism_id(case: Case, registry: Registry) -> str:
    """Stable fingerprint to quote alongside any simulation run."""

    gases = "-".join(sorted(case.gases))
    return f"{case.name}.{gases}.{digest_registry(registry)[:8]}"


def digest_registry(registry: Registry) -> str:
    """Fingerprint of every registry file, so drift is detectable."""

    digest = hashlib.sha256()
    for path in sorted(registry.root.rglob("*.yaml")):
        digest.update(path.relative_to(registry.root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def write(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _digest(path: Path | None) -> str | None:
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
