from __future__ import annotations

from pathlib import Path
import hashlib
import re


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_filename(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text))
    safe = re.sub(r"_+", "_", safe).strip("._-")
    return safe or "unknown"
