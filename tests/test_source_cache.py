import hashlib
from pathlib import Path

import yaml

from plasma_reactgen.data_sources.cache import record_source_file
from plasma_reactgen.data_sources.cross_section_table import import_cross_section_table


def test_record_source_file_copies_file_and_writes_manifest(tmp_path):
    source = tmp_path / "input" / "table.csv"
    source.parent.mkdir()
    source.write_text("energy_eV,cross_section_m2\n0,0\n1,1e-20\n", encoding="utf-8")
    cache_root = tmp_path / "workspace" / "source_cache"

    record = record_source_file(cache_root, "lxcat_offline", source)

    cached = cache_root / record["cached_path"]
    manifest = yaml.safe_load((cache_root / "manifest.yaml").read_text(encoding="utf-8"))
    assert cached.exists()
    assert cached.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert record["source_type"] == "local_file_cache"
    assert record["source_name"] == "lxcat_offline"
    assert record["original_path"] == str(source)
    assert record["sha256"] == _sha256(source)
    assert len(record["imported_at"]) > 10
    assert manifest["schema_version"] == 1
    assert manifest["source_files"] == [record]


def test_repeated_source_file_record_adds_note_and_does_not_crash(tmp_path):
    source = tmp_path / "same.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    cache_root = tmp_path / "source_cache"

    first = record_source_file(cache_root, "manual", source)
    second = record_source_file(cache_root, "manual", source)

    manifest = yaml.safe_load((cache_root / "manifest.yaml").read_text(encoding="utf-8"))
    assert first["sha256"] == second["sha256"]
    assert second["notes"] == ["A source file with the same sha256 was already recorded."]
    assert len(manifest["source_files"]) == 2


def test_import_cross_sections_records_source_cache_and_metadata_link(tmp_path):
    input_file = tmp_path / "e_cf4.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0,0\n"
        "1,1e-20\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    result = import_cross_section_table(
        input_file,
        workspace,
        source="lxcat_offline",
        reaction_id="e_CF4_elastic",
        target="CF4",
    )

    manifest = yaml.safe_load((workspace / "source_cache" / "manifest.yaml").read_text(encoding="utf-8"))
    metadata = yaml.safe_load(result.metadata_path.read_text(encoding="utf-8"))
    record = manifest["source_files"][0]
    assert result.source_cache_record == record
    assert metadata["source_cache"] == record
    assert (workspace / "source_cache" / record["cached_path"]).exists()
    assert record["sha256"] == _sha256(input_file)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
