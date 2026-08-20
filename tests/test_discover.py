"""Tests for candidate channel proposal and source routing."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from discover import fragments, screen, sources
from discover.cli import main
from reactgen.case import DEFAULT_STATUS
from reactgen.registry import Registry

FIXTURE = Path(__file__).parent / "fixtures" / "mini"

CATALOG = {
    "sources": [
        {"id": "pubchem", "covers": ["species_identity"], "access": "api", "priority": 1},
        {"id": "lxcat", "covers": ["electron"], "access": "manual_export", "priority": 1},
        {
            "id": "qdb",
            "covers": ["electron"],
            "access": "api_key",
            "key_env": "NOT_SET",
            "priority": 2,
        },
        {"id": "structural", "covers": ["electron"], "access": "derived", "priority": 9},
    ]
}


def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(CATALOG), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- fragments


def known() -> dict[tuple, str]:
    registry = Registry.load(FIXTURE)
    return {
        (tuple(sorted(s.composition.items())), s.charge): s.id
        for s in registry.species.values()
        if s.composition
    }


def test_registered_fragments_keep_their_id():
    proposed = fragments.electron_channels("F2", {"F": 2}, known())
    equations = {item.equation for item in proposed}
    assert "e + F2 -> e + F2" in equations
    assert "e + F2 -> e + e + F2+" in equations
    assert "e + F2 -> e + F + F" in equations
    assert not [item for item in proposed if item.new_species and "F2+" in item.new_species]


def test_an_unregistered_fragment_is_named_and_flagged():
    """A gas with no registered chemistry is exactly what discover is for."""

    proposed = fragments.electron_channels("SiH4", {"Si": 1, "H": 4}, {})
    equations = {item.equation for item in proposed}
    assert "e + SiH4 -> e + SiH3 + H" in equations
    assert "e + SiH4 -> e + SiH2 + H2" in equations
    assert "e + SiH4 -> e + e + SiH4+" in equations

    dissociation = next(i for i in proposed if i.equation == "e + SiH4 -> e + SiH3 + H")
    assert set(dissociation.new_species) == {"SiH3", "H"}


def test_only_the_ligand_leaves():
    """Stripping anything but the ligand invents fragments like H4."""

    proposed = fragments.electron_channels("SiH4", {"Si": 1, "H": 4}, {})
    products = {name for item in proposed for name in item.products}
    assert products & {"H", "H2"}  # the ligand leaves, singly or paired
    assert not products & {"H3", "H4"}  # never the whole hydrogen shell


def test_formula_is_written_least_electronegative_first():
    assert fragments.formula({"Si": 1, "H": 4}) == "SiH4"
    assert fragments.formula({"S": 1, "F": 6}) == "SF6"
    assert fragments.formula({"C": 1, "F": 4}) == "CF4"


# --------------------------------------------------------------------------- sources


def test_reachability_depends_on_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("NOT_SET", raising=False)
    catalog_sources = sources.load(catalog(tmp_path))
    by_id = {item.id: item for item in catalog_sources}

    assert by_id["pubchem"].reachable
    assert by_id["structural"].reachable
    assert not by_id["lxcat"].reachable
    assert "export from the site" in by_id["lxcat"].blocked_by

    monkeypatch.setenv("NOT_SET", "x")
    assert {s.id: s.reachable for s in sources.load(catalog(tmp_path))}["qdb"]


def test_covering_orders_by_priority(tmp_path):
    covering = sources.covering(sources.load(catalog(tmp_path)), "electron")
    assert [item.id for item in covering] == ["lxcat", "qdb", "structural"]


# --------------------------------------------------------------------------- command


def test_candidates_are_written_and_never_generation_ready(tmp_path):
    out = tmp_path / "out"
    code = main(
        [
            "channels",
            "--gas",
            "F2",
            "--registry",
            str(FIXTURE),
            "--catalog",
            str(catalog(tmp_path)),
            "--out",
            str(out),
            "--offline",
        ]
    )
    assert code == 0

    document = yaml.safe_load((out / "candidates.yaml").read_text(encoding="utf-8"))
    assert document["status"] == "candidate"
    assert all(item["status"] == "candidate" for item in document["candidates"])
    # No case accepts candidates, so nothing here can reach a generated network.
    assert "candidate" not in DEFAULT_STATUS


def test_unreachable_sources_are_named_with_their_next_step(tmp_path):
    out = tmp_path / "out"
    main(
        [
            "channels",
            "--gas",
            "F2",
            "--registry",
            str(FIXTURE),
            "--catalog",
            str(catalog(tmp_path)),
            "--out",
            str(out),
            "--offline",
        ]
    )
    document = yaml.safe_load((out / "candidates.yaml").read_text(encoding="utf-8"))
    blocked = {item["id"]: item["blocked_by"] for item in document["sources_consulted"]}
    assert blocked["lxcat"]
    assert blocked["structural"] is None


def test_an_unregistered_gas_is_reported_not_invented(tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "channels",
            "--gas",
            "Xe",
            "--registry",
            str(FIXTURE),
            "--catalog",
            str(catalog(tmp_path)),
            "--out",
            str(out),
            "--offline",
        ]
    )
    assert code == 1
    assert "unknown" in capsys.readouterr().out


# --------------------------------------------------------------------------- screening


def test_charge_transfer_is_open_toward_the_easier_ionization():
    """A+ + B is exothermic exactly when B is easier to ionize than A."""

    screened = screen.charge_transfer({"Ar": 15.76, "O2": 12.07}, {"Ar": "Ar+", "O2": "O2+"})
    by_equation = {item.equation: item for item in screened}

    forward = by_equation["Ar+ + O2 -> Ar + O2+"]
    assert forward.verdict == "open"
    assert forward.delta_e_eV < 0

    assert by_equation["O2+ + Ar -> O2 + Ar+"].verdict == "closed"


def test_a_near_resonant_channel_is_open_in_both_directions():
    """Near resonance is where charge transfer is fastest, not where it is doubtful."""

    screened = screen.charge_transfer({"A": 10.0, "B": 10.02}, {"A": "A+", "B": "B+"})
    assert {item.verdict for item in screened} == {"open"}


def test_a_clearly_endothermic_transfer_stays_closed():
    screened = screen.charge_transfer({"A": 10.0, "B": 13.0}, {"A": "A+", "B": "B+"})
    by_equation = {item.equation: item.verdict for item in screened}
    assert by_equation["B+ + A -> B + A+"] == "open"  # A ionizes more easily
    assert by_equation["A+ + B -> A + B+"] == "closed"


def test_a_neutral_without_a_registered_ion_is_skipped():
    screened = screen.charge_transfer({"Ar": 15.76, "Xe": 12.13}, {"Ar": "Ar+"})
    assert not [item for item in screened if "Xe+" in item.equation]


# --------------------------------------------------------------------------- evidence


def test_a_name_collision_is_not_evidence_against_the_species():
    """PubChem answers `SF5` with an unrelated organic; that is not a refutation."""

    from acquire import pubchem
    from acquire.pubchem import Identity
    from discover.evidence import _read

    collided = Identity(species="SF5", cid=1, formula="C15H13NS", mass_amu=255.3)
    verdict = pubchem.compare(collided, {"S": 1, "F": 5})
    assert verdict == "wrong_compound"

    status, note = _read(verdict, collided.formula)
    assert status == "unavailable"  # not "not_found"
    assert "C15H13NS" in note  # the reviewer can see what it hit


# --------------------------------------------------------------------------- existence


SNAPSHOT = {
    "source": {"source_type": "umist"},
    "records": [
        {"reaction": "E + Ar -> E + E + Ar^+", "parameters": {"A": 1.0}},
        {"reaction": "e + F2 -> e + F + F", "parameters": {"A": 2.0}},
    ],
}


def index(tmp_path: Path):
    from reactgen import known

    path = tmp_path / "snap.yaml"
    path.write_text(yaml.safe_dump(SNAPSHOT), encoding="utf-8")
    return known.load([path])


def test_a_listed_reaction_is_found_through_foreign_notation(tmp_path):
    """The source wrote `E` and `Ar^+`; the candidate writes `e` and `Ar+`."""

    listed = index(tmp_path)
    assert [item.source for item in listed.lists("e + Ar -> e + e + Ar+")] == ["umist"]
    assert listed.lists("e + F2 -> e + F + F")


def test_a_reaction_nobody_lists_is_not_confirmed(tmp_path):
    assert index(tmp_path).lists("e + Ar -> Ar-") == []


def test_existence_is_read_without_any_number(tmp_path):
    """The index carries equations only; coefficients are a separate question."""

    listed = index(tmp_path)
    found = listed.lists("e + Ar -> e + e + Ar+")[0]
    assert not hasattr(found, "rate")
    assert found.written == "E + Ar -> E + E + Ar^+"


def test_the_registry_is_the_strongest_listing(tmp_path):
    """A candidate matching a registered reaction is not new work."""

    from reactgen import known

    registry = Registry.load(FIXTURE)
    listed = known.load([], registry)
    assert listed.sources["registry"] > 0

    stated = [item.source for item in listed.lists("e + F2 -> e + F + F")]
    assert stated == ["registry"]
    assert listed.lists("e + F2 -> F2-") == []


# --------------------------------------------------------------------------- proposing


def test_a_new_gas_grows_a_multi_step_list(tmp_path):
    """The crux: products of proposed channels are asked for their own channels."""

    from discover.cli import main

    out = tmp_path / "out"
    # Non-zero: the fixture carries a deliberately unbalanced reaction, which
    # the run reports as blocking under the same contract `rgen generate` uses.
    main(["network", "--gas", "F2", "--registry", str(FIXTURE), "--out", str(out)])
    # The bundle is the same contract `rgen generate` writes.
    document = yaml.safe_load((out / "reactions.yaml").read_text(encoding="utf-8"))
    depths = {item["depth"] for item in document["reactions"]}
    assert max(depths) >= 1  # the frontier moved past the input gas
    assert (out / "species.yaml").is_file()


def test_an_excited_state_gets_no_ion_of_its_own(tmp_path):
    """Ionizing a metastable leaves the ground-state ion; `Ar_4s+` is not a species."""

    from dataclasses import replace

    from discover import propose
    from reactgen.model import State

    registry = Registry.load(FIXTURE)
    argon = registry.species["Ar"]
    registry.species["Ar_4s"] = replace(argon, id="Ar_4s", state=State(kind="excited"))
    proposer = propose.Proposer.build(registry, {"Ar": 15.76, "Ar_4s": 4.16})
    assert "Ar_4s" not in proposer.relations.cations()


def test_nothing_proposed_can_reach_a_normal_run():
    from discover import propose

    assert propose.CANDIDATE not in DEFAULT_STATUS


def test_heavy_particle_chemistry_is_skipped_without_energies():
    """No screen means no layer: an unscreened enumeration would be noise."""

    from discover import propose

    registry = Registry.load(FIXTURE)
    bare = propose.Proposer.build(registry, {}, {})
    assert bare._collide({"F"}, {"F", "F2", "F2+"}) == []


def test_only_exothermic_transfers_are_proposed():
    from discover import screen

    enthalpy = {"F": 0.8, "F2": 0.0, "CF3": -4.9, "CF4": -9.7}
    downhill = screen.reaction_energy(["CF3", "F2"], ["CF4", "F"], enthalpy)
    assert downhill < 0
    assert screen.neutral_verdict(downhill) == "open"
    assert screen.neutral_verdict(-downhill) == "closed"
    assert screen.neutral_verdict(None) == "unknown"


def test_a_closed_shell_atom_splits_into_metastable_and_resonant():
    """Selection rules on the ground configuration decide the split, not data."""

    from discover import fragments

    assert fragments.excited_states("Ar", {"Ar": 1}, "metastable") == [
        ("Ar_meta", "metastable"),
        ("Ar_res", "resonant"),
    ]


def test_an_open_shell_atom_has_no_resonant_partner():
    """O(1D) and O(1S) sit in the ground configuration; radiation is forbidden."""

    from discover import fragments

    assert fragments.excited_states("O", {"O": 1}, "metastable") == [("O_meta", "metastable")]


def test_a_molecule_carries_vibrational_and_electronic_separately():
    """Two processes, not two resolutions: their thresholds differ by an order."""

    from discover import fragments

    assert fragments.excited_states("CF4", {"C": 1, "F": 4}, "metastable") == [
        ("CF4_v", "vibrational"),
        ("CF4*", "lumped"),
    ]


def test_an_excited_species_does_not_excite_again():
    from discover import fragments

    assert fragments.excited_states("Ar_meta", {"Ar": 1}, "metastable") == []
    assert fragments.excited_states("N2_v", {"N": 2}, "lumped") == []


def test_three_ligands_leave_as_atoms_not_as_a_molecule():
    """`F3` is not a species; writing one would put a fiction in the list."""

    from discover import fragments

    proposed = fragments.electron_channels("SF6", {"S": 1, "F": 6}, {}, max_leaving=3)
    equations = {item.equation for item in proposed}
    assert "e + SF6 -> e + SF3 + F + F + F" in equations
    products = {name for item in proposed for name in item.products}
    assert "F3" not in products  # the leaving trio is three atoms, not a molecule


def test_a_leaving_pair_may_be_the_real_diatomic():
    from discover import fragments

    proposed = fragments.electron_channels("SF6", {"S": 1, "F": 6}, {}, max_leaving=2)
    assert "e + SF6 -> e + SF4 + F2" in {item.equation for item in proposed}


def test_every_candidate_says_how_far_it_can_be_trusted():
    from discover import propose

    registry = Registry.load(FIXTURE)
    proposer = propose.Proposer.build(registry, {}, {})
    # F has no registered electron chemistry in the fixture, so it is proposed for.
    offered = proposer({"F"}, {"F", "F2", "Ar", "e"})
    assert offered
    assert {item.source["confidence"] for item in offered} <= set(propose.CONFIDENCE)
    assert all(item.source["citation"] for item in offered)


def test_dissociative_charge_transfer_needs_the_bond_to_be_paid():
    """`Ar+ + CF4 -> Ar + CF3+ + F` opens only if IE(CF3) + D(CF3-F) < IE(Ar)."""

    from discover import screen

    ionization = {"Ar": 15.76, "CF3": 9.05}
    enthalpy = {"CF4": -9.67, "CF3": -4.85, "F": 0.82}
    energy = screen.dissociative_transfer_energy("Ar", "CF3", "F", "CF4", ionization, enthalpy)
    assert energy == pytest.approx(9.05 - 15.76 + (-4.85 + 0.82 + 9.67), abs=1e-9)
    assert screen.neutral_verdict(energy) == "open"


def test_penning_is_closed_when_the_metastable_carries_too_little():
    """Ar(4s) holds 11.6 eV and cannot ionize CF4, which needs 14.7."""

    from discover import screen

    ionization = {"CF4": 14.7, "CF3": 9.05}
    assert screen.neutral_verdict(screen.penning_energy(11.6, "CF4", ionization)) == "closed"
    assert screen.neutral_verdict(screen.penning_energy(11.6, "CF3", ionization)) == "open"


def test_penning_is_unknown_without_an_excitation_energy():
    from discover import screen

    assert screen.penning_energy(None, "CF3", {"CF3": 9.05}) is None


def test_mutual_neutralization_releases_the_ionization_energy():
    """A+ + B- returns the electron, releasing IE(A) - EA(B)."""

    from discover import screen

    energy = screen.neutralization_energy("Ar", "F", {"Ar": 15.76}, {"F": 3.40})
    assert energy == pytest.approx(3.40 - 15.76)
    assert screen.neutral_verdict(energy) == "open"


def test_neutralization_is_unknown_without_an_affinity():
    from discover import screen

    assert screen.neutralization_energy("Ar", "F", {"Ar": 15.76}, {}) is None


def test_thermochemistry_now_lives_in_the_registry(tmp_path):
    """Neutral chemistry must not need an overlay to appear."""

    from discover import view

    registry = Registry.load(Path("registry"))
    assert len(view.enthalpy(registry)) > 30
    assert len(view.affinity(registry)) > 5


def test_no_anion_is_proposed_for_a_species_that_cannot_bind_one():
    """Argon's electron affinity is -11.5 eV: `e + Ar -> Ar-` is impossible."""

    from discover import fragments

    bound = fragments.electron_channels("Ar", {"Ar": 1}, {}, binds_electron=True)
    unbound = fragments.electron_channels("Ar", {"Ar": 1}, {}, binds_electron=False)
    assert "e + Ar -> Ar-" in {item.equation for item in bound}
    assert "e + Ar -> Ar-" not in {item.equation for item in unbound}


