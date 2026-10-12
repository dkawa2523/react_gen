"""Tests for the acquisition package and its handoff to `rgen ingest`."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from acquire import lxcat, snapshot
from acquire.cli import main
from reactgen import export as bundle_export
from reactgen import ingest
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze

FIXTURE = Path(__file__).parent / "fixtures" / "mini"

EXPORT = """\
ELASTIC
Ar
 1.360000e-5
SPECIES: e / Ar
PROCESS: E + Ar -> E + Ar, Elastic
PARAM.:  m/M = 1.360000e-5, complete set
COMMENT: momentum transfer.
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 0.000000e+0\t7.500000e-20
 1.000000e+1\t7.700000e-20
-----------------------------

IONIZATION
Ar -> Ar^+
 1.575960e+1
SPECIES: e / Ar
PROCESS: E + Ar -> E + E + Ar+, Ionization
PARAM.:  E = 15.7596 eV, complete set
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 1.575960e+1\t0.000000e+0
 1.000000e+2\t2.700000e-20
-----------------------------
"""


@pytest.fixture
def export(tmp_path: Path) -> Path:
    path = tmp_path / "export.txt"
    path.write_text(EXPORT, encoding="utf-8")
    return path


def test_every_process_block_is_parsed(export):
    processes = lxcat.parse(export)
    assert [item.kind for item in processes] == ["ELASTIC", "IONIZATION"]
    assert processes[0].equation == "E + Ar -> E + Ar"
    assert processes[0].table == [(0.0, 7.5e-20), (10.0, 7.7e-20)]


def test_threshold_comes_from_the_param_line(export):
    ionization = lxcat.parse(export)[1]
    assert ionization.threshold_eV == pytest.approx(15.7596)
    assert ionization.target == "Ar"


def test_a_block_without_a_table_is_an_input_error(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("ELASTIC\nAr\nPROCESS: E + Ar -> E + Ar, Elastic\n", encoding="utf-8")
    with pytest.raises(ValueError, match="process block has no table"):
        lxcat.parse(path)


def test_converted_export_matches_registered_reactions(export, tmp_path):
    assert main(["lxcat", str(export), "--out", str(tmp_path / "work")]) == 0

    document = yaml.safe_load((tmp_path / "work" / "snapshot.yaml").read_text(encoding="utf-8"))
    assert document["kind"] == "cross_section"
    assert len(document["records"]) == 2

    catalog = EvidenceCatalog.load(FIXTURE)
    generated = analyze(Case("argon", ("Ar",)), catalog)
    bundle_export.write(tmp_path / "bundle", generated)
    report = ingest.ingest(
        tmp_path / "work" / "snapshot.yaml",
        tmp_path / "bundle",
        tmp_path / "work" / "overlay.yaml",
    )
    assert report.accepted == 2


def test_overlay_assets_resolve_against_the_overlay(export, tmp_path):
    work = tmp_path / "work"
    main(["lxcat", str(export), "--out", str(work)])
    catalog = EvidenceCatalog.load(FIXTURE)
    generated = analyze(Case("argon", ("Ar",)), catalog)
    bundle_export.write(work / "bundle", generated)
    ingest.ingest(work / "snapshot.yaml", work / "bundle", work / "overlay.yaml")

    overlay = yaml.safe_load((work / "overlay.yaml").read_text(encoding="utf-8"))
    datasets = [item for group in overlay["datasets"].values() for item in group]
    ionization = next(item for item in datasets if "ionization" in Path(item["asset"]["path"]).name)
    asset = (work / ionization["asset"]["path"]).resolve()
    assert not Path(ionization["asset"]["path"]).is_absolute()
    with asset.open(encoding="utf-8", newline="") as stream:
        table = list(csv.reader(stream))[1:]
    assert (15.7596, 0.0) in [tuple(map(float, row)) for row in table]


def test_table_asset_is_written_next_to_the_snapshot(tmp_path):
    relative = snapshot.write_table(tmp_path, "demo", [(1.0, 2.0)], "energy_eV,cross_section_m2")
    assert relative == "assets/demo.csv"
    with (tmp_path / relative).open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [["energy_eV", "cross_section_m2"], ["1.0", "2.0"]]


# --------------------------------------------------------------------------- umist

RELEASE = """\
1:CE:Ar+:O2:Ar:O2+:::1:1.00e-11:0.00:0.00:10:41000:M:A:2012
2:NN:O:O2:O:O2:::1:2.00e-12:0.00:1200.0:200:2000:C:C:2012
3:PH:F2:PHOTON:F:F:::1:1.00e-10:0.00:0.00:10:300:M:D:2012
# a comment, and a blank line follow

