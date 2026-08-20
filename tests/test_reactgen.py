"""Behaviour tests for the reactgen core, run against tests/fixtures/mini."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from reactgen import audit, export, ingest, lock, plan, quality, rank
from reactgen.case import Case, Conditions
from reactgen.expand import expand
from reactgen.model import Dataset, Network, State, Term, Validity
from reactgen.physics import langevin_rate, rate_of
from reactgen.registry import Registry
from reactgen.thermo import equilibrium_constant

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(FIXTURE)


def build_case(tmp_path: Path, **overrides) -> Case:
    data = {
        "name": "mini",
        "gases": ["Ar", "F2"],
        "conditions": {"pressure_Pa": 5.0, "gas_temperature_K": 400.0},
        "surfaces": ["SiO2"],
        "accept_status": ["curated"],
        **overrides,
    }
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return Case.load(path)


# --------------------------------------------------------------------------- registry


def test_folding_ignores_punctuation():
    from reactgen.naming import fold

    assert fold("SF5_p") == fold("SF5p") == "sf5p"


def test_alias_resolves_to_registered_id(registry):
    assert registry.resolve("fluorine") == "F2"
    assert registry.resolve("Ar_p") == "Ar+"
    assert registry.resolve("nonsense") is None


def test_mass_is_derived_when_absent(registry):
    assert registry.species["F2"].value("mass_amu") == pytest.approx(37.996, abs=1e-3)
    assert registry.species["Ar+"].value("mass_amu") == pytest.approx(39.9474, abs=1e-3)


# --------------------------------------------------------------------------- expansion


def test_expansion_reaches_products_of_products(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    assert {"Ar", "F2", "F", "Ar+", "e"} <= set(network.species)
    assert network.depth["Ar+"] == 1


def test_unbalanced_channel_is_rejected(tmp_path, registry):
    network, gaps = expand(registry, build_case(tmp_path))
    assert "e_F2_broken_balance" not in {r.id for r in network.reactions}
    rejected = [gap for gap in gaps if gap.kind == "rejected_reaction"]
    assert rejected
    assert "element balance" in rejected[0].detail


def test_precursors_point_at_earlier_reactions(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    charge_transfer = next(r for r in network.reactions if r.id == "Arp_F2_charge_transfer")
    assert "e_Ar_ionization" in charge_transfer.precursors


def test_three_body_channel_is_generated(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.family == "three_body")
    assert reaction.equation == "F + F + M -> F2 + M"


def test_surface_channel_needs_the_material_in_the_case(tmp_path, registry):
    with_wall, _ = expand(registry, build_case(tmp_path))
    without_wall, _ = expand(registry, build_case(tmp_path, surfaces=[]))
    assert any(r.surface == "SiO2" for r in with_wall.reactions)
    assert not any(r.surface for r in without_wall.reactions)


def test_max_depth_is_recorded_as_truncation(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path, limits={"max_depth": 0}))
    assert network.truncated


# --------------------------------------------------------------------------- physics


def test_langevin_matches_the_known_argon_value():
    # Ar+ in Ar: 6.7e-10 cm3/s in the literature.
    assert langevin_rate(1.64, 39.948 / 2) == pytest.approx(6.7e-16, rel=0.05)


def test_langevin_fills_in_when_no_dataset_exists(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.id == "Arp_Ar_charge_transfer")
    rate = rate_of(reaction, network.species, Conditions())
    assert rate.basis == "langevin_estimate"
    assert rate.value == pytest.approx(6.7e-16, rel=0.05)


def test_no_rate_is_invented_when_the_neutral_lacks_polarizability(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.id == "Arp_F2_charge_transfer")
    assert rate_of(reaction, network.species, Conditions()) is None


def test_arrhenius_uses_the_case_temperature(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.family == "three_body")
    cold = rate_of(reaction, network.species, Conditions(gas_temperature_K=300.0))
    hot = rate_of(reaction, network.species, Conditions(gas_temperature_K=600.0))
    assert cold.value == pytest.approx(1.0e-45)
    assert hot.value == pytest.approx(0.5e-45)


def test_validity_reports_undecidable_ranges():
    assert Validity("gas_temperature", 200.0, 400.0, "K").covers(300.0) is True
    assert Validity("gas_temperature", 200.0, 400.0, "K").covers(500.0) is False
    assert Validity("gas_temperature", None, None, "K").covers(300.0) is None


# --------------------------------------------------------------------------- conditions


def test_wall_loss_needs_a_geometry(tmp_path, registry):
    bare = build_case(tmp_path)
    sized = build_case(
        tmp_path,
        conditions={"gas_temperature_K": 400.0, "volume_m3": 0.02, "surface_area_m2": 0.5},
    )
    network, _ = expand(registry, bare)
    wall = next(r for r in network.reactions if r.surface)
    assert rate_of(wall, network.species, bare.conditions) is None

    sized_rate = rate_of(wall, network.species, sized.conditions)
    assert sized_rate.unit == "1/s"
    assert sized_rate.basis == "wall_loss"
    assert sized_rate.value > 0


def test_missing_geometry_is_reported_as_a_gap(tmp_path, registry):
    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    gaps = quality.quality(network, case, registry) + audit.audit(registry, network)
    assert any(gap.kind == "missing_condition" and gap.subject == "geometry" for gap in gaps)


def test_scientific_notation_without_a_sign_still_loads(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("gases: [Ar]\nconditions: {electron_density_m3: 5.0e16}\n", encoding="utf-8")
    assert Case.load(path).conditions.electron_density_m3 == pytest.approx(5.0e16)


# --------------------------------------------------------------------------- thermo


def test_reverse_rate_follows_from_the_polynomials(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.family == "three_body")
    rate = rate_of(reaction, network.species, Conditions(gas_temperature_K=400.0))
    assert rate.reverse is not None
    assert rate.reverse > 0


def test_no_equilibrium_constant_without_thermochemistry(registry):
    charge_transfer = registry.channels[("ion_neutral", "Ar+", "F2")][0]
    assert equilibrium_constant(charge_transfer, registry.species, 400.0) is None


def test_uncertainty_becomes_rate_bounds(tmp_path, registry):
    network, _ = expand(registry, build_case(tmp_path))
    reaction = next(r for r in network.reactions if r.family == "three_body")
    rate = rate_of(reaction, network.species, Conditions(gas_temperature_K=300.0))
    assert rate.bounds == pytest.approx((0.5e-45, 2.0e-45))


# --------------------------------------------------------------------------- ranking


CHAMBER = {
    "pressure_Pa": 5.0,
    "gas_temperature_K": 400.0,
    "volume_m3": 0.02,
    "surface_area_m2": 0.5,
}


def test_ranking_orders_wall_loss_above_three_body(tmp_path, registry):
    case = build_case(tmp_path, conditions=CHAMBER)
    network, _ = expand(registry, case)
    rates = {r.id: rate_of(r, network.species, case.conditions) for r in network.reactions}
    ranked = rank.annotate(network, rates, case.conditions)

    wall = ranked["F_SiO2_recombination"]["frequency_upper_bound_s-1"]
    termolecular = ranked["F_F_M_recombination"]["frequency_upper_bound_s-1"]
    # At 5 Pa the wall dominates radical loss and three-body recombination cannot compete.
    assert wall > termolecular * 1e4
    assert ranked["F_F_M_recombination"]["relevance"] == "negligible"
    assert ranked["Arp_Ar_charge_transfer"]["relevance"] == "fast"
    assert ranked["Arp_Ar_charge_transfer"]["relevance_basis"] == "fastest_reaction"


def test_residence_time_becomes_the_reference_when_given(tmp_path, registry):
    case = build_case(tmp_path, conditions={**CHAMBER, "residence_time_s": 0.05})
    network, _ = expand(registry, case)
    rates = {r.id: rate_of(r, network.species, case.conditions) for r in network.reactions}
    ranked = rank.annotate(network, rates, case.conditions)

    assert ranked["F_SiO2_recombination"]["relevance_basis"] == "residence_time"
    # Wall loss at 83 1/s outruns a 20 1/s gas exchange; three-body still cannot.
    assert ranked["F_SiO2_recombination"]["relevance"] == "fast"
    assert ranked["F_F_M_recombination"]["relevance"] == "negligible"


def test_ranking_is_unknown_without_an_electron_density(tmp_path, registry):
    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    rates = {r.id: rate_of(r, network.species, case.conditions) for r in network.reactions}
    ranked = rank.annotate(network, rates, case.conditions)
    assert ranked["e_Ar_ionization"]["relevance"] == "unknown"


def test_nothing_is_removed_by_ranking(tmp_path, registry):
    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    rates = {r.id: rate_of(r, network.species, case.conditions) for r in network.reactions}
    assert set(rank.annotate(network, rates, case.conditions)) == {r.id for r in network.reactions}


# --------------------------------------------------------------------------- audit


def test_audit_flags_out_of_range_conditions(tmp_path, registry):
    case = build_case(tmp_path, conditions={"gas_temperature_K": 1500.0})
    network, _ = expand(registry, case)
    kinds = {gap.kind for gap in quality.quality(network, case, registry)}
    assert "out_of_range" in kinds


def test_audit_flags_double_counted_momentum_transfer(registry):
    elastic = registry.channels[("electron", "e", "Ar")][0]
    network = Network(
        species=registry.species,
        reactions=[elastic, replace(elastic, id="e_Ar_effective", type="effective")],
    )
    kinds = {gap.kind for gap in audit.audit(registry, network)}
    assert "double_counted" in kinds


def test_conflicting_rate_forms_are_blocking(registry):
    elastic = registry.channels[("electron", "e", "Ar")][0]
    both = replace(
        elastic,
        datasets=[
            Dataset(
                id="x", reaction_id=elastic.id, kind="cross_section", form="table", asset="a.csv"
            ),
            Dataset(
                id="k",
                reaction_id=elastic.id,
                kind="rate_coefficient",
                form="constant",
                params={"value": 1.0},
            ),
        ],
    )
    network = Network(species=registry.species, reactions=[both])
    gaps = quality.quality(network, Case("x", ("Ar",)), registry)
    assert any(gap.kind == "conflicting_rate_form" for gap in gaps)


def test_lumped_state_cannot_coexist_with_its_members(registry):
    argon = registry.species["Ar"]
    lumped = replace(
        argon, id="Ar_4s", state=State(kind="excited", resolution="lumped", members=("Ar",))
    )
    network = Network(species={"Ar": argon, "Ar_4s": lumped}, reactions=[])
    gaps = audit.audit(registry, network)
    assert any(gap.kind == "double_counted" and gap.severity == "blocking" for gap in gaps)


def test_registry_audit_is_clean_for_the_fixture(registry):
    assert not [gap for gap in audit.audit(registry) if gap.severity == "blocking"]


# --------------------------------------------------------------------------- ingest


def test_ingest_matches_a_written_equation(tmp_path, registry):
    snapshot = tmp_path / "snap.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {
                "kind": "rate_coefficient",
                "source": {"source_id": "doi:test", "citation": "fixture"},
                "records": [
                    {
                        "reaction": "Ar+ + F2 -> Ar + F2+",
                        "form": "constant",
                        "unit": "m3/s",
                        "parameters": {"value": 1.0e-15},
                    },
                    {
                        "reaction": "Xe + F2 -> Xe + F2",
                        "form": "constant",
                        "parameters": {"value": 1.0},
                    },
                    {"species": "fluorine", "property": "polarizability_A3", "value": 1.3},
                ],
            }
        ),
        encoding="utf-8",
    )
    report = ingest.ingest(snapshot, registry, tmp_path / "overlay.yaml")
    assert report.accepted == 2
    assert len(report.review) == 1
    # Xe is not registered, so the record is queued naming the species, not the reaction.
    assert report.review[0]["reason"] == "species not identified"
    assert set(report.review[0]["unresolved"]) == {"Xe"}
    assert (tmp_path / "review_queue.yaml").is_file()


def test_overlay_supplies_data_without_touching_the_registry(tmp_path):
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "Arp_F2_charge_transfer": [
                        {
                            "id": "imported",
                            "kind": "rate_coefficient",
                            "representation": "constant",
                            "unit": "m3/s",
                            "parameters": {"value": 2.0e-15},
                            "preferred": True,
                        }
                    ]
                },
                "properties": {"F2": {"polarizability_A3": {"value": 1.3, "unit": "A3"}}},
            }
        ),
        encoding="utf-8",
    )
    plain = Registry.load(FIXTURE)
    merged = Registry.load(FIXTURE, overlay=overlay)

    assert plain.species["F2"].value("polarizability_A3") is None
    assert merged.species["F2"].value("polarizability_A3") == 1.3
    assert (
        merged.channels[("ion_neutral", "Ar+", "F2")][0].best("rate_coefficient").id == "imported"
    )


def test_equation_parsing_ignores_order_and_spelling(registry):
    """Foreign notation reaches the same registered species."""

    canonical, _ = ingest.parse_equation("Ar+ + F2 -> Ar + F2+", registry)
    foreign, _ = ingest.parse_equation("F2 + Ar^+ -> F2_p + AR", registry)
    assert canonical == foreign

    two, _ = ingest.parse_equation("E + F2 -> E + 2 F", registry)
    three, _ = ingest.parse_equation("e- + F2 -> e- + 3 F", registry)
    assert two != three


def test_an_unidentifiable_name_is_reported_not_guessed(registry):
    _, unresolved = ingest.parse_equation("Xe2 + F2 -> Xe2 + F2", registry)
    assert unresolved


# --------------------------------------------------------------------------- output


def test_bundle_contains_every_promised_file(tmp_path, registry):
    case = build_case(tmp_path)
    network, gaps = expand(registry, case)
    gaps += quality.quality(network, case, registry) + audit.audit(registry, network)
    out = tmp_path / "out"
    export.write(out, case, network, registry, gaps, "test.mechanism")

    for name in (
        "species.yaml",
        "reactions.yaml",
        "reactions.csv",
        "gaps.yaml",
        "summary.yaml",
        "coverage.yaml",
        "reduced.yaml",
    ):
        assert (out / name).is_file()
    assert (out / "datasets" / "rates.yaml").is_file()
    assert (out / "datasets" / "cross_sections" / "index.yaml").is_file()
    assert (out / "datasets" / "dnt" / "index.yaml").is_file()


def test_species_output_carries_values_not_just_names(tmp_path, registry):
    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    out = tmp_path / "out"
    export.write(out, case, network, registry, [], "test.mechanism")
    document = yaml.safe_load((out / "species.yaml").read_text(encoding="utf-8"))
    argon = next(item for item in document["species"] if item["id"] == "Ar")
    assert argon["properties"]["polarizability_A3"]["value"] == 1.64
    assert argon["properties"]["polarizability_A3"]["source"] == "fixture"


def test_dnt_reports_readiness_per_model_tier(tmp_path, registry):
    """A pair whose long-range parameters are known is not hidden by the full tier."""

    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    out = tmp_path / "out"
    export.write(out, case, network, registry, [], "test.mechanism")

    complete = yaml.safe_load((out / "datasets" / "dnt" / "Ar_p__Ar.yaml").read_text("utf-8"))
    assert complete["short_range"]["model"] == "born_mayer"
    assert complete["readiness"]["long_range"]["status"] == "ready"
    assert complete["readiness"]["full"]["status"] == "ready"
    assert complete["energy_grid"]["energy_max_eV"] == 100.0

    # F2 has no polarizability and the pair has no potential, so both tiers block.
    # A blocked pair gets no input file; the index still carries it as work to do.
    assert not (out / "datasets" / "dnt" / "Ar_p__F2.yaml").exists()
    index = yaml.safe_load((out / "datasets" / "dnt" / "index.yaml").read_text("utf-8"))
    listed = {entry["pair"]: entry for entry in index["pairs"]}
    assert listed["Ar_p__F2"]["runnable"] == []
    assert "short_range_potential" in listed["Ar_p__F2"]["blocked_by"]
    ready, total = index["summary"]["long_range"].split("/")
    assert int(ready) >= 1
    assert int(total) == index["pairs_total"]


def test_every_ion_neutral_pair_is_work_for_dnt(tmp_path, registry):
    """DNT+ computes what no database states, so a pair with no reaction counts."""

    from reactgen import dnt

    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    documents, index = dnt.build(case, network, registry)

    ions = [s for s in network.species.values() if s.charge != 0 and s.id != "e"]
    neutrals = [s for s in network.species.values() if s.is_neutral]
    assert index["pairs_total"] == len(ions) * len(neutrals)
    assert index["no_known_channel"] > 0  # the reason the calculation exists

    # Symmetric charge exchange changes nothing chemically and so is often absent
    # from the reaction list, while being the largest ion-neutral cross section.
    argon = next(d for d in documents if d["pair"] == "Ar_p__Ar")
    assert "analytic_resonant" in argon["readiness"]


def test_lock_records_the_registry_fingerprint(tmp_path, registry):
    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    pinned = lock.build(case, network, registry)
    assert pinned["registry_digest"] == lock.digest_registry(registry)


def test_mechanism_id_names_the_case_and_gases(tmp_path, registry):
    assert lock.mechanism_id(build_case(tmp_path), registry).startswith("mini.Ar-F2.")


def test_plan_routes_gaps_to_sources():
    from reactgen.model import Gap

    document = plan.build([Gap("missing_cross_section", "e_F2_elastic", "electron", "data")])
    item = document["acquisition_plan"][0]
    assert item["priority"] == "P1"
    assert item["target"] == "electron_cross_section"


def test_dataset_usability_distinguishes_a_citation_from_numbers():
    citation = Dataset(id="d1", reaction_id="r", kind="cross_section", form="reference_only")
    table = Dataset(id="d2", reaction_id="r", kind="cross_section", form="table", asset="a.csv")
    assert not citation.usable
    assert table.usable


def test_a_channel_without_an_onset_is_named(registry):
    """A missing threshold is a gap the reader can act on, not a silent None."""

    elastic = registry.channels[("electron", "e", "Ar")][0]
    blind = replace(elastic, id="e_Ar_excitation_x", type="excitation", threshold_eV=None)
    network = Network(species=registry.species, reactions=[blind])
    gaps = audit.audit(registry, network)
    named = [gap for gap in gaps if gap.kind == "missing_threshold"]
    assert [gap.subject for gap in named] == ["e_Ar_excitation_x"]
    assert "excitation energy" in named[0].detail


def test_elastic_and_superelastic_need_no_onset(registry):
    """Zero by definition, so neither is reported as missing."""

    elastic = registry.channels[("electron", "e", "Ar")][0]
    free = [
        replace(elastic, id="a", type="elastic", threshold_eV=0.0),
        replace(elastic, id="b", type="deexcitation", threshold_eV=0.0),
    ]
    network = Network(species=registry.species, reactions=free)
    assert not [g for g in audit.audit(registry, network) if g.kind == "missing_threshold"]


def test_an_excitation_costing_more_than_ionization_is_blocking(registry):
    """A free check on acquired data; silent where no ionization energy is recorded."""

    from reactgen.model import Property

    elastic = registry.channels[("electron", "e", "Ar")][0]
    impossible = replace(elastic, id="e_Ar_excite", type="excitation", threshold_eV=99.0)
    argon = replace(
        registry.species["Ar"],
        properties={"ionization_energy_eV": Property(value=15.7596, unit="eV")},
    )
    network = Network(species={**registry.species, "Ar": argon}, reactions=[impossible])
    gaps = audit.audit(registry, network)
    assert any(g.kind == "energy_above_ionization" and g.severity == "blocking" for g in gaps)

    unknown = Network(species=registry.species, reactions=[impossible])
    assert not [g for g in audit.audit(registry, unknown) if g.kind == "energy_above_ionization"]


def test_electron_chemistry_is_judged_on_the_network(registry):
    """A proposed species carries its channels in the network, not the registry."""

    elastic = registry.channels[("electron", "e", "Ar")][0]
    network = Network(species=registry.species, reactions=[elastic])
    struck = {
        g.subject for g in audit.audit(registry, network) if g.kind == "missing_electron_chemistry"
    }
    assert "Ar" not in struck


def test_vibrational_and_electronic_excitation_may_coexist(registry):
    """Two processes, not two resolutions: neither hides the other's count."""

    argon = registry.species["Ar"]
    vibrational = replace(
        argon, id="Ar_v", state=State(kind="excited", label="vibrational", resolution="lumped")
    )
    electronic = replace(
        argon, id="Ar_1D", state=State(kind="excited", label="1D", resolution="state_resolved")
    )
    elastic = registry.channels[("electron", "e", "Ar")][0]
    channels = [
        replace(elastic, id="v", type="excitation", products=[Term("e"), Term("Ar_v")]),
        replace(elastic, id="e1", type="excitation", products=[Term("e"), Term("Ar_1D")]),
    ]
    species = {**registry.species, "Ar_v": vibrational, "Ar_1D": electronic}
    gaps = audit.audit(registry, Network(species=species, reactions=channels))
    assert not [g for g in gaps if g.kind == "double_counted"]


