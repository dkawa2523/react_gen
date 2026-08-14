from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .http_client import download_url
from .vamdc_query_records import (
    build_tap_sync_url as build_tap_sync_url,
)
from .vamdc_query_records import (
    collect_query_records,
)


def run_vamdc_queries(
    manifest_path: Path,
    *,
    output_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    output_root = Path(output_root)
    payload = _read_yaml(manifest_path)
    queries = payload.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("VAMDC manifest must contain a queries list")

    records, unresolved = collect_query_records(
        queries,
        output_root=output_root,
        dry_run=dry_run,
        downloader=download_url,
    )

    result = {
        "schema_version": 1,
        "source": {
            "database": "VAMDC",
            "access_mode": "tap_sync",
            "generated_at": _utc_now(),
        },
        "dry_run": bool(dry_run),
        "records": records,
        "unresolved": unresolved,
        "summary": {
            "total_queries": len(queries),
            "planned": len(records) if dry_run else 0,
            "downloaded": 0 if dry_run else len(records),
            "unresolved": len(unresolved),
        },
    }
    _write_manifest(output_root / "manifest.yaml", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run explicit user-provided VAMDC TAP sync queries and cache raw results."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("external_data/raw/vamdc"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = run_vamdc_queries(args.manifest, output_root=args.output_root, dry_run=args.dry_run)
    print(
        "vamdc query: "
        f"planned={result['summary']['planned']} "
        f"downloaded={result['summary']['downloaded']} "
        f"unresolved={result['summary']['unresolved']} "
        f"manifest={args.output_root / 'manifest.yaml'}"
    )
    return 1 if result["summary"]["unresolved"] else 0


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("VAMDC manifest must be a YAML mapping")
    return payload


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
