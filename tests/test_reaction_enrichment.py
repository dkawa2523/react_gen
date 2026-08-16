from pathlib import Path

import yaml

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.reaction_enrichment import enrich_reaction_channels


def test_reaction_enrichment_writes_provider_channel_and_product_species_seed(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    config = _case_config()
    provider = _ReactionProvider([_valid_dissociation_channel()])

    report = enrich_reaction_channels(prepared_registry, [provider], config, {"name": "test"})

    reaction_file = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(encoding="utf-8")
    )
    assert report["summary"]["n_reaction_channels_imported"] == 1
    assert report["reaction_channels_imported"] == [
        {"pair": "electron|e|CF4", "id": "e_CF4_dissociation_CF3_F"}
    ]
    assert reaction_file["channels"][0]["id"] == "e_CF4_dissociation_CF3_F"
    assert reaction_file["channels"][0]["status"] == "literature_supported"
    assert reaction_file["channels"][0]["data"]["source_record"] == {
        "source_type": "internal_file_db",
        "source_id": "internal_reaction:e_CF4_dissociation_CF3_F",
    }
    assert (prepared_registry / "species" / "CF3.yaml").exists()
    assert (prepared_registry / "species" / "F.yaml").exists()


def test_reaction_enrichment_does_not_overwrite_duplicate_channel(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    _write_yaml(
        prepared_registry / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
            "channels": [
                {
                    "id": "e_CF4_dissociation_CF3_F",
                    "type": "dissociation",
                    "products": [{"species": "e", "n": 1}, {"species": "CF4", "n": 1}],
                    "status": "curated",
                    "data": {"note": "keep me"},
                }
            ],
        },
    )
    provider = _ReactionProvider([_valid_dissociation_channel()])

    report = enrich_reaction_channels(prepared_registry, [provider], _case_config(), {"name": "test"})

    reaction_file = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(encoding="utf-8")
    )
    assert report["reaction_channels_skipped"] == [
        {
            "pair": "electron|e|CF4",
            "id": "e_CF4_dissociation_CF3_F",
            "reason": "duplicate_channel",
        }
    ]
    assert len(reaction_file["channels"]) == 1
    assert reaction_file["channels"][0]["status"] == "curated"
    assert reaction_file["channels"][0]["data"] == {"note": "keep me"}


def test_reaction_enrichment_skips_invalid_charge_balance(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    provider = _ReactionProvider(
        [
            {
                "id": "e_CF4_invalid_ionization",
                "type": "ionization",
                "products": [
                    {
                        "species": "CF4+",
                        "n": 1,
                        "species_candidate": {
                            "composition": {"C": 1, "F": 4},
                            "charge": 1,
                            "classes": ["positive_ion"],
                            "status": "imported",
                        },
                    }
                ],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "bad"},
            }
        ]
    )

    report = enrich_reaction_channels(prepared_registry, [provider], _case_config(), {"name": "test"})

    assert report["summary"]["n_reaction_channels_imported"] == 0
    assert report["reaction_channels_skipped"][0]["reason"] == "validation_failed"
    assert report["reaction_channels_skipped"][0]["validation"]["charge_balance"] == "failed"


def test_reaction_enrichment_reports_missing_product_species(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    provider = _ReactionProvider(
        [
            {
                "id": "e_CF4_missing_product",
                "type": "dissociation",
                "products": [{"species": "e", "n": 1}, {"species": "CF3", "n": 1}],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "missing_product"},
            }
        ]
    )

    report = enrich_reaction_channels(prepared_registry, [provider], _case_config(), {"name": "test"})

    assert report["summary"]["n_reaction_channels_imported"] == 0
    assert report["unresolved_reactions"] == [
        {
            "pair": "electron|e|CF4",
            "id": "e_CF4_missing_product",
            "reason": "missing_product_species",
        }
    ]


