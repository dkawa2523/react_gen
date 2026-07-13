from pathlib import Path

import yaml

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.data_sources.local_registry import LocalRegistryReactionProvider
from plasma_reactgen.domain.models import CollisionPair
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.preparer import prepare_case
from plasma_reactgen.preparation.reaction_enrichment import enrich_reaction_channels


def test_prepare_case_does_not_requery_local_registry_as_enrichment(tmp_path):
    registry_root = tmp_path / "registry"
    prepared_registry = tmp_path / "prepared_registry"
    for species_id, composition in (
        ("SF6", {"S": 1, "F": 6}),
        ("O2", {"O": 2}),
        ("CF4", {"C": 1, "F": 4}),
    ):
        payload = _neutral_species(species_id, composition)
        _write_yaml(registry_root / "species" / f"{species_id}.yaml", payload)
        _write_yaml(prepared_registry / "species" / f"{species_id}.yaml", payload)

    case_path = tmp_path / "case.yaml"
    _write_yaml(
        case_path,
        {
            "case": {"name": "sf6-o2-property-scope-test"},
            "gases": ["SF6", "O2"],
            "outputs": {"csv_summary": False},
        },
    )
    profile = {
        "name": "local-property-scope-test",
        "properties": ["local_registry"],
        "local_registry": {"root": str(registry_root)},
    }

    report = prepare_case(
        case_path,
        registry_root,
        source_profile=profile,
        output_dir=prepared_registry,
        preserve_local_overlays=True,
    )

    assert report["summary"]["n_properties_written"] == 0
    assert not report.get("unresolved")


def test_sf6_o2_reaction_enrichment_does_not_scan_unrelated_cf_species(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_yaml(
        prepared_registry / "species" / "SF6.yaml",
        _neutral_species("SF6", {"S": 1, "F": 6}),
    )
    _write_yaml(
        prepared_registry / "species" / "O2.yaml",
        _neutral_species("O2", {"O": 2}),
    )
    _write_yaml(
        prepared_registry / "species" / "CF4.yaml",
        _neutral_species("CF4", {"C": 1, "F": 4}),
    )
    _write_yaml(
        prepared_registry / "species" / "SF6_p.yaml",
        _positive_ion_species("SF6+", {"S": 1, "F": 6}),
    )
    _write_yaml(
        prepared_registry / "reactions" / "electron" / "e__SF6.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "SF6"},
            "channels": [
                {
                    "id": "e_SF6_ionization",
                    "type": "ionization",
                    "products": [
                        {"species": "e", "n": 2},
                        {"species": "SF6+", "n": 1},
                    ],
                    "status": "curated",
                    "data": {},
                }
            ],
        },
    )
    config = case_config_from_dict(
        {
            "case": {"name": "sf6-o2-reaction-scope-test"},
            "gases": ["SF6", "O2"],
            "expansion": {"max_depth": 1},
            "outputs": {"csv_summary": False},
        }
    )
    provider = _MissingIdForCfPairsProvider()

    report = enrich_reaction_channels(
        prepared_registry,
        [provider],
        config,
        {"name": "test"},
    )

    assert "ion_neutral|SF6+|SF6" in provider.seen_pair_keys
    assert all("CF" not in pair_key for pair_key in provider.seen_pair_keys)
    assert report["unresolved_reactions"] == []


def test_local_registry_reaction_provider_preserves_channel_id(tmp_path):
    registry_root = tmp_path / "registry"
    _write_yaml(
        registry_root / "reactions" / "electron" / "e__SF6.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "SF6"},
            "channels": [
                {
                    "id": "e_SF6_elastic",
                    "type": "elastic",
                    "products": [
                        {"species": "e", "n": 1},
                        {"species": "SF6", "n": 1},
                    ],
                    "status": "curated",
                    "data": {},
                }
            ],
        },
    )
    provider = LocalRegistryReactionProvider(FileRegistry(registry_root))

    channels = provider.find_channels(CollisionPair("electron", "e", "SF6"))

    assert channels[0]["id"] == "e_SF6_elastic"


class _MissingIdForCfPairsProvider:
    def __init__(self):
        self.seen_pair_keys: list[str] = []

    def find_channels(self, pair):
        self.seen_pair_keys.append(pair.key)
        if pair.target != "CF4":
            return []
        return [
            {
                "type": "elastic",
                "products": [
                    {"species": pair.projectile, "n": 1},
                    {"species": pair.target, "n": 1},
                ],
                "status": "imported",
            }
        ]


def _neutral_species(species_id: str, composition: dict[str, int]):
    return _species(species_id, composition, charge=0, classes=["neutral", "molecule"])


def _positive_ion_species(species_id: str, composition: dict[str, int]):
    return _species(species_id, composition, charge=1, classes=["positive_ion"])


def _species(
    species_id: str,
    composition: dict[str, int],
    *,
    charge: int,
    classes: list[str],
):
    return {
        "schema_version": 1,
        "id": species_id,
        "composition": composition,
        "charge": charge,
        "classes": classes,
        "state": {},
        "properties": {},
        "metadata": {"status": "curated", "notes": []},
    }


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
