from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re
import shutil


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


def copy_to_cache(source: Path, cache_dir: Path, source_name: str) -> dict:
    source = Path(source)
    cache_dir = Path(cache_dir)
    digest = sha256_file(source)
    safe_source = safe_filename(source_name)
    safe_stem = safe_filename(source.stem)
    cached_path = cache_dir / safe_source / f"{safe_stem}_{digest[:12]}{source.suffix}"
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, cached_path)
    return {
        "original_path": str(source),
        "cached_path": str(cached_path),
        "sha256": digest,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_name": source_name,
    }

