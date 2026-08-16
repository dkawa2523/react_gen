"""Import evaluated O2 process cross sections into a prepared registry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from external_data_tools.cache import sha256_file
from external_data_tools.http_client import download_url
from external_data_tools.oxygen_cross_sections import (
    O2_DATASET_DOI,
    O2_PAPER_DOI,
    O2_WORKBOOK_URL,
    TARGETS,
    OxygenCrossSectionTarget,
    parse_oxygen_cross_section,
)
from external_data_tools.registry_admin_io import write_numeric_csv, write_report, write_yaml
from external_data_tools.registry_records import (
    append_dataset,
    channel_records,
    exact_channel_matches,
    validate_redistribution_status,
)


def import_oxygen_cross_sections(
    *,
    registry_root: str | Path,
    report_dir: str | Path,
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    """Download the official workbook once and import its reviewed process tables."""

    validate_redistribution_status(redistribution_status)
    root = Path(registry_root)
    reports = Path(report_dir)
    if not (root / "reactions").is_dir():
        raise FileNotFoundError(f"prepared registry reactions not found: {root / 'reactions'}")

    raw_path = reports / "raw" / "o2_evaluated_cross_sections.xlsx"
    download = download_url(O2_WORKBOOK_URL, raw_path)
    report = import_oxygen_cross_section_file(
        raw_path,
        registry_root=root,
        redistribution_status=redistribution_status,
        download_record=download,
    )
    write_report(reports, "oxygen_cross_section_import.yaml", report)
    return report


def import_oxygen_cross_section_file(
    workbook_path: str | Path,
    *,
    registry_root: str | Path,
    redistribution_status: str = "site-local",
    download_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize every reviewed O2 table and attach exact reaction-ID matches."""

    validate_redistribution_status(redistribution_status)
    source = Path(workbook_path)
    root = Path(registry_root)
    raw_digest = sha256_file(source)
    channels = channel_records(root)
    results = [
        _import_target(
            source,
            target,
            root=root,
            channels=channels,
            raw_digest=raw_digest,
            redistribution_status=redistribution_status,
            download_record=download_record,
        )
        for target in TARGETS
    ]
    return {
        "schema_version": 1,
        "kind": "evaluated_o2_process_cross_sections",
        "input_file": str(source),
        "raw_sha256": raw_digest,
        "registry_root": str(root),
        "results": results,
        "summary": {
            "n_requested": len(TARGETS),
            "n_applied": sum(item["applied"] for item in results),
            "n_review": sum(bool(item["review_reason"]) for item in results),
        },
    }


def _import_target(
    source: Path,
    target: OxygenCrossSectionTarget,
    *,
    root: Path,
    channels: list[dict[str, Any]],
    raw_digest: str,
    redistribution_status: str,
    download_record: dict[str, Any] | None,
) -> dict[str, Any]:
    rows = parse_oxygen_cross_section(source, target)
    stem = f"song_2026_o2_{target.id}_{raw_digest[:12]}"
    relative_path = f"assets/cross_sections/{stem}.csv"
    asset_path = root / relative_path
    fields = tuple(rows[0])
    write_numeric_csv(asset_path, rows, fields)
    asset_digest = sha256_file(asset_path)
    write_yaml(
        asset_path.with_suffix(".metadata.yaml"),
        _metadata(
            source,
            target,
            rows,
            raw_digest=raw_digest,
            asset_digest=asset_digest,
            redistribution_status=redistribution_status,
            download_record=download_record,
        ),
    )

    matches = exact_channel_matches({"reaction_id": target.reaction_id}, channels)
    review_reason = None
    applied = False
    if len(matches) == 1:
        applied = append_dataset(
            matches[0],
            _dataset(target, relative_path, rows, raw_digest, asset_digest),
        )
    else:
        review_reason = "no_exact_mapping" if not matches else "ambiguous_mapping"
    return {
        "target_id": target.id,
        "reaction_id": target.reaction_id,
        "asset_path": relative_path,
        "asset_sha256": asset_digest,
        "row_count": len(rows),
        "applied": int(applied),
        "review_reason": review_reason,
    }


def _dataset(
    target: OxygenCrossSectionTarget,
    relative_path: str,
    rows: list[dict[str, float]],
    raw_digest: str,
    asset_digest: str,
) -> dict[str, Any]:
    return {
        "id": f"ds_{target.reaction_id}_song_2026_{target.id}_{raw_digest[:12]}",
        "kind": "cross_section",
        "representation": "table",
        "independent_variable": "energy",
        "dependent_variable": target.quantity,
        "unit": "m2",
        "parameters": {"target": "O2", "process": target.id},
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
            "source_type": "evaluated_literature_dataset",
            "citation": (
                "M.-Y. Song et al., Cross Sections for Electron Collisions with Molecular "
                "and Atomic Oxygen, JPCRD (2026)"
            ),
            "url": O2_DATASET_DOI,
            "paper_url": O2_PAPER_DOI,
            "accessed_date": datetime.now(UTC).date().isoformat(),
            "license": "CC BY-NC 4.0",
            "raw_sha256": raw_digest,
        },
        "status": "imported",
        "preferred": target.preferred,
        "notes": [
            "Evaluated process-resolved data; no extrapolation outside the tabulated range.",
            "The source unit 10^-16 cm2 was converted to m2 by multiplying by 1e-20.",
        ],
    }


def _metadata(
    source: Path,
    target: OxygenCrossSectionTarget,
    rows: list[dict[str, float]],
    *,
    raw_digest: str,
    asset_digest: str,
    redistribution_status: str,
    download_record: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source_type": "evaluated_literature_dataset",
        "paper_doi": O2_PAPER_DOI,
        "dataset_doi": O2_DATASET_DOI,
        "download_url": O2_WORKBOOK_URL,
        "raw_file": str(source),
        "raw_sha256": raw_digest,
        "asset_sha256": asset_digest,
        "downloaded_at": (download_record or {}).get("downloaded_at"),
        "license": "CC BY-NC 4.0",
        "redistribution_status": redistribution_status,
        "worksheet": target.sheet,
        "quantity": target.quantity,
        "source_units": {"energy": "eV", "cross_section": "10^-16 cm2"},
        "units": {"energy": "eV", "cross_section": "m2"},
        "conversion": "1e-16 cm2 = 1e-20 m2",
        "row_count": len(rows),
        "energy_min_eV": rows[0]["energy_eV"],
        "energy_max_eV": rows[-1]["energy_eV"],
    }
