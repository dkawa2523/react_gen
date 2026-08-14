"""Import local LXCat exports and attach exact channel matches."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from external_data_tools.cache import safe_filename, sha256_file
from external_data_tools.lxcat_raw_import import parse_lxcat_raw_file
from external_data_tools.registry_admin_io import (
    duplicate_report,
    find_import,
    record_import,
    write_numeric_csv,
    write_report,
    write_yaml,
)
from external_data_tools.registry_records import (
    append_dataset,
    channel_records,
    exact_channel_matches,
    validate_redistribution_status,
)


def import_lxcat_raw(
    raw_file: str | Path,
    *,
    registry_root: str | Path,
    report_dir: str | Path | None = None,
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    """Import blocks and attach datasets only when one channel matches exactly."""

    validate_redistribution_status(redistribution_status)
    source = Path(raw_file)
    root = Path(registry_root)
    digest = sha256_file(source)
    duplicate = find_import(root, "lxcat_raw", digest)
    if duplicate is not None:
        return duplicate_report("lxcat_raw", source, digest, duplicate)

    blocks = _split_lxcat_blocks(source)
    channels = channel_records(root)
    assets: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    temporary = (Path(report_dir) if report_dir else root) / ".lxcat_blocks"
    try:
        for index, block in enumerate(blocks, start=1):
            _import_block(
                block,
                index,
                source,
                root,
                temporary,
                digest,
                redistribution_status,
                channels,
                assets,
                applied,
                review,
            )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    report = {
        "schema_version": 1,
        "kind": "lxcat_raw",
        "input_file": str(source),
        "sha256": digest,
        "assets": assets,
        "applied": applied,
        "review": review,
        "duplicate": False,
        "summary": {
            "n_blocks": len(blocks),
            "n_assets": len(assets),
            "n_applied": len(applied),
            "n_review": len(review),
        },
    }
    record_import(root, report)
    write_report(report_dir, "lxcat_raw_import.yaml", report)
    return report


def _import_block(
    block: str,
    index: int,
    source: Path,
    registry_root: Path,
    temporary: Path,
    digest: str,
    redistribution_status: str,
    channels: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    applied: list[dict[str, Any]],
    review: list[dict[str, Any]],
) -> None:
    temporary_path = temporary / f"{digest[:12]}_{index:03d}.txt"
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.write_text(block, encoding="utf-8")
    try:
        parsed = parse_lxcat_raw_file(temporary_path)
    except ValueError as exc:
        review.append({"block": index, "reason": "unsupported_block", "message": str(exc)})
        return

    matches = exact_channel_matches(
        {"reaction_id": parsed.reaction_id, "equation": parsed.process_label_original},
        channels,
    )
    relative_path, metadata = _write_asset(
        parsed,
        block,
        index,
        source,
        registry_root,
        digest,
        redistribution_status,
    )
    assets.append({"path": relative_path, "metadata": metadata})
    if len(matches) != 1:
        review.append(
            {
                "block": index,
                "asset_path": relative_path,
                "reason": "ambiguous_mapping" if len(matches) > 1 else "no_exact_mapping",
                "candidate_reaction_ids": [match["reaction_id"] for match in matches],
            }
        )
        return
    match = matches[0]
    dataset = _cross_section_dataset(
        match["reaction_id"],
        parsed,
        relative_path,
        metadata,
        digest,
        index,
        redistribution_status,
    )
    if append_dataset(match, dataset):
        applied.append({"reaction_id": match["reaction_id"], "dataset_id": dataset["id"]})


def _write_asset(
    parsed: Any,
    block: str,
    index: int,
    source: Path,
    registry_root: Path,
    digest: str,
    redistribution_status: str,
) -> tuple[str, dict[str, Any]]:
    relative_path = f"assets/cross_sections/lxcat_{digest[:12]}_{index:03d}.csv"
    asset_path = registry_root / relative_path
    write_numeric_csv(asset_path, parsed.rows, ("energy_eV", "cross_section_m2"))
    header = _source_header(block)
    metadata = {
        "original_file": str(source),
        "sha256": digest,
        "block_index": index,
        "source_header": header,
        "database": _header_value(header, "database"),
        "contributor": _header_value(header, "contributor"),
        "citation": _header_value(header, "citation"),
        "process_label_original": parsed.process_label_original,
        "reaction_id": parsed.reaction_id,
        "units": {"energy": "eV", "cross_section": "m2"},
        "redistribution_status": redistribution_status,
        "license_note": "Follow the original LXCat database citation and redistribution terms.",
    }
    write_yaml(asset_path.with_suffix(".metadata.yaml"), metadata)
    return relative_path, metadata


def _cross_section_dataset(
    reaction_id: str,
    parsed: Any,
    relative_path: str,
    metadata: dict[str, Any],
    digest: str,
    index: int,
    redistribution_status: str,
) -> dict[str, Any]:
    return {
        "id": f"ds_{safe_filename(reaction_id)}_xs_{digest[:12]}_{index:03d}",
        "kind": "cross_section",
        "representation": "table",
        "independent_variable": "energy",
        "dependent_variable": "cross_section",
        "unit": "m2",
        "path": relative_path,
        "validity": {
            "minimum": parsed.rows[0]["energy_eV"],
            "maximum": parsed.rows[-1]["energy_eV"],
            "unit": "eV",
        },
        "source_record": {
            "source_type": "lxcat_local_export",
            "sha256": digest,
            "database": metadata["database"],
            "contributor": metadata["contributor"],
            "citation": metadata["citation"],
            "redistribution_status": redistribution_status,
        },
        "status": "imported",
    }


def _split_lxcat_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) >= 5 and set(stripped) <= {"-", "="}:
            if blocks[-1]:
                blocks.append([])
        else:
            blocks[-1].append(line)
    common_header = blocks[0] if blocks and not _has_numeric_rows(blocks[0]) else []
    result = [
        "\n".join([*common_header, *block]).strip() + "\n"
        for block in blocks
        if _has_numeric_rows(block)
    ]
    return result or [text]


def _has_numeric_rows(lines: list[str]) -> bool:
    numeric_rows = 0
    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            float(parts[0])
            float(parts[1])
            numeric_rows += 1
        except ValueError:
            continue
    return numeric_rows >= 2


def _source_header(block: str) -> list[str]:
    return [
        line.rstrip() for line in block.splitlines() if line.strip() and not _is_numeric_row(line)
    ]


def _is_numeric_row(line: str) -> bool:
    parts = line.replace(",", " ").split()
    if len(parts) < 2:
        return False
    try:
        float(parts[0])
        float(parts[1])
    except ValueError:
        return False
    return True


def _header_value(header: list[str], key: str) -> str | None:
    for line in header:
        name, separator, value = line.strip().partition(":")
        if separator and name.strip().lower() == key.lower():
            return value.strip()
    return None