"""


def test_umist_rows_become_si_arrhenius(tmp_path):
    from acquire import umist

    path = tmp_path / "rate.rates"
    path.write_text(RELEASE, encoding="utf-8")
    rates = {item.equation: item for item in umist.parse(path)}

    charge_transfer = rates["Ar+ + O2 -> Ar + O2+"]
    assert charge_transfer.a_si == pytest.approx(1.0e-17)  # cm3/s -> m3/s
    assert charge_transfer.t_min == 10.0

    # gamma is in kelvin in the release and in eV in the registry
    assert rates["O + O2 -> O + O2"].activation_eV == pytest.approx(1200.0 / 11604.518)


def test_photoprocesses_are_not_misread_as_thermal_arrhenius_rates(tmp_path):
    from acquire import umist

    path = tmp_path / "rate.rates"
    path.write_text(RELEASE, encoding="utf-8")
    equations = {item["reaction"] for item in umist.records(umist.parse(path))}
    assert "Ar+ + O2 -> Ar + O2+" in equations
    assert not [name for name in equations if "PHOTON" in name]


def test_the_astrochemical_range_travels_with_the_rate(tmp_path):
    """A 10-300 K coefficient must announce itself at a plasma temperature."""

    from acquire import umist

    path = tmp_path / "rate.rates"
    path.write_text("9:NN:O:O2:O:O2:::1:1.0e-12:0.0:0.0:10:300:C:C:2012\n", encoding="utf-8")
    record = umist.records(umist.parse(path))[0]
    assert record["validity"] == {
        "quantity": "gas_temperature",
        "minimum": 10.0,
        "maximum": 300.0,
        "unit": "K",
    }


# --------------------------------------------------------------------------- download


def test_a_web_page_is_never_accepted_as_a_release():
    """A single-page site answers 200 for every path; the body decides."""

    from acquire.download import _wrong_content

    page = b"<!DOCTYPE html>\n<html><body>UDfA</body></html>"
    assert "web page" in (_wrong_content(page, "umist") or "")


def test_a_body_that_is_not_the_declared_format_is_refused():
    from acquire.download import _wrong_content

    assert _wrong_content(b"energy,cross_section\n1,2\n", "umist")
    assert _wrong_content(b"1:CE:Ar+:O2::Ar:O2+:::1e-11:0:0:10:41000\n", "umist") is None


def test_only_https_is_fetched():
    from acquire import download

    got = download.fetch("http://example.invalid/RATE.txt", "umist")
    assert not got.ok
    assert "https" in (got.error or "")


# --------------------------------------------------------------------------- thermo


def test_thermo_is_optional_and_says_so_when_absent(monkeypatch):
    from acquire import thermo

    monkeypatch.setattr(thermo, "available", lambda: False)
    found = thermo.fetch(["CF4"])
    assert not found[0].known
    assert "not installed" in (found[0].error or "")


def test_enthalpy_is_converted_to_eV_per_molecule():
    from acquire import thermo

    found = thermo.fetch(["CF4"])
    if not found[0].known:
        pytest.skip("chemicals is not installed")
    # -933.38 kJ/mol for CF4; the registry records eV per molecule.
    assert found[0].enthalpy_eV == pytest.approx(-933380.0 / 96485.33212, rel=1e-6)


def test_records_carry_the_source_and_the_cas():
    from acquire import thermo

    found = thermo.fetch(["CF4"])
    if not found[0].known:
        pytest.skip("chemicals is not installed")
    written = thermo.records(found, "chemicals")
    assert {item["property"] for item in written} == {"enthalpy_formation_eV", "entropy_J_mol_K"}
    assert found[0].cas in written[0]["source"]["citation"]
    enthalpy = next(item for item in written if item["property"] == "enthalpy_formation_eV")
    assert enthalpy["source"]["collection"] == found[0].enthalpy_method
    assert enthalpy["source"]["release"] == found[0].package_version
    assert enthalpy["source"]["record_id"] == f"{found[0].cas}:enthalpy_formation_eV"
    assert enthalpy["formation_reference"] == {
        "temperature_K": 298.15,
        "basis": "standard_elements",
    }


def test_thermo_adapter_preserves_unstated_reference_without_guessing_from_package_name():
    from acquire import thermo

    original = thermo.Thermo(
        "synthetic",
        "example",
        "F",
        enthalpy_eV=1,
        enthalpy_method="another_table",
        package_version="test",
    )
    written = thermo.records([original], "chemicals")[0]
    assert written["formation_reference"]["temperature_K"] is None
    assert "standard_pressure_Pa" not in written["formation_reference"]
    assert "electron_convention" not in written["formation_reference"]


def test_a_fuzzy_name_match_is_refused(monkeypatch):
    """`CF` resolves to fluoromethane; a wrong enthalpy would corrupt the screen."""

    from acquire import thermo

    if not thermo.available():
        pytest.skip("chemicals is not installed")
    found = thermo.fetch(["CF"], {"CF": {"C": 1, "F": 1}})[0]
    assert not found.known
    assert "different compound" in (found.error or "")


def test_a_correct_match_still_passes():
    from acquire import thermo

    if not thermo.available():
        pytest.skip("chemicals is not installed")
    found = thermo.fetch(["CF4"], {"CF4": {"C": 1, "F": 4}})[0]
    assert found.known
    assert found.formula == "CF4"


# --------------------------------------------------------------------------- chemkin

BURCAT = """\
CF3               J 6/77C   1F   3    0    0G   300.000  5000.000 1000.00      1
 0.55563634E+01 0.22149130E-02-0.89000000E-06 0.16000000E-09-0.11000000E-13    2