def test_reaction_enrichment_seeds_product_species_from_species_provider(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    provider = _ReactionProvider(
        [
            {
                "id": "e_CF4_dissociation_CF3_F",
                "type": "dissociation",
                "products": [
                    {"species": "e", "n": 1},
                    {"species": "CF3", "n": 1},
                    {"species": "F", "n": 1},
                ],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "reaction:cf3_f"},
            }
        ]
    )
    species_provider = _SpeciesProvider(
        {
            "CF3": {
                "id": "CF3",
                "composition": {"C": 1, "F": 3},
                "charge": 0,
                "classes": ["neutral", "radical"],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "species:CF3"},
            },
            "F": {
                "id": "F",
                "composition": {"F": 1},
                "charge": 0,
                "classes": ["neutral", "atom"],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "species:F"},
            },
        }
    )

    report = enrich_reaction_channels(
        prepared_registry,
        [provider],
        _case_config(),
        {"name": "test"},
        species_providers=[species_provider],
    )

    assert report["summary"]["n_reaction_channels_imported"] == 1
    assert report["summary"]["n_species_seeded_from_reactions"] == 2
    assert {item["species"] for item in report["species_seeded_from_reactions"]} == {"CF3", "F"}
    assert (prepared_registry / "species" / "CF3.yaml").exists()
    assert (prepared_registry / "species" / "F.yaml").exists()


