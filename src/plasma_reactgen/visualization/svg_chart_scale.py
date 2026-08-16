from __future__ import annotations

from math import ceil, floor, log10


def tick_max(value: float) -> float:
    if value <= 0:
        return 1.0
    step = _nice_number(value / 4)
    return step * ceil(value / step)


def tick_values(maximum: float) -> list[float]:
    step = _nice_number(maximum / 4)
    ticks: list[float] = []
    current = 0.0
    while current <= maximum + step * 0.5:
        ticks.append(round(current, 10))
        current += step
    if ticks[-1] < maximum:
        ticks.append(maximum)
    return ticks


def _nice_number(value: float) -> float:
    if value <= 0:
        return 1.0
    exponent = floor(log10(value))
    fraction = value / (10**exponent)
    if fraction < 1.5:
        nice_fraction = 1
    elif fraction < 3:
        nice_fraction = 2
    elif fraction < 7:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * (10**exponent)