-0.58000000E+04-0.42000000E+01 0.29000000E+01 0.11000000E-01-0.10000000E-04    3
 0.44000000E-08-0.70000000E-12-0.57000000E+04 0.10000000E+02                   4
"""


def test_a_chemkin_block_yields_both_temperature_ranges(tmp_path):
    from acquire import chemkin

    path = tmp_path / "burcat.thr"
    path.write_text(BURCAT, encoding="utf-8")
    entry = chemkin.parse(path)[0]

    assert entry.name == "CF3"
    assert entry.composition == {"C": 1, "F": 3}
    assert (entry.t_min, entry.t_mid, entry.t_max) == (300.0, 1000.0, 5000.0)
    assert len(entry.low) == 7
    assert len(entry.high) == 7
    # The file writes the high range first.
    assert entry.high[0] == pytest.approx(5.5563634)
    assert entry.low[0] == pytest.approx(2.9)


def test_an_incomplete_block_is_dropped(tmp_path):
    from acquire import chemkin

    path = tmp_path / "short.thr"
    path.write_text("\n".join(BURCAT.splitlines()[:2]) + "\n", encoding="utf-8")
    assert chemkin.parse(path) == []


# --------------------------------------------------------------------------- ideal gas


def test_pyromat_supplies_a_radical_the_compilations_lack():
    """`CF` is absent from all seven sources `chemicals` aggregates."""

    from acquire import ideal_gas

    if not ideal_gas.available():
        pytest.skip("pyromat is not installed")
    found = ideal_gas.fetch(["CF"], {"CF": {"C": 1, "F": 1}})[0]
    assert found.known
    assert found.enthalpy_eV == pytest.approx(2.65, abs=0.1)


def test_a_composition_mismatch_is_refused():
    from acquire import ideal_gas

    if not ideal_gas.available():
        pytest.skip("pyromat is not installed")
    found = ideal_gas.fetch(["CF4"], {"CF4": {"C": 1, "F": 3}})[0]
    assert not found.known
    assert "composition" in (found.error or "")


def test_an_unknown_species_reports_rather_than_raises():
    from acquire import ideal_gas

    if not ideal_gas.available():
        pytest.skip("pyromat is not installed")
    assert not ideal_gas.fetch(["SOF3"])[0].known


# --------------------------------------------------------------------------- asd

ARGON_LEVELS = "\n".join(
    [
        "Configuration\tTerm\tJ\tPrefix\tLevel (eV)\tSuffix",
        '"3s2.3p6"\t"1S"\t"0"\t""\t"0.00000000"\t""',
        '"3s2.3p5.(2P*<3/2>).4s"\t"2[3/2]*"\t"2"\t""\t"11.54835442"\t""',
        '"3s2.3p5.(2P*<3/2>).4s"\t"2[3/2]*"\t"1"\t""\t"11.62359272"\t""',
    ]
)

OXYGEN_LEVELS = "\n".join(
    [
        "Configuration\tTerm\tJ\tPrefix\tLevel (eV)\tSuffix",
        '"2s2.2p4"\t"3P"\t"2"\t""\t"0.0000000"\t""',
        '"2s2.2p4"\t"3P"\t"1"\t""\t"0.0196224"\t""',
        '"2s2.2p4"\t"1D"\t"2"\t""\t"1.9673642"\t""',
    ]
)


def _levels(monkeypatch, text):
    from acquire import asd

    monkeypatch.setattr(asd, "_request", lambda symbol: text)
    return asd.fetch(["X"])[0]


def test_a_forbidden_level_is_the_metastable(monkeypatch):
    """Argon's J=2 cannot radiate to a J=0 ground state; the J=1 beside it can."""

    found = _levels(monkeypatch, ARGON_LEVELS)
    assert found.metastable_eV == pytest.approx(11.548354)
    assert found.resonant_eV == pytest.approx(11.623593)


