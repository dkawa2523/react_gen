"""Orchestrate reproducible acquisition plans for arbitrary input gases."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from external_data_tools.acquisition_manifests import build_source_manifests
from external_data_tools.acquisition_targets import collect_acquisition_targets
from external_data_tools.registry_pack_plan import analyze_registry_pack


def plan_data_acquisition(
    *,
    seed_gases: list[str],
    max_depth: int | None,
    registry_root: str | Path,
    output_dir: str | Path,
    vamdc_endpoint: str | None = None,
) -> dict[str, Any]:
    """Write a source-routed collection plan without downloading or promoting data."""

    root = Path(registry_root)
    destination = Path(output_dir)
    coverage, network, registry = analyze_registry_pack(seed_gases, max_depth, root)
    targets = collect_acquisition_targets(
        network,
        registry,
        seed_gases=seed_gases,
        pair_candidates=coverage["missing_reaction_pairs"],
    )
    manifests = build_source_manifests(
        targets,
        vamdc_endpoint=vamdc_endpoint,
        seed_gases=seed_gases,
    )
    files = _write_manifests(destination, manifests)
    acquisition_coverage = {
        key: value
        for key, value in coverage["summary"].items()
        if key != "n_dnt_properties_missing"
    }
    plan = _overview(
        seed_gases=seed_gases,
        max_depth=max_depth,
        registry_root=root,
        output_dir=destination,
        targets=targets,
        files=files,
        coverage_summary=acquisition_coverage,
        electron_imports=manifests["electron_cross_section_targets.yaml"]["automated_imports"],
        vamdc_endpoint=vamdc_endpoint,
    )
    _write_yaml(destination / "acquisition_plan.yaml", plan)
    return plan


def _overview(
    *,
    seed_gases: list[str],
    max_depth: int | None,
    registry_root: Path,
    output_dir: Path,
    targets: dict[str, list[dict[str, Any]]],
    files: dict[str, str],
    coverage_summary: dict[str, Any],
    electron_imports: dict[str, Any],
    vamdc_endpoint: str | None,
) -> dict[str, Any]:
    summary = {f"n_{name}": len(items) for name, items in targets.items()}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "seed_gases": seed_gases,
            "max_depth": max_depth,
            "registry": str(registry_root),
            "mixture_pack_required": False,
        },
        "priorities": _priorities(
            summary,
            targets["reaction_pair_candidates"],
            coverage_summary["n_missing_reaction_pairs"],
        ),
        "commands": _commands(
            output_dir,
            registry_root,
            manifests=files,
            electron_imports=electron_imports,
            vamdc_ready=bool(vamdc_endpoint),
        ),
        "files": files,
        "coverage_summary": coverage_summary,
        "summary": summary,
        "completion_rules": [
            "Every imported value has source ID, citation, access date, units, and review status.",
            "Every numerical dataset maps to exactly one registered reaction ID.",
            "Reaction equations are registered before optional numerical or solver outputs.",
            "DNT and calculated-result ingestion are outside this acquisition-plan scope.",
            "Source ranges are preserved; no silent temperature or energy extrapolation.",
            "Candidate reaction pairs remain candidates until channel evidence is reviewed.",
            "Generation and quality-pr pass after registry changes.",
        ],
    }


def _priorities(
    summary: dict[str, int],
    pair_candidates: list[dict[str, Any]],
    exhaustive_pair_count: int,
) -> list[dict[str, Any]]:
    pair_counts = {
        priority: sum(item["priority"] == priority for item in pair_candidates)
        for priority in ("P1", "P2", "P3")
    }
    return [
        {
            "priority": "P0",
            "work": "review and register evidence-backed missing reaction equations",
            "counts": {
                "direct_candidates": pair_counts["P1"],
                "secondary_candidates": pair_counts["P2"],
            },
        },
        {
            "priority": "P1",
            "work": "collect numerical cross sections, rates, and species properties",
            "counts": {
                "electron_datasets": summary["n_electron_datasets"],
                "heavy_particle_datasets": summary["n_heavy_particle_datasets"],
                "properties": summary["n_properties"],
            },
        },
        {
            "priority": "P2",
            "work": "validate source applicability and numerical consistency",
            "count": (summary["n_electron_datasets"] + summary["n_heavy_particle_datasets"]),
        },
        {
            "priority": "P3",
            "work": "deferred combinatorial product-product discovery",
            "count": exhaustive_pair_count - len(pair_candidates),
        },
    ]


def _commands(
    output_dir: Path,
    registry_root: Path,
    *,
    manifests: dict[str, str],
    electron_imports: dict[str, Any],
    vamdc_ready: bool,
) -> list[dict[str, Any]]:
    commands = [
        {
            "step": "review_identity_queries",
            "command": (
                "python -m external_data_tools.pubchem_fetch "
                f"{manifests['pubchem_species.yaml']} --dry-run"
            ),
        },
        {
            "step": "fetch_reviewed_identities",
            "command": (
                "python -m external_data_tools.pubchem_fetch "
                f"{manifests['pubchem_species.yaml']} "
                f"--output-root {output_dir / 'raw' / 'pubchem'} "
                f"--snapshot {output_dir / 'pubchem_species_snapshot.yaml'}"
            ),
        },
        {
            "step": "import_reviewed_cross_sections",
            "command": (
                "python -m external_data_tools.data_admin import_lxcat_raw RAW_FILE "
                f"--registry {registry_root} --report-dir {output_dir / 'reports'}"
            ),
        },
        {
            "step": "fetch_umist_rate22",
            "command": (
                "python -m external_data_tools.umist_rate22 "
                f"--output {output_dir / 'raw' / 'umist' / 'rate22_final.rates'}"
            ),
        },
        {
            "step": "match_umist_rates_to_registered_targets",
            "command": (
                "python -m external_data_tools.astrochem_network_convert "
                f"{output_dir / 'raw' / 'umist' / 'rate22_final.rates'} "
                "--database UMIST "
                f"--target-manifest {manifests['astrochem_rate_targets.yaml']} "
                f"--output {output_dir / 'umist_candidates.yaml'}"
            ),
        },
        {
            "step": "import_reviewed_properties",
            "command": (
                "python -m external_data_tools.data_admin import_property_snapshot "
                f"REVIEWED_PROPERTY_SNAPSHOT.yaml --registry {registry_root} "
                f"--report-dir {output_dir / 'reports'}"
            ),
        },
        {
            "step": "import_reviewed_rates",
            "command": (
                "python -m external_data_tools.data_admin import_rate_snapshot "
                f"REVIEWED_RATE_SNAPSHOT.yaml --registry {registry_root} "
                f"--report-dir {output_dir / 'reports'}"
            ),
        },
        {
            "step": "cache_reviewed_openadas_files",
            "command": (
                "python -m external_data_tools.openadas_raw_import "
                f"{manifests['openadas_manifest.yaml']} "
                f"--workspace {output_dir / 'openadas_workspace'}"
            ),
        },
        {
            "step": "fetch_one_reviewed_qdb_chemistry",
            "command": (
                "python -m external_data_tools.qdb_chemistry "
                "--chemistry-id CHEMISTRY_ID "
                f"--output {output_dir / 'raw' / 'qdb' / 'chemistry_CHEMISTRY_ID.txt'}"
            ),
            "prerequisite": (
                "Select an ID from qdb_chemistry_requests.yaml, review QDB terms, "
                "and set QDB_API_KEY in the environment."
            ),
        },
    ]
    commands.extend(_known_electron_import_commands(electron_imports, registry_root, output_dir))
    if vamdc_ready:
        commands.extend(
            [
                {
                    "step": "download_vamdc_xsams",
                    "command": (
                        "python -m external_data_tools.vamdc_query "
                        f"{manifests['vamdc_queries.yaml']} "
                        f"--output-root {output_dir / 'raw' / 'vamdc'}"
                    ),
                },
                {
                    "step": "inventory_one_vamdc_response",
                    "command": (
                        "python -m external_data_tools.vamdc_xsams_inventory RESPONSE.xml "
                        f"--output {output_dir / 'vamdc_inventory.yaml'}"
                    ),
                },
            ]
        )
    return commands


def _known_electron_import_commands(
    imports: dict[str, Any],
    registry_root: Path,
    output_dir: Path,
) -> list[dict[str, str]]:
    nist_targets = imports["nist_beb_targets"]
    commands = []
    if nist_targets:
        commands.append(
            {
                "step": "import_nist_beb_total_ionization",
                "command": (
                    "python -m external_data_tools.data_admin import_nist_beb --targets "
                    f"{' '.join(nist_targets)} --registry {registry_root} "
                    f"--report-dir {output_dir / 'reports'}"
                ),
            }
        )
    if imports["oxygen_workbook_required"]:
        commands.append(
            {
                "step": "import_evaluated_o2_cross_sections",
                "command": (
                    "python -m external_data_tools.data_admin import_oxygen_cross_sections "
                    f"--registry {registry_root} --report-dir {output_dir / 'reports'}"
                ),
            }
        )
    return commands


def _write_manifests(
    output_dir: Path,
    manifests: dict[str, dict[str, Any]],
) -> dict[str, str]:
    paths = {}
    for name, payload in manifests.items():
        path = output_dir / name
        _write_yaml(path, payload)
        paths[name] = str(path)
    return paths


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


__all__ = ["plan_data_acquisition"]
