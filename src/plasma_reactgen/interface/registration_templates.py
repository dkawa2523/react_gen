from __future__ import annotations

import yaml

from plasma_reactgen.domain.identifiers import pair_filename, to_file_key


def render_registration_template(kind: str, args: list[str]) -> str:
    """Render the small compatibility templates exposed by the CLI."""

    if kind == "species":
        if len(args) != 1:
            raise SystemExit("template species requires: SPECIES_ID")
        species_id = args[0]
        data = {
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
    elif kind in {"electron-pair", "ion-pair"}:
        data = _pair_template(kind, args)
    else:
        raise SystemExit(f"unknown template kind: {kind}")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _pair_template(kind: str, args: list[str]) -> dict:
    if len(args) != 2:
        raise SystemExit(f"template {kind} requires: " + ("e TARGET" if kind == "electron-pair" else "ION NEUTRAL"))
    projectile, target = args
    if kind == "electron-pair":
        channel = {
            "id": f"e_{to_file_key(target)}_elastic",
            "type": "elastic",
            "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
            "threshold_eV": 0.0,
            "data": {"cross_section": {"path": None, "format": "csv_energy_eV_sigma_m2"}},
            "status": "draft",
        }
        family = "electron"
    else:
        channel = {
            "id": f"{to_file_key(projectile)}_{to_file_key(target)}_elastic",
            "type": "elastic",
            "dnt_class": "elastic",
            "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
            "deltaE_products_minus_reactants_eV": 0.0,
            "status": "draft",
        }
        family = "ion_neutral"
    return {
        "schema_version": 1,
        "pair": {"family": family, "projectile": projectile, "target": target},
        "channels": [channel],
        "suggested_filename": pair_filename(projectile, target),
    }