def test_ground_term_fine_structure_is_not_an_excited_state(monkeypatch):
    """Oxygen's 3P1 sits 0.02 eV up and is the same chemical species as 3P2."""

    found = _levels(monkeypatch, OXYGEN_LEVELS)
    assert found.lowest_eV == pytest.approx(1.9673642)  # 1D, not 3P1


def test_levels_are_recorded_against_the_ground_state_atom(monkeypatch):
    from acquire import asd

    records = asd.records([_levels(monkeypatch, ARGON_LEVELS)], "NIST ASD")
    assert {item["species"] for item in records} == {"X"}
    assert "metastable_energy_eV" in {item["property"] for item in records}
    assert "lowest_excitation_energy_eV" in {item["property"] for item in records}
    assert "excitation_energy_eV" not in {item["property"] for item in records}
    assert all(item["phase"] == "gas" and item["status"] == "imported" for item in records)


def test_a_diatomic_quantum_comes_back_near_its_measured_one():
    """One mode, one fit: nitrogen and oxygen are the check on the method."""

    from acquire import vibration

    if not vibration.available():
        pytest.skip("chemicals is not installed")
    found = {
        item.species: item
        for item in vibration.fetch(
            ["N2", "O2", "CO"],
            {"N2": True, "O2": True, "CO": True},
            {"N2": 2, "O2": 2, "CO": 2},
        )
    }
    # Measured fundamentals: N2 0.289, O2 0.196, CO 0.269 eV.
    assert found["N2"].energy_eV == pytest.approx(0.289, abs=0.02)
    assert found["O2"].energy_eV == pytest.approx(0.196, abs=0.02)
    assert found["CO"].energy_eV == pytest.approx(0.269, abs=0.02)


def test_a_polyatomic_is_divided_by_its_mode_count():
    """Without it the fit lowers theta until one mode carries them all."""

    from acquire import vibration

    if not vibration.available():
        pytest.skip("chemicals is not installed")
    found = vibration.fetch(["CF4"], {"CF4": False}, {"CF4": 5})[0]
    assert found.known
    # Nine modes spanning 0.078 to 0.16 eV; an average sits inside that.
    assert 0.06 < found.energy_eV < 0.20
    assert "9 modes" in found.fit_note


