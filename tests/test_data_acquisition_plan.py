from pathlib import Path

import yaml

from external_data_tools.data_acquisition_plan import plan_data_acquisition


def test_plan_routes_existing_reactions_without_creating_mixture_pack(tmp_path):
    output_dir = tmp_path / "plan"

    plan = plan_data_acquisition(
        seed_gases=["Ar", "O2"],
        max_depth=1,
        registry_root=Path("registry"),
        output_dir=output_dir,
    )

    assert plan["scope"]["seed_gases"] == ["Ar", "O2"]
    assert plan["scope"]["mixture_pack_required"] is False
    assert "n_dnt_properties_missing" not in plan["coverage_summary"]
    assert (output_dir / "acquisition_plan.yaml").exists()
    assert (output_dir / "pubchem_species.yaml").exists()
    assert (output_dir / "reaction_pair_candidates.yaml").exists()

    electron = _read(output_dir / "electron_cross_section_targets.yaml")["targets"]
    assert electron
    assert {item["family"] for item in electron} == {"electron"}
    assert any(item["reaction_id"] == "e_O2_ionization" for item in electron)
    assert all(item["mapping_rule"] == "exact_reaction_id_and_process_only" for item in electron)

    heavy = _read(output_dir / "astrochem_rate_targets.yaml")["targets"]
    assert all(item["family"] != "electron" for item in heavy)
    assert all("candidate_sources" in item for item in heavy)
    assert all("dnt_calculation" not in item for item in heavy)


def test_pair_candidates_exclude_same_sign_ion_collisions(tmp_path):
    output_dir = tmp_path / "plan"

    plan_data_acquisition(
        seed_gases=["Ar", "SF6", "O2"],
        max_depth=2,
        registry_root=Path("registry"),
        output_dir=output_dir,
    )

    candidates = _read(output_dir / "reaction_pair_candidates.yaml")["candidates"]
    keys = {item["pair_key"] for item in candidates}
    assert "ion_ion|Ar+|O+" not in keys
    assert "ion_ion|O+|O-" in keys
    assert all(item["status"] == "candidate_requires_channel_evidence" for item in candidates)
    assert all(item["priority"] in {"P1", "P2"} for item in candidates)


def test_vamdc_queries_are_only_executable_with_reviewed_endpoint(tmp_path):
    without_endpoint = tmp_path / "without"
    with_endpoint = tmp_path / "with"

    plan_data_acquisition(
        seed_gases=["Ar"],
        max_depth=1,
        registry_root=Path("registry"),
        output_dir=without_endpoint,
    )
    plan_data_acquisition(
        seed_gases=["Ar"],
        max_depth=1,
        registry_root=Path("registry"),
        output_dir=with_endpoint,
        vamdc_endpoint="https://example.test/tap/sync",
    )

    missing = _read(without_endpoint / "vamdc_queries.yaml")
    ready = _read(with_endpoint / "vamdc_queries.yaml")
    assert missing["endpoint_required"] is True
    assert missing["queries"] == []
    assert ready["endpoint_required"] is False
    assert all(item["endpoint"] == "https://example.test/tap/sync" for item in ready["queries"])


def test_reviewed_values_and_unbound_properties_are_not_reported_as_gaps(tmp_path):
    output_dir = tmp_path / "plan"

    plan_data_acquisition(
        seed_gases=["Ar", "CF4", "SF6"],
        max_depth=2,
        registry_root=Path("registry"),
        output_dir=output_dir,
    )

    requests = _read(output_dir / "nist_property_requests.yaml")["required_records"]
    requested = {
        (record["species"], property_name)
        for record in requests
        for property_name in record["properties"]
    }
    assert ("Ar", "electron_affinity_eV") not in requested
    assert ("CF2", "electron_affinity_eV") not in requested
    assert ("CF4", "electron_affinity_eV") not in requested
    assert ("SF3", "electron_affinity_eV") not in requested
    heavy_summary = _read(output_dir / "astrochem_rate_targets.yaml")["summary"]
    assert heavy_summary["calculation_results_in_scope"] is False


def test_unimplemented_feedstock_routes_to_reaction_discovery_and_qdb(tmp_path):
    output_dir = tmp_path / "nf3-plan"

    plan = plan_data_acquisition(
        seed_gases=["Ar", "NF3"],
        max_depth=2,
        registry_root=Path("registry"),
        output_dir=output_dir,
    )

    candidates = _read(output_dir / "reaction_pair_candidates.yaml")["candidates"]
    qdb = _read(output_dir / "qdb_chemistry_requests.yaml")
    assert any(item["pair_key"] == "electron|e|NF3" for item in candidates)
    assert any(item["id"] == "C31" and item["match"] == "exact" for item in qdb["requests"])
    assert plan["priorities"][0]["work"].startswith("review and register")


def _read(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
