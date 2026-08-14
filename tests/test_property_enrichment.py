from pathlib import Path

import yaml

from plasma_reactgen.preparation.property_enrichment import enrich_species_properties


def test_enrichment_fills_missing_property_with_provenance(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(
        prepared_registry,
        "CF4",
        {"mass_amu": {"value": None, "unit": "amu", "source": None}},
    )
    provider = _PropertyProvider(
        {
            ("CF4", "mass_amu"): {
                "species": "CF4",
                "property": "mass_amu",
                "value": 88.0043,
                "unit": "amu",
                "source": "test source",
                "source_record": _source_record("test:CF4:mass"),
            }
        }
    )

    report = enrich_species_properties(prepared_registry, [provider], {"name": "test"})

    species = _read_species(prepared_registry, "CF4")
    assert species["properties"]["mass_amu"]["value"] == 88.0043
    assert species["properties"]["mass_amu"]["unit"] == "amu"
    assert species["properties"]["mass_amu"]["source"] == "test source"
    assert species["properties"]["mass_amu"]["source_record"] == _source_record("test:CF4:mass")
    assert species["metadata"]["property_sources"]["mass_amu"] == _source_record("test:CF4:mass")
    assert report["summary"]["n_properties_filled"] == 1


def test_enrichment_does_not_overwrite_existing_curated_property_and_reports_conflict(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(
        prepared_registry,
        "CF4",
        {"polarizability_A3": {"value": 2.824, "unit": "A3", "source": "curated"}},
    )
    provider = _PropertyProvider(
        {
            ("CF4", "polarizability_A3"): {
                "species": "CF4",
                "property": "polarizability_A3",
                "value": 3.86,
                "unit": "A3",
                "source": "candidate",
                "source_record": _source_record("test:CF4:polarizability"),
            }
        }
    )

    report = enrich_species_properties(prepared_registry, [provider], {"name": "test"})

    species = _read_species(prepared_registry, "CF4")
    assert species["properties"]["polarizability_A3"]["value"] == 2.824
    assert report["property_conflicts"] == [
        {
            "kind": "property_conflict",
            "species": "CF4",
            "property": "polarizability_A3",
            "existing_value": 2.824,
            "candidate_value": 3.86,
            "candidate_source": _source_record("test:CF4:polarizability"),
            "action": "manual_review",
        }
    ]


def test_enrichment_skips_unsupported_unit(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF4", {})
    provider = _PropertyProvider(
        {
            ("CF4", "enthalpy_formation_eV"): {
                "species": "CF4",
                "property": "enthalpy_formation_eV",
                "value": -933.2,
                "unit": "kJ/mol",
                "source": "unsupported",
                "source_record": _source_record("test:CF4:enthalpy"),
            }
        }
    )

    report = enrich_species_properties(prepared_registry, [provider], {"name": "test"})

    species = _read_species(prepared_registry, "CF4")
    assert "enthalpy_formation_eV" not in species["properties"]
    assert {
        "kind": "unsupported_unit",
        "species": "CF4",
        "property": "enthalpy_formation_eV",
        "candidate_unit": "kJ/mol",
        "expected_unit": "eV",
        "candidate_source": _source_record("test:CF4:enthalpy"),
    } in report["unresolved"]


def test_enrichment_uses_source_profile_order_for_supported_candidates(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF4", {})
    provider = _MultiPropertyProvider(
        [
            {
                "species": "CF4",
                "property": "mass_amu",
                "value": 1.0,
                "unit": "amu",
                "source": "local",
                "status": "imported",
                "source_record": {"source_type": "local_registry", "source_id": "CF4.mass_amu"},
            },
            {
                "species": "CF4",
                "property": "mass_amu",
                "value": 88.0043,
                "unit": "amu",
                "source": "internal",
                "status": "imported",
                "source_record": {
                    "source_type": "internal_file_db",
                    "source_id": "internal:CF4.mass_amu",
                },
            },
        ]
    )

    enrich_species_properties(
        prepared_registry,
        [provider],
        {"name": "internal_first", "properties": ["internal_property_db", "local_registry"]},
    )

    species = _read_species(prepared_registry, "CF4")
    assert species["properties"]["mass_amu"]["value"] == 88.0043
    assert species["properties"]["mass_amu"]["source"] == "internal"


def test_null_candidate_is_not_applied_and_matching_value_is_not_a_conflict(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(
        prepared_registry,
        "CF4",
        {"mass_amu": {"value": 88.0043, "unit": "amu", "source": "curated"}},
    )
    provider = _MultiPropertyProvider(
        [
            {
                "species": "CF4",
                "property": "mass_amu",
                "value": 88.0043,
                "unit": "amu",
                "source_record": _source_record("same-value"),
            },
            {
                "species": "CF4",
                "property": "collision_radius_A",
                "value": None,
                "unit": "A",
                "source_record": _source_record("missing-value"),
            },
        ]
    )

    report = enrich_species_properties(
        prepared_registry,
        [object(), provider],
        {"name": "test"},
    )

    species = _read_species(prepared_registry, "CF4")
    assert species["properties"]["mass_amu"]["source"] == "curated"
    assert "collision_radius_A" not in species["properties"]
    assert report["property_conflicts"] == []
    assert {
        "kind": "missing_property",
        "species": "CF4",
        "property": "collision_radius_A",
        "reason": "no_supported_candidate",
        "required_by": "dnt_readiness",
    } in report["unresolved"]


def test_collision_radius_is_not_invented(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF4", {})

    report = enrich_species_properties(prepared_registry, [], {"name": "test"})

    species = _read_species(prepared_registry, "CF4")
    assert "collision_radius_A" not in species["properties"]
    assert {
        "kind": "missing_property",
        "species": "CF4",
        "property": "collision_radius_A",
        "reason": "no_supported_candidate",
        "required_by": "dnt_readiness",
    } in report["unresolved"]


def test_enrichment_can_be_limited_to_selected_species(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF3", {})
    _write_species(prepared_registry, "CF4", {})
    provider = _PropertyProvider(
        {
            ("CF3", "mass_amu"): {
                "species": "CF3",
                "property": "mass_amu",
                "value": 69.0,
                "unit": "amu",
                "source": "seeded product source",
                "source_record": _source_record("test:CF3:mass"),
            },
            ("CF4", "mass_amu"): {
                "species": "CF4",
                "property": "mass_amu",
                "value": 88.0,
                "unit": "amu",
                "source": "gas source",
                "source_record": _source_record("test:CF4:mass"),
            },
        }
    )

    report = enrich_species_properties(
        prepared_registry,
        [provider],
        {"name": "test"},
        species_ids=["CF3"],
    )

    assert _read_species(prepared_registry, "CF3")["properties"]["mass_amu"]["value"] == 69.0
    assert "mass_amu" not in _read_species(prepared_registry, "CF4")["properties"]
    assert report["summary"]["n_properties_filled"] == 1


class _PropertyProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    def find_properties(self, species_id, names=None):
        requested = names or []
        return [
            self.candidates[(species_id, name)]
            for name in requested
            if (species_id, name) in self.candidates
        ]


class _MultiPropertyProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    def find_properties(self, species_id, names=None):
        requested = set(names or [])
        return [
            candidate
            for candidate in self.candidates
            if candidate.get("species") == species_id and candidate.get("property") in requested
        ]


def _source_record(source_id):
    return {
        "source_type": "test",
        "source_id": source_id,
        "evidence_type": "fixture",
    }


def _write_species(prepared_registry: Path, species_id: str, properties: dict) -> None:
    path = prepared_registry / "species" / f"{species_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": species_id,
                "composition": {},
                "charge": 0,
                "classes": ["neutral"],
                "properties": properties,
                "metadata": {"status": "prepared"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _read_species(prepared_registry: Path, species_id: str):
    return yaml.safe_load(
        (prepared_registry / "species" / f"{species_id}.yaml").read_text(encoding="utf-8")
    )