# --------------------------------------------------------------------------- cantera


def test_a_polynomial_is_matched_on_composition_not_name():
    """A mechanism writes AR and this registry writes Ar; the atom counts agree."""

    from acquire import nasa

    if not nasa.available():
        pytest.skip("cantera is not installed")
    found = nasa.fetch([{"id": "Ar", "composition": {"Ar": 1}, "charge": 0}])[0]
    assert found.known
    assert found.listed_as.upper() == "AR"
    low, high = found.nasa7
    assert len(low) == 7
    assert len(high) == 7


def test_charge_is_part_of_the_match():
    """Ar and Ar+ share a composition and are different substances."""

    from acquire import nasa

    if not nasa.available():
        pytest.skip("cantera is not installed")
    neutral, cation = nasa.fetch(
        [
            {"id": "Ar", "composition": {"Ar": 1}, "charge": 0},
            {"id": "Ar+", "composition": {"Ar": 1}, "charge": 1},
        ]
    )
    assert neutral.known
    assert cation.known
    assert neutral.nasa7 != cation.nasa7


def test_gas_atom_is_never_given_a_condensed_polynomial():
    from acquire import nasa

    if not nasa.available():
        pytest.skip("cantera is not installed")
    sulfur = nasa.fetch([{"id": "S", "composition": {"S": 1}, "charge": 0}])[0]
    assert sulfur.known
    assert sulfur.origin == "nasa_gas.yaml"
    assert sulfur.listed_as == "S"
    assert sulfur.standard_pressure_Pa == 101325.0


def test_competing_structures_are_not_chosen_by_source_order(monkeypatch):
    from acquire import nasa

    entries = [{"name": "ethanol", "thermo": {}}, {"name": "dimethyl ether", "thermo": {}}]
    key = ((("C", 2), ("H", 6), ("O", 1)), 0)
    item = {"id": "C2H6O", "composition": {"C": 2, "H": 6, "O": 1}, "charge": 0}
    for choices in (entries, list(reversed(entries))):
        result = nasa._one(item, {key: choices})
        assert not result.known
        assert "ambiguous" in result.error


def test_umist_reads_every_declared_temperature_fit(tmp_path):
    from acquire import umist

    path = tmp_path / "rate.txt"
    path.write_text(
        "1:NN:O:O2:O:O2:::2:1e-12:0:0:10:100:M:A:ref1:2e-12:1:5:100:300:C:B:ref2\n",
        encoding="utf-8",
    )
    rates = umist.parse(path)
    assert [(rate.t_min, rate.t_max) for rate in rates] == [(10.0, 100.0), (100.0, 300.0)]
    assert [rate.reference for rate in rates] == ["ref1", "ref2"]
    assert len({record["source"]["record_id"] for record in umist.records(rates)}) == 2


def test_molecular_lookup_rejects_a_formula_alias_for_another_compound():
    from acquire import molecular

    if not molecular.available():
        pytest.skip("chemicals is not installed")
    radical = molecular.fetch(["CF"])[0]
    assert not radical.known
    assert "different compound" in radical.error


def test_cccbdb_cli_does_not_assign_neutral_values_to_ions(tmp_path):
    states = tmp_path / "species.yaml"
    states.write_text(
        yaml.safe_dump({"states": [{"id": "Ar+@ground", "composition": {"Ar": 1}, "charge": 1}]}),
        encoding="utf-8",
    )
    page = Path(__file__).parent / "fixtures" / "cccbdb_polarizability.html"
    output = tmp_path / "acquired"
    assert main(["cccbdb", str(states), "--page", str(page), "--out", str(output)]) == 0
    assert yaml.safe_load((output / "snapshot.yaml").read_text(encoding="utf-8"))["records"] == []


