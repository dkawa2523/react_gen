from __future__ import annotations

from pathlib import Path
import csv

import yaml

from external_data_tools.astrochem_network_convert import convert_astrochem_network, main


FIELDS = [
    "reactant1",
    "reactant2",
    "product1",
    "product2",
    "product3",
    "alpha",
    "beta",
    "gamma",
    "temperature_min_K",
    "temperature_max_K",
    "source",
    "reference",
]


def test_converts_simple_ion_neutral_row(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "Ar+",
                "reactant2": "CF4",
                "product1": "Ar",
                "product2": "CF4+",
                "product3": "",
                "alpha": "1.2e-9",
                "beta": "0.0",
                "gamma": "10.0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "KIDA:row1",
                "reference": "Example reference",
            }
        ],
    )
    output = tmp_path / "external_data" / "snapshots" / "kida_converted_ion_neutral.yaml"

    report = convert_astrochem_network(network, database="KIDA", output=output)
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    reaction = payload["reactions"][0]

    assert report["total_rows"] == 1
    assert report["ion_neutral_rows"] == 1
    assert report["converted"] == 1
    assert report["skipped"] == 0
    assert report["unresolved"] == []
    assert payload["source"]["database"] == "KIDA"
    assert payload["source"]["review_required"] is True
    assert reaction["projectile"] == "Ar+"
    assert reaction["target"] == "CF4"
    assert reaction["family"] == "ion_neutral"
    assert reaction["type"] == "reactive_scattering"
    assert reaction["status"] == "imported"
    assert reaction["dnt_class"] == "long_range_charge_exchange"
    assert reaction["products"] == [{"species": "Ar", "n": 1}, {"species": "CF4+", "n": 1}]


def test_skips_neutral_neutral_row(tmp_path):
    network = _write_network(
        tmp_path / "umist.tsv",
        [
            {
                "reactant1": "H2",
                "reactant2": "CO",
                "product1": "HCO",
                "product2": "",
                "product3": "",
                "alpha": "1e-10",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "100",
                "source": "UMIST:row1",
                "reference": "Neutral-neutral",
            }
        ],
        delimiter="\t",
    )

    report = convert_astrochem_network(
        network,
        database="UMIST",
        output=tmp_path / "external_data" / "snapshots" / "umist.yaml",
    )

    assert report["total_rows"] == 1
    assert report["ion_neutral_rows"] == 0
    assert report["converted"] == 0
    assert report["skipped"] == 1


def test_preserves_rate_coefficients_separately_from_cross_sections(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "H+",
                "reactant2": "H",
                "product1": "H",
                "product2": "H+",
                "product3": "",
                "alpha": "2.0e-9",
                "beta": "-0.5",
                "gamma": "0.1",
                "temperature_min_K": "5",
                "temperature_max_K": "500",
                "source": "KIDA:ct",
                "reference": "Rate reference",
            }
        ],
    )
    output = tmp_path / "snapshot.yaml"

    convert_astrochem_network(network, database="KIDA", output=output)
    reaction = yaml.safe_load(output.read_text(encoding="utf-8"))["reactions"][0]

    assert reaction["data"]["rate_form"] == {
        "alpha": 2.0e-9,
        "beta": -0.5,
        "gamma": 0.1,
        "temperature_min_K": 5.0,
        "temperature_max_K": 500.0,
    }
    assert reaction["data"]["provenance"] == {
        "database": "KIDA",
        "original_source": "KIDA:ct",
        "reference": "Rate reference",
    }
    assert reaction["data"]["review_status"] == "astrochem_candidate_not_semiconductor_validated"
    assert "cross_section" not in reaction["data"]
    assert reaction["source_record"]["review_required"] is True


def test_invalid_notation_reports_unresolved(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "C?+",
                "reactant2": "CF4",
                "product1": "C",
                "product2": "CF4+",
                "product3": "",
                "alpha": "1e-9",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "bad",
                "reference": "bad notation",
            }
        ],
    )

    report = convert_astrochem_network(network, database="KIDA", output=tmp_path / "out.yaml")

    assert report["converted"] == 0
    assert report["unresolved"] == [
        {
            "line": 2,
            "reason": "invalid_notation",
            "message": "reactant notation could not be normalized",
            "reactants": ["C?+", "CF4"],
        }
    ]


def test_cli_writes_output_and_report(tmp_path):
    network = _write_network(
        tmp_path / "umist.csv",
        [
            {
                "reactant1": "C+",
                "reactant2": "O",
                "product1": "C",
                "product2": "O+",
                "product3": "",
                "alpha": "1e-9",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "UMIST:ct",
                "reference": "UMIST ref",
            }
        ],
    )
    output = tmp_path / "external_data" / "snapshots" / "umist_converted_ion_neutral.yaml"

    exit_code = main([str(network), "--database", "UMIST", "--output", str(output)])

    report = yaml.safe_load(output.with_suffix(".conversion_report.yaml").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output.exists()
    assert report["converted"] == 1


def _write_network(path: Path, rows: list[dict[str, str]], delimiter: str = ",") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path
