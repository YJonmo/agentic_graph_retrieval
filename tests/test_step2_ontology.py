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