def test_a_negative_affinity_switches_the_gate_off():
    from discover import propose

    registry = Registry.load(FIXTURE)
    proposer = propose.Proposer.build(registry, {}, {"Ar": -11.5, "F": 3.40})
    assert not proposer._binds_electron("Ar")
    assert proposer._binds_electron("F")
    assert proposer._binds_electron("unmeasured")  # no record is not a denial


def test_attachment_is_off_until_asked_for():
    """Without electron affinity the parent anion is invented, so it stays off."""

    from reactgen import processes

    assert not processes.select().allows("attachment")
    assert processes.select(enable=["attachment"]).allows("attachment")


def test_collisions_that_no_database_covers_run_by_default():
    """Ion-neutral chemistry is the point: deciding what DNT+ should compute."""

    from reactgen import processes

    active = processes.select()
    assert active.report()["on"] == [
        "dissociation",
        "elastic",
        "excitation",
        "heavy_particle",
        "ionization",
        "vibrational_relaxation",
    ]
    # Attachment still waits for electron affinities, and three-body for
    # third-body efficiencies; neither is on for want of data.
    assert not active.on("attachment")
    assert not active.on("three_body")


def test_an_unbuilt_family_is_named_rather_than_hidden():
    """Asking for growth reports that it does not exist yet."""

    from reactgen import processes

    asked = processes.select(enable=["growth"])
    assert "growth" in asked.missing
    assert not asked.on("growth")
    assert "growth" in processes.describe()


