from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from .cache import sha256_file
from .http_client import download_url


def build_tap_sync_url(endpoint: str, query: str) -> str:
    parts = urlsplit(endpoint)
    params = parse_qsl(parts.query, keep_blank_values=True)
    params.extend(
        [
            ("REQUEST", "doQuery"),
            ("LANG", "VSS2"),
            ("QUERY", query),
        ]
    )
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(params),
            parts.fragment,
        )
    )


def run_vamdc_queries(manifest_path: Path, *, output_root: Path, dry_run: bool = False) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    output_root = Path(output_root)
    payload = _read_yaml(manifest_path)
    queries = payload.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("VAMDC manifest must contain a queries list")

    records = []
    unresolved = []
    for item in queries:
        if not isinstance(item, dict):
            unresolved.append({"reason": "query_record_not_mapping"})
            continue

        query_id = str(item.get("id") or "")
        endpoint = item.get("endpoint")
        query = item.get("query")
        output = item.get("output")
        if not query_id or not endpoint or not query or not output:
            unresolved.append(
                {
                    "id": query_id or None,
                    "reason": "missing_required_query_field",
                }
            )
            continue

        output_path = _resolve_output_path(output_root, str(output))
        url = build_tap_sync_url(str(endpoint), str(query))
        try:
            download_record = download_url(url, output_path, dry_run=dry_run)
            if not dry_run and "sha256" not in download_record and output_path.exists():
                download_record["sha256"] = sha256_file(output_path)
            records.append(
                _query_record(
                    item,
                    url=url,
                    output_path=output_path,
                    download_record=download_record,
                    dry_run=dry_run,
                )
            )
        except Exception as exc:
            unresolved.append(
                {
                    "id": query_id,
                    "endpoint": endpoint,
                    "query": query,
                    "output": str(output),
                    "reason": "download_failed",
                    "message": str(exc),
                }
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


def _query_record(
    item: dict[str, Any],
    *,
    url: str,
    output_path: Path,
    download_record: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    record = {
        "id": item["id"],
        "endpoint": item["endpoint"],
        "query": item["query"],
        "url": url,
        "output_path": str(output_path),
        "dry_run": bool(dry_run),
        "recorded_at": _utc_now(),
        "notes": list(item.get("notes", [])) if isinstance(item.get("notes", []), list) else [],
    }
    for key in ("sha256", "downloaded_at", "planned_at", "user_agent", "timeout"):
        if key in download_record:
            record[key] = download_record[key]
    if not dry_run:
        record["xml_detected"] = _looks_like_xml(output_path)
    return record


def _resolve_output_path(output_root: Path, output: str) -> Path:
    output_root = Path(output_root).resolve()
    relative_output = Path(output)
    if relative_output.is_absolute():
        raise ValueError(f"VAMDC output must be relative: {output}")
    output_path = (output_root / relative_output).resolve()
    try:
        output_path.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"VAMDC output escapes output root: {output}") from exc
    return output_path


def _looks_like_xml(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as handle:
        prefix = handle.read(256).lstrip()
    return prefix.startswith(b"<")


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
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
