from plasma_reactgen.data_sources.selection import (
    select_first_candidate,
    source_rank,
    status_rank,
)


def test_status_rank_curated_beats_imported():
    profile = {"properties": ["local_registry"]}

    assert status_rank("curated", profile) < status_rank("imported", profile)
    assert select_first_candidate(
        [
            {"value": 1, "status": "imported", "source_name": "local_registry"},
            {"value": 2, "status": "curated", "source_name": "local_registry"},
        ],
        "properties",
        profile,
    )["value"] == 2


def test_internal_first_profile_prioritizes_internal_source():
    profile = {
        "properties": ["internal_property_db", "local_registry"],
        "policy": {"prefer_status": ["curated", "literature_supported", "imported"]},
    }

    selected = select_first_candidate(
        [
            {
                "value": 1,
                "status": "imported",
                "source_record": {"source_type": "local_registry"},
            },
            {
                "value": 2,
                "status": "imported",
                "source_record": {"source_type": "internal_file_db"},
            },
        ],
        "properties",
        profile,
    )

    assert selected["value"] == 2


def test_unknown_source_goes_last():
    profile = {"properties": ["local_registry"]}

    assert source_rank("unknown", "properties", profile) > source_rank("local_registry", "properties", profile)
    selected = select_first_candidate(
        [
            {"value": 1, "status": "curated", "source_name": "unknown"},
            {"value": 2, "status": "imported", "source_name": "local_registry"},
        ],
        "properties",
        profile,
    )

    assert selected["value"] == 2


def test_empty_candidates_returns_none():
    assert select_first_candidate([], "properties", {"properties": ["local_registry"]}) is None
