"""Fetch NIST SRD 107 total-ionization tables into a site-local registry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from external_data_tools.cache import safe_filename, sha256_file
from external_data_tools.http_client import download_url
from external_data_tools.nist_beb import NIST_SRD107_DOI, parse_nist_beb_ascii, target_for
from external_data_tools.registry_admin_io import write_numeric_csv, write_report, write_yaml
from external_data_tools.registry_records import (
    append_dataset,
    channel_records,
    exact_channel_matches,
    validate_redistribution_status,
)


def import_nist_beb(
    species_ids: list[str],
    *,
    registry_root: str | Path,
    report_dir: str | Path,
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    """Download and register selected BEB total-ionization tables."""

    validate_redistribution_status(redistribution_status)
    root = Path(registry_root)
    reports = Path(report_dir)
    if not (root / "reactions").is_dir():
        raise FileNotFoundError(f"prepared registry reactions not found: {root / 'reactions'}")

    results = []
    for species_id in dict.fromkeys(species_ids):
        target = target_for(species_id)
        raw_path = reports / "raw" / f"nist_srd107_{safe_filename(species_id)}.txt"
        download = download_url(target.download_url, raw_path)
        results.append(
            import_nist_beb_file(
                raw_path,
                species_id=species_id,
                registry_root=root,
                redistribution_status=redistribution_status,
                download_record=download,
            )
        )

    report = {
        "schema_version": 1,
        "kind": "nist_srd107_beb_total_ionization",
        "registry_root": str(root),
        "results": results,
        "summary": {
            "n_requested": len(dict.fromkeys(species_ids)),
            "n_applied": sum(item["applied"] for item in results),
            "n_review": sum(bool(item["review_reason"]) for item in results),
        },
    }
    write_report(reports, "nist_beb_import.yaml", report)
    return report


def import_nist_beb_file(
    raw_path: str | Path,
    *,
    species_id: str,
    registry_root: str | Path,
    redistribution_status: str = "site-local",
    download_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one downloaded table and attach it to its related channel."""

    validate_redistribution_status(redistribution_status)
    source = Path(raw_path)
    root = Path(registry_root)
    target = target_for(species_id)
    rows = parse_nist_beb_ascii(source.read_text(encoding="utf-8"))
    digest = sha256_file(source)
    stem = f"nist_srd107_{safe_filename(species_id)}_total_ionization_{digest[:12]}"
    relative_path = f"assets/cross_sections/{stem}.csv"
    asset_path = root / relative_path
    write_numeric_csv(asset_path, rows, ("energy_eV", "cross_section_m2"))
    asset_digest = sha256_file(asset_path)
    write_yaml(
        asset_path.with_suffix(".metadata.yaml"),
        _metadata(
            target.download_url,
            source,
            rows,
            raw_digest=digest,
            asset_digest=asset_digest,
            redistribution_status=redistribution_status,
            download_record=download_record,
        ),
    )

    matches = exact_channel_matches(
        {"reaction_id": target.reaction_id},
        channel_records(root),
    )
    review_reason = None
    applied = False
    if len(matches) == 1:
        applied = append_dataset(
            matches[0],
            _dataset(
                target.reaction_id,
                species_id,
                relative_path,
                rows,
                raw_digest=digest,
                asset_digest=asset_digest,
            ),
        )
    else:
        review_reason = "no_exact_mapping" if not matches else "ambiguous_mapping"

    return {
        "species_id": species_id,
        "reaction_id": target.reaction_id,
        "raw_sha256": digest,
        "asset_sha256": asset_digest,
        "asset_path": relative_path,
        "row_count": len(rows),
        "applied": int(applied),
        "review_reason": review_reason,
    }


def _dataset(
    reaction_id: str,
    species_id: str,
    relative_path: str,
    rows: list[dict[str, float]],
    *,
    raw_digest: str,
    asset_digest: str,
) -> dict[str, Any]:
    return {
        "id": (f"ds_{safe_filename(reaction_id)}_nist_srd107_total_ionization_{raw_digest[:12]}"),
        "kind": "total_ionization_cross_section",
        "representation": "table",
        "independent_variable": "energy",
        "dependent_variable": "total_ionization_cross_section",
        "unit": "m2",
        "parameters": {
            "target": species_id,
            "model": "BEB",
            "scope": "pair_total_ionization",
            "product_branching": "unresolved",
        },
        "asset": {
            "path": relative_path,
            "format": "csv_energy_eV_cross_section_m2",
            "checksum": asset_digest,
        },
        "validity": {
            "minimum": rows[0]["energy_eV"],
            "maximum": rows[-1]["energy_eV"],
            "unit": "eV",
        },
        "source": {
            "source_type": "nist_srd107",
            "source_id": "NIST-SRD-107",
            "citation": "NIST Electron-Impact Cross Section Database, Version 3.0",
            "url": NIST_SRD107_DOI,
            "accessed_date": datetime.now(UTC).date().isoformat(),
            "license": "NIST SRD; site-local use pending redistribution review",
            "raw_sha256": raw_digest,
        },
        "status": "imported",
        "preferred": False,
        "notes": [
            "Total ionization only; do not use as a product-resolved channel cross section.",
            "BEB model data; product branching must come from a separate measurement.",
        ],
    }


def _metadata(
    url: str,
    raw_path: Path,
    rows: list[dict[str, float]],
    *,
    raw_digest: str,
    asset_digest: str,
    redistribution_status: str,
    download_record: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source_type": "nist_srd107",
        "database": "NIST Electron-Impact Cross Section Database",
        "database_version": "3.0",
        "doi": NIST_SRD107_DOI,
        "download_url": url,
        "raw_file": str(raw_path),
        "raw_sha256": raw_digest,
        "asset_sha256": asset_digest,
        "downloaded_at": (download_record or {}).get("downloaded_at"),
        "units": {"energy": "eV", "cross_section": "m2"},
        "source_units": {"energy": "eV", "cross_section": "A2"},
        "conversion": "1 A2 = 1e-20 m2",
        "row_count": len(rows),
        "energy_min_eV": rows[0]["energy_eV"],
        "energy_max_eV": rows[-1]["energy_eV"],
        "model": "Binary-Encounter-Bethe total ionization",
        "redistribution_status": redistribution_status,
        "license_note": (
            "NIST Standard Reference Data; keep site-local unless redistribution is approved."
        ),
    }
