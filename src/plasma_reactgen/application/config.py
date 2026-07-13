from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


@dataclass
class ExpansionConfig:
    max_depth: int = 2
    propagate_species_classes: list[str] = field(
        default_factory=lambda: ["neutral", "radical", "positive_ion", "negative_ion"]
    )
    propagate_excited_states: bool = False


@dataclass
class ElectronCollisionConfig:
    enabled: bool = True
    targets: list[str] = field(default_factory=lambda: ["neutral", "radical"])


@dataclass
class IonNeutralCollisionConfig:
    enabled: bool = True
    projectiles: list[str] = field(default_factory=lambda: ["positive_ion", "negative_ion"])
    targets: list[str] = field(default_factory=lambda: ["neutral", "radical"])


@dataclass
class CollisionConfig:
    electron: ElectronCollisionConfig = field(default_factory=ElectronCollisionConfig)
    ion_neutral: IonNeutralCollisionConfig = field(default_factory=IonNeutralCollisionConfig)


@dataclass
class LimitsConfig:
    max_species: int = 150
    max_reactions: int = 2000
    max_pairs_per_depth: int = 1000
    max_missing_pairs_per_depth: int = 100

    def __post_init__(self) -> None:
        for name in (
            "max_species",
            "max_reactions",
            "max_pairs_per_depth",
            "max_missing_pairs_per_depth",
        ):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"limits.{name} must be greater than or equal to zero")


@dataclass
class DataPolicyConfig:
    include_incomplete_reactions: bool = True
    include_reactions_without_cross_section: bool = True
    include_reactions_without_dnt_ready_properties: bool = True
    allowed_status: list[str] = field(
        default_factory=lambda: ["curated", "literature_supported", "imported", "estimated", "draft"]
    )


@dataclass
class OutputConfig:
    dnt_inputs: bool = False


@dataclass
class InferenceConfig:
    enabled: bool = False
    include_inferred_species: bool = True
    include_inferred_reactions: bool = False
    min_confidence: float = 0.4
    max_products: int = 3
    max_fragment_depth: int = 1


@dataclass
class CaseInfo:
    name: str = "case"


@dataclass
class CaseConfig:
    case: CaseInfo
    gases: list[str]
    expansion: ExpansionConfig = field(default_factory=ExpansionConfig)
    collisions: CollisionConfig = field(default_factory=CollisionConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    data_policy: DataPolicyConfig = field(default_factory=DataPolicyConfig)
    outputs: OutputConfig = field(default_factory=OutputConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)


def load_case_config(input_path: str | Path, registry_root: str | Path) -> CaseConfig:
    input_path = Path(input_path)
    _ = registry_root
    return case_config_from_dict(_read_yaml(input_path))


def case_config_from_dict(data: dict[str, Any]) -> CaseConfig:
    case_data = data.get("case", {})
    expansion_data = data.get("expansion", {})
    collisions_data = data.get("collisions", {})
    electron_data = collisions_data.get("electron", {})
    ion_data = collisions_data.get("ion_neutral", {})
    limits_data = data.get("limits", {})
    policy_data = data.get("data_policy", {})
    outputs_data = data.get("outputs", {})
    inference_data = data.get("inference", {})

    gases = data.get("gases", [])
    if not gases:
        raise ValueError("input yaml must define at least one gas in 'gases'.")

    return CaseConfig(
        case=CaseInfo(
            name=case_data.get("name", "case"),
        ),
        gases=list(gases),
        expansion=ExpansionConfig(
            max_depth=int(expansion_data.get("max_depth", 2)),
            propagate_species_classes=list(
                expansion_data.get(
                    "propagate_species_classes",
                    ["neutral", "radical", "positive_ion", "negative_ion"],
                )
            ),
            propagate_excited_states=bool(
                expansion_data.get("propagate_excited_states", False)
            ),
        ),
        collisions=CollisionConfig(
            electron=ElectronCollisionConfig(
                enabled=bool(electron_data.get("enabled", True)),
                targets=list(electron_data.get("targets", ["neutral", "radical"])),
            ),
            ion_neutral=IonNeutralCollisionConfig(
                enabled=bool(ion_data.get("enabled", True)),
                projectiles=list(
                    ion_data.get("projectiles", ["positive_ion", "negative_ion"])
                ),
                targets=list(ion_data.get("targets", ["neutral", "radical"])),
            ),
        ),
        limits=LimitsConfig(
            max_species=int(limits_data.get("max_species", 150)),
            max_reactions=int(limits_data.get("max_reactions", 2000)),
            max_pairs_per_depth=int(limits_data.get("max_pairs_per_depth", 1000)),
            max_missing_pairs_per_depth=int(
                limits_data.get("max_missing_pairs_per_depth", 100)
            ),
        ),
        data_policy=DataPolicyConfig(
            include_incomplete_reactions=bool(
                policy_data.get("include_incomplete_reactions", True)
            ),
            include_reactions_without_cross_section=bool(
                policy_data.get("include_reactions_without_cross_section", True)
            ),
            include_reactions_without_dnt_ready_properties=bool(
                policy_data.get("include_reactions_without_dnt_ready_properties", True)
            ),
            allowed_status=list(
                policy_data.get(
                    "allowed_status",
                    ["curated", "literature_supported", "imported", "estimated", "draft"],
                )
            ),
        ),
        outputs=OutputConfig(
            dnt_inputs=bool(outputs_data.get("dnt_inputs", False)),
        ),
        inference=InferenceConfig(
            enabled=bool(inference_data.get("enabled", False)),
            include_inferred_species=bool(inference_data.get("include_inferred_species", True)),
            include_inferred_reactions=bool(inference_data.get("include_inferred_reactions", False)),
            min_confidence=float(inference_data.get("min_confidence", 0.4)),
            max_products=int(inference_data.get("max_products", 3)),
            max_fragment_depth=int(inference_data.get("max_fragment_depth", 1)),
        ),
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}
