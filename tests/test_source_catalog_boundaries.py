"""A catalog chooses an unambiguous acquisition source, without approving it."""

from pathlib import Path

import pytest

from acquire import download
from acquire.cli import main
from reactgen import yamlio


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"sources": "umist"},
        {"sources": ["umist"]},
        {"sources": [{"source_id": 1}]},
        {"sources": [{"source_id": "one", "file": 1}]},
        {"sources": [{"source_id": "one"}, {"id": "one"}]},
    ],
)
def test_invalid_catalog_is_rejected_before_external_access(tmp_path, monkeypatch, document):
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(yamlio.dump(document), encoding="utf-8")

    def forbidden(*args):
        raise AssertionError("invalid catalog must not access the network")

    monkeypatch.setattr(download, "fetch", forbidden)
    assert main(["fetch", "one", "--catalog", str(catalog), "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


def test_sources_reads_the_canonical_catalog_without_network(monkeypatch, capsys) -> None:
    def forbidden(*args):
        raise AssertionError("source inventory must be local")

    monkeypatch.setattr(download, "fetch", forbidden)
    catalog = Path(__file__).resolve().parents[1] / "external_data" / "source_catalog.yaml"
    assert main(["sources", "--catalog", str(catalog)]) == 0
    document = yamlio.load(capsys.readouterr().out)
    assert document["schema_version"] == 3
    assert any(entry["source_id"] == "umist" for entry in document["sources"])