def test_the_same_reaction_written_two_ways_is_one_process():
    """A registry writes `2 e`; a proposal writes `e + e`."""

    from reactgen.model import Reaction, Term

    def build(products):
        return Reaction(
            id="x",
            family="electron",
            type="ionization",
            reactants=[Term("e"), Term("Ar")],
            products=products,
        )

    collapsed = build([Term("e", 2.0), Term("Ar+")])
    spelled_out = build([Term("e"), Term("e"), Term("Ar+")])
    assert collapsed.signature == spelled_out.signature


def test_a_registered_level_is_not_shadowed_by_a_lumped_one():
    """`O2*` beside `O2_a1Delta` would carry the same excitation twice."""

    from discover import fragments

    assert fragments.excited_states("O2", {"O": 2}, "lumped", electronic=False) == [
        ("O2_v", "vibrational")
    ]
    assert ("O2*", "lumped") in fragments.excited_states("O2", {"O": 2}, "lumped")


def test_an_atom_with_registered_levels_proposes_nothing_lumped():
    from discover import fragments

    assert fragments.excited_states("Ar", {"Ar": 1}, "lumped", electronic=False) == []


def test_every_excited_suffix_parses_back_to_its_parent():
    """`Ar_m` would read as the anion: the suffixes must not collide with charge."""

    from discover.propose import SUFFIX
    from reactgen import naming

    for suffix in SUFFIX.values():
        parsed = naming.parse(f"Ar{suffix}")
        assert dict(parsed.composition) == {"Ar": 1}, suffix
        assert parsed.charge == 0, suffix


