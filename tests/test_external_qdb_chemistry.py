from pathlib import Path

import pytest
import yaml

from external_data_tools.qdb_chemistry import fetch_qdb_chemistry


def test_qdb_fetch_keeps_api_key_out_of_artifacts(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "raw" / "qdb" / "C31.txt"
    seen = {}

    def fake_download(url: str, destination: Path, *, sensitive_query_keys: set[str]):
        seen["url"] = url
        seen["sensitive_query_keys"] = sensitive_query_keys
        destination.parent.mkdir(parents=True)
        destination.write_text("REACTION\nNF3 + e -> NF2 + F + e\n", encoding="utf-8")
        return {"downloaded_at": "2026-08-14T00:00:00Z", "url": "redacted"}

    monkeypatch.setattr("external_data_tools.qdb_chemistry.download_url", fake_download)

    result = fetch_qdb_chemistry(31, output, api_key="secret-api-key")

    metadata_path = output.with_suffix(".txt.metadata.yaml")
    metadata_text = metadata_path.read_text(encoding="utf-8")
    metadata = yaml.safe_load(metadata_text)
    assert "secret-api-key" in seen["url"]
    assert seen["sensitive_query_keys"] == {"key"}
    assert "secret-api-key" not in metadata_text
    assert metadata["chemistry_id"] == 31
    assert metadata["request"]["api_key_recorded"] is False
    assert result["redistribution_status"] == "site-local_license_review_required"


@pytest.mark.parametrize(("chemistry_id", "api_key"), [(0, "key"), (1, ""), (-1, "key")])
def test_qdb_fetch_rejects_invalid_credentials_or_id(
    tmp_path: Path,
    chemistry_id: int,
    api_key: str,
) -> None:
    with pytest.raises(ValueError, match="required|positive"):
        fetch_qdb_chemistry(chemistry_id, tmp_path / "qdb.txt", api_key=api_key)
