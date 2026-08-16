from pathlib import Path

import pytest
import yaml

from external_data_tools.astrochem_network_convert import convert_astrochem_network
from external_data_tools.umist_rate22 import fetch_umist_rate22, main, read_umist_rate22

RATE22_ROWS = (
    "1:CE:CF3+:CF4:CF3:CF4+:::1:1.20e-09:0.00:10.0:10:300:M:A:"
    '"10.1/example":"Example CF4 reaction":\n'
    "2:CE:O+:O2:O:O2+:::1:2.00e-10:0.00:0.0:10:1000:M:A:"
    '"10.2/example":"Example O2 reaction":\n'
)


def test_native_rate22_parser_preserves_four_products_and_source_fields(tmp_path: Path):
    source = tmp_path / "rate22_final.rates"
    source.write_text(RATE22_ROWS, encoding="utf-8")

    rows = read_umist_rate22(source)

    assert len(rows) == 2
    assert rows[0]["reactant1"] == "CF3+"
    assert rows[0]["product4"] == ""
    assert rows[0]["alpha"] == "1.20e-09"
    assert rows[0]["source"] == "UMIST Rate22:1:CE"
    assert rows[0]["reference"] == "10.1/example; Example CF4 reaction"


def test_native_rate22_parser_skips_blanks_and_rejects_truncated_rows(tmp_path: Path):
    source = tmp_path / "broken.rates"
    source.write_text("\n1:CE:too:few\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 2 has 4 fields"):
        read_umist_rate22(source)


def test_rate22_conversion_filters_to_acquisition_pair_targets(tmp_path: Path):
    source = tmp_path / "rate22_final.rates"
    source.write_text(RATE22_ROWS, encoding="utf-8")
    manifest = tmp_path / "targets.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {"targets": [{"pair_key": "ion_neutral|CF3+|CF4"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "candidates.yaml"

    report = convert_astrochem_network(
        source,
        database="UMIST",
        output=output,
        target_manifest=manifest,
    )

    assert report["total_rows"] == 2
    assert report["selected_rows"] == 1
    assert report["filtered_out"] == 1
    assert report["converted"] == 1
    rates = yaml.safe_load(output.with_suffix(".rate_candidates.yaml").read_text("utf-8"))
    assert rates["records"][0]["equation"] == "CF3+ + CF4 -> CF3 + CF4+"


def test_empty_target_manifest_does_not_expand_to_the_full_database(tmp_path: Path):
    source = tmp_path / "rate22_final.rates"
    source.write_text(RATE22_ROWS, encoding="utf-8")
    manifest = tmp_path / "targets.yaml"
    manifest.write_text("targets: []\n", encoding="utf-8")

    report = convert_astrochem_network(
        source,
        database="UMIST",
        output=tmp_path / "candidates.yaml",
        target_manifest=manifest,
    )

    assert report["selected_rows"] == 0
    assert report["converted"] == 0


def test_native_rate_file_rejects_non_umist_database(tmp_path: Path):
    source = tmp_path / "rate22_final.rates"
    source.write_text(RATE22_ROWS, encoding="utf-8")

    with pytest.raises(ValueError, match="supported only for UMIST"):
        convert_astrochem_network(
            source,
            database="KIDA",
            output=tmp_path / "candidates.yaml",
        )


def test_fetch_rate22_records_checksum_and_site_local_status(tmp_path: Path, monkeypatch):
    destination = tmp_path / "raw" / "rate22_final.rates"

    def download_fixture(url: str, output: Path) -> dict:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(RATE22_ROWS, encoding="utf-8")
        return {"downloaded_at": "2026-08-14T00:00:00Z"}

    monkeypatch.setattr("external_data_tools.umist_rate22.download_url", download_fixture)

    result = fetch_umist_rate22(destination)

    assert len(result["sha256"]) == 64
    assert result["redistribution_status"] == "site-local"
    metadata = yaml.safe_load(
        destination.with_suffix(".rates.metadata.yaml").read_text(encoding="utf-8")
    )
    assert metadata["downloaded_at"] == "2026-08-14T00:00:00Z"


def test_fetch_cli_reports_downloaded_artifact(tmp_path: Path, monkeypatch, capsys):
    output = tmp_path / "rate22_final.rates"

    def fetch_fixture(destination: Path) -> dict:
        assert destination == output
        return {"sha256": "a" * 64, "file": str(destination)}

    monkeypatch.setattr("external_data_tools.umist_rate22.fetch_umist_rate22", fetch_fixture)

    assert main(["--output", str(output)]) == 0
    assert "sha256=" + "a" * 64 in capsys.readouterr().out