def test_two_resolutions_of_one_manifold_still_clash(registry):
    argon = registry.species["Ar"]
    lumped = replace(argon, id="Ar_x", state=State(kind="excited", label="x", resolution="lumped"))
    resolved = replace(
        argon, id="Ar_1D", state=State(kind="excited", label="1D", resolution="state_resolved")
    )
    elastic = registry.channels[("electron", "e", "Ar")][0]
    channels = [
        replace(elastic, id="a", type="excitation", products=[Term("e"), Term("Ar_x")]),
        replace(elastic, id="b", type="excitation", products=[Term("e"), Term("Ar_1D")]),
    ]
    species = {**registry.species, "Ar_x": lumped, "Ar_1D": resolved}
    gaps = audit.audit(registry, Network(species=species, reactions=channels))
    assert [g for g in gaps if g.kind == "double_counted" and g.severity == "blocking"]


def test_a_duplicate_written_with_a_collapsed_count_is_caught(registry):
    """`2 e` and `e + e` are one reaction, however the file spells them."""

    elastic = registry.channels[("electron", "e", "Ar")][0]
    pair = [
        replace(elastic, id="a", type="ionization", products=[Term("e", 2.0), Term("Ar+")]),
        replace(elastic, id="b", type="ionization", products=[Term("e"), Term("e"), Term("Ar+")]),
    ]
    gaps = audit.audit(registry, Network(species=registry.species, reactions=pair))
    assert [g for g in gaps if g.kind == "duplicate_equation"]


