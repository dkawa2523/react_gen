"""Polarizability estimated by element additivity, for species no source holds.

Every radical this project needs -- CF, CF2, CF3, SF, SF2, SF4, SF5, SO, SOF,
SOF3, SOF4 -- is absent from every polarizability compilation that exists.
Measured, not assumed: `chemicals` and `thermo` hold no polarizability table at
all, `mendeleev` answers for atoms, the CCCBDB experimental list covers 261
closed-shell species and none of these, and CCCBDB's calculated pages offer
only PM6 (-22% to +14% against measurement) and Miller's group additivity,
which returns 1.294 A3 for CF3 against 3.041 for CF4 -- a ratio no molecule has.

So this fits the additivity itself, on the 243 CCCBDB species whose elements
this registry uses:

    alpha = c0 + sum_i n_i c_i

Leave-one-out over that set gives a median error of 4.4%, a 90th percentile of
18%, and a worst case above 100%. Against the anchors that matter it lands at
+0.9% on SF6, -4.6% on CF4, +6.6% on SOF2.

It is not part of `tools/refresh_properties.py` and `rgen adopt` should not be
pointed at its output. The reason is the kinetics layer, whose whole claim is
that its rate is an upper bound -- "this reaction is no faster than this". The
fit is trained entirely on closed-shell molecules, and a radical is more
polarizable than its closed-shell analogue, so these numbers are low. Since
k_L scales as sqrt(alpha), a low alpha gives a low rate, and a bound that can
be exceeded is not a bound. Feeding these into the registry would quietly turn
a guarantee into a guess.

What they are good for is a documented exploratory collision-property estimate.
They remain estimated evidence and are never promoted to measured kinetics.
"""

from __future__ import annotations

from dataclasses import dataclass

# Leave-one-out error over the CCCBDB training set, carried into every record.
LOO_MEDIAN = 0.044
LOO_90TH = 0.181


@dataclass(frozen=True)
class Estimate:
    """One species' fitted polarizability, and the fit it came from."""

    species: str
    polarizability_A3: float
    training_size: int
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.error is None


def fit(training: list[tuple[dict[str, int], float]]) -> tuple[dict[str, float], float] | None:
    """Least-squares element contributions and an intercept, or None if underdetermined."""

    import numpy as np

    if len(training) < 20:
        return None
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
        missing = [element for element in composition if element not in contributions]
        if missing:
            out.append(Estimate(name, 0.0, len(training), f"no contribution fitted for {missing}"))
            continue
        value = intercept + sum(count * contributions[e] for e, count in composition.items())
        if value <= 0:
            out.append(Estimate(name, 0.0, len(training), "fit returned a non-physical value"))
            continue
        out.append(Estimate(name, round(value, 4), len(training)))
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
            "source": {
                "citation": (
                    f"{citation}; element additivity fitted to {item.training_size} CCCBDB "
                    f"species, leave-one-out median {LOO_MEDIAN:.1%} and 90th percentile "
                    f"{LOO_90TH:.1%}; trained on closed-shell molecules, so a radical is low"
                )
            },
        }
        for item in found
        if item.known
    ]
