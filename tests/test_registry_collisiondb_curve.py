"""A real source curve remains distinct from an EEDF-averaged rate coefficient."""

from pathlib import Path

import pytest

from reactgen.case import Conditions
from reactgen.evidence import EvidenceCatalog
from reactgen.numeric import assess_dataset, data_use, table_points
from reactgen.registry import Registry, registry_reaction_candidate

ROOT = Path(__file__).resolve().parents[1] / "registry"


def test_hydrogen_source_curve_keeps_its_quantity_domain_and_conversion_boundary() -> None:
    registry = Registry.load(ROOT)
    channel = registry.channels[("electron", "e", "H")][0]
    reaction = registry_reaction_candidate(channel, registry.species)
    assert reaction is not None
    evidence = EvidenceCatalog.load(ROOT).reaction(reaction)
    dataset = evidence.datasets[0]
    native = assess_dataset(dataset, reaction, evidence, Conditions())
    assert native.status == "valid"
    assert native.value is None
    assert native.kind == "cross_section"
    assert dataset.method == "calculated"
    assert dataset.provenance.record_id == "D108105"
    assert dataset.source_declaration["metadata"]["data_from_fit"] is True
    assert dataset.source_declaration["metadata"]["fit"]["fit_unc_perc"] == 1.3
    assert dataset.uncertainty is None
    assert dataset.validity is not None
    assert dataset.validity.minimum == 13.601
    # Native curve availability does not perform a scalar query at the user's
    # electron energy; its stored applicability remains part of the curve.
    assert dataset.validity.maximum == 100000
    assert (
        assess_dataset(dataset, reaction, evidence, Conditions(electron_energy_eV=40)).status
        == "valid"
    )

    # Janev and Smith, IAEA-APID-4 (1993), section 1.2.1, printed p.28:
    # original recommendation 5.88e-17 cm2 at 40 eV. The supplied table is
    # sampled from a fit, whose declared maximum deviation is 4.4%.
    points = table_points(dataset)
    assert points is not None
    left = max(point for point in points if point[0] <= 40)
    right = min(point for point in points if point[0] > 40)
    sigma = left[1] + (right[1] - left[1]) * (40 - left[0]) / (right[0] - left[0])
    assert sigma == pytest.approx(5.88e-21, rel=0.044)

    use = data_use(reaction, evidence, Conditions(electron_energy_eV=40))
    assert use.value is None
    assert use.status == "needs_input"
    assert "electron_energy_distribution" in use.required_inputs
    assert "eedf_integration" in use.required_transforms
