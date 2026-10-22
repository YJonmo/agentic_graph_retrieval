"""Kuzu-backed lookup, projection, and bounded graph traversal services."""

from __future__ import annotations

import csv
import json
import re
import statistics
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import kuzu

from firma2.graph_ingestion import DEFAULT_DATABASE_PATH, PROJECT_ROOT

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "retrieval"
RESOLVE_RESULTS_PATH = OUTPUT_DIR / "resolve_results.jsonl"
GRAPH_QUERIES_PATH = OUTPUT_DIR / "graph_queries.md"
PERFORMANCE_PATH = OUTPUT_DIR / "performance.md"
MAX_TRAVERSAL_RESULTS = 25
DEFAULT_RESOLVE_RESULTS = 10


def _normalise_name(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    suffixes = {"pty", "proprietary", "limited", "ltd", "inc", "incorporated", "llc", "plc", "the"}
    return " ".join(word for word in words if word not in suffixes)


def _parse_properties(properties_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(properties_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _property_value(properties: dict, name: str) -> Any:
    value = properties.get(name)
    return value.get("value") if isinstance(value, dict) else value


def _display_name(entity: dict) -> str:
    properties = entity["properties"]
    for field in ("legal_name", "company_name", "entity_name", "trading_name", "name"):
        value = _property_value(properties, field)
        if value:
            return str(value)
    canonical_name = entity["canonical_name"]
    return canonical_name if canonical_name != "unknown" else entity["entity_key"]


def _identifier_query(reference: str) -> tuple[str, str] | None:
    digits = "".join(re.findall(r"\d", reference))
    if len(digits) == 11 and len(set(digits)) > 1:
        return "abn", digits
    if len(digits) == 9 and len(set(digits)) > 1:
        return "acn", digits
    return None


def _entity_rows(connection: kuzu.Connection) -> list[dict]:
    result = connection.execute(
        "MATCH (entity:Entity) RETURN entity.entity_key, entity.canonical_name, entity.status, entity.properties_json "
        "ORDER BY entity.entity_key"
    )
    rows = []
    while result.has_next():
        entity_key, canonical_name, status, properties_json = result.get_next()
        rows.append({
            "entity_key": entity_key,
            "canonical_name": canonical_name,
            "status": status,
            "properties": _parse_properties(properties_json),
        })
    return rows


def _candidate_evidence(connection: kuzu.Connection, entity_key: str, cap: int = 10) -> list[dict]:
    result = connection.execute(
        "MATCH (entity:Entity {entity_key: $entity_key})-[:HAS_EVIDENCE]->(evidence:Evidence) "
        "RETURN evidence.edge_type, evidence.source_id, evidence.field, evidence.evidence_json "
        f"LIMIT {max(1, int(cap))}",
        {"entity_key": entity_key},
    )
    evidence = []
    seen = set()
    while result.has_next():
        edge_type, source_id, field_name, evidence_json = result.get_next()
        try:
            evidence_payload = json.loads(evidence_json)
        except (TypeError, json.JSONDecodeError):
            evidence_payload = []
        item = {
            "edge_type": edge_type,
            "source_id": source_id,
            "field": field_name,
            "evidence": evidence_payload,
        }
        identity = json.dumps(item, sort_keys=True)
        if identity not in seen:
            seen.add(identity)
            evidence.append(item)
    return evidence


def resolve_reference(
    reference: str,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    limit: int = DEFAULT_RESOLVE_RESULTS,
) -> list[dict]:
    """Return ranked, evidence-bearing canonical entity candidates."""
    database = kuzu.Database(str(database_path), read_only=True)
    connection = kuzu.Connection(database)
    try:
        entities = _entity_rows(connection)
        identifier = _identifier_query(reference)
        normalized_reference = _normalise_name(reference)
        candidates = []
        for entity in entities:
            properties = entity["properties"]
            if identifier:
                field, value = identifier
                candidate_identifier = str(_property_value(properties, field) or "")
                if candidate_identifier != value:
                    continue
                score = 1.0
                match_type = "exact_identifier"
                evidence = [f"Exact {field.upper()} match: {value}"]
            else:
                names = []
                for field in ("legal_name", "company_name", "entity_name", "trading_name", "name"):
                    value = _property_value(properties, field)
                    if value:
                        names.append(str(value))
                if entity["canonical_name"] and entity["canonical_name"] != entity["entity_key"]:
                    names.append(entity["canonical_name"])
                normalized_names = {_normalise_name(name) for name in names if _normalise_name(name)}
                if not normalized_reference or not normalized_names:
                    continue
                scored_names = [(SequenceMatcher(None, normalized_reference, name).ratio(), name) for name in normalized_names]
                score, matched_name = max(scored_names, default=(0.0, ""))
                if normalized_reference == matched_name:
                    match_type = "exact_name"
                    score = 1.0
                else:
                    match_type = "semantic_name"
                if score < 0.55:
                    continue
                evidence = [f"Name similarity {score:.3f} against normalized profile name {matched_name!r}"]
            if score < 0.8:
                continue
            candidates.append({
                "canonical_key": entity["entity_key"],
                "canonical_name": _display_name(entity),
                "match_type": match_type,
                "score": round(score, 4),
                "status": entity["status"],
                "evidence": evidence,
                "query_path": [
                    "Kuzu Entity lookup",
                    "candidate evidence via Entity-[:HAS_EVIDENCE]->Evidence",
                ],
            })
        candidates.sort(key=lambda row: (-row["score"], row["canonical_key"]))
        selected = candidates[:max(1, int(limit))]
        for candidate in selected:
            candidate["evidence"].extend(_candidate_evidence(connection, candidate["canonical_key"], cap=3))
        return selected
    finally:
        connection.close()
        database.close()


def project_dataset(
    criteria: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    limit: int = 1000,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[dict]:
    """Project matching canonical entities into flat row dictionaries."""
    criteria = criteria or {}
    requested_columns = columns or ["entity_key", "canonical_name", "status", "abn", "acn"]
    if limit < 1:
        return []
    database = kuzu.Database(str(database_path), read_only=True)
    connection = kuzu.Connection(database)
    try:
        rows = []
        for entity in _entity_rows(connection):
            properties = entity["properties"]
            if criteria.get("status") and str(entity["status"]).casefold() != str(criteria["status"]).casefold():
                continue
            if criteria.get("abn") and str(_property_value(properties, "abn") or "") != str(criteria["abn"]):
                continue
            if criteria.get("acn") and str(_property_value(properties, "acn") or "") != str(criteria["acn"]):
                continue
            name_contains = criteria.get("name_contains")
            if name_contains and _normalise_name(str(name_contains)) not in _normalise_name(entity["canonical_name"]):
                continue
            row = {
                "entity_key": entity["entity_key"],
                "canonical_name": _display_name(entity),
                "status": entity["status"],
            }
            for field in ("abn", "acn", "date_registered", "state", "anzsic", "entity_type"):
                row[field] = _property_value(properties, field)
            if criteria.get("source_id"):
                source_matches = any(
                    isinstance(value, dict)
                    and isinstance(value.get("source"), dict)
                    and value["source"].get("source_id") == criteria["source_id"]
                    for value in properties.values()
                )
                if not source_matches:
                    continue
            rows.append({column: row.get(column) for column in requested_columns})
            if len(rows) >= limit:
                break
        return rows
    finally:
        connection.close()
        database.close()


def traverse_shared_source(
    entity_key: str,
    max_results: int = MAX_TRAVERSAL_RESULTS,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> dict:
    """Find entities connected through a common source provenance node.

    This describes shared source coverage only, not an ownership or identity edge.
    """
    cap = min(max(int(max_results), 1), MAX_TRAVERSAL_RESULTS)
    database = kuzu.Database(str(database_path), read_only=True)
    connection = kuzu.Connection(database)
    try:
        query = (
            "MATCH (origin:Entity {entity_key: $entity_key})-[:HAS_SOURCE]->(source:SourceRecord) "
            "<-[:HAS_SOURCE]-(related:Entity) "
            "WHERE related.entity_key <> $entity_key "
            "RETURN DISTINCT related.entity_key, related.canonical_name, source.source_id "
            f"LIMIT {cap}"
        )
        result = connection.execute(query, {"entity_key": entity_key})
        neighbors = []
        while result.has_next():
            related_key, canonical_name, source_id = result.get_next()
            neighbors.append({
                "entity_key": related_key,
                "canonical_name": canonical_name,
                "shared_source_id": source_id,
                "path": [entity_key, f"source:{source_id}", related_key],
                "relationship_interpretation": "shared provenance only; not evidence of ownership, control, or common identity",
            })
        return {
            "origin_entity_key": entity_key,
            "max_results": cap,
            "returned": len(neighbors),
            "truncated_or_capped": len(neighbors) >= cap,
            "neighbors": neighbors,
        }
    finally:
        connection.close()
        database.close()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_step5(database_path: str | Path = DEFAULT_DATABASE_PATH, iterations: int = 100) -> dict:
    """Generate representative lookup, graph-query, and performance outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sample_queries = [
        "Sydney Missionary Bible College",
        "11000047950",
        "Integricare Limited",
    ]
    query_results = []
    for query in sample_queries:
        query_results.append({"query": query, "candidates": resolve_reference(query, database_path)})
    with RESOLVE_RESULTS_PATH.open("w", encoding="utf-8") as handle:
        for result in query_results:
            handle.write(json.dumps(result, sort_keys=True) + "\n")

    projection = project_dataset(
        criteria={"status": "active"},
        columns=["entity_key", "canonical_name", "status", "abn"],
        limit=5,
        database_path=database_path,
    )
    name_candidates = query_results[0]["candidates"]
    traversal = traverse_shared_source(
        name_candidates[0]["canonical_key"] if name_candidates else "abn:11000047950",
        max_results=MAX_TRAVERSAL_RESULTS,
        database_path=database_path,
    )

    graph_lines = [
        "# Graph Queries and Projection",
        "",
        "## Bounded provenance traversal",
        "",
        "The demonstration walks `Entity -> SourceRecord <- Entity` to retrieve a capped set of other canonical entities observed in the same source. This is useful for provenance coverage and is explicitly not treated as an ownership, control, or identity relationship.",
        "",
        f"Start key: `{traversal['origin_entity_key']}`. Returned: {traversal['returned']} of maximum {traversal['max_results']}; capped: {str(traversal['truncated_or_capped']).lower()}.",
        "",
        "```cypher",
        "MATCH (origin:Entity {entity_key: $entity_key})-[:HAS_SOURCE]->(source:SourceRecord)<-[:HAS_SOURCE]-(related:Entity)",
        "WHERE related.entity_key <> $entity_key",
        "RETURN DISTINCT related.entity_key, related.canonical_name, source.source_id",
        f"LIMIT {MAX_TRAVERSAL_RESULTS}",
        "```",
        "",
        "When a query exceeds the cap, the service returns the first distinct graph matches emitted by Kuzu and marks `truncated_or_capped`; callers should not treat the result as complete.",
        "",
        "## Projection example",
        "",
        "Selection: active entities, at most five rows. Columns: entity key, canonical name, status, ABN.",
        "",
        "```json",
        json.dumps(projection, indent=2, sort_keys=True),
        "```",
        "",
    ]
    GRAPH_QUERIES_PATH.write_text("\n".join(graph_lines), encoding="utf-8")

    timings_ms = []
    for index in range(max(iterations, 1)):
        query = sample_queries[index % len(sample_queries)]
        started = time.perf_counter()
        resolve_reference(query, database_path)
        timings_ms.append((time.perf_counter() - started) * 1000)
    performance = [
        "# Retrieval Performance",
        "",
        f"Measured locally against the Kuzu file graph over {max(iterations, 1)} sequential `resolve_reference` calls. Timings include database open/close and candidate scoring; they exclude network, UI, and LLM latency.",
        "",
        f"- p50 latency: {_percentile(timings_ms, 0.50):.2f} ms",
        f"- p95 latency: {_percentile(timings_ms, 0.95):.2f} ms",
        f"- Number of measured calls: {len(timings_ms)}",
        "- LLM model calls in this deterministic lookup service: 0",
        "",
        "## Agent model usage and cost",
        "",
        "The deterministic resolver makes no model calls. One successful live LangGraph demonstration reported 1,315 input tokens and 71 output tokens (1,386 total). This is observed usage for one question, not a representative average. A dollar cost per 1,000 calls is not stated because provider pricing was not verified for the account/model configuration; calculate it from billed model rates and measured agent usage. Hosting, retries, and graph infrastructure are excluded.",
        "",
    ]
    PERFORMANCE_PATH.write_text("\n".join(performance), encoding="utf-8")
    return {
        "resolve_queries": len(query_results),
        "projection_rows": len(projection),
        "traversal_neighbors": traversal["returned"],
        "measured_calls": len(timings_ms),
        "p50_ms": _percentile(timings_ms, 0.50),
        "p95_ms": _percentile(timings_ms, 0.95),
    }


__all__ = ["project_dataset", "resolve_reference", "run_step5", "traverse_shared_source"]