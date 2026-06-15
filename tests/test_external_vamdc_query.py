from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from external_data_tools import vamdc_query
from external_data_tools.cache import sha256_file
from external_data_tools.vamdc_query import build_tap_sync_url, main, run_vamdc_queries


def test_build_tap_sync_url_encodes_query():
    url = build_tap_sync_url(
        "https://example-vamdc-node.example/tap/sync",
        "SELECT * WHERE MoleculeStoichiometricFormula = 'CF4'",
    )

    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "example-vamdc-node.example"
    assert parsed.path == "/tap/sync"
    assert params["REQUEST"] == ["doQuery"]
    assert params["LANG"] == ["VSS2"]
    assert params["QUERY"] == ["SELECT * WHERE MoleculeStoichiometricFormula = 'CF4'"]


def test_vamdc_dry_run_records_planned_queries_without_download(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path / "vamdc_queries.yaml")
    output_root = tmp_path / "external_data" / "raw" / "vamdc"

    def fake_download_url(url, output_path, dry_run=False):
        assert dry_run is True
        assert not Path(output_path).exists()
        return {
            "url": url,
            "output_path": str(output_path),
            "dry_run": True,
            "planned_at": "2026-06-15T00:00:00+00:00",
            "user_agent": "test-agent",
            "timeout": 1.0,
        }

    monkeypatch.setattr(vamdc_query, "download_url", fake_download_url)

    result = run_vamdc_queries(manifest, output_root=output_root, dry_run=True)
    written = yaml.safe_load((output_root / "manifest.yaml").read_text(encoding="utf-8"))

    assert result["summary"] == {
        "total_queries": 1,
        "planned": 1,
        "downloaded": 0,
        "unresolved": 0,
    }
    assert written["records"][0]["id"] == "cf4_query"
    assert written["records"][0]["dry_run"] is True
    assert "sha256" not in written["records"][0]
    assert not (output_root / "cf4_query.xml").exists()


def test_vamdc_mocked_http_response_writes_xml_and_sha256(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path / "vamdc_queries.yaml")
    output_root = tmp_path / "external_data" / "raw" / "vamdc"
    xml_payload = "<XSAMSData><Species/></XSAMSData>\n"

    def fake_download_url(url, output_path, dry_run=False):
        assert dry_run is False
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml_payload, encoding="utf-8")
        return {
            "url": url,
            "output_path": str(output_path),
            "sha256": sha256_file(output_path),
            "downloaded_at": "2026-06-15T00:00:00+00:00",
            "dry_run": False,
        }

    monkeypatch.setattr(vamdc_query, "download_url", fake_download_url)

    result = run_vamdc_queries(manifest, output_root=output_root)
    record = result["records"][0]

    assert (output_root / "cf4_query.xml").read_text(encoding="utf-8") == xml_payload
    assert record["sha256"] == sha256_file(output_root / "cf4_query.xml")
    assert record["endpoint"] == "https://example-vamdc-node.example/tap/sync"
    assert record["query"] == "SELECT * WHERE MoleculeStoichiometricFormula = 'CF4'"
    assert record["xml_detected"] is True
    assert record["notes"] == ["endpoint is user-provided"]


def test_vamdc_network_failure_records_unresolved_and_continues(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "vamdc_queries.yaml",
        queries=[
            {
                "id": "bad_query",
                "endpoint": "https://example.invalid/tap/sync",
                "query": "SELECT * WHERE AtomSymbol = 'Ar'",
                "output": "bad.xml",
            }
        ],
    )

    def fake_download_url(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(vamdc_query, "download_url", fake_download_url)

    result = run_vamdc_queries(manifest, output_root=tmp_path / "raw" / "vamdc")

    assert result["summary"]["unresolved"] == 1
    assert result["records"] == []
    assert result["unresolved"] == [
        {
            "id": "bad_query",
            "endpoint": "https://example.invalid/tap/sync",
            "query": "SELECT * WHERE AtomSymbol = 'Ar'",
            "output": "bad.xml",
            "reason": "download_failed",
            "message": "network unavailable",
        }
    ]


def test_vamdc_query_no_real_network_access_and_cli(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path / "vamdc_queries.yaml")
    output_root = tmp_path / "raw" / "vamdc"

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("VAMDC tests must not use real network access")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    def fake_download_url(url, output_path, dry_run=False):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<XSAMSData />\n", encoding="utf-8")
        return {
            "url": url,
            "output_path": str(output_path),
            "sha256": sha256_file(output_path),
            "downloaded_at": "2026-06-15T00:00:00+00:00",
            "dry_run": False,
        }

    monkeypatch.setattr(vamdc_query, "download_url", fake_download_url)

    exit_code = main([str(manifest), "--output-root", str(output_root)])

    written = yaml.safe_load((output_root / "manifest.yaml").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written["summary"]["downloaded"] == 1


def test_vamdc_output_path_traversal_is_rejected(tmp_path):
    manifest = _write_manifest(
        tmp_path / "vamdc_queries.yaml",
        queries=[
            {
                "id": "escape",
                "endpoint": "https://example.invalid/tap/sync",
                "query": "SELECT *",
                "output": "../escape.xml",
            }
        ],
    )

    with pytest.raises(ValueError, match="escapes output root"):
        run_vamdc_queries(manifest, output_root=tmp_path / "raw" / "vamdc")


def _write_manifest(path: Path, queries: list[dict] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "queries": queries
                or [
                    {
                        "id": "cf4_query",
                        "endpoint": "https://example-vamdc-node.example/tap/sync",
                        "query": "SELECT * WHERE MoleculeStoichiometricFormula = 'CF4'",
                        "output": "cf4_query.xml",
                        "notes": ["endpoint is user-provided"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path