def test_a_fragment_is_named_with_the_ground_state():
    """`O_1D` sits beside `O`; naming a fragment must not pick the excited one."""

    from discover import view

    registry = Registry.load("registry")
    index = view.known(registry)
    assert index[(((("O"), 1),), 0)] == "O"
    assert index[(((("Ar"), 1),), 0)] == "Ar"
    assert index[(((("O"), 2),), 0)] == "O2"


def test_relations_answers_with_the_ground_state_too():
    from discover.relations import Relations

    registry = Registry.load("registry")
    relations = Relations(registry.species)
    assert relations.neutral_of("O+") == "O"
    assert relations.neutral_of("Ar+") == "Ar"


def test_an_excited_dissociation_fragment_is_not_an_excitation_of_the_target():
    """`e + SO -> e + O_1D + S` says nothing about how finely SO is resolved."""

    from dataclasses import replace

    from reactgen import audit
    from reactgen.model import Network, Term

    registry = Registry.load("registry")
    elastic = registry.channels[("electron", "e", "O2")][0]
    channels = [
        replace(elastic, id="a", type="excitation", products=[Term("e"), Term("O2_v")]),
        replace(
            elastic, id="b", type="dissociation", products=[Term("e"), Term("O"), Term("O_1D")]
        ),
    ]
    o2_v = replace(
        registry.species["O2"],
        id="O2_v",
        state=__import__("reactgen.model", fromlist=["State"]).State(
            kind="excited", label="vibrational", resolution="lumped"
        ),
    )
    species = {**registry.species, "O2_v": o2_v}
    gaps = audit.audit(registry, Network(species=species, reactions=channels))
    assert not [g for g in gaps if g.kind == "double_counted"]


