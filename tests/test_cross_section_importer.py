from pathlib import Path

import pytest
import yaml

from plasma_reactgen.data_sources.cross_section_table import import_cross_section_table
from plasma_reactgen.data_sources.lxcat_offline import LxcatOfflineCrossSectionProvider
from plasma_reactgen.data_sources.registry import get_providers, register_lxcat_offline_provider
from plasma_reactgen.domain.models import CollisionPair
from plasma_reactgen.interface.cli import main


def test_valid_csv_imports_normalized_asset_and_sorted_rows(tmp_path):
    input_file = tmp_path / "e_cf4.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2,process,target\n"
        "2.0,2.5e-20,elastic,CF4\n"
        "0.0,0.0,elastic,CF4\n",
        encoding="utf-8",
    )

    result = import_cross_section_table(
        input_file,
        tmp_path / "workspace",
        source="lxcat_offline",
        reaction_id="e_CF4_elastic",
        target="CF4",
    )

    assert result.asset_path.exists()
    assert result.metadata_path.exists()
    assert result.row_count == 2
    assert result.relative_asset_path.startswith("assets/cross_sections/e_CF4_elastic_")
    assert result.asset_path.read_text(encoding="utf-8").splitlines() == [
        "energy_eV,cross_section_m2",
        "0.0,0.0",
        "2.0,2.5e-20",
    ]


def test_negative_cross_section_fails(tmp_path):
    input_file = tmp_path / "bad.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0.0,0.0\n"
        "1.0,-1.0e-20\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-negative"):
        import_cross_section_table(input_file, tmp_path / "workspace")


def test_nonnumeric_value_fails(tmp_path):
    input_file = tmp_path / "bad.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0.0,0.0\n"
        "oops,1.0e-20\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="energy_eV must be numeric"):
        import_cross_section_table(input_file, tmp_path / "workspace")


def test_metadata_sidecar_contains_source_hash_and_energy_bounds(tmp_path):
    input_file = tmp_path / "e_cf4.tsv"
    input_file.write_text(
        "energy_eV\tcross_section_m2\tcomment\n"
        "0\t0\tthreshold\n"
        "5\t1.2e-20\tpeak\n",
        encoding="utf-8",
    )

    result = import_cross_section_table(
        input_file,
        tmp_path / "workspace",
        source="local_file",
        target="CF4",
        license_note="local lab file; do not redistribute",
    )
    metadata = yaml.safe_load(result.metadata_path.read_text(encoding="utf-8"))

    assert metadata["source_type"] == "local_file"
    assert metadata["database"] == "user_provided"
    assert metadata["original_file"] == str(input_file)
    assert metadata["columns"] == ["energy_eV", "cross_section_m2", "comment"]
    assert metadata["units"] == {"energy": "eV", "cross_section": "m2"}
    assert metadata["row_count"] == 2
    assert metadata["energy_min_eV"] == 0.0
    assert metadata["energy_max_eV"] == 5.0
    assert len(metadata["sha256"]) == 64
    assert metadata["license_note"] == "local lab file; do not redistribute"


def test_import_does_not_modify_curated_registry_and_links_only_prepared_registry(tmp_path):
    workspace = tmp_path / "workspace"
    registry_root = tmp_path / "registry"
    input_file = tmp_path / "e_xe.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0,0\n"
        "1,1.0e-20\n",
        encoding="utf-8",
    )
    _write_yaml(
        workspace / "prepared_registry" / "reactions" / "electron" / "e__Xe.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "Xe"},
            "channels": [
                {
                    "id": "e_Xe_elastic",
                    "type": "elastic",
                    "products": [{"species": "e", "n": 1}, {"species": "Xe", "n": 1}],
                    "status": "prepared",
                    "data": {"cross_section": {"path": None}},
                }
            ],
        },
    )
    _write_yaml(
        registry_root / "reactions" / "electron" / "e__Xe.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "Xe"},
            "channels": [{"id": "e_Xe_elastic", "data": {"cross_section": {"path": None}}}],
        },
    )
    original_registry = {
        path: path.read_text(encoding="utf-8")
        for path in registry_root.rglob("*.yaml")
    }

    result = import_cross_section_table(
        input_file,
        workspace,
        source="lxcat_offline",
        reaction_id="e_Xe_elastic",
        target="Xe",
    )

    prepared = yaml.safe_load(
        (workspace / "prepared_registry" / "reactions" / "electron" / "e__Xe.yaml").read_text(
            encoding="utf-8"
        )
    )
    cross_section = prepared["channels"][0]["data"]["cross_section"]

    assert len(result.linked_reaction_files) == 1
    assert cross_section == {
        "status": "local_file_registered",
        "path": result.relative_asset_path,
        "format": "csv_energy_eV_sigma_m2",
        "source": "lxcat_offline",
    }
    assert {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")} == original_registry


def test_cli_import_cross_sections_writes_prepared_assets(tmp_path):
    input_file = tmp_path / "e_ar.csv"
    input_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0,0\n"
        "1,2e-20\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    rc = main(
        [
            "import-cross-sections",
            str(input_file),
            "--workspace",
            str(workspace),
            "--source",
            "lxcat_offline",
            "--reaction-id",
            "e_Ar_elastic",
            "--target",
            "Ar",
        ]
    )

    assert rc == 0
    outputs = list((workspace / "prepared_registry" / "assets" / "cross_sections").glob("*.csv"))
    sidecars = list((workspace / "prepared_registry" / "assets" / "cross_sections").glob("*.metadata.yaml"))
    assert len(outputs) == 1
    assert len(sidecars) == 1


def test_lxcat_offline_provider_reads_index_without_parsing_numeric_tables(tmp_path):
    root = tmp_path / "external_data" / "lxcat"
    _write_yaml(
        root / "index.yaml",
        [
            {
                "reaction_id": "e_CF4_elastic",
                "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
                "path": "files/e_cf4.csv",
                "source": "LXCat test snapshot",
            }
        ],
    )
    data_file = root / "files" / "e_cf4.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("not parsed by provider\n", encoding="utf-8")

    register_lxcat_offline_provider(root)
    provider = get_providers(
        "electron_cross_sections",
        {"electron_cross_sections": ["lxcat_offline"]},
    )[0]
    direct_provider = LxcatOfflineCrossSectionProvider(root)

    assert provider.find_cross_sections("e_CF4_elastic")[0]["status"] == "local_file_registered"
    assert direct_provider.find_cross_sections(CollisionPair("electron", "e", "CF4"))[0]["path"] == "files/e_cf4.csv"


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
