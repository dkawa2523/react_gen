from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .http_client import download_many
from .manifest import append_record


DEFAULT_RECORD_MANIFEST = Path("external_data") / "manifests" / "download_manifest.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download explicit user-supplied URLs from a YAML manifest."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("external_data") / "raw")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = args.manifest
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("download manifest must be a YAML mapping")

    report = download_many(payload, args.output_root, dry_run=args.dry_run)
    report_path = manifest_path.with_name(f"{manifest_path.stem}.download_report.yaml")
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    for record in report.get("records", []):
        if "error" not in record:
            append_record(DEFAULT_RECORD_MANIFEST, record)

    summary = report["summary"]
    print(
        "download manifest: "
        f"total={summary['total']} "
        f"planned={summary['planned']} "
        f"downloaded={summary['downloaded']} "
        f"failed={summary['failed']} "
        f"report={report_path}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
