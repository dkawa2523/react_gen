from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.benchmark_metrics import collect_metrics
from plasma_reactgen.infrastructure.indexer import check_registry_details
from plasma_reactgen.preparation.preparer import prepare_case


def test_registry_check_preserves_error_and_strict_warning_contract(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _write_yaml(
        registry / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "charge": 0, "classes": ["neutral"]},
    )
    _write_yaml(
        registry / "reactions" / "electron" / "e__Ar.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
            "channels": [
                {
                    "id": "e_Ar_bad_product",
                    "type": "ionization",
                    "products": [{"species": "Ar+", "n": 1}],
                    "data": {"cross_section": {"path": "assets/missing.csv"}},
                }
            ],
        },
    )
    _write_required_rules(registry)

    advisory = check_registry_details(registry, strict=False)
    strict = check_registry_details(registry, strict=True)

    expected_product = "product species not registered: Ar+"
    expected_asset = "cross-section path does not exist: assets/missing.csv"
    assert advisory["errors"] == []
    assert any(expected_product in item for item in advisory["warnings"])
    assert any(expected_asset in item for item in advisory["warnings"])
    assert strict["warnings"] == []
    assert any(expected_product in item for item in strict["errors"])
    assert any(expected_asset in item for item in strict["errors"])


def test_collect_metrics_preserves_complete_summary_contract(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    _write_yaml(
        output / "network.reactions.yaml",
        {
            "summary": {"n_species": 4, "generation_complete": False},
            "truncations": [{"limit_name": "max_reactions"}],
            "reactions": [
                {
                    "id": "e_Ar_elastic",
                    "family": "electron",
                    "depth": 2,
                    "data_status": {"reaction": "imported"},
                    "data": {"provenance": {"source": "fixture"}},
                    "validation": {"charge_balance": "ok", "element_balance": "ok"},
                }
            ],
        },
    )
    _write_yaml(output / "network.states.yaml", {"species": []})
    _write_yaml(
        output / "coverage_report.yaml",
        {"summary": {"n_pairs_found": 2, "n_pairs_missing": 1}},
    )
    _write_yaml(
        output / "missing_data.yaml",
        {"missing_data": [{"severity": "error"}, {"severity": "warning"}]},
    )
    _write_yaml(output / "dnt_tasks.yaml", {"summary": {"n_dnt_pairs": 0}, "dnt_tasks": []})

    metrics = collect_metrics(
        output,
        expectation_score=0.75,
        structural_enrichment_unresolved_count=2,
    )

    assert metrics == {
        "schema_version": 1,
        "n_species": 4,
        "n_reactions": 1,
        "n_electron_reactions": 1,
        "n_ion_neutral_reactions": 0,
        "max_depth_reached": 2,
        "n_pairs_found": 2,
        "n_pairs_missing": 1,
        "n_missing_data_items": 2,
        "generation_complete": False,
        "n_generation_truncations": 1,
        "n_missing_plan_actions": 0,
        "n_dnt_tasks": 0,
        "n_dnt_property_ready_pairs": 0,
        "n_dnt_complete_ready_pairs": 0,
        "n_dnt_ready_with_warnings_pairs": 0,
        "n_dnt_pairs_with_missing_properties": 0,
        "n_dnt_pairs_missing_required_data": 0,
        "n_dnt_pairs_without_channels": 0,
        "dnt_complete_readiness_available": True,
        "n_cross_section_assets": 0,
        "n_reactions_with_cross_section_asset": 0,
        "cross_section_asset_coverage_fraction": 0.0,
        "n_reactions_with_provenance": 1,
        "provenance_coverage_fraction": 1.0,
        "n_inferred_reactions": 0,
        "n_imported_reactions": 1,
        "n_literature_supported_reactions": 0,
        "inferred_reaction_fraction": 0.0,
        "imported_or_literature_supported_fraction": 1.0,
        "validation_error_count": 1,
        "structural_enrichment_unresolved_count": 2,
        "expectation_score": 0.75,
    }


def test_prepare_case_without_sources_keeps_registry_read_only(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    registry = tmp_path / "registry"
    output = tmp_path / "prepared"
    registry.mkdir()
    _write_yaml(case_path, {"case": {"name": "empty-source"}, "gases": ["Ar"]})

    report = prepare_case(
        case_path,
        registry,
        source_profile={"name": "empty"},
        output_dir=output,
    )

    assert report["schema_version"] == 2
    assert report["prepared_registry"] == str(output)
    assert report["summary"] == {
        "n_species_written": 0,
        "n_properties_filled": 0,
        "n_reaction_pairs_imported": 0,
        "n_species_seeded_from_reactions": 0,
        "n_properties_filled_for_seeded_species": 0,
        "n_unresolved_product_species": 0,
    }
    assert (output / "prepare_report.yaml").is_file()
    assert list(registry.iterdir()) == []


def _write_required_rules(registry: Path) -> None:
    _write_yaml(registry / "rules" / "reaction_type_catalog.yaml", {"schema_version": 1})
    _write_yaml(
        registry / "rules" / "role_required_properties.yaml",
        {"schema_version": 1, "roles": {}},
    )


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