# --------------------------------------------------------------------------- collide

HF = {"Ar": 0.0, "O2": 0.0, "F": 0.82, "SF6": -12.650, "SF5": -9.415}
IE = {"Ar": 15.7596, "O2": 12.0697, "SF5": 9.60}
EA = {"F": 3.40119}


def _energies():
    from discover import collide

    return collide.Energies(HF, IE, EA, {})


def test_one_enthalpy_difference_reproduces_the_hand_written_formulas():
    """Charge transfer, neutralization and dissociative transfer were one rule."""

    from discover import collide

    def hf(name, charge):
        return collide.enthalpy(name, charge, HF, IE, EA)

    transfer = (hf("Ar", 0) + hf("O2", 1)) - (hf("Ar", 1) + hf("O2", 0))
    assert transfer == pytest.approx(IE["O2"] - IE["Ar"])

    neutralize = (hf("Ar", 0) + hf("F", 0)) - (hf("Ar", 1) + hf("F", -1))
    assert neutralize == pytest.approx(EA["F"] - IE["Ar"])

    bond = HF["SF5"] + HF["F"] - HF["SF6"]
    dissociative = (hf("Ar", 0) + hf("SF5", 1) + hf("F", 0)) - (hf("Ar", 1) + hf("SF6", 0))
    assert dissociative == pytest.approx(IE["SF5"] - IE["Ar"] + bond)


