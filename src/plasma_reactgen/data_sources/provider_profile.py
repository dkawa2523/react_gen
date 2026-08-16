from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "ProviderProfile",
    "configured_paths",
    "selected_chemicals_provider",
    "uses_internal_provider",
]

_DISABLED_ALIASES = {
    "internal_species_db": "internal_file",
    "internal_property_db": "internal_file",
    "internal_reaction_db": "internal_file",
    "internal_cross_section_db": "internal_file",
    "chemicals_local": "chemicals_optional",
    "pubchem_offline": "pubchem",
    "pubchem_online": "pubchem",
}


@dataclass(frozen=True)
class ProviderProfile:
    """Interpret provider selection and local configuration in one place."""

    data: dict[str, Any]

    @property
    def strict(self) -> bool:
        return bool(self.data.get("strict_sources"))

    def names(self, *sections: str) -> list[str]:
        selected: list[str] = []
        for section in sections:
            values = self.data.get(section, [])
            if not isinstance(values, list):
                continue
            for value in values:
                name = str(value)
                if name not in selected and not self.disabled(name):
                    selected.append(name)
        return selected

    def listed(self, section: str, name: str) -> bool:
        return name in self.names(section)

    def internal_root(self) -> Path | None:
        config = self.data.get("internal_file")
        if isinstance(config, dict) and config.get("root"):
            return Path(config["root"])
        return None

    def disabled(self, name: str) -> bool:
        values = self.data.get("disabled_sources", [])
        disabled_names = {str(item) for item in values} if isinstance(values, list) else set()
        return name in disabled_names or _DISABLED_ALIASES.get(name) in disabled_names


def uses_internal_provider(profile: ProviderProfile, section: str) -> bool:
    return any(
        profile.listed(section, name)
        for name in (
            "internal_file",
            "internal_species_db",
            "internal_property_db",
            "internal_reaction_db",
        )
    )


def configured_paths(
    profile: ProviderProfile,
    source_name: str,
    key: str = "files",
) -> list[Path]:
    config = profile.data.get(source_name)
    if not isinstance(config, dict):
        return []
    value = config.get(key)
    if isinstance(value, list):
        return [Path(item) for item in value if item]
    for single_key in ("file", "path", "snapshot"):
        if config.get(single_key):
            return [Path(config[single_key])]
    return []


def selected_chemicals_provider(profile: ProviderProfile, section: str) -> str | None:
    for name in ("chemicals_optional", "chemicals_local"):
        if profile.listed(section, name):
            return name
    return None
