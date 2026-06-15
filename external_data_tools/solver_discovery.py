from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import shutil
import sys


COMMON_EXECUTABLE_NAMES = {
    "bolsig_plus": ["bolsigminus", "bolsig+", "BOLSIG+"],
    "ngspice": ["ngspice"],
    "thunderboltz": ["thunderboltz"],
    "loki_b": ["loki-b", "lokib"],
    "zdplaskin": ["zdplaskin"],
}


DEFAULT_INSTALL_COMMANDS = {
    "ngspice": {
        "windows": ["winget install ngspice"],
        "macos": ["brew install ngspice"],
        "linux": ["sudo apt-get install ngspice"],
    }
}


def which_executable(name: str) -> str | None:
    return shutil.which(name)


def validate_executable(path: str | None) -> dict[str, Any]:
    if not path:
        return {"status": "missing_executable", "executable": None}
    candidate = Path(path)
    if candidate.exists() and candidate.is_file():
        return {"status": "ready", "executable": str(candidate)}
    return {"status": "missing_executable", "executable": str(candidate)}


def suggest_install_commands(solver_name: str, os_name: str) -> list[str]:
    return list(DEFAULT_INSTALL_COMMANDS.get(solver_name, {}).get(_normalize_os(os_name), []))


def check_solver_config(config: dict[str, Any]) -> dict[str, Any]:
    solvers = config.get("solvers", {})
    if not isinstance(solvers, dict):
        raise ValueError("solver config must contain a solvers mapping")

    statuses = {}
    for solver_name, solver_config in solvers.items():
        if not isinstance(solver_config, dict):
            solver_config = {}
        statuses[str(solver_name)] = _check_one_solver(str(solver_name), solver_config)

    return {
        "schema_version": 1,
        "solvers": statuses,
        "summary": {
            "n_solvers": len(statuses),
            "n_ready": sum(1 for item in statuses.values() if item["status"] == "ready"),
            "n_enabled_missing": sum(
                1 for item in statuses.values() if item.get("enabled") and item["status"] != "ready"
            ),
        },
    }


def _check_one_solver(solver_name: str, config: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(config.get("enabled", False))
    adapter = config.get("adapter")
    install = config.get("install", {}) if isinstance(config.get("install"), dict) else {}
    required_for = list(config.get("required_for", [])) if isinstance(config.get("required_for"), list) else []
    explicit = validate_executable(config.get("executable"))
    executable = explicit.get("executable") if explicit["status"] == "ready" else None

    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "executable": executable,
            "adapter": adapter,
            "required_for": required_for,
            "suggested_actions": ["Enable this solver and set an executable path if this benchmark requires it."],
        }

    if not adapter:
        return {
            "enabled": True,
            "status": "missing_adapter",
            "executable": executable,
            "adapter": adapter,
            "required_for": required_for,
            "suggested_actions": ["Set an adapter name or disable this solver."],
        }

    if explicit["status"] == "ready":
        return {
            "enabled": True,
            "status": "ready",
            "executable": explicit["executable"],
            "adapter": adapter,
            "required_for": required_for,
            "suggested_actions": [],
        }

    found = _find_on_path(solver_name)
    if found:
        return {
            "enabled": True,
            "status": "ready",
            "executable": found,
            "adapter": adapter,
            "required_for": required_for,
            "suggested_actions": [],
        }

    mode = str(install.get("mode") or "")
    commands = _commands_from_config_or_default(solver_name, install)
    if mode == "package_manager_or_user_path":
        status = "package_install_suggested"
        actions = commands or ["Install with an OS package manager, or set executable in solver config."]
    elif mode in {"manual_or_user_path", "user_source_or_executable_path"}:
        status = "manual_install_required"
        actions = list(install.get("notes", [])) if isinstance(install.get("notes"), list) else []
        actions.append(f"Set executable path for {solver_name} in benchmarks/external_solvers.yaml.")
    else:
        status = "missing_executable"
        actions = [f"Set executable path for {solver_name} or disable it."]

    return {
        "enabled": True,
        "status": status,
        "executable": None,
        "adapter": adapter,
        "required_for": required_for,
        "suggested_actions": actions,
        "suggested_install_commands": commands,
    }


def _find_on_path(solver_name: str) -> str | None:
    for candidate in COMMON_EXECUTABLE_NAMES.get(solver_name, [solver_name]):
        found = which_executable(candidate)
        if found:
            return found
    return None


def _commands_from_config_or_default(solver_name: str, install: dict[str, Any]) -> list[str]:
    commands = install.get("commands")
    os_name = _current_os_name()
    if isinstance(commands, dict):
        value = commands.get(os_name, [])
        if isinstance(value, list):
            return [str(item) for item in value]
    return suggest_install_commands(solver_name, os_name)


def _current_os_name() -> str:
    if os.name == "nt" or sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _normalize_os(os_name: str) -> str:
    value = os_name.lower()
    if value.startswith("win"):
        return "windows"
    if value in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    return "linux"
