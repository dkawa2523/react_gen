from plasma_reactgen.application.config import CaseConfig, CaseInfo
from plasma_reactgen.preparation.pair_selection import select_pairs_involving_frontier
from plasma_reactgen.domain.models import Species


def test_frontier_pair_selection():
    config = CaseConfig(case=CaseInfo(name="x"), gases=["Ar", "CF4"])
    active = {
        "Ar": Species("Ar", {"Ar": 1}, 0, {"neutral", "atom"}),
        "CF4": Species("CF4", {"C": 1, "F": 4}, 0, {"neutral", "molecule"}),
        "Ar+": Species("Ar+", {"Ar": 1}, 1, {"positive_ion", "atom"}),
    }
    pairs = select_pairs_involving_frontier(active, {"Ar+"}, config)
    labels = {p.label for p in pairs}
    assert "Ar+ + Ar" in labels
    assert "Ar+ + CF4" in labels
    assert "e + Ar+" not in labels
