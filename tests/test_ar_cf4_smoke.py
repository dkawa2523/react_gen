from pathlib import Path

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.infrastructure.file_registry import FileRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_ar_cf4_sample_generates_network():
    registry = FileRegistry(ROOT / "registry")
    config = load_case_config(ROOT / "cases" / "ar_cf4" / "input.yaml", ROOT / "registry")
    deps = NetworkBuilderDependencies(registry, registry, registry)
    network = ReactionNetworkBuilder(deps).generate(config)
    states = build_state_list(network, registry)
    dnt_tasks = build_dnt_tasks(network)

    assert len(network.reactions) > 0
    assert any(r.id == "Arp_CF4_dissociative_charge_transfer_CF3p" for r in network.reactions)
    assert any(s["id"] == "CF3+" for s in states)
    assert any(t["pair_id"] == "Ar+__CF4" for t in dnt_tasks)
