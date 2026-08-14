from __future__ import annotations

from typing import Any

import yaml

from plasma_reactgen.domain.identifiers import pair_filename, to_file_key


def render_registration_template(kind: str, args: list[str]) -> str:
    """Render the small compatibility templates exposed by the CLI."""

    builders = {
        "species": _species_template,
        "electron-pair": _electron_pair_template,
        "ion-pair": _ion_pair_template,
    }
    builder = builders.get(kind)
    if builder is None:
        raise SystemExit(f"unknown template kind: {kind}")
    return yaml.safe_dump(builder(args), sort_keys=False, allow_unicode=True)


def _species_template(args: list[str]) -> dict[str, Any]:
    _require_arity("species", args, 1, "SPECIES_ID")
    species_id = args[0]
    return {
        "schema_version": 1,
        "id": species_id,
        "display_name": species_id,
        "composition": {},
        "charge": 0,
        "classes": ["neutral"],
        "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
        "properties": {
            "mass_amu": {"value": None, "unit": "amu", "source": None},
            "polarizability_A3": {"value": None, "unit": "A3", "source": None},
            "dipole_moment_D": {"value": None, "unit": "D", "source": None},
            "collision_radius_A": {"value": None, "unit": "A", "source": None},
            "enthalpy_formation_eV": {"value": None, "unit": "eV", "source": None},
            "ionization_energy_eV": {"value": None, "unit": "eV", "source": None},
            "electron_affinity_eV": {"value": None, "unit": "eV", "source": None},
        },
        "metadata": {"status": "draft", "notes": []},
        "suggested_filename": f"{to_file_key(species_id)}.yaml",
    }


def _electron_pair_template(args: list[str]) -> dict[str, Any]:
    _require_arity("electron-pair", args, 2, "e TARGET")
    projectile, target = args
    return _pair_document(
        "electron",
        projectile,
        target,
        {
            "id": f"e_{to_file_key(target)}_elastic",
            "type": "elastic",
            "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
            "threshold_eV": 0.0,
            "data": {"cross_section": {"path": None, "format": "csv_energy_eV_sigma_m2"}},
            "status": "draft",
        },
    )


def _ion_pair_template(args: list[str]) -> dict[str, Any]:
    _require_arity("ion-pair", args, 2, "ION NEUTRAL")
    projectile, target = args
    return _pair_document(
        "ion_neutral",
        projectile,
        target,
        {
            "id": f"{to_file_key(projectile)}_{to_file_key(target)}_elastic",
            "type": "elastic",
            "dnt_class": "elastic",
            "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
            "deltaE_products_minus_reactants_eV": 0.0,
            "status": "draft",
        },
    )


def _pair_document(
    family: str,
    projectile: str,
    target: str,
    channel: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pair": {"family": family, "projectile": projectile, "target": target},
        "channels": [channel],
        "suggested_filename": pair_filename(projectile, target),
    }


def _require_arity(kind: str, args: list[str], expected: int, usage: str) -> None:
    if len(args) != expected:
        raise SystemExit(f"template {kind} requires: {usage}")
