import json
from pathlib import Path

from firma2.ontology import get_edge_types, get_node_types, load_schema


def test_schema_is_machine_readable():
    schema = load_schema()
    assert isinstance(schema, dict)
    assert "classes" in schema
    assert "relationships" in schema


def test_core_entity_types_are_defined():
    node_types = get_node_types()
    assert {"Organisation", "Person", "Licence", "RegulatoryAction"}.issubset(node_types)


def test_core_relationship_types_are_defined():
    edge_types = get_edge_types()
    assert {"HAS_LICENCE", "HAS_PARENT", "HAS_NAME", "HAS_EVIDENCE"}.issubset(edge_types)


def test_json_ontology_contract_matches_required_graph_semantics():
    schema_path = Path(__file__).resolve().parents[1] / "ontology" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert {"Organisation", "Person", "Licence", "RegulatoryAction", "Observation", "Evidence"}.issubset(schema["node_types"])
    assert {"HAS_PARENT", "HAS_LICENCE", "IS_SUBJECT_OF", "HAS_OBSERVATION"}.issubset(schema["relationship_types"])
    assert "OwnershipRelation" in schema["reified_relationships"]
    assert any("reversible" in invariant for invariant in schema["invariants"])
