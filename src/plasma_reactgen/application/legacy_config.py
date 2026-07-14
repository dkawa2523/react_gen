from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ElectronCollisionConfig:
    """Legacy P0 configuration retained for case-file compatibility.

    Pair discovery is registry-driven and does not use these selectors.
    """

    enabled: bool = True
    targets: list[str] = field(default_factory=lambda: ["neutral", "radical"])


@dataclass
class IonNeutralCollisionConfig:
    """Legacy P0 configuration retained for case-file compatibility."""

    enabled: bool = True
    projectiles: list[str] = field(
        default_factory=lambda: ["positive_ion", "negative_ion"]
    )
    targets: list[str] = field(default_factory=lambda: ["neutral", "radical"])


@dataclass
class CollisionConfig:
    """Compatibility container; normal generation ignores family switches."""

    electron: ElectronCollisionConfig = field(default_factory=ElectronCollisionConfig)
    ion_neutral: IonNeutralCollisionConfig = field(
        default_factory=IonNeutralCollisionConfig
    )
