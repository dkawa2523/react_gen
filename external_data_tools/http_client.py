from __future__ import annotations

import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import sha256_file
from .config import load_config


def download_url(
    url: str,
    output_path: Path,
    *,
    user_agent: str | None = None,
    timeout: float | None = None,
    sleep_seconds: float | None = None,
    dry_run: bool = False,
) -> dict:
    url = _validated_http_url(url)
    config = load_config()
    resolved_user_agent = user_agent or config.user_agent
    resolved_timeout = config.http_timeout if timeout is None else timeout
    resolved_sleep = config.http_sleep_seconds if sleep_seconds is None else sleep_seconds
    output_path = Path(output_path)

    record = {
        "url": url,
        "output_path": str(output_path),
        "user_agent": resolved_user_agent,
        "timeout": resolved_timeout,
        "sleep_seconds": resolved_sleep,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        record["planned_at"] = _utc_now()
        return record

    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": resolved_user_agent})
    with _open_http_request(request, resolved_timeout) as response:
        output_path.write_bytes(response.read())

    record.update(
        {
            "sha256": sha256_file(output_path),
            "downloaded_at": _utc_now(),
            "dry_run": False,
        }
    )
    return record


def download_many(manifest: dict, output_root: Path, dry_run: bool = False) -> dict:
    downloads = manifest.get("downloads", [])
    if not isinstance(downloads, list):
        raise ValueError("download manifest must contain a downloads list")

    config = load_config()
    records = []
    failed = 0
    successes = 0

    for index, item in enumerate(downloads):
        if not isinstance(item, dict):
            raise ValueError("download entries must be mappings")

        url = item["url"]
        output_path = _resolve_output_path(output_root, item["output"])
        try:
            record = download_url(
                url,
                output_path,
                user_agent=config.user_agent,
                timeout=config.http_timeout,
                sleep_seconds=config.http_sleep_seconds,
                dry_run=dry_run,
            )
            successes += 1
        except Exception as exc:  # pragma: no cover - exact urllib errors vary by platform
            failed += 1
            record = {
                "url": url,
                "output_path": str(output_path),
                "dry_run": bool(dry_run),
                "error": str(exc),
            }

        _attach_manifest_metadata(record, item)
        records.append(record)

        if not dry_run and index < len(downloads) - 1:
            time.sleep(config.http_sleep_seconds)

    return {
        "schema_version": 1,
        "dry_run": bool(dry_run),
        "summary": {
            "total": len(downloads),
            "planned": successes if dry_run else 0,
            "downloaded": 0 if dry_run else successes,
            "failed": failed,
        },
        "records": records,
    }


def _attach_manifest_metadata(record: dict, item: dict) -> None:
    for key in ("id", "source_name", "license_note", "citation"):
        if key in item:
            record[key] = item[key]


def _resolve_output_path(output_root: Path, output: str) -> Path:
    output_root = Path(output_root).resolve()
    relative_output = Path(output)
    if relative_output.is_absolute():
        raise ValueError(f"download output must be relative: {output}")

    resolved = (output_root / relative_output).resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"download output escapes output root: {output}") from exc
    return resolved


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validated_http_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    has_credentials = parsed.username is not None or parsed.password is not None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or has_credentials:
        raise ValueError("download URL must be an HTTP(S) URL with a host and no credentials")
    return url


def _open_http_request(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener().open(request, timeout=timeout)
