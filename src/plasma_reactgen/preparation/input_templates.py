"""Generate editable manual-input files from missing-data reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.preparation.input_report_reader import load_missing_input_context
from plasma_reactgen.preparation.input_template_records import build_missing_input_templates


def generate_missing_input_templates(
    outputs_or_missing_data: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    context = load_missing_input_context(outputs_or_missing_data)
    destination = Path(output_dir)
    templates = build_missing_input_templates(context.items)
    destination.mkdir(parents=True, exist_ok=True)

    written = _write_templates(destination, templates)
    readme_path = destination / "README.md"
    readme_path.write_text(
        _readme_payload(context.missing_path, context.case_name),
        encoding="utf-8",
    )
    written["README.md"] = readme_path

    return {
        "schema_version": 2,
        "missing_data": str(context.missing_path),
        "prepare_report": _optional_path(context.prepare_report_path),
        "coverage_report": _optional_path(context.coverage_report_path),
        "output_dir": str(destination),
        "files": {name: str(path) for name, path in written.items()},
        "summary": _template_summary(context.items, templates),
    }


def _write_templates(
    output_dir: Path,
    templates: dict[str, dict[str, Any]],
) -> dict[str, Path]:
    written: dict[str, Path] = {}
    for filename, payload in templates.items():
        path = output_dir / filename
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        written[filename] = path
    return written


def _optional_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _template_summary(
    items: list[dict[str, Any]],
    templates: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return {
        "n_missing_items": len(items),
        "n_species_property_records": len(templates["species_properties.yaml"]["records"]),
        "n_reaction_channel_records": len(templates["reaction_channels.yaml"]["records"]),
        "n_cross_section_mappings": len(templates["cross_section_mapping.yaml"]["mappings"]),
        "n_reaction_energetics_records": len(templates["reaction_energetics.yaml"]["records"]),
        "n_manual_review_items": len(templates["manual_review.yaml"]["items"]),
    }


def _readme_payload(missing_path: Path, case_name: str | None = None) -> str:
    return f"""# Manual Missing Data Inputs

Generated from `{missing_path}`.

These files are fill-in templates only. They do not contain guessed physical
values, do not fetch data, and do not mutate curated `registry/`.

Recommended workflow:

1. Fill only values that have been reviewed from internal data, local snapshots,
   transport/DNT fits, or literature.
2. Keep `source_record` provenance with citation/source IDs wherever possible.
3. Convert filled property records into an `internal_file` property snapshot or
   another reviewed local source profile input.
4. Import cross-section tables with `reactgen import-cross-sections`, then copy
   the resulting `assets/cross_sections/<file>.csv` path into
   `cross_section_mapping.yaml`.
5. Keep uncertain or unsupported fields in `manual_review.yaml`.

Do not invent collision radii, reaction energetics, cross sections, or species
composition just to satisfy diagnostics.

{_case_guidance(case_name)}
"""


def _case_guidance(case_name: str | None) -> str:
    guidance = {
        "ar_o2_simple": (
            "## Case-Specific Recommendations: Ar/O2\n\n"
            "- Review/import O2 electron cross sections.\n"
            "- Fill O2 DNT properties from reviewed transport/DNT sources.\n"
            "- Review Ar+ + O2 ion-neutral energetics before DNT use.\n"
        ),
        "ar_cf4_fluorocarbon": (
            "## Case-Specific Recommendations: Ar/CF4\n\n"
            "- Review/import CF4 and CFx electron cross sections.\n"
            "- Fill CFx thermochemistry from reviewed local snapshots or internal data.\n"
            "- Review Ar+ + CF4 ion-neutral energetics before DNT use.\n"
        ),
        "sf6_o2_electronegative": (
            "## Case-Specific Recommendations: Ar/SF6/O2\n\n"
            "- Review/import SF6 attachment and dissociation cross sections.\n"
            "- Review negative ion channels before expanding chemistry.\n"
            "- Fill SFx thermochemistry and DNT properties from reviewed sources.\n"
        ),
    }
    default = (
        "## Case-Specific Recommendations\n\n"
        "- Use the missing plan to prioritize reviewed properties, reaction energetics,\n"
        "  reaction channels, and cross-section mappings for this case.\n"
    )
    return guidance.get(case_name, default) if case_name is not None else default
