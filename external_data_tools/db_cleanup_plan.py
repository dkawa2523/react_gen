from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import argparse
import sys

import yaml


ACTIONS = {"keep", "disable", "remove", "move_to_future_notes"}


TARGETS: dict[str, dict[str, Any]] = {
    "pubchem_external_tools": {
        "label": "PubChem external fetch/normalize tooling",
        "provider_names": ["pubchem_offline", "pubchem_online"],
        "profile_sections": ["species_identity", "properties"],
        "source_files": [
            "external_data_tools/pubchem_fetch.py",
            "external_data_tools/pubchem_normalize.py",
            "src/plasma_reactgen/data_sources/pubchem_provider.py",
        ],
        "test_files": [
            "tests/test_external_pubchem_fetch.py",
            "tests/test_pubchem_provider.py",
        ],
        "doc_files": [
            "external_data/pubchem/README.md",
            "docs/data_sources.md",
        ],
        "import_tokens": [
            "pubchem_fetch",
            "pubchem_normalize",
            "pubchem_provider",
            "PubChemProvider",
        ],
    },
    "vamdc_external_tools": {
        "label": "VAMDC external raw query tooling",
        "provider_names": [],
        "profile_sections": [],
        "source_files": ["external_data_tools/vamdc_query.py"],
        "test_files": ["tests/test_external_vamdc_query.py"],
        "doc_files": ["external_data/vamdc/README.md", "docs/data_sources.md"],
        "import_tokens": ["vamdc_query", "run_vamdc_queries"],
    },
    "openadas_external_tools": {
        "label": "OpenADAS external raw import tooling",
        "provider_names": [],
        "profile_sections": [],
        "source_files": ["external_data_tools/openadas_raw_import.py"],
        "test_files": ["tests/test_external_openadas_raw_import.py"],
        "doc_files": ["external_data/openadas/README.md", "docs/data_sources.md"],
        "import_tokens": ["openadas_raw_import", "import_openadas_manifest"],
    },
    "astrochem_external_tools": {
        "label": "KIDA/UMIST-like astrochemical converter",
        "provider_names": ["ion_reaction_table"],
        "profile_sections": ["ion_neutral_reactions"],
        "source_files": ["external_data_tools/astrochem_network_convert.py"],
        "test_files": ["tests/test_external_astrochem_network_convert.py"],
        "doc_files": ["external_data/astrochem/README.md", "docs/data_sources.md"],
        "import_tokens": ["astrochem_network_convert", "convert_astrochem_network"],
    },
    "chemicals_optional": {
        "label": "Optional Python chemicals provider",
        "provider_names": ["chemicals_optional", "chemicals_local"],
        "profile_sections": ["species_identity", "properties"],
        "source_files": ["src/plasma_reactgen/data_sources/chemicals_provider.py"],
        "test_files": ["tests/test_chemicals_provider.py"],
        "doc_files": ["external_data/chemicals/README.md", "docs/chemicals_optional_provider.md", "docs/data_sources.md"],
        "import_tokens": ["chemicals_provider", "ChemicalsPropertyProvider", "ChemicalsSpeciesProvider"],
    },
    "chemical_identity_snapshot": {
        "label": "Chemical identity local snapshot provider and external skeletons",
        "provider_names": ["chemical_identity_snapshot"],
        "profile_sections": ["species_identity"],
        "source_files": [
            "src/plasma_reactgen/data_sources/chemical_identity_snapshot.py",
            "external_data_tools/chemical_identity_fetch.py",
            "external_data_tools/chemical_identity_normalize.py",
        ],
        "test_files": ["tests/test_chemical_identity_workflow.py"],
        "doc_files": ["external_data/chemical_identity/README.md", "docs/data_sources.md"],
        "import_tokens": [
            "chemical_identity_snapshot",
            "chemical_identity_fetch",
            "chemical_identity_normalize",
            "ChemicalIdentitySnapshotProvider",
        ],
    },
    "nist_snapshot": {
        "label": "NIST local snapshot provider and planning tools",
        "provider_names": ["nist_snapshot"],
        "profile_sections": ["properties"],
        "source_files": [
            "src/plasma_reactgen/data_sources/nist_snapshot.py",
            "external_data_tools/nist_snapshot_plan.py",
            "external_data_tools/nist_snapshot_validate.py",
        ],
        "test_files": ["tests/test_nist_snapshot.py", "tests/test_external_nist_snapshot_tools.py"],
        "doc_files": ["external_data/nist/README.md", "docs/data_sources.md"],
        "import_tokens": ["nist_snapshot", "NistSnapshotPropertyProvider"],
    },
    "argonne_atct_snapshot": {
        "label": "Argonne/ATcT-style thermochemistry snapshot workflow",
        "provider_names": ["argonne_atct_snapshot"],
        "profile_sections": ["properties"],
        "source_files": [
            "src/plasma_reactgen/data_sources/argonne_atct_snapshot.py",
            "external_data_tools/argonne_atct_snapshot_plan.py",
            "external_data_tools/argonne_atct_snapshot_validate.py",
            "src/plasma_reactgen/preparation/reaction_energetics.py",
        ],
        "test_files": ["tests/test_argonne_atct_workflow.py"],
        "doc_files": ["external_data/argonne_atct/README.md", "docs/data_sources.md"],
        "import_tokens": ["argonne_atct_snapshot", "ArgonneAtctSnapshotPropertyProvider", "reaction_energetics"],
    },
    "lxcat_offline": {
        "label": "LXCat/manual cross-section local workflow",
        "provider_names": ["lxcat_offline"],
        "profile_sections": ["electron_cross_sections"],
        "source_files": [
            "src/plasma_reactgen/data_sources/lxcat_offline.py",
            "external_data_tools/lxcat_raw_import.py",
            "external_data_tools/lxcat_manifest.py",
        ],
        "test_files": ["tests/test_cross_section_importer.py", "tests/test_external_lxcat_raw_import.py"],
        "doc_files": ["external_data/lxcat/README.md", "docs/data_sources.md"],
        "import_tokens": ["lxcat_offline", "lxcat_raw_import", "lxcat_manifest", "LxcatOfflineCrossSectionProvider"],
    },
}