def test_an_excited_fragment_is_not_a_level_of_the_target(registry):
    """`e + CF2 -> e + F2 + C(1D)` breaks a bond; C(1D) is not a level of CF2."""

    argon = registry.species["Ar"]
    lumped = replace(argon, id="Ar_x", state=State(kind="excited", label="x", resolution="lumped"))
    fragment = replace(
        registry.species["F"],
        id="F_1D",
        state=State(kind="excited", label="1D", resolution="state_resolved"),
    )
    elastic = registry.channels[("electron", "e", "Ar")][0]
    channels = [
        replace(elastic, id="a", type="excitation", products=[Term("e"), Term("Ar_x")]),
        replace(elastic, id="b", type="dissociation", products=[Term("e"), Term("F_1D")]),
    ]
    species = {**registry.species, "Ar_x": lumped, "F_1D": fragment}
    gaps = audit.audit(registry, Network(species=species, reactions=channels))
    assert not [g for g in gaps if g.kind == "double_counted"]


def test_each_layer_answers_separately(registry):
    """Four questions, not one confidence word: they can disagree."""

    from reactgen import layers

    elastic = registry.channels[("electron", "e", "Ar")][0]
    proposed = replace(elastic, id="x", status="candidate", delta_e_eV=-4.4)
    answers = layers.verdicts(proposed, ["a_paper"], "fast", layers.LAYERS)
    assert answers["structure"] == "conserved, species proposed"
    assert answers["thermochemistry"] == "exothermic by 4.40 eV"
    assert answers["kinetics"] == "fast"
    assert answers["attestation"] == "a_paper"


