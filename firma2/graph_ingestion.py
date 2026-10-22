"""Kuzu graph storage and ingestion layer for the firma2 project."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import kuzu

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "outputs" / "ingestion" / "part4" / "profiles.jsonl"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "outputs" / "load_report.csv"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "outputs" / "graph_loading_summary.md"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "outputs" / "retrieval" / "firma_graph.kuzu"


def _read_profile_records(path: str | Path | None = None, limit: int | None = None) -> list[dict]:
    """Read canonical entity profile records from a JSONL file."""
    profile_path = Path(path) if path is not None else DEFAULT_PROFILE_PATH
    records: list[dict] = []
    with profile_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            records.append(json.loads(raw))
            if limit is not None and len(records) >= limit:
                break
    return records


def _canonical_name(profile: dict) -> str:
    """Infer a stable canonical name from known profile fields."""
    for field_name in ("legal_name", "company_name", "name", "entity_name"):
        value = profile.get(field_name)
        if isinstance(value, dict):
            name = value.get("value")
            if name:
                return str(name)
        elif isinstance(value, str):
            return value
    return "unknown"


def _infer_status(profile: dict) -> str:
    """Infer the primary status for an entity when present."""
    status_field = profile.get("status")
    if isinstance(status_field, dict):
        return str(status_field.get("value") or "unknown")
    return str(status_field or "unknown")


def build_graph_store(path: str | Path | None = None, limit: int | None = None) -> dict:
    """Create an in-memory graph store from the canonical profiles file."""
    records = _read_profile_records(path=path, limit=limit)
    entities: dict[str, dict] = {}
    edges: list[dict] = []
    source_counts: dict[str, int] = defaultdict(int)

    for record in records:
        entity_key = record.get("entity_key")
        profile = record.get("profile", {}) if isinstance(record.get("profile"), dict) else {}
        if not entity_key:
            continue

        entity = entities.setdefault(
            entity_key,
            {
                "entity_key": entity_key,
                "canonical_name": _canonical_name(profile),
                "status": _infer_status(profile),
                "source_records": set(),
                "properties": {},
            },
        )

        entity["canonical_name"] = _canonical_name(profile)
        entity["status"] = _infer_status(profile)

        for field_name, field_value in profile.items():
            if not isinstance(field_value, dict):
                continue
            value = field_value.get("value")
            source_meta = field_value.get("source", {}) if isinstance(field_value.get("source"), dict) else {}
            source_id = source_meta.get("source_id")
            if source_id:
                entity["source_records"].add(source_id)
                source_counts[source_id] += 1
                edges.append(
                    {
                        "edge_type": "HAS_SOURCE",
                        "from": entity_key,
                        "to": f"source:{source_id}",
                        "source_id": source_id,
                        "evidence": field_value.get("evidence", []),
                    }
                )
            entity["properties"][field_name] = {
                "value": value,
                "confidence": field_value.get("confidence"),
                "source": source_meta,
                "evidence": field_value.get("evidence", []),
            }

        provenance = record.get("provenance", {}) if isinstance(record.get("provenance"), dict) else {}
        for field_name, items in provenance.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    source_id = item.get("source_id")
                    if source_id:
                        entity["source_records"].add(source_id)
                        source_counts[source_id] += 1
                        edges.append(
                            {
                                "edge_type": "HAS_EVIDENCE",
                                "from": entity_key,
                                "to": f"source:{source_id}:{field_name}",
                                "source_id": source_id,
                                "field": field_name,
                                "evidence": [item],
                            }
                        )

    serialised_entities = {}
    for key, entity in entities.items():
        serialised_entities[key] = {
            "entity_key": entity["entity_key"],
            "canonical_name": entity["canonical_name"],
            "status": entity["status"],
            "source_records": sorted(entity["source_records"]),
            "properties": entity["properties"],
        }

    return {
        "records_in": len(records),
        "nodes_out": len(serialised_entities),
        "edges_out": len(edges),
        "rejected_records": 0,
        "top_rejection_reason": "none",
        "entities": serialised_entities,
        "edges": edges,
        "source_counts": dict(source_counts),
    }


def _persist_graph_store(store: dict, database_path: str | Path) -> None:
    """Upsert entities, source records, and evidence into Kuzu."""
    database_file = Path(database_path)
    database_file.parent.mkdir(parents=True, exist_ok=True)
    database = kuzu.Database(str(database_file))
    connection = kuzu.Connection(database)
    try:
        for statement in (
            "CREATE NODE TABLE IF NOT EXISTS Entity (entity_key STRING, canonical_name STRING, status STRING, properties_json STRING, PRIMARY KEY (entity_key))",
            "CREATE NODE TABLE IF NOT EXISTS SourceRecord (source_id STRING, PRIMARY KEY (source_id))",
            "CREATE NODE TABLE IF NOT EXISTS Evidence (evidence_id STRING, edge_type STRING, source_id STRING, field STRING, evidence_json STRING, PRIMARY KEY (evidence_id))",
            "CREATE REL TABLE IF NOT EXISTS HAS_SOURCE (FROM Entity TO SourceRecord)",
            "CREATE REL TABLE IF NOT EXISTS HAS_EVIDENCE (FROM Entity TO Evidence)",
        ):
            connection.execute(statement)

        for entity_key, entity in store["entities"].items():
            connection.execute(
                "MERGE (entity:Entity {entity_key: $entity_key}) "
                "SET entity.canonical_name = $canonical_name, entity.status = $status, entity.properties_json = $properties_json",
                {
                    "entity_key": entity_key,
                    "canonical_name": entity["canonical_name"],
                    "status": entity["status"],
                    "properties_json": json.dumps(entity["properties"], sort_keys=True),
                },
            )

        for edge_index, edge in enumerate(store["edges"]):
            entity_key = edge["from"]
            source_id = edge["source_id"]
            connection.execute(
                "MERGE (source:SourceRecord {source_id: $source_id})",
                {"source_id": source_id},
            )
            connection.execute(
                "MATCH (entity:Entity {entity_key: $entity_key}), "
                "(source:SourceRecord {source_id: $source_id}) "
                "MERGE (entity)-[:HAS_SOURCE]->(source)",
                {"entity_key": entity_key, "source_id": source_id},
            )

            evidence_payload = {
                "edge_index": edge_index,
                "entity_key": entity_key,
                "edge_type": edge["edge_type"],
                "source_id": source_id,
                "field": edge.get("field", ""),
                "evidence": edge.get("evidence", []),
            }
            evidence_id = hashlib.sha256(
                json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            connection.execute(
                "MERGE (evidence:Evidence {evidence_id: $evidence_id}) "
                "SET evidence.edge_type = $edge_type, evidence.source_id = $source_id, "
                "evidence.field = $field, evidence.evidence_json = $evidence_json",
                {
                    "evidence_id": evidence_id,
                    "edge_type": edge["edge_type"],
                    "source_id": source_id,
                    "field": edge.get("field", ""),
                    "evidence_json": json.dumps(edge.get("evidence", []), sort_keys=True),
                },
            )
            connection.execute(
                "MATCH (entity:Entity {entity_key: $entity_key}), "
                "(evidence:Evidence {evidence_id: $evidence_id}) "
                "MERGE (entity)-[:HAS_EVIDENCE]->(evidence)",
                {"entity_key": entity_key, "evidence_id": evidence_id},
            )
    finally:
        connection.close()
        database.close()


def load_profiles_to_graph(
    path: str | Path | None = None,
    limit: int | None = None,
    report_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    database_path: str | Path | None = None,
) -> dict:
    """Load canonical profiles into Kuzu and persist a load report."""
    store = build_graph_store(path=path, limit=limit)
    report_file = Path(report_path) if report_path is not None else DEFAULT_REPORT_PATH
    summary_file = Path(summary_path) if summary_path is not None else DEFAULT_SUMMARY_PATH
    graph_database = Path(database_path) if database_path is not None else DEFAULT_DATABASE_PATH
    _persist_graph_store(store, graph_database)

    report_file.parent.mkdir(parents=True, exist_ok=True)
    with report_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_id", "records_in", "nodes_out", "edges_out", "rejected_records", "top_rejection_reason"])
        writer.writerow([
            "canonical_profiles",
            store["records_in"],
            store["nodes_out"],
            store["edges_out"],
            store["rejected_records"],
            store["top_rejection_reason"],
        ])

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(
        "# Graph loading summary\n\n"
        f"- Records ingested: {store['records_in']}\n"
        f"- Canonical entities created: {store['nodes_out']}\n"
        f"- Graph edges created: {store['edges_out']}\n"
        f"- Rejected records: {store['rejected_records']}\n"
        f"- Top rejection reason: {store['top_rejection_reason']}\n\n"
        f"- Kuzu database: `{graph_database}`\n\n"
        "The canonical entity graph is built from the profiles in the ingestion output and retains provenance and evidence nodes for explainability and idempotent reloads.\n",
        encoding="utf-8",
    )

    store["database_path"] = str(graph_database)
    return store


__all__ = ["build_graph_store", "load_profiles_to_graph"]
