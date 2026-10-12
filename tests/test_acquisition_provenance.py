"""Acquisition declarations survive conversion and scientific-record storage."""

import hashlib
from pathlib import Path

import pytest
import yaml

from acquire import download, snapshot
from acquire.cli import main
from reactgen import adopt, export, ingest
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.registry import Registry

LXCAT = (
    "ELASTIC\nAr\nPROCESS: E + Ar -> E + Ar, Elastic\n"
    "CHANNEL SCOPE: product_resolved\nOBSERVABLE: momentum_transfer\n"
    "COLUMNS: Energy (eV) | Cross section (m2)\n"
    "-----\n0 1e-20\n1 2e-20\n-----\n"
)
UMIST = "1:NN:Ar:Ar:Ar:Ar:::1:1e-12:0:0:10:1000:M:A:synthetic reference\n"


def write_yaml(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def manifest_for(raw: Path) -> dict:
    return {
        "file": raw.name,
        "source_id": "download-route",
        "provider": "declared-upstream",
        "collection": "declared-collection",
        "release": "declared-release",
        "requested_url": "https://example.invalid/request",
        "final_url": "https://example.invalid/final",
        "retrieved_at": "2026-10-12T01:02:03+00:00",
        "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "raw_path": "original-storage/location",
    }


def registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    write_yaml(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas"},
    )
    for family, projectile in (("electron", "e"), ("neutral", "Ar")):
        products = [{"species": "Ar", "n": 2}]
        if projectile == "e":
            products = [{"species": "e"}, {"species": "Ar"}]
        write_yaml(
            root / "reactions" / family / "pair.yaml",
            {
                "pair": {"family": family, "projectile": projectile, "target": "Ar"},
                "channels": [{"id": f"{family}-elastic", "type": "elastic", "products": products}],
            },
        )
    return root


@pytest.mark.parametrize(("converter", "body"), [("lxcat", LXCAT), ("umist", UMIST)])
def test_fetch_conversion_and_all_numeric_storage_routes_preserve_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, converter: str, body: str
) -> None:
    payload = body.encode("utf-8")
    checksum = hashlib.sha256(payload).hexdigest()
    source = {
        "source_id": "download-route",
        "provider": "declared-upstream",
        "collection": "declared-collection",
        "release": "declared-release",
        "file": "https://example.invalid/input.txt",
        "format": converter,
    }
    catalog = write_yaml(tmp_path / "catalog.yaml", {"sources": [source]})
    monkeypatch.setattr(
        download,
        "fetch",
        lambda url, expect: download.Fetched(
            "https://example.invalid/final.txt", payload, checksum
        ),
    )
    fetched = tmp_path / "fetched"
    assert main(["fetch", "download-route", "--catalog", str(catalog), "--out", str(fetched)]) == 0
    manifest = yaml.safe_load((fetched / "acquisition.yaml").read_text(encoding="utf-8"))
    assert {name: manifest[name] for name in ("provider", "collection", "release")} == {
        name: source[name] for name in ("provider", "collection", "release")
    }
    work = tmp_path / "converted"
    assert main([converter, str(fetched / "input.txt"), "--out", str(work)]) == 0
    document = yaml.safe_load((work / "snapshot.yaml").read_text(encoding="utf-8"))
    acquisition = document["acquisition"]
    assert acquisition["source_manifest"] == manifest
    assert acquisition["raw_path"] == "raw/input.txt"
    assert (work / acquisition["raw_path"]).read_bytes() == payload
    assert document["source"]["acquisition"] == acquisition

    if converter == "umist":
        # RATE's NN class does not identify this particular physical process.
        # This synthetic fixture explicitly supplies that separate identification.
        document["records"][0]["type"] = "elastic"
        write_yaml(work / "snapshot.yaml", document)

    direct = (
        EvidenceCatalog.load(None, known=(work / "snapshot.yaml",)).reaction_records[0].datasets[0]
    )
    assert direct.source_declaration["snapshot_source"]["acquisition"] == acquisition
    assert direct.tier == "imported"
    assert direct.provenance.collection == (
        "gas_phase_rates" if converter == "umist" else "declared-collection"
    )
    assert direct.provenance.release == "declared-release"
    root = registry(tmp_path)
    export.write(tmp_path / "result", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    overlay = work / "overlay.yaml"
    assert ingest.ingest(work / "snapshot.yaml", tmp_path / "result", overlay).accepted == 1
    placed = next(iter(EvidenceCatalog.load(None, overlay).overlay_datasets.values()))[0]
    assert placed.source_declaration == direct.source_declaration
    assert adopt.adopt(overlay, root).values == 2
    saved = next(
        dataset
        for channels in Registry.load(root).channels.values()
        for channel in channels
        for dataset in channel.datasets
    )
    assert saved.source_declaration == direct.source_declaration
    assert saved.provenance == direct.provenance
    assert saved.tier == "imported"


def test_state_declaration_and_original_manifest_paths_survive_adoption(tmp_path: Path) -> None:
    raw = tmp_path / "input.tsv"
    raw.write_text("original property declaration", encoding="utf-8")
    manifest = manifest_for(raw)
    write_yaml(raw.with_name("acquisition.yaml"), manifest)
    source = snapshot.write(
        tmp_path / "converted",
        "state_property",
        {"citation": "synthetic fixture"},
        [{"species": "Ar", "phase": "gas", "property": "mass_amu", "value": 40, "unit": "amu"}],
        input_path=raw,
    )
    direct = EvidenceCatalog.load(None, known=(source,)).state_records[0]
    acquisition = direct.source_declaration["snapshot_source"]["acquisition"]
    assert acquisition["source_manifest"] == manifest
    assert acquisition["raw_path"] == "raw/input.tsv"
    assert acquisition["source_manifest"]["raw_path"] == "original-storage/location"
    assert direct.provenance.provider == "declared-upstream"
    root = registry(tmp_path)
    export.write(tmp_path / "result", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    overlay = tmp_path / "converted" / "overlay.yaml"
    assert ingest.ingest(source, tmp_path / "result", overlay).accepted == 1
    assert adopt.adopt(overlay, root).values == 1
    saved = Registry.load(root).species["Ar"].records[0]
    assert saved.source_declaration == direct.source_declaration
    assert saved.provenance == direct.provenance
    assert saved.existence == "unknown"


def test_fetch_does_not_infer_provider_from_source_id(tmp_path: Path, monkeypatch) -> None:
    payload = b"1:NN:Ar:Ar:Ar:Ar:::1:1e-12:0:0:10:100:M:A:ref\n"
    source = {"source_id": "umist", "file": "https://example.invalid/rates", "format": "umist"}
    catalog = write_yaml(tmp_path / "catalog.yaml", {"sources": [source]})
    monkeypatch.setattr(
        download,
        "fetch",
        lambda url, expect: download.Fetched(url, payload, hashlib.sha256(payload).hexdigest()),
    )
    out = tmp_path / "out"
    assert main(["fetch", "umist", "--catalog", str(catalog), "--out", str(out)]) == 0
    manifest = yaml.safe_load((out / "acquisition.yaml").read_text(encoding="utf-8"))
    assert not {"provider", "collection", "release"}.intersection(manifest)


def test_unrelated_file_manifest_is_not_adopted(tmp_path: Path) -> None:
    raw = tmp_path / "input.txt"
    raw.write_text("raw bytes", encoding="utf-8")
    manifest = manifest_for(raw) | {"file": "different.txt", "sha256": "0" * 64}
    write_yaml(raw.with_name("acquisition.yaml"), manifest)
    path = snapshot.write(tmp_path / "out", "state_property", {}, [], input_path=raw)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "source_manifest" not in document["acquisition"]
    assert "provider" not in document["source"]


@pytest.mark.parametrize(
    "invalid", [[], {"file": "input.txt"}, {"file": "input.txt", "sha256": "short"}]
)
def test_malformed_manifest_fails_before_snapshot_writes(tmp_path: Path, invalid) -> None:
    raw = tmp_path / "input.txt"
    raw.write_text("raw bytes", encoding="utf-8")
    write_yaml(raw.with_name("acquisition.yaml"), invalid)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="manifest"):
        snapshot.write(out, "state_property", {}, [], input_path=raw)
    assert not out.exists()


def test_manifest_hash_conflict_leaves_existing_conversion_files_unchanged(tmp_path: Path) -> None:
    raw = tmp_path / "input.txt"
    raw.write_text(LXCAT, encoding="utf-8")
    write_yaml(raw.with_name("acquisition.yaml"), manifest_for(raw) | {"sha256": "0" * 64})
    out = tmp_path / "out"
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "Ar_elastic_0.csv").write_bytes(b"existing asset")
    (out / "snapshot.yaml").write_bytes(b"existing snapshot")
    before = {path.relative_to(out): path.read_bytes() for path in out.rglob("*") if path.is_file()}
    assert main(["lxcat", str(raw), "--out", str(out)]) == 2
    after = {path.relative_to(out): path.read_bytes() for path in out.rglob("*") if path.is_file()}
    assert after == before


def test_duplicate_manifest_declarations_fail_before_writes(tmp_path: Path) -> None:
    raw = tmp_path / "input.txt"
    raw.write_text("raw bytes", encoding="utf-8")
    raw.with_name("acquisition.yaml").write_text(
        f"file: input.txt\nfile: other.txt\nsha256: {'0' * 64}\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        snapshot.write(out, "state_property", {}, [], input_path=raw)
    assert not out.exists()


def test_snapshot_digest_is_the_complete_sha256(tmp_path: Path) -> None:
    path = tmp_path / "asset.csv"
    path.write_bytes(b"energy_eV,cross_section_m2\n0,1e-20\n")
    assert snapshot.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()
