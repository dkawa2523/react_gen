"""Tests for the acquisition package and its handoff to `rgen ingest`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from acquire import lxcat, snapshot
from acquire.cli import main
from reactgen import ingest
from reactgen.registry import Registry

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


def test_a_block_without_a_table_is_dropped(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("ELASTIC\nAr\nPROCESS: E + Ar -> E + Ar, Elastic\n", encoding="utf-8")
    assert lxcat.parse(path) == []


def test_converted_export_matches_registered_reactions(export, tmp_path):
    assert main(["lxcat", str(export), "--out", str(tmp_path / "work")]) == 0

    document = yaml.safe_load((tmp_path / "work" / "snapshot.yaml").read_text(encoding="utf-8"))
    assert document["kind"] == "cross_section"
    assert len(document["records"]) == 2

    report = ingest.ingest(
        tmp_path / "work" / "snapshot.yaml",
        Registry.load(FIXTURE),
        tmp_path / "work" / "overlay.yaml",
    )
    assert report.accepted == 2
    assert report.ok


def test_overlay_assets_resolve_against_the_overlay(export, tmp_path):
    work = tmp_path / "work"
    main(["lxcat", str(export), "--out", str(work)])
    ingest.ingest(work / "snapshot.yaml", Registry.load(FIXTURE), work / "overlay.yaml")

    merged = Registry.load(FIXTURE, overlay=work / "overlay.yaml")
    reaction = next(
        r for r in merged.channels[("electron", "e", "Ar")] if r.id == "e_Ar_ionization"
    )
    dataset = reaction.best("cross_section")
    assert dataset is not None
    assert merged.table(dataset.asset) == [(15.7596, 0.0), (100.0, 2.7e-20)]


def test_table_asset_is_written_next_to_the_snapshot(tmp_path):
    relative = snapshot.write_table(tmp_path, "demo", [(1.0, 2.0)], "energy_eV,cross_section_m2")
    assert relative == "assets/demo.csv"
    assert "1.000000e+00,2.000000e+00" in (tmp_path / relative).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- umist

RELEASE = """\
1:CE:Ar+:O2::Ar:O2+:::1.00e-11:0.00:0.00:10:41000:A:1:2012
2:NN:O:O2::O:O2:::2.00e-12:0.00:1200.0:200:2000:C:1:2012
3:TB:F:F:M:F2:M:::1.00e-33:0.00:0.00:10:300:D:1:2012
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


def test_three_body_rows_are_left_out(tmp_path):
    from acquire import umist

    path = tmp_path / "rate.rates"
    path.write_text(RELEASE, encoding="utf-8")
    equations = {item["reaction"] for item in umist.records(umist.parse(path))}
    assert "Ar+ + O2 -> Ar + O2+" in equations
    assert not [name for name in equations if " M " in name]


def test_the_astrochemical_range_travels_with_the_rate(tmp_path):
    """A 10-300 K coefficient must announce itself at a plasma temperature."""

    from acquire import umist

    path = tmp_path / "rate.rates"
    path.write_text("9:NN:O:O2::O:O2:::1.0e-12:0.0:0.0:10:300:C:1:2012\n", encoding="utf-8")
    record = umist.records(umist.parse(path))[0]
    assert record["validity"] == {"minimum": 10.0, "maximum": 300.0, "unit": "K"}


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