def test_reaction_enrichment_rejects_incomplete_provider_species_candidate(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    provider = _ReactionProvider(
        [
            {
                "id": "e_CF4_dissociation_incomplete",
                "type": "dissociation",
                "products": [{"species": "e", "n": 1}, {"species": "CF3", "n": 1}],
                "status": "imported",
                "source_record": {"source_type": "internal_file_db", "source_id": "reaction:bad"},
            }
        ]
    )
    species_provider = _SpeciesProvider(
        {
            "CF3": {
                "id": "CF3",
                "composition": {"C": 1, "F": 3},
                "classes": ["neutral", "radical"],
                "status": "imported",
            }
        }
    )

    report = enrich_reaction_channels(
        prepared_registry,
        [provider],
        _case_config(),
        {"name": "test"},
        species_providers=[species_provider],
    )

    assert report["summary"]["n_reaction_channels_imported"] == 0
    assert report["unresolved_reactions"] == [
        {
            "pair": "electron|e|CF4",
            "id": "e_CF4_dissociation_incomplete",
            "reason": "incomplete_species_candidate",
        }
    ]
    assert report["unresolved_product_species"] == [
        {
            "pair": "electron|e|CF4",
            "channel": "e_CF4_dissociation_incomplete",
            "species": "CF3",
            "reason": "incomplete_species_candidate",
        }
    ]
    assert not (prepared_registry / "species" / "CF3.yaml").exists()


def test_enriched_prepared_registry_can_be_used_by_generate(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    config = _case_config()
    enrich_reaction_channels(prepared_registry, [_ReactionProvider([_valid_dissociation_channel()])], config, {"name": "test"})

    registry = FileRegistry(prepared_registry)
    network = ReactionNetworkBuilder(
        NetworkBuilderDependencies(
            species_repo=registry,
            reaction_repo=registry,
            rule_repo=registry,
        )
    ).generate(config)

    assert any(reaction.id == "e_CF4_dissociation_CF3_F" for reaction in network.reactions)


def test_reaction_enrichment_imports_provider_channels_across_depths(tmp_path):
    prepared_registry = _make_base_prepared_registry(tmp_path / "prepared_registry")
    config = case_config_from_dict(
        {
            "case": {"name": "reaction-enrichment-depth-test"},
            "gases": ["CF4"],
            "expansion": {"max_depth": 3},
            "outputs": {"csv_summary": False},
        }
    )
    provider = _DepthReactionProvider()

    report = enrich_reaction_channels(prepared_registry, [provider], config, {"name": "test"})

    assert report["summary"]["n_reaction_channels_imported"] == 4
    assert (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").exists()
    assert (prepared_registry / "reactions" / "electron" / "e__CF3.yaml").exists()
    assert (prepared_registry / "reactions" / "electron" / "e__CF2.yaml").exists()
    assert (prepared_registry / "reactions" / "electron" / "e__CF.yaml").exists()
    assert (prepared_registry / "species" / "CF.yaml").exists()


class _ReactionProvider:
    def __init__(self, channels):
        self.channels = channels

    def find_channels(self, pair):
        if pair.family == "electron" and pair.projectile == "e" and pair.target == "CF4":
            return self.channels
        return []


class _SpeciesProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    def find_species(self, query):
        candidate = self.candidates.get(query)
        return [candidate] if candidate is not None else []


class _DepthReactionProvider:
    def find_channels(self, pair):
        return {
            "electron|e|CF4": [
                _dissociation_with_candidate("e_CF4_to_CF3_F", "CF3", {"C": 1, "F": 3}, "F", {"F": 1})
            ],
            "electron|e|CF3": [
                _dissociation_with_candidate("e_CF3_to_CF2_F", "CF2", {"C": 1, "F": 2}, "F", {"F": 1})
            ],
            "electron|e|CF2": [
                _dissociation_with_candidate("e_CF2_to_CF_F", "CF", {"C": 1, "F": 1}, "F", {"F": 1})
            ],
            "electron|e|CF": [
                {
                    "id": "e_CF_elastic",
                    "type": "elastic",
                    "products": [{"species": "e", "n": 1}, {"species": "CF", "n": 1}],
                    "status": "imported",
                    "source_record": {"source_type": "internal_file_db", "source_id": "reaction:e_CF_elastic"},
                }
            ],
        }.get(pair.key, [])


def _valid_dissociation_channel():
    return {
        "id": "e_CF4_dissociation_CF3_F",
        "type": "dissociation",
        "products": [
            {"species": "e", "n": 1},
            {
                "species": "CF3",
                "n": 1,
                "species_candidate": {
                    "composition": {"C": 1, "F": 3},
                    "charge": 0,
                    "classes": ["neutral", "radical"],
                    "status": "imported",
                    "source_record": {
                        "source_type": "internal_file_db",
                        "source_id": "internal_species:CF3",
                    },
                },
            },
            {
                "species": "F",
                "n": 1,
                "species_candidate": {
                    "composition": {"F": 1},
                    "charge": 0,
                    "classes": ["neutral", "atom"],
                    "status": "imported",
                    "source_record": {
                        "source_type": "internal_file_db",
                        "source_id": "internal_species:F",
                    },
                },
            },
        ],
        "threshold_eV": 12.5,
        "status": "literature_supported",
        "source_record": {
            "source_type": "internal_file_db",
            "source_id": "internal_reaction:e_CF4_dissociation_CF3_F",
        },
    }


def _dissociation_with_candidate(channel_id, product_a, composition_a, product_b, composition_b):
    return {
        "id": channel_id,
        "type": "dissociation",
        "products": [
            {"species": "e", "n": 1},
            {
                "species": product_a,
                "n": 1,
                "species_candidate": {
                    "composition": composition_a,
                    "charge": 0,
                    "classes": ["neutral", "radical"],
                    "status": "imported",
                    "source_record": {"source_type": "internal_file_db", "source_id": f"species:{product_a}"},
                },
            },
            {
                "species": product_b,
                "n": 1,
                "species_candidate": {
                    "composition": composition_b,
                    "charge": 0,
                    "classes": ["neutral", "atom"],
                    "status": "imported",
                    "source_record": {"source_type": "internal_file_db", "source_id": f"species:{product_b}"},
                },
            },
        ],
        "status": "imported",
        "source_record": {"source_type": "internal_file_db", "source_id": f"reaction:{channel_id}"},
    }


def _case_config():
    return case_config_from_dict(
        {
            "case": {"name": "reaction-enrichment-test"},
            "gases": ["CF4"],
            "expansion": {"max_depth": 0},
            "outputs": {"csv_summary": False},
        }
    )


def _make_base_prepared_registry(root: Path) -> Path:
    _write_yaml(
        root / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
            "properties": {},
            "metadata": {"status": "prepared", "notes": []},
        },
    )
    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {
            "schema_version": 1,
            "electron": {"dissociation": {"expands_species": True}, "ionization": {"expands_species": True}},
            "ion_neutral": {},
        },
    )
    _write_yaml(root / "rules" / "role_required_properties.yaml", {"schema_version": 1})
    return root


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