def test_a_layer_not_asked_for_says_so(registry):
    """`not_run` and `unknown` are different answers, and the file says which."""

    from reactgen import layers

    elastic = registry.channels[("electron", "e", "Ar")][0]
    answers = layers.verdicts(elastic, [], None, ("structure",))
    assert answers["structure"] == "conserved"
    assert answers["thermochemistry"] == "not_run"
    assert answers["kinetics"] == "not_run"

    with pytest.raises(ValueError, match="unknown layers"):
        layers.select("bogus")


def test_a_curated_reaction_is_attested_by_its_own_record(registry):
    """A channel read from a paper carries the paper; no index is needed."""

    from reactgen import layers

    elastic = registry.channels[("electron", "e", "Ar")][0]
    cited = replace(elastic, source={"source_type": "literature_mechanism", "source_id": "doi:x"})
    assert layers.verdicts(cited, [], None, layers.LAYERS)["attestation"] == "doi:x"

    # What this repository worked out for itself is not evidence about itself.
    derived = replace(elastic, source={"source_type": "formation_enthalpy"})
    assert layers.verdicts(derived, [], None, layers.LAYERS)["attestation"] == "unattested"


def test_an_electron_channel_gets_its_reaction_enthalpy(registry):
    """The electron carries none, so the cost is the heavy species' difference."""

    from reactgen.model import Property
    from reactgen.thermo import formation_delta

    def carrying(name: str, value: float):
        return replace(
            registry.species[name],
            properties={"enthalpy_formation_eV": Property(value=value, unit="eV")},
        )

    species = {**registry.species, "F": carrying("F", 0.82), "F2": carrying("F2", 0.0)}
    elastic = registry.channels[("electron", "e", "F2")][0]
    split = replace(elastic, type="dissociation", products=[Term("e"), Term("F", 2.0)])
    assert formation_delta(split, species) == pytest.approx(2 * 0.82 - 0.0)

    # One species without an enthalpy is enough to leave the whole thing unknown.
    assert formation_delta(split, registry.species) is None


