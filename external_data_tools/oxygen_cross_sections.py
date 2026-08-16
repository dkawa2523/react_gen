"""Mappings and parsing for the evaluated O2 collision workbook."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from external_data_tools.xlsx_table import CellValue, read_xlsx_rows

O2_DATASET_DOI = "https://doi.org/10.60893/figshare.jpr.30850013"
O2_PAPER_DOI = "https://doi.org/10.1063/5.0287254"
O2_WORKBOOK_URL = "https://api.figshare.com/v2/file/download/60268601"
SOURCE_CROSS_SECTION_TO_M2 = 1.0e-20


@dataclass(frozen=True)
class OxygenCrossSectionTarget:
    id: str
    reaction_id: str
    sheet: str
    energy_column: int
    cross_section_column: int
    uncertainty_column: int | None
    quantity: str
    preferred: bool = True


TARGETS = (
    OxygenCrossSectionTarget(
        id="elastic_integral",
        reaction_id="e_O2_elastic",
        sheet="Elastic scattering cross sectio",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=2,
        quantity="integral_elastic_cross_section",
        preferred=False,
    ),
    OxygenCrossSectionTarget(
        id="elastic_momentum_transfer",
        reaction_id="e_O2_elastic",
        sheet="momentum transfer cross section",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=2,
        quantity="momentum_transfer_cross_section",
    ),
    OxygenCrossSectionTarget(
        id="excitation_a1_delta",
        reaction_id="e_O2_excitation_O2_a1Delta",
        sheet="electronic excitation",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=None,
        quantity="state_resolved_excitation_cross_section",
    ),
    OxygenCrossSectionTarget(
        id="excitation_b1_sigma",
        reaction_id="e_O2_excitation_O2_b1Sigma",
        sheet="electronic excitation",
        energy_column=3,
        cross_section_column=4,
        uncertainty_column=None,
        quantity="state_resolved_excitation_cross_section",
    ),
    OxygenCrossSectionTarget(
        id="dissociation",
        reaction_id="e_O2_dissociation_O_O",
        sheet="Dissociation",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=2,
        quantity="neutral_dissociation_cross_section",
    ),
    OxygenCrossSectionTarget(
        id="ionization_o2_positive",
        reaction_id="e_O2_ionization",
        sheet="ionization",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=2,
        quantity="product_resolved_ionization_cross_section",
    ),
    OxygenCrossSectionTarget(
        id="dissociative_attachment",
        reaction_id="e_O2_attachment_Om_O",
        sheet="dissociative electron attachmen",
        energy_column=0,
        cross_section_column=1,
        uncertainty_column=2,
        quantity="dissociative_attachment_cross_section",
    ),
)


def parse_oxygen_cross_section(
    workbook_path: str | Path,
    target: OxygenCrossSectionTarget,
) -> list[dict[str, float]]:
    """Read one evaluated process table and convert 10^-16 cm2 to m2."""

    source_rows = read_xlsx_rows(workbook_path, target.sheet)
    rows = [_numeric_row(row, target) for row in source_rows if _has_numeric_cells(row, target)]
    if len(rows) < 2:
        raise ValueError(f"{target.id} did not contain a numeric cross-section table")
    if any(left["energy_eV"] >= right["energy_eV"] for left, right in pairwise(rows)):
        raise ValueError(f"{target.id} energies must be strictly increasing")
    return rows


def _has_numeric_cells(row: list[CellValue], target: OxygenCrossSectionTarget) -> bool:
    required_column = max(target.energy_column, target.cross_section_column)
    return (
        len(row) > required_column
        and isinstance(row[target.energy_column], float)
        and isinstance(row[target.cross_section_column], float)
    )


def _numeric_row(
    row: list[CellValue],
    target: OxygenCrossSectionTarget,
) -> dict[str, float]:
    energy_value = row[target.energy_column]
    cross_section_value = row[target.cross_section_column]
    if not isinstance(energy_value, float) or not isinstance(cross_section_value, float):
        raise ValueError(f"{target.id} row must contain numeric energy and cross section")
    energy = energy_value
    cross_section = cross_section_value
    if energy < 0 or cross_section < 0:
        raise ValueError(f"{target.id} rows must contain non-negative values")

    result = {
        "energy_eV": energy,
        "cross_section_m2": cross_section * SOURCE_CROSS_SECTION_TO_M2,
    }
    uncertainty_column = target.uncertainty_column
    if uncertainty_column is not None and len(row) > uncertainty_column:
        uncertainty = row[uncertainty_column]
        if isinstance(uncertainty, float):
            if uncertainty < 0:
                raise ValueError(f"{target.id} uncertainty must be non-negative")
            result["uncertainty_percent"] = uncertainty
    return result
