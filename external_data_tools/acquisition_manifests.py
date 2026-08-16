"""Build DB-specific acquisition manifests from source-independent targets."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from external_data_tools.nist_beb import TARGETS as NIST_BEB_TARGETS

NIST_PROPERTIES = {
    "mass_amu",
    "polarizability_A3",
    "dipole_moment_D",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "enthalpy_formation_eV",
}
ATCT_PROPERTIES = {"enthalpy_formation_eV"}
TRANSPORT_PROPERTIES = {"collision_radius_A"}
NIST_BEB_REACTIONS = {target.reaction_id: target.species_id for target in NIST_BEB_TARGETS.values()}
OXYGEN_REACTIONS = {
    "e_O2_elastic",
    "e_O2_excitation_O2_a1Delta",
    "e_O2_excitation_O2_b1Sigma",
    "e_O2_dissociation_O_O",
    "e_O2_ionization",
    "e_O2_attachment_Om_O",
}


def build_source_manifests(
    targets: dict[str, list[dict[str, Any]]],
    *,
    vamdc_endpoint: str | None,
    seed_gases: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return editable source request files; no unknown value is synthesized."""

    properties = targets["properties"]
    electron = targets["electron_datasets"]
    heavy = targets["heavy_particle_datasets"]
    atomic_heavy, molecular_heavy = _partition_heavy_targets(heavy)
    return {
        "pubchem_species.yaml": _pubchem_manifest(targets["identities"]),
        "nist_property_requests.yaml": _property_manifest("NIST", properties, NIST_PROPERTIES),
        "atct_thermochemistry_requests.yaml": _property_manifest(
            "Argonne ATcT", properties, ATCT_PROPERTIES
        ),
        "transport_property_requests.yaml": _property_manifest(
            "transport_literature", properties, TRANSPORT_PROPERTIES
        ),
        "electron_cross_section_targets.yaml": _electron_manifest(electron),
        "astrochem_rate_targets.yaml": _astrochem_manifest(molecular_heavy),
        "vamdc_queries.yaml": _vamdc_manifest(atomic_heavy, vamdc_endpoint),
        "openadas_manifest.yaml": _openadas_manifest(atomic_heavy),
        "qdb_chemistry_requests.yaml": _qdb_manifest(seed_gases or []),
        "reaction_pair_candidates.yaml": _pair_manifest(targets["reaction_pair_candidates"]),
    }


def _pubchem_manifest(targets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_url": "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest",
        "purpose": "identity_formula_synonyms_only",
        "review_before_fetch": True,
        "species": targets,
    }


