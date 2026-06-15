from pathlib import Path
import hashlib

import yaml

from external_data_tools.cache import copy_to_cache, safe_filename, sha256_file
from external_data_tools.config import load_config
from external_data_tools.manifest import append_record, load_manifest


def test_sha256_file_matches_known_hash(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("react-gen\n", encoding="utf-8")

    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_safe_filename_replaces_unsafe_text():
    assert safe_filename("CF4 table.csv") == "CF4_table.csv"
    assert safe_filename("nist/webbook:CF4") == "nist_webbook_CF4"
    assert safe_filename("Ar+ + CF4") == "Ar_CF4"
    assert safe_filename("delta \u0394 sigma") == "delta_sigma"
    assert safe_filename("///") == "unknown"


def test_copy_to_cache_copies_file_and_returns_source_record(tmp_path):
    source = tmp_path / "inputs" / "table.csv"
    source.parent.mkdir()
    source.write_text("energy_eV,cross_section_m2\n0,0\n1,1e-20\n", encoding="utf-8")
    cache_dir = tmp_path / "external_data" / "raw"

    record = copy_to_cache(source, cache_dir, "LXCat Offline")

    cached_path = Path(record["cached_path"])
    assert cached_path.exists()
    assert cached_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert cached_path.parent == cache_dir / "LXCat_Offline"
    assert cached_path.name.startswith("table_")
    assert record["original_path"] == str(source)
    assert record["sha256"] == sha256_file(source)
    assert record["source_name"] == "LXCat Offline"
    assert len(record["imported_at"]) > 10


def test_manifest_append_creates_and_appends_records(tmp_path):
    manifest_path = tmp_path / "external_data" / "manifests" / "manifest.yaml"
    first = {"source_name": "first", "sha256": "abc"}
    second = {"source_name": "second", "sha256": "def"}

    assert load_manifest(manifest_path) == {"schema_version": 1, "records": []}

    append_record(manifest_path, first)
    append_record(manifest_path, second)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": 1,
        "records": [first, second],
    }


def test_load_config_defaults_and_env_overrides():
    defaults = load_config({})
    assert defaults.data_home == Path("external_data")
    assert defaults.cache_dir == Path("external_data/raw")
    assert defaults.user_agent == "react_gen_external_data_tools/0.1"
    assert defaults.http_timeout == 30.0
    assert defaults.http_sleep_seconds == 1.0

    overridden = load_config(
        {
            "REACTGEN_DATA_HOME": "custom_data",
            "REACTGEN_EXTERNAL_CACHE": "custom_cache",
            "REACTGEN_USER_AGENT": "test-agent",
            "REACTGEN_HTTP_TIMEOUT": "12.5",
            "REACTGEN_HTTP_SLEEP_SECONDS": "0.25",
        }
    )
    assert overridden.data_home == Path("custom_data")
    assert overridden.cache_dir == Path("custom_cache")
    assert overridden.user_agent == "test-agent"
    assert overridden.http_timeout == 12.5
    assert overridden.http_sleep_seconds == 0.25

    invalid = load_config(
        {
            "REACTGEN_HTTP_TIMEOUT": "not-a-number",
            "REACTGEN_HTTP_SLEEP_SECONDS": "also-bad",
        }
    )
    assert invalid.http_timeout == 30.0
    assert invalid.http_sleep_seconds == 1.0
