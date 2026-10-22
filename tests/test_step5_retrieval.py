from firma2.graph_ingestion import load_profiles_to_graph
from firma2.retrieval import project_dataset, resolve_reference, traverse_shared_source


def make_database(tmp_path):
    profiles = tmp_path / "profiles.jsonl"
    profiles.write_text(
        '\n'.join([
            '{"entity_key":"abn:51824753556","profile":{"legal_name":{"value":"North Star Pty Ltd","confidence":0.9,"source":{"source_id":"source-a","source_record_id":"1"},"evidence":["profile evidence"]},"abn":{"value":"51824753556","confidence":0.9,"source":{"source_id":"source-a","source_record_id":"1"},"evidence":["ABN source"]},"status":{"value":"active"}},"provenance":{}}',
            '{"entity_key":"abn:51824753557","profile":{"legal_name":{"value":"South Star Limited","confidence":0.9,"source":{"source_id":"source-a","source_record_id":"2"},"evidence":["profile evidence"]},"abn":{"value":"51824753557","confidence":0.9,"source":{"source_id":"source-a","source_record_id":"2"},"evidence":["ABN source"]},"status":{"value":"active"}},"provenance":{}}',
            '{"entity_key":"abn:51824753558","profile":{"legal_name":{"value":"Quiet Example Pty Ltd","confidence":0.9,"source":{"source_id":"source-b","source_record_id":"1"},"evidence":["profile evidence"]},"abn":{"value":"51824753558","confidence":0.9,"source":{"source_id":"source-b","source_record_id":"1"},"evidence":["ABN source"]},"status":{"value":"inactive"}},"provenance":{}}',
        ]),
        encoding="utf-8",
    )
    database_path = tmp_path / "graph.kuzu"
    load_profiles_to_graph(
        path=profiles,
        database_path=database_path,
        report_path=tmp_path / "report.csv",
        summary_path=tmp_path / "summary.md",
    )
    return database_path


def test_resolve_returns_ranked_candidates_with_evidence(tmp_path):
    database_path = make_database(tmp_path)

    exact = resolve_reference("51824753556", database_path)
    fuzzy = resolve_reference("North Star Limited", database_path)

    assert exact[0]["canonical_key"] == "abn:51824753556"
    assert exact[0]["match_type"] == "exact_identifier"
    assert exact[0]["evidence"]
    assert fuzzy[0]["canonical_key"] == "abn:51824753556"
    assert fuzzy[0]["score"] >= 0.8
    assert all(candidate["score"] >= 0.8 for candidate in fuzzy)
    assert resolve_reference("Unrelated Made-Up Corporation", database_path) == []


def test_projection_and_bounded_shared_source_traversal(tmp_path):
    database_path = make_database(tmp_path)

    rows = project_dataset({"status": "active"}, ["entity_key", "canonical_name"], 1, database_path)
    traversal = traverse_shared_source("abn:51824753556", max_results=1, database_path=database_path)

    assert len(rows) == 1
    assert rows[0]["canonical_name"] == "North Star Pty Ltd"
    assert len(traversal["neighbors"]) <= 1
    assert traversal["neighbors"][0]["entity_key"] == "abn:51824753557"
    assert "not evidence of ownership" in traversal["neighbors"][0]["relationship_interpretation"]