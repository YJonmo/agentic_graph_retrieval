import kuzu

from firma2.graph_ingestion import build_graph_store, load_profiles_to_graph


def test_graph_loader_creates_entities_and_edges_from_profiles(tmp_path):
    store = load_profiles_to_graph(
        limit=3,
        database_path=tmp_path / "graph.kuzu",
        report_path=tmp_path / "report.csv",
        summary_path=tmp_path / "summary.md",
    )
    assert store["records_in"] == 3
    assert store["nodes_out"] >= 3
    assert store["edges_out"] >= 3
    assert store["rejected_records"] == 0
    assert store["top_rejection_reason"] == "none"


def test_graph_loader_is_idempotent(tmp_path):
    database_path = tmp_path / "graph.kuzu"
    first = load_profiles_to_graph(
        limit=5,
        database_path=database_path,
        report_path=tmp_path / "report.csv",
        summary_path=tmp_path / "summary.md",
    )
    second = load_profiles_to_graph(
        limit=5,
        database_path=database_path,
        report_path=tmp_path / "report.csv",
        summary_path=tmp_path / "summary.md",
    )
    assert first["nodes_out"] == second["nodes_out"]
    assert first["edges_out"] == second["edges_out"]

    database = kuzu.Database(str(database_path))
    connection = kuzu.Connection(database)
    try:
        entity_count = connection.execute("MATCH (entity:Entity) RETURN count(entity)").get_next()[0]
        evidence_count = connection.execute("MATCH (evidence:Evidence) RETURN count(evidence)").get_next()[0]
        evidence_link_count = connection.execute(
            "MATCH (:Entity)-[link:HAS_EVIDENCE]->(:Evidence) RETURN count(link)"
        ).get_next()[0]
    finally:
        connection.close()
        database.close()

    assert entity_count == first["nodes_out"]
    assert evidence_count == first["edges_out"]
    assert evidence_link_count == first["edges_out"]


def test_graph_store_includes_temporal_and_provenance_context():
    store = build_graph_store(limit=2)
    first_entity = next(iter(store["entities"].values()))
    assert "entity_key" in first_entity
    assert "canonical_name" in first_entity
    assert "source_records" in first_entity