def test_valence_refuses_a_skeleton_that_cannot_carry_the_ligands():
    """Recombination is otherwise free to write species that do not exist."""

    from discover import collide

    assert collide.plausible({"C": 1, "F": 4})
    assert collide.plausible({"S": 1, "F": 6})
    assert collide.plausible({"C": 2, "F": 6})
    assert not collide.plausible({"C": 1, "F": 5})
    assert not collide.plausible({"S": 1, "F": 7})
    assert not collide.plausible({"C": 2, "F": 7})
    assert not collide.plausible({"F": 3})


def test_an_endothermic_channel_is_kept_with_its_threshold():
    """DNT+ computes a cross section with an onset; deleting the channel loses it."""

    from discover import collide

    argon = collide.Partner("Ar+", {"Ar": 1}, 1)
    hexafluoride = collide.Partner("SF6", {"S": 1, "F": 6}, 0)
    found = collide.channels(argon, hexafluoride, _energies())

    uphill = [c for c in found if c.delta_h_eV and c.delta_h_eV > 0]
    assert uphill, "endothermic channels must survive the screen"
    assert all(c.threshold_eV == pytest.approx(c.delta_h_eV) for c in uphill)

    downhill = [c for c in found if c.delta_h_eV and c.delta_h_eV < 0]
    assert all(c.threshold_eV == 0.0 for c in downhill)


