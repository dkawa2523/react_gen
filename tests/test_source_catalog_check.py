from __future__ import annotations

from pathlib import Path

from external_data_tools.source_catalog_check import (
    validate_catalog_payload,
    validate_source_catalog,
)


def test_source_catalog_validates() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report = validate_source_catalog(
        repo_root / "external_data" / "source_catalog.yaml",
        project_root=repo_root,
    )

    assert report["valid"], report["errors"]
    assert report["summary"]["n_sources"] >= 15


def test_public_api_source_cannot_be_allowed_in_core_generate(tmp_path: Path) -> None:
    payload = _catalog_with(
        {
            "source_id": "bad_public_api",
            "category": "public_api",
            "allowed_in_core_generate": True,
            "requires_license_review": True,
            "redistribution_risk": "medium",
        }
    )

    report = validate_catalog_payload(payload, project_root=tmp_path)

    assert not report["valid"]
    assert any("cannot be allowed in core generate" in error for error in report["errors"])


def test_high_risk_without_license_review_fails(tmp_path: Path) -> None:
    payload = _catalog_with(
        {
            "source_id": "bad_high_risk",
            "category": "user_provided_file",
            "requires_license_review": False,
            "redistribution_risk": "high",
        }
    )

    report = validate_catalog_payload(payload, project_root=tmp_path)

    assert not report["valid"]
    assert any("requires license review" in error for error in report["errors"])


def test_optional_package_must_not_be_core_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pyyaml>=6.0", "chemicals>=1.0"]\n',
        encoding="utf-8",
    )
    payload = _catalog_with(
        {
            "source_id": "chemicals_optional",
            "category": "optional_python_package",
            "package_name": "chemicals",
            "requires_license_review": True,
            "redistribution_risk": "medium",
        }
    )

    report = validate_catalog_payload(payload, project_root=tmp_path)

    assert not report["valid"]
    assert any("core pyproject dependencies" in error for error in report["errors"])


def test_catalog_reports_record_shape_value_and_advisory_problems(tmp_path: Path) -> None:
    valid_source = _catalog_with({})["sources"][0]
    invalid_source = {
        **valid_source,
        "category": "unsupported",
        "redistribution_risk": "critical",
        "default_status": "unknown",
        "allowed_in_enrich": "yes",
    }
    bundled_source = {
        **valid_source,
        "source_id": "bundled_with_key",
        "category": "bundled",
        "requires_api_key": True,
    }

    report = validate_catalog_payload(
        {
            "schema_version": 2,
            "sources": [valid_source, invalid_source, bundled_source, "not-a-record"],
        },
        project_root=tmp_path,
    )

    assert report["valid"] is False
    assert report["summary"] == {"n_sources": 4, "n_errors": 7, "n_warnings": 1}
    assert "schema_version must be 1" in report["errors"]
    assert "example: duplicate source_id" in report["errors"]
    assert "example: allowed_in_enrich must be boolean" in report["errors"]
    assert report["warnings"] == ["bundled_with_key: bundled sources should not require API keys"]


def _catalog_with(overrides: dict) -> dict:
    source = {
        "source_id": "example",
        "category": "user_provided_file",
        "allowed_in_core_generate": False,
        "allowed_in_enrich": True,
        "allowed_in_external_tools": True,
        "requires_license_review": True,
        "requires_api_key": False,
        "redistribution_risk": "medium",
        "default_status": "imported",
        "notes": "test source",
    }
    source.update(overrides)
    return {"schema_version": 1, "sources": [source]}
