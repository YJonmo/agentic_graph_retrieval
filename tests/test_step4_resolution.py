import csv
import json

import kuzu

from firma2.resolution import resolve_observations, run_resolution


SOURCE_A = "source-a"
SOURCE_B = "source-b"


def observation(source_id, record_id, entity):
    return {
        "entity": entity,
        "observation": {"source_id": source_id, "source_record_id": record_id},
    }


def test_resolution_separates_exact_semantic_and_abstention_paths():
    rows = [
        observation(SOURCE_A, "1", {"legal_name": "Example Holdings Pty Ltd", "abn": "51824753556"}),
        observation(SOURCE_B, "1", {"legal_name": "Example Holdings Limited", "abn": "51824753556"}),
        observation(SOURCE_A, "2", {"legal_name": "Harbour Financial Group Pty Ltd"}),
        observation(SOURCE_B, "2", {"legal_name": "Harbor Financial Group Limited"}),
        observation(SOURCE_A, "3", {"legal_name": "Unique Business Pty Ltd", "abn": "51824753557", "acn": "123456789"}),
        observation(SOURCE_B, "3", {"legal_name": "Different Business Pty Ltd", "abn": "51824753557", "acn": "987654321"}),
        observation(SOURCE_A, "4", {"legal_name": "Unmatched Example"}),
    ]

    links, abstentions = resolve_observations(rows)

    assert any(link["match_type"] == "exact_identifier" for link in links)
    assert any(link["match_type"] == "semantic_name" for link in links)
    assert any(item["reason_code"] == "identifier_conflict" for item in abstentions)
    assert not any(
        {link["left_record_id"], link["right_record_id"]} == {"3"}
        and link["left_source_id"] == SOURCE_A
        and link["right_source_id"] == SOURCE_B
        for link in links
    )
    assert any(item["source_record_id"] == "4" for item in abstentions)
    assert all(link["evidence"] and link["canonical_key"] for link in links)


def test_resolution_outputs_and_kuzu_evidence_are_idempotent(tmp_path):
    observations = tmp_path / "observations"
    observations.mkdir()
    rows = [
        observation(SOURCE_A, "1", {"legal_name": "North Star Pty Ltd", "abn": "51824753556"}),
        observation(SOURCE_B, "1", {"legal_name": "North Star Limited", "abn": "51824753556"}),
    ]
    (observations / "source-a.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    arguments = {
        "observation_dir": observations,
        "links_path": tmp_path / "links.jsonl",
        "abstentions_path": tmp_path / "abstentions.jsonl",
        "evaluation_path": tmp_path / "evaluation.md",
        "review_sample_path": tmp_path / "review_sample.jsonl",
        "review_labels_path": tmp_path / "review_labels.csv",
        "reference_path": tmp_path / "reference.jsonl",
        "database_path": tmp_path / "graph.kuzu",
    }

    first = run_resolution(**arguments)
    labels_path = arguments["review_labels_path"]
    with labels_path.open("r", encoding="utf-8", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
        fieldnames = list(review_rows[0])
    review_rows[0]["review_same_entity"] = "true"
    review_rows[0]["reviewer"] = "unit-test-reviewer"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    second = run_resolution(**arguments)

    assert first == second
    with labels_path.open("r", encoding="utf-8", newline="") as handle:
        preserved = list(csv.DictReader(handle))
    assert preserved[0]["review_same_entity"] == "true"
    assert preserved[0]["reviewer"] == "unit-test-reviewer"
    evaluation = (tmp_path / "evaluation.md").read_text(encoding="utf-8")
    assert "Explicitly labeled pairs: 1" in evaluation
    assert "| overall | 1 | 1.0000 | 1.0000 |" in evaluation
    database = kuzu.Database(str(arguments["database_path"]))
    connection = kuzu.Connection(database)
    try:
        matches = connection.execute("MATCH (match:ResolutionMatch) RETURN count(match)").get_next()[0]
        edges = connection.execute(
            "MATCH (:Entity)-[edge:HAS_RESOLUTION_EVIDENCE]->(:ResolutionMatch) RETURN count(edge)"
        ).get_next()[0]
    finally:
        connection.close()
        database.close()
    assert matches == 1
    assert edges == 1