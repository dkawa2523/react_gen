import yaml

from external_data_tools.vamdc_xsams_inventory import build_xsams_inventory, main

XSAMS = """<?xml version="1.0" encoding="UTF-8"?>
<XSAMSData xmlns="http://vamdc.org/xml/xsams/1.0">
  <Species><Atoms><Atom><ChemicalElement><ElementSymbol>O</ElementSymbol></ChemicalElement>
    <Isotope><Ion speciesID="O0"><IonCharge>0</IonCharge>
      <AtomicState stateID="O0-S1"><AtomicStateEnergy>
        <Value units="1/cm">0</Value>
      </AtomicStateEnergy></AtomicState>
    </Ion></Isotope>
  </Atom></Atoms></Species>
  <Processes><Collisions><CollisionalTransition id="P1">
    <Reactant speciesRef="O0" stateRef="O0-S1"/><Product speciesRef="O0" stateRef="O0-S1"/>
    <SourceRef>S1</SourceRef>
  </CollisionalTransition></Collisions></Processes>
  <Sources><Source sourceID="S1"><Title>Example data</Title><Year>2024</Year></Source></Sources>
</XSAMSData>
"""


def test_builds_compact_review_inventory(tmp_path):
    source = tmp_path / "response.xml"
    source.write_text(XSAMS, encoding="utf-8")
    output = tmp_path / "inventory.yaml"

    result = build_xsams_inventory(source, output=output)

    assert result["summary"] == {
        "n_species": 1,
        "n_states": 1,
        "n_processes": 1,
        "n_references": 1,
        "n_unresolved": 0,
        "process_types": {"CollisionalTransition": 1},
    }
    assert result["states"][0]["state_id"] == "O0-S1"
    assert result["states"][0]["energy"] == 0.0
    assert result["processes"][0]["reactant_refs"] == [{"speciesRef": "O0", "stateRef": "O0-S1"}]
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["status"] == (
        "inventory_requires_explicit_registry_mapping"
    )


def test_cli_returns_success_for_resolved_inventory(tmp_path):
    source = tmp_path / "response.xml"
    source.write_text(XSAMS, encoding="utf-8")
    output = tmp_path / "inventory.yaml"

    assert main([str(source), "--output", str(output)]) == 0
