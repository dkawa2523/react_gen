from __future__ import annotations

import hashlib

import pytest
import yaml

from external_data_tools import download_manifest, http_client
from external_data_tools.http_client import download_many, download_url


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def test_download_url_dry_run_does_not_create_output(tmp_path, monkeypatch):
    output = tmp_path / "raw" / "table.csv"

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not run during dry-run")

    monkeypatch.setattr(http_client, "_open_http_request", fail_urlopen)

    record = download_url("https://example.invalid/table.csv", output, dry_run=True)

    assert record["dry_run"] is True
    assert record["url"] == "https://example.invalid/table.csv"
    assert record["output_path"] == str(output)
    assert record["user_agent"] == "react_gen_external_data_tools/0.1"
    assert record["timeout"] == 30.0
    assert record["sleep_seconds"] == 1.0
    assert "sha256" not in record
    assert not output.exists()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.invalid/table.csv",
        "https:///missing-host.csv",
        "https://user" + chr(58) + "password@example.invalid/table.csv",
    ],
)
def test_download_url_rejects_unsafe_or_ambiguous_urls(tmp_path, url):
    with pytest.raises(ValueError, match=r"HTTP\(S\) URL"):
        download_url(url, tmp_path / "download.csv", dry_run=True)


def test_download_url_writes_bytes_and_records_sha256(tmp_path, monkeypatch):
    payload = b"energy_eV,cross_section_m2\n0,0\n1,1e-20\n"
    output = tmp_path / "raw" / "download.csv"
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["user_agent"] = request.headers["User-agent"]
        seen["timeout"] = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr(http_client, "_open_http_request", fake_urlopen)

    record = download_url(
        "https://example.invalid/download.csv",
        output,
        user_agent="test-agent",
        timeout=4.5,
        sleep_seconds=0.0,
    )

    assert output.read_bytes() == payload
    assert record["dry_run"] is False
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["downloaded_at"]
    assert seen == {
        "url": "https://example.invalid/download.csv",
        "user_agent": "test-agent",
        "timeout": 4.5,
    }


def test_download_many_preserves_manifest_metadata_and_summary(tmp_path, monkeypatch):
    payloads = {
        "https://example.invalid/a.csv": b"a\n",
        "https://example.invalid/b.csv": b"b\n",
    }
    slept = []

    def fake_urlopen(request, timeout):
        return _FakeResponse(payloads[request.full_url])

    monkeypatch.setattr(http_client, "_open_http_request", fake_urlopen)
    monkeypatch.setattr(http_client.time, "sleep", lambda seconds: slept.append(seconds))

    manifest = {
        "schema_version": 1,
        "downloads": [
            {
                "id": "first",
                "url": "https://example.invalid/a.csv",
                "output": "tables/a.csv",
                "source_name": "example",
                "license_note": "review terms",
                "citation": "Example citation",
            },
            {
                "id": "second",
                "url": "https://example.invalid/b.csv",
                "output": "tables/b.csv",
                "source_name": "example",
            },
        ],
    }

    report = download_many(manifest, tmp_path / "raw")

    assert report["summary"] == {
        "total": 2,
        "planned": 0,
        "downloaded": 2,
        "failed": 0,
    }
    assert [record["id"] for record in report["records"]] == ["first", "second"]
    assert report["records"][0]["source_name"] == "example"
    assert report["records"][0]["license_note"] == "review terms"
    assert report["records"][0]["citation"] == "Example citation"
    assert (tmp_path / "raw" / "tables" / "a.csv").read_bytes() == b"a\n"
    assert slept == [1.0]


def test_download_many_rejects_path_traversal(tmp_path):
    manifest = {
        "schema_version": 1,
        "downloads": [
            {
                "id": "escape",
                "url": "https://example.invalid/a.csv",
                "output": "../a.csv",
            }
        ],
    }

    with pytest.raises(ValueError, match="escapes output root"):
        download_many(manifest, tmp_path / "raw")


def test_download_manifest_main_writes_report_and_durable_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manifest_path = tmp_path / "downloads.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "downloads": [
                    {
                        "id": "planned",
                        "url": "https://example.invalid/planned.csv",
                        "output": "planned.csv",
                        "source_name": "example",
                        "license_note": "local review required",
                        "citation": "Example citation",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = download_manifest.main(
        [str(manifest_path), "--output-root", "external_data/raw", "--dry-run"]
    )

    assert exit_code == 0
    report_path = tmp_path / "downloads.download_report.yaml"
    durable_manifest_path = tmp_path / "external_data" / "manifests" / "download_manifest.yaml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    durable_manifest = yaml.safe_load(durable_manifest_path.read_text(encoding="utf-8"))

    assert report["summary"] == {
        "total": 1,
        "planned": 1,
        "downloaded": 0,
        "failed": 0,
    }
    assert durable_manifest["schema_version"] == 1
    assert durable_manifest["records"][0]["id"] == "planned"
    assert durable_manifest["records"][0]["dry_run"] is True