# --------------------------------------------------------------------------- derive / adopt


def test_nothing_is_inherited_across_a_charge_change():
    """A cation is smaller and less polarizable; same composition is not enough."""

    from reactgen import derive

    registry = Registry.load("registry")
    inherited = derive.parents(registry)
    for state_id, parent_id in inherited.items():
        assert registry.species[state_id].charge == registry.species[parent_id].charge


def test_a_state_borrows_its_ground_state_polynomial_shifted():
    """The manifold has the parent's heat capacity but not its enthalpy.

    Checked against what the registry ships rather than against a fresh
    derivation, because a wrong shift here is wrong in the data a user gets.
    """

    registry = Registry.load("registry")
    state, parent = registry.species["O_1D"], registry.species["O"]
    if state.thermo is None or parent.thermo is None:
        pytest.skip("no polynomial for O or O_1D in this registry")
    shift = state.state.energy_eV * 11604.518
    # a6 carries the enthalpy constant, in kelvin; Cp and S are untouched.
    assert state.thermo.low[5] == pytest.approx(parent.thermo.low[5] + shift, rel=1e-6)
    assert state.thermo.low[:5] == parent.thermo.low[:5]
    assert state.thermo.high[5] == pytest.approx(parent.thermo.high[5] + shift, rel=1e-6)


