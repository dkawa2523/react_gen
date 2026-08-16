from pathlib import Path

import pytest
import yaml

from external_data_tools.nist_beb import TARGETS, parse_nist_beb_ascii
from external_data_tools.registry_nist_beb_import import import_nist_beb, import_nist_beb_file

RAW_TABLE = """Oxygen molecule (O2)

Energy (eV) BEB (A^2)
12.07 0.000
12.50 0.018
13.00 0.040
"""


def test_nist_beb_targets_cover_reachable_cfx_and_sfx_species() -> None:
    assert set(TARGETS) == {"CF2", "CF3", "CF4", "O2", "SF3", "SF4", "SF5", "SF6"}
    assert TARGETS["CF4"].reaction_id == "e_CF4_ionization_parent_effective"
    assert TARGETS["SF4"].reaction_id == "e_SF4_ionization"


def test_nist_beb_parser_converts_square_angstrom_to_square_metre() -> None:
    rows = parse_nist_beb_ascii(RAW_TABLE)

    assert rows == [
        {"energy_eV": 12.07, "cross_section_m2": 0.0},
        {"energy_eV": 12.5, "cross_section_m2": pytest.approx(1.8e-22)},
        {"energy_eV": 13.0, "cross_section_m2": pytest.approx(4.0e-22)},
    ]


def test_nist_beb_import_keeps_total_ionization_separate_from_channel_cross_section(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "prepared_registry"
    reaction_path = registry / "reactions" / "electron" / "e__O2.yaml"
    _write_yaml(
        reaction_path,
        {
            "pair": {"family": "electron", "projectile": "e", "target": "O2"},
            "channels": [
                {
                    "id": "e_O2_ionization",
                    "type": "ionization",
                    "products": [{"species": "e", "n": 2}, {"species": "O2+", "n": 1}],
                    "status": "curated",
                }
            ],
        },
    )
    raw_path = tmp_path / "o2.txt"
    raw_path.write_text(RAW_TABLE, encoding="utf-8")

    result = import_nist_beb_file(
        raw_path,
        species_id="O2",
        registry_root=registry,
    )

    assert result["applied"] == 1
    assert result["row_count"] == 3
    asset = registry / result["asset_path"]
    assert asset.is_file()
    channel = _read_yaml(reaction_path)["channels"][0]
    dataset = channel["data"]["datasets"][0]
    assert dataset["kind"] == "total_ionization_cross_section"
    assert dataset["parameters"]["product_branching"] == "unresolved"
    assert dataset["preferred"] is False
    assert "cross_section" not in channel["data"]
    assert dataset["asset"]["checksum"] == result["asset_sha256"]


def test_nist_beb_workflow_downloads_each_unique_target_and_writes_report(
    tmp_path: Path, monkeypatch
) -> None:
    registry = tmp_path / "prepared_registry"
    reaction_path = registry / "reactions" / "electron" / "e__O2.yaml"
    _write_yaml(
        reaction_path,
        {
            "pair": {"family": "electron", "projectile": "e", "target": "O2"},
            "channels": [
                {
                    "id": "e_O2_ionization",
                    "type": "ionization",
                    "products": [{"species": "e", "n": 2}, {"species": "O2+", "n": 1}],
                    "status": "curated",
                }
            ],
        },
    )
    downloaded_urls: list[str] = []

    def download_fixture(url: str, destination: Path) -> dict:
        downloaded_urls.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(RAW_TABLE, encoding="utf-8")
        return {"downloaded_at": "2026-08-14T00:00:00Z"}

    monkeypatch.setattr(
        "external_data_tools.registry_nist_beb_import.download_url",
        download_fixture,
    )
    reports = tmp_path / "reports"

    result = import_nist_beb(
        ["O2", "O2"],
        registry_root=registry,
        report_dir=reports,
    )

    assert result["summary"] == {"n_requested": 1, "n_applied": 1, "n_review": 0}
    assert len(downloaded_urls) == 1
    assert _read_yaml(reports / "nist_beb_import.yaml")["summary"] == result["summary"]
    metadata_path = registry / result["results"][0]["asset_path"]
    metadata = _read_yaml(metadata_path.with_suffix(".metadata.yaml"))
    assert metadata["downloaded_at"] == "2026-08-14T00:00:00Z"


def test_nist_beb_parser_rejects_non_monotonic_energy() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_nist_beb_ascii("header\n20 1\n19 2\n")


def test_nist_beb_parser_rejects_negative_cross_section() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        parse_nist_beb_ascii("header\n12 -0.1\n13 0.2\n")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
