"""Gas-phase ground-state polarizability estimates from composition additivity.

The model alpha = c0 + sum(n_i*c_i) is an explicit approximation, not a
measurement, bound, identity determination or reaction-rate calculation.
It does not distinguish structures of the same composition. CCCBDB describes
its target collection as gas-phase atoms and small molecules:
https://cccbdb.nist.gov/
"""

from __future__ import annotations

from dataclasses import dataclass

from reactgen.chemistry import parse_state_id


@dataclass(frozen=True)
class Estimate:
    """One species' fitted polarizability, and the fit it came from."""

    species: str
    polarizability_A3: float
    training_size: int
    error: str | None = None
    phase: str = "gas"
    structure: str | None = None

    @property
    def known(self) -> bool:
        return self.error is None


def fit(training: list[tuple[dict[str, int], float]]) -> tuple[dict[str, float], float] | None:
    """Least-squares element contributions and an intercept, or None if underdetermined."""

    if len(training) < 20:
        return None

    import numpy as np

    elements = sorted({element for composition, _ in training for element in composition})
    design = np.array(
        [
            [composition.get(element, 0) for element in elements] + [1.0]
            for composition, _ in training
        ],
        float,
    )
    values = np.array([value for _, value in training], float)
    beta, *_ = np.linalg.lstsq(design, values, rcond=None)
    # float(), not numpy scalars: these are serialised to YAML downstream.
    return {e: float(b) for e, b in zip(elements, beta[:-1], strict=True)}, float(beta[-1])


def estimate(
    wanted: list[tuple[str, dict[str, int]]],
    training: list[tuple[dict[str, int], float]],
) -> list[Estimate]:
    """A value per species, refusing any whose elements the fit never saw."""

    fitted = fit(training)
    if fitted is None:
        return [Estimate(name, 0.0, 0, "not enough training data") for name, _ in wanted]
    contributions, intercept = fitted
    out = []
    for name, composition in wanted:
        state = parse_state_id(name)
        if state is None or state.charge or state.state.kind != "ground" or state.phase != "gas":
            out.append(
                Estimate(name, 0.0, len(training), "model requires neutral gas ground state")
            )
            continue
        if state.composition != composition:
            out.append(
                Estimate(name, 0.0, len(training), "composition contradicts target identity")
            )
            continue
        missing = [element for element in composition if element not in contributions]
        if missing:
            out.append(Estimate(name, 0.0, len(training), f"no contribution fitted for {missing}"))
            continue
        value = intercept + sum(count * contributions[e] for e, count in composition.items())
        if value <= 0:
            out.append(Estimate(name, 0.0, len(training), "fit returned a non-physical value"))
            continue
        out.append(Estimate(name, round(value, 4), len(training), structure=state.structure))
    return out


def records(found: list[Estimate], citation: str) -> list[dict]:
    """Property records, each marked as the estimate it is."""

    return [
        {
            "species": item.species,
            "property": "polarizability_A3",
            "value": item.polarizability_A3,
            "unit": "A3",
            "quality": "estimated",
            "status": "estimated",
            "phase": item.phase,
            "structure": item.structure,
            "source": {
                "citation": (
                    f"{citation}; element additivity fitted to {item.training_size} CCCBDB "
                    "species; gas-phase ground-state estimate; dependence on structure "
                    "is neglected, target accuracy has not been established"
                )
            },
        }
        for item in found
        if item.known
    ]
