from external_data_tools.acquisition_manifests import build_source_manifests


def test_nist_beb_is_not_replanned_when_total_ionization_is_already_available():
    targets = _empty_targets()
    targets["electron_datasets"] = [
        {
            "reaction_id": "e_SF5_ionization",
            "pair_key": "electron|e|SF5",
            "family": "electron",
            "process": "ionization",
            "equation": "e + SF5 -> 2 e + SF5+",
            "target": "SF5",
            "products": ["e", "SF5+"],
            "threshold_eV": 9.6,
            "missing_dataset_kind": "cross_section",
            "available_related_datasets": {
                "total_ionization_cross_section": ["nist_total"],
                "rate_coefficient": [],
            },
        }
    ]

    manifest = build_source_manifests(targets, vamdc_endpoint=None)[
        "electron_cross_section_targets.yaml"
    ]

    assert manifest["automated_imports"]["nist_beb_targets"] == []
    assert manifest["targets"][0]["candidate_sources"] == ["lxcat_manual_export"]
    assert manifest["targets"][0]["missing_dataset_kind"] == "cross_section"


def test_cfx_total_ionization_and_heavy_particle_sources_are_routed_by_process():
    targets = _empty_targets()
    targets["electron_datasets"] = [
        {
            "reaction_id": "e_CF4_ionization_parent_effective",
            "pair_key": "electron|e|CF4",
            "family": "electron",
            "process": "ionization",
            "equation": "e + CF4 -> 2 e + CF4+",
            "target": "CF4",
            "products": ["e", "CF4+"],
            "threshold_eV": 14.7,
            "missing_dataset_kind": "cross_section",
            "available_related_datasets": {
                "total_ionization_cross_section": [],
                "rate_coefficient": [],
            },
        }
    ]
    targets["heavy_particle_datasets"] = [
        _heavy_target("CF3p_CF4_elastic", "elastic", dnt_ready=True),
        _heavy_target("CF3p_CF4_reaction", "reactive_scattering"),
    ]

    manifests = build_source_manifests(targets, vamdc_endpoint=None)
    electron = manifests["electron_cross_section_targets.yaml"]
    heavy = manifests["astrochem_rate_targets.yaml"]["targets"]

    assert electron["automated_imports"]["nist_beb_targets"] == ["CF4"]
    assert heavy[0]["candidate_sources"] == [
        "ion_mobility_transport_literature",
        "primary_scattering_literature",
    ]
    assert heavy[1]["candidate_sources"] == [
        "primary_ion_molecule_kinetics",
        "kida",
        "umist_rate22",
    ]
    assert manifests["astrochem_rate_targets.yaml"]["summary"] == {
        "registered_rates_missing": 2,
        "calculation_results_in_scope": False,
    }


def test_qdb_manifest_routes_relevant_semiconductor_chemistries() -> None:
    manifest = build_source_manifests(
        _empty_targets(),
        vamdc_endpoint=None,
        seed_gases=["Ar", "NF3"],
    )["qdb_chemistry_requests.yaml"]

    requests = {item["id"]: item for item in manifest["requests"]}
    assert requests["C31"]["match"] == "exact"
    assert requests["C31"]["n_reactions_2016"] == 104
    assert requests["C31"]["use"] == "remote_chamber_clean"
    assert manifest["credential_environment_name"] == "QDB_API_KEY"
    assert len(manifest["catalog"]) == 29


def _heavy_target(reaction_id: str, process: str, *, dnt_ready: bool = False):
    target = {
        "reaction_id": reaction_id,
        "pair_key": "ion_neutral|CF3+|CF4",
        "family": "ion_neutral",
        "process": process,
        "equation": "CF3+ + CF4 -> CF3+ + CF4",
        "target": "CF4",
        "products": ["CF3+", "CF4"],
        "threshold_eV": None,
        "missing_dataset_kind": "one_of",
        "accepted_dataset_kinds": ["rate_coefficient", "cross_section"],
    }
    if dnt_ready:
        target["dnt_calculation"] = {
            "pair_id": "CF3+__CF4",
            "model_variant": "dnt_plus_dm",
            "status": "ready",
            "missing": [],
        }
    return target


def _empty_targets():
    return {
        "identities": [],
        "properties": [],
        "electron_datasets": [],
        "heavy_particle_datasets": [],
        "reaction_pair_candidates": [],
    }
