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
