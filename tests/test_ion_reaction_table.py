from pathlib import Path

import yaml

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.data_sources.ion_reaction_table import IonReactionTableProvider
from plasma_reactgen.data_sources.registry import get_providers, register_ion_reaction_table_provider
from plasma_reactgen.domain.models import CollisionPair
from plasma_reactgen.preparation.reaction_enrichment import enrich_reaction_channels


def test_ion_reaction_table_returns_matching_reaction_with_provenance(tmp_path):
    table = _make_table(tmp_path / "ion_reactions.yaml", [_valid_reaction()])
    provider = IonReactionTableProvider(table)

    channels = provider.find_channels(CollisionPair("ion_neutral", "Ar+", "CF4"))

    assert len(channels) == 1
    channel = channels[0]
    assert channel["id"] == "Arp_CF4_dct_CF3p"
    assert channel["pair"] == {"family": "ion_neutral", "projectile": "Ar+", "target": "CF4"}
    assert channel["dnt_class"] == "short_range_charge_exchange"
    assert channel["deltaE_products_minus_reactants_eV"] == -1.0891
    assert channel["citation"] == "local literature table"
    assert channel["status"] == "literature_supported"
    assert channel["source_record"] == {
        "source_type": "local_snapshot",
        "database": "internal_ion_reaction_db",
        "version": "2026-06",
        "source_id": "Arp_CF4_dct_CF3p",
        "citation": "local literature table",
        "evidence_type": "experimental_or_literature",
    }


def test_ion_reaction_table_ignores_nonmatching_pair_and_non_ion_family(tmp_path):
    table = _make_table(
        tmp_path / "ion_reactions.yaml",
        [
            _valid_reaction(),
            {
                "id": "e_CF4_ignore",
                "family": "electron",
                "projectile": "e",
                "target": "CF4",
                "type": "elastic",
                "products": [],
            },
        ],
    )
    provider = IonReactionTableProvider(table)

    assert provider.find_channels(CollisionPair("ion_neutral", "CF3+", "CF4")) == []
    assert provider.find_channels(CollisionPair("electron", "e", "CF4")) == []


def test_register_ion_reaction_table_provider_returns_profile_provider(tmp_path):
    table = _make_table(tmp_path / "ion_reactions.yaml", [_valid_reaction()])

    register_ion_reaction_table_provider([table])
    provider = get_providers("ion_neutral_reactions", {"ion_neutral_reactions": ["ion_reaction_table"]})[0]

    assert provider.find_reactions(["Ar+", "CF4"], family="ion_neutral")[0]["id"] == "Arp_CF4_dct_CF3p"


def test_valid_ion_reaction_table_channel_is_written_and_provenance_preserved(tmp_path):
    prepared_registry = _make_prepared_registry(tmp_path / "prepared_registry")
    provider = IonReactionTableProvider(_make_table(tmp_path / "ion_reactions.yaml", [_valid_reaction()]))

    report = enrich_reaction_channels(prepared_registry, [provider], _case_config(), {"name": "test"})

    payload = _read_yaml(prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml")
    channel = payload["channels"][0]
    assert report["summary"]["n_reaction_channels_imported"] == 1
    assert channel["id"] == "Arp_CF4_dct_CF3p"
    assert channel["status"] == "literature_supported"
    assert channel["data"]["source_record"]["database"] == "internal_ion_reaction_db"
    assert channel["data"]["provenance"] == channel["data"]["source_record"]
    assert channel["citation"] == "local literature table"


def test_invalid_ion_reaction_table_balance_is_skipped_by_enrichment(tmp_path):
    prepared_registry = _make_prepared_registry(tmp_path / "prepared_registry")
    invalid = _valid_reaction()
    invalid["id"] = "Arp_CF4_invalid_missing_F"
    invalid["products"] = [{"species": "Ar", "n": 1}, {"species": "CF3+", "n": 1}]
    provider = IonReactionTableProvider(_make_table(tmp_path / "ion_reactions.yaml", [invalid]))

    report = enrich_reaction_channels(prepared_registry, [provider], _case_config(), {"name": "test"})

    assert report["summary"]["n_reaction_channels_imported"] == 0
    assert report["reaction_channels_skipped"] == [
        {
            "pair": "ion_neutral|Ar+|CF4",
            "id": "Arp_CF4_invalid_missing_F",
            "reason": "validation_failed",
            "validation": {
                "species_reference": "ok",
                "charge_balance": "ok",
                "element_balance": "failed",
            },
        }
    ]
    assert not (prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml").exists()


def _valid_reaction() -> dict:
    return {
        "id": "Arp_CF4_dct_CF3p",
        "projectile": "Ar+",
        "target": "CF4",
        "family": "ion_neutral",
        "type": "dissociative_charge_transfer",
        "dnt_class": "short_range_charge_exchange",
        "products": [
            {"species": "Ar", "n": 1},
            {"species": "CF3+", "n": 1},
            {"species": "F", "n": 1},
        ],
        "deltaE_products_minus_reactants_eV": -1.0891,
        "status": "literature_supported",
        "evidence_type": "experimental_or_literature",
        "citation": "local literature table",
    }


def _case_config():
    return case_config_from_dict(
        {
            "case": {"name": "ion-reaction-table-test"},
            "gases": ["Ar+", "CF4"],
            "expansion": {"max_depth": 0},
            "outputs": {"csv_summary": False},
        }
    )


def _make_prepared_registry(root: Path) -> Path:
    _write_species(root, "Ar+", {"Ar": 1}, 1, ["positive_ion", "atom"])
    _write_species(root, "Ar", {"Ar": 1}, 0, ["neutral", "atom"])
    _write_species(root, "CF4", {"C": 1, "F": 4}, 0, ["neutral", "molecule"])
    _write_species(root, "CF3+", {"C": 1, "F": 3}, 1, ["positive_ion"])
    _write_species(root, "F", {"F": 1}, 0, ["neutral", "atom"])
    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {
            "schema_version": 1,
            "electron": {},
            "ion_neutral": {
                "dissociative_charge_transfer": {"expands_species": True},
            },
        },
    )
    _write_yaml(root / "rules" / "role_required_properties.yaml", {"schema_version": 1})
    return root


def _write_species(root: Path, species_id: str, composition: dict, charge: int, classes: list[str]) -> None:
    _write_yaml(
        root / "species" / f"{species_id.replace('+', '_p')}.yaml",
        {
            "schema_version": 1,
            "id": species_id,
            "composition": composition,
            "charge": charge,
            "classes": classes,
            "properties": {},
            "metadata": {"status": "prepared"},
        },
    )


def _make_table(path: Path, reactions: list[dict]) -> Path:
    _write_yaml(
        path,
        {
            "schema_version": 1,
            "source": {
                "source_type": "local_snapshot",
                "database": "internal_ion_reaction_db",
                "version": "2026-06",
            },
            "reactions": reactions,
        },
    )
    return path


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