def test_adopt_never_overrules_a_curated_value(tmp_path):
    """Someone read that number out of a paper; a table has no standing over it."""

    from reactgen import adopt

    species = tmp_path / "species"
    species.mkdir()
    (species / "X.yaml").write_text(
        yaml.safe_dump(
            {"id": "X", "properties": {"mass_amu": {"value": 1.0, "source": "a paper"}}}
        ),
        encoding="utf-8",
    )
    overlay = {
        "properties": {
            "X": {
                "mass_amu": {"value": 99.0, "source": "a table"},
                "dipole_moment_D": {"value": 0.5, "unit": "D", "source": "a table"},
            }
        }
    }
    report = adopt.adopt(overlay, tmp_path)
    written = yaml.safe_load((species / "X.yaml").read_text(encoding="utf-8"))
    assert written["properties"]["mass_amu"]["value"] == 1.0
    assert written["properties"]["dipole_moment_D"]["value"] == 0.5
    assert report.kept["X"] == ["mass_amu"]


def test_a_bundle_writes_the_state_list_as_csv(tmp_path, registry):
    """The property table, with a column per element the bundle actually uses."""

    import csv

    case = build_case(tmp_path)
    network, _ = expand(registry, case)
    out = tmp_path / "out"
    export.write(out, case, network, registry, [], "test.mechanism")
    rows = list(csv.reader((out / "species.csv").read_text(encoding="utf-8").splitlines()))
    header = rows[0]
    assert header[:2] == ["id", "formula"]
    assert "mass_amu" in header
    assert "polarizability_A3" in header
    assert any(column.startswith("n_") for column in header)
    # Every row has to line up with the header or the file is not a table.
    assert all(len(row) == len(header) for row in rows[1:])
    # Provenance survives the flattening; the wide table alone cannot say
    # whether a zero dipole is a measurement or a symmetry argument.
    long_form = list(
        csv.reader((out / "species_sources.csv").read_text(encoding="utf-8").splitlines())
    )
    assert long_form[0] == ["id", "property", "value", "unit", "source"]
    assert all(row[4] for row in long_form[1:])


def test_a_species_id_is_not_a_filename():
    """`F2*` and `CF3-` are legal ids and illegal names on Windows."""

    from reactgen import naming

    assert naming.slug("F2*") == "F2_x"
    assert naming.slug("CF3-") == "CF3_m"
    assert naming.slug("Ar+") == "Ar_p"
    assert not set(naming.slug("O2(a1Dg)*")) & set('<>:"/\|?*')
