import json

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


def test_loader_retains_manifest_observations_and_upstream_links(tmp_path):
    profiles = tmp_path / "profiles.jsonl"
    profiles.write_text(
        json.dumps({
            "entity_key": "abn:51824753556",
            "profile": {
                "legal_name": {
                    "value": "North Star Pty Ltd",
                    "confidence": 0.9,
                    "source": {"source_id": "source-a", "source_record_id": "1"},
                    "evidence": ["profile evidence"],
                },
                "abn": {
                    "value": "51824753556",
                    "confidence": 0.9,
                    "source": {"source_id": "source-a", "source_record_id": "1"},
                    "evidence": ["ABN evidence"],
                },
            },
            "provenance": {},
        }) + "\n",
        encoding="utf-8",
    )
    observations = tmp_path / "observations"
    observations.mkdir()
    observation = {
        "entity": {"legal_name": "North Star Pty Ltd", "abn": "51824753556"},
        "observation": {"source_id": "source-a", "source_record_id": "1"},
    }
    (observations / "source-a.jsonl").write_text(json.dumps(observation) + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": [{"source_id": "source-a", "title": "Test source", "licence": "CC BY 4.0"}]}), encoding="utf-8")
    links = tmp_path / "links.jsonl"
    links.write_text(
        json.dumps({
            "source_a_record": {"source_id": "source-a", "source_record_id": "1"},
            "source_b_record": {"source_id": "source-b", "source_record_id": "9"},
            "canonical_entity_key": "abn:51824753556",
            "confidence": 0.99,
            "link_type": "identifier_match",
            "evidence": ["shared ABN"],
        }) + "\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "graph.kuzu"
    arguments = {
        "path": profiles,
        "database_path": database_path,
        "report_path": tmp_path / "report.csv",
        "summary_path": tmp_path / "summary.md",
        "observation_dir": observations,
        "manifest_path": manifest,
        "links_path": links,
        "coverage_path": tmp_path / "coverage.md",
    }

    first = load_profiles_to_graph(**arguments)
    second = load_profiles_to_graph(**arguments)
    assert first["observations_loaded"] == second["observations_loaded"] == 1
    assert first["source_links_loaded"] == second["source_links_loaded"] == 1
    assert first["identifier_coverage"]["source-a"]["abn_percent"] == 100.0

    database = kuzu.Database(str(database_path))
    connection = kuzu.Connection(database)
    try:
        assert connection.execute("MATCH (source:SourceDefinition) RETURN count(source)").get_next()[0] == 1
        assert connection.execute("MATCH (observation:Observation) RETURN count(observation)").get_next()[0] == 1
        assert connection.execute("MATCH (link:IngestionLink) RETURN count(link)").get_next()[0] == 1
        assert connection.execute("MATCH (:SourceDefinition)-[:HAS_OBSERVATION]->(:Observation) RETURN count(*)").get_next()[0] == 1
    finally:
        connection.close()
        database.close()
