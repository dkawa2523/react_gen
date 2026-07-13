from __future__ import annotations

from pathlib import Path

import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.data_sources.cross_section_table import import_cross_section_table
from plasma_reactgen.data_sources.source_profile import load_source_profile
from plasma_reactgen.domain.chemistry import make_electron_species
from plasma_reactgen.domain.models import Species, SpeciesAmount
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.validation.validators import validate_reaction


CASES = {
    "ar_o2_simple": {
        "input": Path("benchmarks/cases/ar_o2_simple/input.yaml"),
        "fixture": Path("benchmarks/fixtures/ar_o2_simple"),
    },
    "ar_cf4_fluorocarbon": {
        "input": Path("benchmarks/cases/ar_cf4_fluorocarbon/input.yaml"),
        "fixture": Path("benchmarks/fixtures/ar_cf4_fluorocarbon"),
    },
    "sf6_o2_electronegative": {
        "input": Path("benchmarks/cases/sf6_o2_electronegative/input.yaml"),
        "fixture": Path("benchmarks/fixtures/sf6_o2_electronegative"),
    },
}


def test_semiconductor_benchmark_inputs_parse():
    for case_id, paths in CASES.items():
        config = load_case_config(paths["input"], Path("registry"))
        assert config.case.name == case_id
        assert config.gases
        assert "imported" in config.data_policy.allowed_status


def test_semiconductor_benchmark_source_profiles_load():
    for paths in CASES.values():
        profile = load_source_profile(paths["fixture"] / "source_profile.yaml", Path("registry"))
        assert profile["internal_file"]["root"] == (paths["fixture"] / "internal_data").as_posix()
        assert "internal_file" in profile["species_identity"]
        assert "internal_file" in profile["ion_neutral_reactions"]


def test_semiconductor_fixture_directories_and_cross_sections_import(tmp_path):
    for paths in CASES.values():
        fixture = paths["fixture"]
        assert (fixture / "internal_data/species/species.yaml").exists()
        assert (fixture / "internal_data/properties/properties.yaml").exists()
        assert (fixture / "internal_data/reactions/electron.yaml").exists()
        assert (fixture / "internal_data/reactions/ion_neutral.yaml").exists()
        for csv_path in sorted((fixture / "cross_sections").glob("*.csv")):
            result = import_cross_section_table(
                csv_path,
                tmp_path / csv_path.parent.parent.name,
                source="local_file",
                reaction_id=csv_path.stem,
                target=csv_path.stem.split("_")[1],
                license_note="synthetic benchmark fixture",
            )
            assert result.asset_path.exists()
            assert result.metadata_path.exists()
            assert result.row_count >= 3


def test_semiconductor_fixture_reactions_are_balanced():
    registry_species = _load_registry_species(Path("registry"))
    for paths in CASES.values():
        species = dict(registry_species)
        species.update(_load_fixture_species(paths["fixture"] / "internal_data/species/species.yaml"))
        for reaction_file in (
            paths["fixture"] / "internal_data/reactions/electron.yaml",
            paths["fixture"] / "internal_data/reactions/ion_neutral.yaml",
        ):
            for pair, channel in _iter_channels(reaction_file):
                for product in channel.get("products", []):
                    candidate = product.get("species_candidate")
                    species_id = product.get("species")
                    if species_id and species_id not in species and isinstance(candidate, dict):
                        species[species_id] = _species_from_candidate(species_id, candidate)

                reactants = [SpeciesAmount(pair["projectile"]), SpeciesAmount(pair["target"])]
                products = [
                    SpeciesAmount(product["species"], float(product.get("n", 1.0)))
                    for product in channel.get("products", [])
                ]
                validation = validate_reaction(reactants, products, species)
                assert validation == {
                    "species_reference": "ok",
                    "charge_balance": "ok",
                    "element_balance": "ok",
                }, (reaction_file, channel.get("id"), validation)


def test_semiconductor_benchmark_config_default_case_ids():
    expected = [
        "ar_o2_simple",
        "ar_cf4_fluorocarbon",
        "sf6_o2_electronegative",
    ]
    config = _read_yaml(Path("benchmarks/benchmark_config_semiconductor.yaml"))
    ids = [item["id"] for item in config["benchmarks"]]
    assert ids == expected
    assert "cl2_bcl3_halogen" not in yaml.safe_dump(config, sort_keys=True)


def test_semiconductor_benchmark_docs_do_not_make_cl2_bcl3_default():
    text = Path("docs/semiconductor_benchmark_cases.md").read_text(encoding="utf-8")
    assert "Cl2/BCl3 is not a default benchmark case" in text
    assert "ar_o2_simple" in text
    assert "sf6_o2_electronegative" in text


def test_semiconductor_fixtures_do_not_mutate_curated_registry(tmp_path):
    before = _snapshot_yaml(Path("registry"))
    for paths in CASES.values():
        for csv_path in sorted((paths["fixture"] / "cross_sections").glob("*.csv")):
            import_cross_section_table(csv_path, tmp_path / paths["fixture"].name, source="local_file")
    assert _snapshot_yaml(Path("registry")) == before


def _load_registry_species(root: Path) -> dict[str, Species]:
    registry = FileRegistry(root)
    species = {"e": make_electron_species()}
    for path in registry.iter_species_files():
        payload = _read_yaml(path)
        species_id = payload.get("id")
        if species_id:
            loaded = registry.get_species(species_id)
            if loaded is not None:
                species[species_id] = loaded
    return species


def _load_fixture_species(path: Path) -> dict[str, Species]:
    records = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {
        record["id"]: Species(
            id=record["id"],
            composition=dict(record.get("composition", {})),
            charge=int(record.get("charge", 0)),
            classes=set(record.get("classes", [])),
            state=dict(record.get("state", {})),
            status=record.get("status", "imported"),
        )
        for record in records
    }


def _iter_channels(path: Path):
    records = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for record in records:
        pair = record["pair"]
        for channel in record.get("channels", []):
            yield pair, channel


def _species_from_candidate(species_id: str, candidate: dict) -> Species:
    return Species(
        id=species_id,
        composition=dict(candidate.get("composition", {})),
        charge=int(candidate.get("charge", 0)),
        classes=set(candidate.get("classes", [])),
        state=dict(candidate.get("state", {})),
        status=candidate.get("status", "imported"),
    )


def _snapshot_yaml(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.yaml"))
    }


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
