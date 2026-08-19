"""Write what a converter produced as a snapshot `rgen ingest` can read.

Tables are written as two-column CSV assets next to the snapshot; the snapshot
references them by path. Nothing here decides whether the data is correct — that
is the reviewer's job, and `rgen ingest` puts anything ambiguous in a queue.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


def write(
    outdir: Path,
    kind: str,
    source: dict[str, str],
    records: list[dict],
) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "snapshot.yaml"
    path.write_text(
        yaml.safe_dump(
            {"kind": kind, "source": source, "records": records},
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def write_table(outdir: Path, name: str, rows: list[tuple[float, float]], header: str) -> str:
    """Write a two-column table and return its path relative to ``outdir``."""

    assets = outdir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    path = assets / f"{name}.csv"
    body = "\n".join(f"{x:.6e},{y:.6e}" for x, y in rows)
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return f"assets/{path.name}"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
