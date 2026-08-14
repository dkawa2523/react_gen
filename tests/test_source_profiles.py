from __future__ import annotations

from pathlib import Path

import pytest

from plasma_reactgen.data_sources.provider_factory import (
    SourceProviderConfigurationError,
    build_property_providers,
)
from plasma_reactgen.data_sources.source_listing import build_source_list_report
from plasma_reactgen.data_sources.source_profile import load_source_profile
from plasma_reactgen.interface.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_source_profiles_include_provider_metadata():
    profile = load_source_profile("local_only", ROOT / "registry")

    assert profile["active_sources"] == ["local_registry", "local_assets"]
    assert "internal_file" in profile["optional_sources"]
    assert "pubchem_online" in profile["disabled_sources"]
    assert "pubchem_fetch" in profile["external_only_sources"]


def test_source_list_cli_works_for_local_only(capsys):
    rc = main(
        ["source-list", "--source-profile", "local_only", "--registry", str(ROOT / "registry")]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Source profile: local_only" in out
    assert "Active sources: local_registry, local_assets" in out
    assert "Disabled sources:" in out
    assert "Missing configuration: none" in out


def test_source_list_reports_optional_missing_config_without_crashing():
    report = build_source_list_report("experimental_first", ROOT / "registry")

    missing = {(item["source"], item["required"]) for item in report["missing_configuration"]}
    assert ("internal_file", "internal_file.root") in missing
    assert ("nist_snapshot", "nist_snapshot.root") in missing
    assert report["source_profile"] == "experimental_first"


def test_disabled_source_is_not_used_by_provider_factory():
    result = build_property_providers(
        {
            "name": "disabled_nist",
            "strict_sources": True,
            "properties": ["nist_snapshot"],
            "disabled_sources": ["nist_snapshot"],
        }
    )

    assert result.providers == []
    assert result.warnings == []


def test_strict_sources_still_fails_when_configured_provider_missing():
    with pytest.raises(SourceProviderConfigurationError):
        build_property_providers(
            {
                "name": "strict_missing_nist",
                "strict_sources": True,
                "properties": ["nist_snapshot"],
            }
        )


def test_source_list_recognizes_each_configuration_shape_and_catalog_alias(tmp_path):
    registry = tmp_path / "registry"
    profile = tmp_path / "profile.yaml"
    catalog = tmp_path / "source_catalog.yaml"
    profile.write_text(
        """\
name: configured
active_sources: [local_assets]
optional_sources:
  - internal_file
  - nist_snapshot
  - argonne_atct_snapshot
  - chemical_identity_snapshot
  - ion_reaction_table
  - selected_by_section
disabled_sources: []
external_only_sources: [local_assets]
properties: [selected_by_section]
internal_file: {root: internal}
nist_snapshot: {root: nist}
argonne_atct_snapshot: {files: [atct.yaml]}
chemical_identity_snapshot: {snapshot: identity.yaml}
ion_reaction_table: {files: [ions.yaml]}
""",
        encoding="utf-8",
    )
    catalog.write_text(
        """\
sources:
  - source_id: user_provided_cross_section_csv
    requires_license_review: true
    redistribution_risk: review
    notes: Verify redistribution terms.
""",
        encoding="utf-8",
    )

    report = build_source_list_report(profile, registry, source_catalog=catalog)

    assert report["optional_configured_sources"] == [
        "internal_file",
        "nist_snapshot",
        "argonne_atct_snapshot",
        "chemical_identity_snapshot",
        "ion_reaction_table",
        "selected_by_section",
    ]
    assert report["license_review_required"] == [
        {
            "source": "local_assets",
            "catalog_source_id": "user_provided_cross_section_csv",
            "redistribution_risk": "review",
            "notes": "Verify redistribution terms.",
        }
    ]