def _property_manifest(
    database: str,
    targets: list[dict[str, Any]],
    supported: set[str],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for target in targets:
        if target["property"] not in supported:
            continue
        species = target["species"]
        record = grouped.setdefault(
            species,
            {"species": species, "properties": [], "priority": target["priority"], "reasons": []},
        )
        record["properties"].append(target["property"])
        record["reasons"].extend(
            reason for reason in target["reasons"] if reason not in record["reasons"]
        )
    return {
        "schema_version": 1,
        "database": database,
        "source_urls": _property_source_urls(database),
        "status": "request_only_values_must_be_reviewed",
        "required_records": list(grouped.values()),
    }


def _electron_manifest(targets: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    for target in targets:
        record = dict(target)
        record["candidate_sources"] = _electron_sources(record)
        record["mapping_rule"] = "exact_reaction_id_and_process_only"
        records.append(record)
    nist_targets = sorted(
        {
            NIST_BEB_REACTIONS[item["reaction_id"]]
            for item in records
            if item["reaction_id"] in NIST_BEB_REACTIONS
            and not item["available_related_datasets"]["total_ionization_cross_section"]
        }
    )
    return {
        "schema_version": 1,
        "quantity": "electron_collision_cross_section",
        "source_urls": {
            "lxcat": "https://us.lxcat.net/",
            "nist_srd107": "https://physics.nist.gov/PhysRefData/Ionization/intro.html",
            "o2_evaluated_workbook": "https://doi.org/10.60893/figshare.jpr.30850013",
        },
        "required_units": {"energy": "eV", "cross_section": "m2"},
        "targets": records,
        "automated_imports": {
            "nist_beb_targets": nist_targets,
            "oxygen_workbook_required": any(
                item["reaction_id"] in OXYGEN_REACTIONS for item in records
            ),
        },
    }


def _electron_sources(record: dict[str, Any]) -> list[str]:
    reaction_id = record["reaction_id"]
    sources = []
    if reaction_id in OXYGEN_REACTIONS:
        sources.append("song_2026_o2_figshare_workbook")
    if (
        reaction_id in NIST_BEB_REACTIONS
        and not record["available_related_datasets"]["total_ionization_cross_section"]
    ):
        sources.append("nist_srd107_beb_total_ionization")
    sources.append("lxcat_manual_export")
    return sources


def _property_source_urls(database: str) -> list[str]:
    if database == "NIST":
        return [
            "https://webbook.nist.gov/chemistry/",
            "https://physics.nist.gov/PhysRefData/ASD/ionEnergy.html",
        ]
    if database == "Argonne ATcT":
        return ["https://atct.anl.gov/Thermochemical%20Data/"]
    return []


def _partition_heavy_targets(
    targets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    atomic: list[dict[str, Any]] = []
    molecular: list[dict[str, Any]] = []
    for target in targets:
        destination = atomic if _atomic_pair(target["pair_key"]) else molecular
        destination.append(target)
    return atomic, molecular


def _atomic_pair(pair_key: str) -> bool:
    _, projectile, target = pair_key.split("|", 2)
    return _atomic_species(projectile) and _atomic_species(target)


def _atomic_species(species_id: str) -> bool:
    base = species_id.rstrip("+-")
    return len(base) <= 2 and base[:1].isupper() and (len(base) == 1 or base[1:].islower())


def _astrochem_manifest(targets: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    for target in targets:
        record = dict(target)
        record["candidate_sources"] = _heavy_particle_sources(record)
        record["mapping_rule"] = "exact_reaction_id_or_equation_only"
        records.append(record)
    return {
        "schema_version": 1,
        "candidate_databases": ["KIDA", "UMIST"],
        "source_urls": [
            "https://kida.astrochem-tools.org/",
            "https://umistdatabase.uk/downloads",
        ],
        "status": "candidate_rates_require_plasma_applicability_review",
        "temperature_policy": "preserve_source_range_do_not_extrapolate_silently",
        "summary": {
            "registered_rates_missing": len(records),
            "calculation_results_in_scope": False,
        },
        "targets": records,
    }


def _heavy_particle_sources(record: dict[str, Any]) -> list[str]:
    if record["process"] == "elastic":
        return [
            "ion_mobility_transport_literature",
            "primary_scattering_literature",
        ]
    return ["primary_ion_molecule_kinetics", "kida", "umist_rate22"]


def _vamdc_manifest(
    targets: list[dict[str, Any]],
    endpoint: str | None,
) -> dict[str, Any]:
    elements = sorted(_atomic_elements(targets))
    queries = []
    if endpoint:
        queries = [
            {
                "id": f"atomic_{element}",
                "endpoint": endpoint,
                "query": f"SELECT ALL WHERE AtomSymbol = '{element}'",
                "output": f"atomic_{element}.xsams.xml",
                "notes": [
                    "Review returned states, processes, units, and references before conversion."
                ],
            }
            for element in elements
        ]
    return {
        "schema_version": 1,
        "source_url": "https://registry.vamdc.org/registry-12.07/main/browse.jsp",
        "endpoint_required": not bool(endpoint),
        "targets": targets,
        "queries": queries,
    }


def _atomic_elements(targets: list[dict[str, Any]]) -> set[str]:
    elements: set[str] = set()
    for target in targets:
        _, projectile, neutral = target["pair_key"].split("|", 2)
        elements.update((projectile.rstrip("+-"), neutral.rstrip("+-")))
    return elements


def _openadas_manifest(targets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_url": "https://open.adas.ac.uk/",
        "source": {"database": "OpenADAS", "access_mode": "manual_download"},
        "status": "local_files_and_explicit_mapping_required",
        "requested_targets": targets,
        "files": [],
        "openadas_mappings": [],
    }


def _pair_manifest(targets: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for target in targets:
        counts[target["priority"]] += 1
    return {
        "schema_version": 1,
        "meaning": "actionable_discovery_candidates_not_assumed_reactions",
        "scope": "P1_and_P2_only; exhaustive_P3_count_is_kept_in_acquisition_plan",
        "acceptance": [
            "balanced_stoichiometry_and_charge",
            "traceable_channel_reference",
            "valid_temperature_or_energy_range",
            "explicit_state_and_products",
        ],
        "summary": dict(sorted(counts.items())),
        "candidates": targets,
    }


def _qdb_manifest(seed_gases: list[str]) -> dict[str, Any]:
    catalog_path = (
        Path(__file__).resolve().parents[1] / "external_data" / "qdb_semiconductor_chemistries.yaml"
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    seeds = set(seed_gases)
    chemistries = catalog.get("chemistries", [])
    requests = []
    for chemistry in chemistries:
        gases = set(chemistry.get("gases", []))
        overlap = sorted(seeds & gases)
        if seeds and not overlap:
            continue
        request = dict(chemistry)
        request["matching_seed_gases"] = overlap
        request["match"] = (
            "exact" if seeds == gases else "contains_all_seeds" if seeds <= gases else "component"
        )
        request["status"] = "licensed_fetch_requires_api_key_and_review"
        requests.append(request)
    return {
        "schema_version": 1,
        "database": "Quantemol-DB",
        "source": catalog.get("source", {}),
        "seed_gases": seed_gases,
        "credential_environment_name": "QDB_API_KEY",
        "redistribution_status": "site-local_license_review_required",
        "requests": sorted(
            requests,
            key=lambda item: (item["priority"], item["chemistry_id"]),
        ),
        "catalog": chemistries,
        "notes": catalog.get("notes", []),
    }


__all__ = ["build_source_manifests"]
