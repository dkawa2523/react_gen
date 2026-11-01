"""Multiple sources preserve unresolved inputs independently of scientific review."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from reactgen import export, ingest
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze

REGISTRY = Path(__file__).parent / "fixtures" / "mini"


def write(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def bundle(path: Path, *gases: str) -> Path:
    export.write(path, analyze(Case("queue", gases), EvidenceCatalog.load(REGISTRY)))
    return path


def source(path: Path, species: str, *, provider: str = "lab") -> Path:
    return write(
        path,
        {
            "snapshot_version": 1,
            "kind": "state_property",
            "source": {"provider": provider},
            "records": [
                {
                    "species": species,
                    "phase": "gas",
                    "property": "mass_amu",
                    "value": 40,
                    "unit": "amu",
                    "source": {"record_id": "one"},
                }
            ],
        },
    )


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_different_source_ingest_does_not_erase_previous_unresolved_input(tmp_path):
    result = bundle(tmp_path / "result", "Ar")
    overlay = tmp_path / "overlay.yaml"
    first = source(tmp_path / "one.yaml", "Xe", provider="one")
    second = source(tmp_path / "two.yaml", "Ne", provider="two")
    for item in (first, second, first):
        report = ingest.ingest(item, result, overlay)
        assert report.accepted == 0
    queue = read(tmp_path / "review_queue.yaml")["review"]
    assert len(queue) == 2
    assert {entry["source"]["provider"] for entry in queue} == {"one", "two"}
    assert {entry["original_record"]["species"] for entry in queue} == {"Xe", "Ne"}
    assert all(entry["kind"] == "state_property" for entry in queue)
    assert report.pending_total == 2
    assert len(report.review) == 1


def test_same_input_later_matched_removes_only_its_unresolved_entry(tmp_path):
    result = bundle(tmp_path / "result", "Ar")
    overlay = tmp_path / "overlay.yaml"
    first = source(tmp_path / "one.yaml", "Xe", provider="one")
    second = source(tmp_path / "two.yaml", "Ne", provider="two")
    ingest.ingest(first, result, overlay)
    ingest.ingest(second, result, overlay)
    result = bundle(tmp_path / "new-result", "Ar", "Xe")
    assert ingest.ingest(first, result, overlay).accepted == 1
    queue = read(tmp_path / "review_queue.yaml")["review"]
    assert len(queue) == 1
    assert queue[0]["source"]["provider"] == "two"
    assert "Xe@ground" in read(overlay)["state_records"]


def test_reordered_rows_do_not_duplicate_unresolved_work(tmp_path):
    result = bundle(tmp_path / "result", "Ar")
    overlay = tmp_path / "overlay.yaml"
    one = source(tmp_path / "source.yaml", "Xe")
    document = read(one)
    document["records"].append(document["records"][0] | {"species": "Ne"})
    write(one, document)
    ingest.ingest(one, result, overlay)
    write(one, document | {"records": list(reversed(document["records"]))})
    ingest.ingest(one, result, overlay)
    assert len(read(tmp_path / "review_queue.yaml")["review"]) == 2


def test_legacy_queue_retains_source_context_and_can_resolve_same_input(tmp_path):
    one = source(tmp_path / "source.yaml", "Xe")
    document = read(one)
    write(
        tmp_path / "review_queue.yaml",
        {
            "snapshot": str(one.resolve()),
            "source": document["source"],
            "review": [{"original_record": document["records"][0], "reason": "no match"}],
        },
    )
    result = bundle(tmp_path / "result", "Xe")
    assert ingest.ingest(one, result, tmp_path / "overlay.yaml").accepted == 1
    assert read(tmp_path / "review_queue.yaml")["review"] == []


def test_corrupt_queue_does_not_get_overwritten_or_change_overlay(tmp_path):
    result = bundle(tmp_path / "result", "Ar")
    overlay = tmp_path / "overlay.yaml"
    one = source(tmp_path / "source.yaml", "Ar")
    queue = write(tmp_path / "review_queue.yaml", {"review": [{"original_record": None}]})
    original = queue.read_bytes()
    with pytest.raises(ValueError, match="original_record"):
        ingest.ingest(one, result, overlay)
    assert not overlay.exists()
    assert queue.read_bytes() == original


def test_overlay_and_queue_restore_when_second_replace_fails(tmp_path, monkeypatch):
    overlay = write(tmp_path / "overlay.yaml", {"before": "overlay"})
    queue = write(tmp_path / "review_queue.yaml", {"before": "queue"})
    originals = {path: path.read_bytes() for path in (overlay, queue)}
    replace = Path.replace
    failed = False

    def fail_once(path, target):
        nonlocal failed
        if target == queue and not failed:
            failed = True
            raise OSError("injected queue replacement failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_once)
    with pytest.raises(OSError, match="injected queue"):
        ingest._write_outputs({overlay: {"after": "overlay"}, queue: {"after": "queue"}})
    assert {path: path.read_bytes() for path in originals} == originals
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob(".*.backup"))


def test_failed_restore_preserves_named_recovery_backup(tmp_path, monkeypatch):
    overlay = write(tmp_path / "overlay.yaml", {"before": "overlay"})
    queue = write(tmp_path / "review_queue.yaml", {"before": "queue"})
    original = overlay.read_bytes()
    replace = Path.replace

    def fail(path, target):
        if target == queue or path.suffix == ".restore":
            raise OSError("injected failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="rollback was incomplete; recovery files:"):
        ingest._write_outputs({overlay: {"after": "overlay"}, queue: {"after": "queue"}})
    backups = list(tmp_path.glob(".overlay.yaml.*.backup"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