def test_an_excited_level_carries_the_ground_state_value():
    """Exact, not estimated: Hf(X*) = Hf(X) + E and IE(X*) = IE(X) - E."""

    from discover import view

    registry = Registry.load("registry")
    enthalpies, energies = view.enthalpy(registry), view.ionization(registry)

    argon = registry.species["Ar_4s"].state.energy_eV
    assert enthalpies["Ar_4s"] == pytest.approx(enthalpies["Ar"] + argon)
    # The registry records this ionization threshold independently, so the two
    # agreeing is a check on both.
    assert energies["Ar_4s"] == pytest.approx(energies["Ar"] - argon, abs=0.01)

    # O_1D records its own enthalpy, so the derivation stands aside; that the
    # two agree to a hundredth of an eV is a check on both.
    excited = registry.species["O_1D"].state.energy_eV
    assert enthalpies["O_1D"] == pytest.approx(enthalpies["O"] + excited, abs=0.01)


def test_a_source_labels_a_reaction_and_never_removes_it(tmp_path):
    """Confirmation is recorded beside the channel; silence refutes nothing."""

    import yaml as _yaml

    from discover.cli import main

    index = tmp_path / "listed.yaml"
    index.write_text(
        _yaml.safe_dump({"reactions": [{"equation": "e + F2 -> e + F + F", "source": "a_paper"}]}),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    main(
        [
            "network",
            "--gas",
            "F2",
            "--registry",
            str(FIXTURE),
            "--known",
            str(index),
            "--out",
            str(out),
        ]
    )
    document = _yaml.safe_load((out / "reactions.yaml").read_text(encoding="utf-8"))
    labelled = {r["equation"]: r["listed_by"] for r in document["reactions"]}
    # The registry is itself a listing: a reaction it states is confirmed.
    assert "registry" in labelled["e + F2 -> e + F2"]
    # Everything else keeps its place in the list, unlabelled.
    assert len(labelled) > 1
    assert any(not marks for marks in labelled.values())


def test_the_registry_is_matched_without_a_snapshot(tmp_path):
    """A curated channel confirms a candidate whether or not a list is supplied.

    Attestation once needed `--known` before it looked at anything, so a run
    with no published list to hand called every reaction unattested -- including
    the ones the registry itself states.
    """

    import yaml as _yaml

    from discover.cli import main

    out = tmp_path / "out"
    main(["network", "--gas", "F2", "--registry", str(FIXTURE), "--out", str(out)])

    document = _yaml.safe_load((out / "reactions.yaml").read_text(encoding="utf-8"))
    labelled = {r["equation"]: r["listed_by"] for r in document["reactions"]}
    assert "registry" in labelled["e + F2 -> e + F2"]
    # Still a label and not a filter: the proposed channels are all still here.
    assert any(not marks for marks in labelled.values())


def test_a_vibrational_manifold_gets_a_heavy_partner_to_relax_on():
    """Without it, electron superelastic is the only way down from X_v."""

    from discover import propose, view
    from reactgen.registry import Registry as _Registry

    registry = _Registry.load("registry")
    proposer = propose.Proposer.build(
        registry,
        view.ionization(registry),
        view.affinity(registry),
        view.enthalpy(registry),
        view.excitation(registry),
        excitation="lumped",
    )
    proposer({"O2"}, {"O2", "Ar", "O"})
    found = proposer._relaxation({"O2_v"}, {"O2_v", "O2", "Ar", "O"})
    written = {r.equation for r in found}

    # The partner is named, not hidden behind a generic third body: which one it
    # is decides the rate by orders of magnitude.
    assert "O2_v + O2 -> O2 + O2" in written
    assert "O2_v + Ar -> O2 + Ar" in written
    assert all(r.threshold_eV == 0.0 for r in found)  # downhill, no barrier