def build_cleanup_report(
    audit_path: str | Path,
    *,
    decision_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    audit = Path(audit_path)
    root = Path(repo_root) if repo_root is not None else _repo_root_from_audit(audit)
    decisions = _load_decisions(decision_path) if decision_path is not None else []
    report: dict[str, Any] = {
        "schema_version": 1,
        "audit": str(audit),
        "mode": "apply" if apply else "dry_run",
        "available_targets": _available_targets(),
        "decisions": [],
        "errors": [],
        "summary": {
            "n_decisions": len(decisions),
            "n_errors": 0,
            "repository_mutated": False,
        },
    }

    if not decisions:
        return report

    for decision in decisions:
        item = _decision_report(root, decision)
        if item.get("error"):
            report["errors"].append(item["error"])
        elif apply:
            _apply_decision(root, item, decision)
            if item.get("applied"):
                report["summary"]["repository_mutated"] = True
        report["decisions"].append(item)

    report["summary"]["n_errors"] = len(report["errors"])
    return report


def write_cleanup_report(report: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or apply decision-based DB/source cleanup.")
    parser.add_argument("audit", type=Path, help="docs/db_provider_audit.md or equivalent audit report")
    parser.add_argument("--decision", type=Path, default=None, help="cleanup decision YAML")
    parser.add_argument("--output", type=Path, default=None, help="optional cleanup plan/report YAML output")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", help="report changes without mutation")
    mode.add_argument("--apply", dest="apply", action="store_true", help="apply explicit safe cleanup decisions")
    parser.set_defaults(apply=False)
    args = parser.parse_args(argv)

    report = build_cleanup_report(args.audit, decision_path=args.decision, apply=args.apply)
    if args.output is not None:
        write_cleanup_report(report, args.output)
    _print_summary(report)
    return 1 if report["errors"] else 0


def _available_targets() -> list[dict[str, Any]]:
    return [
        {
            "target": name,
            "label": target["label"],
            "provider_names": list(target.get("provider_names", [])),
            "source_files": list(target.get("source_files", [])),
        }
        for name, target in sorted(TARGETS.items())
    ]


def _decision_report(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    target_name = decision.get("target")
    action = decision.get("action")
    if target_name not in TARGETS:
        return {
            "target": target_name,
            "action": action,
            "error": f"unknown cleanup target: {target_name}",
        }
    if action not in ACTIONS:
        return {
            "target": target_name,
            "action": action,
            "error": f"unsupported cleanup action: {action}",
        }

    target = TARGETS[target_name]
    item = {
        "target": target_name,
        "action": action,
        "reason": decision.get("reason"),
        "files_to_modify": [],
        "files_to_remove": [],
        "tests_referencing_removed_modules": [],
        "docs_to_review": _existing_paths(root, target.get("doc_files", [])),
        "active_imports": [],
        "blocked": False,
    }

    if action == "keep":
        item["notes"] = ["No cleanup changes requested."]
        return item

    if action in {"disable", "move_to_future_notes"}:
        item["files_to_modify"].extend(_source_profiles_with_provider(root, target))
        item["files_to_modify"].append("docs/db_cleanup_decisions.md")

    if action == "remove":
        item["files_to_remove"].extend(_existing_paths(root, target.get("source_files", [])))
        if decision.get("remove_tests"):
            item["files_to_remove"].extend(_existing_paths(root, target.get("test_files", [])))
        else:
            item["tests_referencing_removed_modules"] = _existing_paths(root, target.get("test_files", []))
        if decision.get("remove_docs"):
            item["files_to_remove"].extend(_existing_paths(root, target.get("doc_files", [])))
        item["active_imports"] = _active_imports(root, target, item["files_to_remove"])
        if item["active_imports"]:
            item["blocked"] = True
            item["block_reason"] = "active imports remain"

    return item


def _apply_decision(root: Path, item: dict[str, Any], decision: dict[str, Any]) -> None:
    if item.get("error") or item.get("blocked"):
        item["applied"] = False
        return
    action = item["action"]
    target = TARGETS[item["target"]]
    if action == "keep":
        item["applied"] = False
        return
    if action == "disable":
        _disable_target_in_source_profiles(root, target)
        _append_cleanup_note(root, decision, "disabled")
        item["applied"] = True
        return
    if action == "move_to_future_notes":
        _append_cleanup_note(root, decision, "moved_to_future_notes")
        item["applied"] = True
        return
    if action == "remove":
        for relative in item["files_to_remove"]:
            path = root / relative
            if path.exists() and path.is_file():
                path.unlink()
        _append_cleanup_note(root, decision, "removed")
        item["applied"] = bool(item["files_to_remove"])


def _disable_target_in_source_profiles(root: Path, target: dict[str, Any]) -> None:
    profile_dir = root / "registry" / "rules" / "source_profiles"
    if not profile_dir.exists():
        return
    provider_names = set(target.get("provider_names", []))
    profile_sections = target.get("profile_sections", [])
    for path in sorted(profile_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        changed = False
        for section in profile_sections:
            values = payload.get(section)
            if not isinstance(values, list):
                continue
            filtered = [value for value in values if value not in provider_names]
            if filtered != values:
                payload[section] = filtered
                changed = True
        if changed:
            path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _append_cleanup_note(root: Path, decision: dict[str, Any], result: str) -> None:
    path = root / "docs" / "db_cleanup_decisions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = "# DB Cleanup Decisions\n\n"
    text += (
        f"- target: `{decision.get('target')}`; action: `{decision.get('action')}`; "
        f"result: `{result}`; reason: {decision.get('reason', '')}\n"
    )
    path.write_text(text, encoding="utf-8")


def _load_decisions(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("cleanup decision file must be a YAML mapping")
    if payload.get("schema_version") != 1:
        raise ValueError("cleanup decision schema_version must be 1")
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("cleanup decisions must be a list")
    return [decision for decision in decisions if isinstance(decision, dict)]


def _source_profiles_with_provider(root: Path, target: dict[str, Any]) -> list[str]:
    result = []
    provider_names = set(target.get("provider_names", []))
    profile_sections = target.get("profile_sections", [])
    profile_dir = root / "registry" / "rules" / "source_profiles"
    if not profile_dir.exists():
        return result
    for path in sorted(profile_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        for section in profile_sections:
            values = payload.get(section, [])
            if isinstance(values, list) and provider_names.intersection(values):
                result.append(_relative(root, path))
                break
    return result


def _active_imports(root: Path, target: dict[str, Any], files_to_remove: list[str]) -> list[dict[str, str]]:
    tokens = [str(token) for token in target.get("import_tokens", [])]
    excluded = {Path(path).as_posix() for path in files_to_remove}
    excluded.update(Path(path).as_posix() for path in target.get("source_files", []))
    active = []
    for path in _iter_text_files(root):
        relative = _relative(root, path)
        if relative in excluded:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in tokens:
            if token in text:
                active.append({"file": relative, "token": token})
                break
    return active


def _iter_text_files(root: Path):
    for base in ("src", "external_data_tools", "tests", "docs", "registry"):
        directory = root / base
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml", ".toml"}:
                yield path


def _existing_paths(root: Path, paths: list[str]) -> list[str]:
    return [path for path in paths if (root / path).exists()]


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _repo_root_from_audit(audit_path: Path) -> Path:
    if audit_path.parent.name == "docs":
        return audit_path.parent.parent
    return Path.cwd()


def _print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "db cleanup plan: "
        f"mode={report['mode']} "
        f"decisions={summary['n_decisions']} "
        f"errors={summary['n_errors']} "
        f"mutated={summary['repository_mutated']}"
    )
    for error in report["errors"]:
        print(f"- {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
