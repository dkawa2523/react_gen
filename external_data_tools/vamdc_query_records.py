from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from external_data_tools.cache import sha256_file

Downloader = Callable[..., dict[str, Any]]


def build_tap_sync_url(endpoint: str, query: str) -> str:
    parts = urlsplit(endpoint)
    params = parse_qsl(parts.query, keep_blank_values=True)
    params.extend([("REQUEST", "doQuery"), ("LANG", "VSS2"), ("QUERY", query)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def collect_query_records(
    queries: list[Any],
    *,
    output_root: Path,
    dry_run: bool,
    downloader: Downloader,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = []
    unresolved = []
    for item in queries:
        record, error = _collect_one_query(
            item,
            output_root=output_root,
            dry_run=dry_run,
            downloader=downloader,
        )
        if record is not None:
            records.append(record)
        if error is not None:
            unresolved.append(error)
    return records, unresolved


def _collect_one_query(
    item: Any,
    *,
    output_root: Path,
    dry_run: bool,
    downloader: Downloader,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(item, dict):
        return None, {"reason": "query_record_not_mapping"}
    query_id = str(item.get("id") or "")
    endpoint = item.get("endpoint")
    query = item.get("query")
    output = item.get("output")
    if not query_id or not endpoint or not query or not output:
        return None, {"id": query_id or None, "reason": "missing_required_query_field"}
    output_path = resolve_output_path(output_root, str(output))
    url = build_tap_sync_url(str(endpoint), str(query))
    try:
        download = downloader(url, output_path, dry_run=dry_run)
        _add_sha256_if_needed(download, output_path, dry_run)
        return _query_record(item, url, output_path, download, dry_run), None
    except Exception as exc:
        return None, _download_error(item, query_id, exc)


def resolve_output_path(output_root: Path, output: str) -> Path:
    root = Path(output_root).resolve()
    relative_output = Path(output)
    if relative_output.is_absolute():
        raise ValueError(f"VAMDC output must be relative: {output}")
    output_path = (root / relative_output).resolve()
    try:
        output_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"VAMDC output escapes output root: {output}") from exc
    return output_path


def _add_sha256_if_needed(download: dict[str, Any], output_path: Path, dry_run: bool) -> None:
    if not dry_run and "sha256" not in download and output_path.exists():
        download["sha256"] = sha256_file(output_path)


def _query_record(
    item: dict[str, Any],
    url: str,
    output_path: Path,
    download: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    record = {
        "id": item["id"],
        "endpoint": item["endpoint"],
        "query": item["query"],
        "url": url,
        "output_path": str(output_path),
        "dry_run": bool(dry_run),
        "recorded_at": datetime.now(UTC).isoformat(),
        "notes": list(item.get("notes", [])) if isinstance(item.get("notes", []), list) else [],
    }
    for key in ("sha256", "downloaded_at", "planned_at", "user_agent", "timeout"):
        if key in download:
            record[key] = download[key]
    if not dry_run:
        record["xml_detected"] = _looks_like_xml(output_path)
    return record


def _download_error(item: dict[str, Any], query_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "id": query_id,
        "endpoint": item.get("endpoint"),
        "query": item.get("query"),
        "output": str(item.get("output")),
        "reason": "download_failed",
        "message": str(exc),
    }


def _looks_like_xml(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as handle:
        return handle.read(256).lstrip().startswith(b"<")