def test_an_excited_state_does_not_inherit_a_ground_nasa_fit():
    """O_1D and O match on composition, and sit 1.967 eV apart."""

    from acquire import nasa

    if not nasa.available():
        pytest.skip("cantera is not installed")
    found = nasa.fetch(
        [{"id": "O_1D", "composition": {"O": 1}, "charge": 0, "state": {"kind": "excited"}}]
    )[0]
    assert not found.known
    assert "independent evidence" in found.error


def test_nasa9_is_refused_rather_than_truncated():
    """Seven of nine terms is a different function, not a rounder one."""

    from acquire import nasa

    item = nasa.Polynomial(
        "X",
        model="NASA9",
        temperature_ranges=[200.0, 1000.0, 6000.0],
        coefficients=[[0.0] * 9, [0.0] * 9],
    )
    assert item.nasa7 == (None, None)
    assert not item.known
    assert "NASA9" in item.unusable


def test_nasa_cli_reads_analysis_state_entries(monkeypatch, tmp_path):
    from acquire import nasa

    states = tmp_path / "result.yaml"
    states.write_text(
        yaml.safe_dump(
            {
                "metadata": {"schema_version": 5},
                "states": [
                    {
                        "id": "Ar@ground",
                        "composition": {"Ar": 1},
                        "charge": 0,
                        "state": {"kind": "ground", "resolution": "resolved"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    received = []
    monkeypatch.setattr(nasa, "available", lambda: True)
    monkeypatch.setattr(nasa, "fetch", lambda items: received.extend(items) or [])
    monkeypatch.setattr(nasa, "records", lambda items, citation: [])
    assert main(["nasa", str(states), "--out", str(tmp_path / "nasa")]) == 0
    assert [item["id"] for item in received] == ["Ar@ground"]


def test_chemicals_answers_for_a_polar_molecule():
    """The value that unblocks ion-dipole capture, where symmetry gives nothing."""

    from acquire import molecular

    if not molecular.available():
        pytest.skip("chemicals is not installed")
    found = {item.species: item for item in molecular.fetch(["SO2", "CF4"])}
    assert found["SO2"].dipole_D == pytest.approx(1.63, abs=0.1)
    assert found["CF4"].dipole_D == pytest.approx(0.0, abs=0.01)
    # Half the Lennard-Jones diameter, so of the order of an atomic radius.
    assert 1.0 < found["CF4"].collision_radius_A < 4.0


def test_atomic_polarizability_is_read_not_estimated():
    """The one place polarizability can be looked up; argon is measured at 1.641."""

    from acquire import atoms

    if not atoms.available():
        pytest.skip("mendeleev is not installed")
    found = {item.symbol: item for item in atoms.fetch(["Ar", "F"])}
    assert found["Ar"].polarizability_A3 == pytest.approx(1.641, abs=0.01)
    assert found["F"].polarizability_A3 == pytest.approx(0.557, abs=0.02)


# --------------------------------------------------------------------------- cccbdb


def test_cccbdb_rows_are_recognised_by_shape_not_position():
    """The page wraps its own navigation in tables too."""

    from acquire import cccbdb

    page = (Path(__file__).parent / "fixtures" / "cccbdb_polarizability.html").read_text(
        encoding="utf-8"
    )
    found = {item.formula: item.polarizability_A3 for item in cccbdb.parse(page)}
    assert found["Ar"] == pytest.approx(1.664, abs=0.01)
    assert found["F"] == pytest.approx(0.557, abs=0.01)


def test_a_formula_is_matched_on_its_atoms():
    """CCCBDB spells thionyl fluoride F2SO and this registry spells it SOF2."""

    from acquire import cccbdb

    assert cccbdb.composition("F2SO") == cccbdb.composition("SOF2")
    assert cccbdb.composition("CF4") == (("C", 1), ("F", 4))
    # A charged or structural formula is refused rather than guessed at.
    assert cccbdb.composition("CF3+") is None
    assert cccbdb.composition("CH3(CH2)2OH") is None


def test_only_what_the_caller_allows_takes_a_value():
    """An ion may not have its neutral's polarizability."""

    from acquire import cccbdb

    page = (Path(__file__).parent / "fixtures" / "cccbdb_polarizability.html").read_text(
        encoding="utf-8"
    )
    found = cccbdb.parse(page)
    written = cccbdb.records(found, {(("Ar", 1),): "Ar"}, "a list")
    assert [item["species"] for item in written] == ["Ar"]
    assert written[0]["unit"] == "A3"


def test_cccbdb_competing_structures_require_an_explicit_source_identity():
    from acquire import cccbdb

    key = (("C", 2), ("H", 6), ("O", 1))
    found = [
        cccbdb.Listed("C2H6O", "ethanol", 5.2, electronic_state="1A"),
        cccbdb.Listed("C2H6O", "dimethyl ether", 5.1, electronic_state="1A1"),
    ]
    assert cccbdb.records(found, {key: "C2H6O"}, "list") == []
    result = cccbdb.records(found, {key: "C2H6O"}, "list", {key: "ethanol"})
    assert len(result) == 1
    assert result[0]["source_species"] == "ethanol"
    assert result[0]["structure"] == "ethanol"


def test_nasa7_rows_must_match_one_or_two_declared_temperature_regions():
    from acquire import nasa

    invalid = nasa.Polynomial("Ar", "NASA7", [200.0, 1000.0, 6000.0], [[1.0] * 7])
    assert not invalid.known
    invalid = nasa.Polynomial("Ar", "NASA7", [200.0, 1000.0, 2000.0, 6000.0], [[1.0] * 7] * 3)
    assert not invalid.known


def test_additivity_refuses_small_training_without_optional_numpy(monkeypatch):
    """Insufficient input needs no numerical solver or optional dependency."""

    import builtins

    from acquire import additivity, cccbdb

    page = (Path(__file__).parent / "fixtures" / "cccbdb_polarizability.html").read_text(
        encoding="utf-8"
    )
    training = [
        (dict(key), item.polarizability_A3)
        for item in cccbdb.parse(page)
        if (key := cccbdb.composition(item.formula)) is not None
    ]
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "numpy":
            raise ModuleNotFoundError("optional NumPy is unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    # The fixture is deliberately small, so the guard has to refuse rather than fit.
    found = additivity.estimate([("CF3", {"C": 1, "F": 3})], training)
    assert not found[0].known
    assert "training data" in found[0].error


def test_an_estimate_says_it_is_one():
    """The registry must never take one of these for a measurement."""

    from acquire import additivity

    written = additivity.records([additivity.Estimate("CF3", 2.47, 243)], "a list")
    assert written[0]["quality"] == "estimated"
    assert written[0]["status"] == "estimated"
    assert written[0]["phase"] == "gas"
    assert "accuracy has not been established" in written[0]["source"]["citation"]


def test_additivity_does_not_apply_to_another_phase_or_target_composition(monkeypatch):
    from acquire import additivity

    monkeypatch.setattr(additivity, "fit", lambda training: ({"Ar": 1.5}, 0.0))
    requested = [("Ar@ground;phase=solid", {"Ar": 1}), ("CF3", {"Ar": 1})]
    found = additivity.estimate(requested, [({"Ar": 1}, 1.5)])
    assert all(not item.known for item in found)
    assert additivity.records(found, "fit") == []


def test_additivity_cli_reports_an_undeclared_phase_without_inventing_one(
    tmp_path, monkeypatch, capsys
):
    from acquire import additivity, cccbdb

    monkeypatch.setattr(cccbdb, "fetch", lambda offline: ([], None))
    monkeypatch.setattr(additivity, "fit", lambda training: ({"Ar": 1.5}, 0.0))
    states = tmp_path / "states.yaml"
    states.write_text(
        yaml.safe_dump({"states": [{"id": "Ar", "composition": {"Ar": 1}}]}), encoding="utf-8"
    )
    out = tmp_path / "acquired"
    assert main(["additivity", str(states), "--out", str(out)]) == 0
    assert "gas phase must be explicit" in capsys.readouterr().out
    assert yaml.safe_load((out / "snapshot.yaml").read_text(encoding="utf-8"))["records"] == []
