"""Kuzu graph storage and ingestion layer for the firma2 project."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import kuzu

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "data" / "input" / "ingestion" / "profiles.jsonl"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "output" / "load_report.csv"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "data" / "output" / "graph_loading_summary.md"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "output" / "retrieval" / "firma_graph.kuzu"
DEFAULT_OBSERVATION_DIR = PROJECT_ROOT / "data" / "input" / "ingestion" / "observations"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "input" / "ingestion" / "source_manifest.json"
DEFAULT_LINKS_PATH = PROJECT_ROOT / "data" / "input" / "ingestion" / "links.jsonl"
DEFAULT_COVERAGE_PATH = PROJECT_ROOT / "data" / "output" / "retrieval" / "source_coverage.md"


def _read_jsonl(path: str | Path) -> list[dict]:
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _chunks(rows: list[dict], size: int = 500) -> list[list[dict]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


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


def _persist_graph_store(
    store: dict,
    database_path: str | Path,
    manifest: dict | None = None,
    observations: list[dict] | None = None,
    source_links: list[dict] | None = None,
) -> None:
    """Batch-upsert canonical entities and source/evidence records into Kuzu."""
    database_file = Path(database_path)
    database_file.parent.mkdir(parents=True, exist_ok=True)
    database = kuzu.Database(str(database_file))
    connection = kuzu.Connection(database)
    try:
        for statement in (
            "CREATE NODE TABLE IF NOT EXISTS Entity (entity_key STRING, canonical_name STRING, status STRING, properties_json STRING, PRIMARY KEY (entity_key))",
            "CREATE NODE TABLE IF NOT EXISTS SourceRecord (source_id STRING, PRIMARY KEY (source_id))",
            "CREATE NODE TABLE IF NOT EXISTS Evidence (evidence_id STRING, edge_type STRING, source_id STRING, field STRING, evidence_json STRING, PRIMARY KEY (evidence_id))",
            "CREATE NODE TABLE IF NOT EXISTS SourceDefinition (source_id STRING, metadata_json STRING, PRIMARY KEY (source_id))",
            "CREATE NODE TABLE IF NOT EXISTS Observation (observation_id STRING, source_id STRING, source_record_id STRING, payload_json STRING, PRIMARY KEY (observation_id))",
            "CREATE NODE TABLE IF NOT EXISTS IngestionLink (link_id STRING, canonical_key STRING, link_type STRING, confidence DOUBLE, left_record_json STRING, right_record_json STRING, evidence_json STRING, PRIMARY KEY (link_id))",
            "CREATE REL TABLE IF NOT EXISTS HAS_SOURCE (FROM Entity TO SourceRecord)",
            "CREATE REL TABLE IF NOT EXISTS HAS_EVIDENCE (FROM Entity TO Evidence)",
            "CREATE REL TABLE IF NOT EXISTS HAS_OBSERVATION (FROM SourceDefinition TO Observation)",
            "CREATE REL TABLE IF NOT EXISTS SUPPORTS_ENTITY (FROM Observation TO Entity)",
            "CREATE REL TABLE IF NOT EXISTS HAS_INGESTION_LINK (FROM Entity TO IngestionLink)",
        ):
            connection.execute(statement)

        entity_rows = [
            {
                "entity_key": entity_key,
                "canonical_name": entity["canonical_name"],
                "status": entity["status"],
                "properties_json": json.dumps(entity["properties"], sort_keys=True),
            }
            for entity_key, entity in store["entities"].items()
        ]
        for batch in _chunks(entity_rows):
            connection.execute(
                "UNWIND $rows AS row MERGE (entity:Entity {entity_key: row.entity_key}) "
                "SET entity.canonical_name = row.canonical_name, entity.status = row.status, "
                "entity.properties_json = row.properties_json",
                {"rows": batch},
            )

        evidence_rows = []
        source_edge_rows = []
        for edge_index, edge in enumerate(store["edges"]):
            entity_key = edge["from"]
            source_id = edge["source_id"]
            source_edge_rows.append({"entity_key": entity_key, "source_id": source_id})
            evidence_payload = {
                "edge_index": edge_index,
                "entity_key": entity_key,
                "edge_type": edge["edge_type"],
                "source_id": source_id,
                "field": edge.get("field", ""),
                "evidence": edge.get("evidence", []),
            }
            evidence_rows.append({
                "evidence_id": hashlib.sha256(
                    json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "entity_key": entity_key,
                "edge_type": edge["edge_type"],
                "source_id": source_id,
                "field": edge.get("field", ""),
                "evidence_json": json.dumps(edge.get("evidence", []), sort_keys=True),
            })
        source_ids = sorted({row["source_id"] for row in source_edge_rows})
        for batch in _chunks([{"source_id": source_id} for source_id in source_ids]):
            connection.execute(
                "UNWIND $rows AS row MERGE (:SourceRecord {source_id: row.source_id})",
                {"rows": batch},
            )
        for batch in _chunks(source_edge_rows):
            connection.execute(
                "UNWIND $rows AS row MATCH (entity:Entity {entity_key: row.entity_key}), "
                "(source:SourceRecord {source_id: row.source_id}) "
                "MERGE (entity)-[:HAS_SOURCE]->(source)",
                {"rows": batch},
            )
        for batch in _chunks(evidence_rows):
            connection.execute(
                "UNWIND $rows AS row MERGE (evidence:Evidence {evidence_id: row.evidence_id}) "
                "SET evidence.edge_type = row.edge_type, evidence.source_id = row.source_id, "
                "evidence.field = row.field, evidence.evidence_json = row.evidence_json",
                {"rows": batch},
            )
            connection.execute(
                "UNWIND $rows AS row MATCH (entity:Entity {entity_key: row.entity_key}), "
                "(evidence:Evidence {evidence_id: row.evidence_id}) "
                "MERGE (entity)-[:HAS_EVIDENCE]->(evidence)",
                {"rows": batch},
            )

        manifest_sources = (manifest or {}).get("sources", [])
        source_definition_rows = [
            {"source_id": row["source_id"], "metadata_json": json.dumps(row, sort_keys=True)}
            for row in manifest_sources
            if row.get("source_id")
        ]
        for batch in _chunks(source_definition_rows):
            connection.execute(
                "UNWIND $rows AS row MERGE (source:SourceDefinition {source_id: row.source_id}) "
                "SET source.metadata_json = row.metadata_json",
                {"rows": batch},
            )

        observation_rows = []
        for row in observations or []:
            metadata = row.get("observation", {})
            source_id = str(metadata.get("source_id", ""))
            record_id = str(metadata.get("source_record_id", ""))
            if not source_id or not record_id:
                continue
            observation_rows.append({
                "observation_id": f"{source_id}:{record_id}",
                "source_id": source_id,
                "source_record_id": record_id,
                "payload_json": json.dumps(row, sort_keys=True),
            })
        for batch in _chunks(observation_rows):
            connection.execute(
                "UNWIND $rows AS row MERGE (observation:Observation {observation_id: row.observation_id}) "
                "SET observation.source_id = row.source_id, observation.source_record_id = row.source_record_id, "
                "observation.payload_json = row.payload_json",
                {"rows": batch},
            )
            connection.execute(
                "UNWIND $rows AS row MATCH (source:SourceDefinition {source_id: row.source_id}), "
                "(observation:Observation {observation_id: row.observation_id}) "
                "MERGE (source)-[:HAS_OBSERVATION]->(observation)",
                {"rows": batch},
            )

        entity_by_record = {}
        for entity_key, entity in store["entities"].items():
            for property_value in entity["properties"].values():
                source = property_value.get("source", {})
                if source.get("source_id") and source.get("source_record_id"):
                    entity_by_record[f"{source['source_id']}:{source['source_record_id']}"] = entity_key
        observation_entity_rows = [
            {"observation_id": row["observation_id"], "entity_key": entity_by_record[row["observation_id"]]}
            for row in observation_rows
            if row["observation_id"] in entity_by_record
        ]
        for batch in _chunks(observation_entity_rows):
            connection.execute(
                "UNWIND $rows AS row MATCH (observation:Observation {observation_id: row.observation_id}), "
                "(entity:Entity {entity_key: row.entity_key}) MERGE (observation)-[:SUPPORTS_ENTITY]->(entity)",
                {"rows": batch},
            )

        ingestion_link_rows = []
        for link in source_links or []:
            left = link.get("source_a_record", {})
            right = link.get("source_b_record", {})
            if not left or not right:
                continue
            left_id = f"{left.get('source_id', '')}:{left.get('source_record_id', '')}"
            right_id = f"{right.get('source_id', '')}:{right.get('source_record_id', '')}"
            link_payload = json.dumps(link, sort_keys=True, separators=(",", ":"))
            ingestion_link_rows.append({
                "link_id": hashlib.sha256(link_payload.encode("utf-8")).hexdigest(),
                "canonical_key": link.get("canonical_entity_key", ""),
                "link_type": link.get("link_type", "upstream_link"),
                "confidence": float(link.get("confidence", 0.0) or 0.0),
                "left_record_json": json.dumps({"observation_id": left_id}),
                "right_record_json": json.dumps({"observation_id": right_id}),
                "evidence_json": json.dumps(link.get("evidence", []), sort_keys=True),
            })
        for batch in _chunks(ingestion_link_rows):
            connection.execute(
                "UNWIND $rows AS row MERGE (link:IngestionLink {link_id: row.link_id}) "
                "SET link.canonical_key = row.canonical_key, link.link_type = row.link_type, "
                "link.confidence = row.confidence, link.left_record_json = row.left_record_json, "
                "link.right_record_json = row.right_record_json, link.evidence_json = row.evidence_json",
                {"rows": batch},
            )
            keys = [row["canonical_key"] for row in batch if row["canonical_key"] in store["entities"]]
            if keys:
                for row in batch:
                    if row["canonical_key"] not in store["entities"]:
                        continue
                    connection.execute(
                        "MATCH (entity:Entity {entity_key: $canonical_key}), "
                        "(link:IngestionLink {link_id: $link_id}) MERGE (entity)-[:HAS_INGESTION_LINK]->(link)",
                        {"canonical_key": row["canonical_key"], "link_id": row["link_id"]},
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
    observation_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    links_path: str | Path | None = None,
    coverage_path: str | Path | None = None,
) -> dict:
    """Load canonical profiles and supporting ingestion provenance into Kuzu."""
    store = build_graph_store(path=path, limit=limit)
    report_file = Path(report_path) if report_path is not None else DEFAULT_REPORT_PATH
    summary_file = Path(summary_path) if summary_path is not None else DEFAULT_SUMMARY_PATH
    graph_database = Path(database_path) if database_path is not None else DEFAULT_DATABASE_PATH
    sources_dir = Path(observation_dir) if observation_dir is not None else DEFAULT_OBSERVATION_DIR
    observations = [
        row
        for file_path in sorted(sources_dir.glob("*.jsonl"))
        for row in _read_jsonl(file_path)
    ] if sources_dir.exists() else []
    manifest_file = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST_PATH
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    link_file = Path(links_path) if links_path is not None else DEFAULT_LINKS_PATH
    source_links = _read_jsonl(link_file) if link_file.exists() else []
    _persist_graph_store(store, graph_database, manifest, observations, source_links)

    mapped_entities_by_record = {}
    for entity_key, entity in store["entities"].items():
        for property_value in entity["properties"].values():
            source = property_value.get("source", {})
            source_id = source.get("source_id")
            record_id = source.get("source_record_id")
            if source_id and record_id:
                mapped_entities_by_record.setdefault(f"{source_id}:{record_id}", set()).add(entity_key)
    observation_counts: dict[str, dict[str, object]] = defaultdict(
        lambda: {"records_in": 0, "nodes": set(), "edges_out": 0, "rejected_records": 0, "reasons": defaultdict(int)}
    )
    for observation in observations:
        metadata = observation.get("observation", {})
        source_id = str(metadata.get("source_id", "unknown"))
        record_id = str(metadata.get("source_record_id", ""))
        counts = observation_counts[source_id]
        counts["records_in"] += 1
        if not record_id:
            counts["rejected_records"] += 1
            counts["reasons"]["missing_source_record_id"] += 1
            continue
        canonical_entities = mapped_entities_by_record.get(f"{source_id}:{record_id}", set())
        counts["nodes"].update(canonical_entities)
        counts["edges_out"] += 1 + len(canonical_entities)
    links_by_source: dict[str, int] = defaultdict(int)
    for link in source_links:
        for record in (link.get("source_a_record", {}), link.get("source_b_record", {})):
            if record.get("source_id"):
                links_by_source[record["source_id"]] += 1

    identifier_coverage = {}
    for source_id, counts in observation_counts.items():
        source_rows = [
            row for row in observations
            if str(row.get("observation", {}).get("source_id", "unknown")) == source_id
        ]
        abn_count = sum(bool(_digits(row.get("entity", {}).get("abn"), 11)) for row in source_rows)
        acn_count = sum(bool(_digits(row.get("entity", {}).get("acn"), 9)) for row in source_rows)
        records_in = int(counts["records_in"])
        identifier_coverage[source_id] = {
            "records_in": records_in,
            "abn_present": abn_count,
            "abn_percent": round(100 * abn_count / records_in, 2) if records_in else 0.0,
            "acn_present": acn_count,
            "acn_percent": round(100 * acn_count / records_in, 2) if records_in else 0.0,
        }

    report_file.parent.mkdir(parents=True, exist_ok=True)
    with report_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "source_id", "records_in", "nodes_out", "edges_out", "rejected_records", "top_rejection_reason",
            "abn_present", "abn_percent", "acn_present", "acn_percent",
        ])
        writer.writerow([
            "canonical_profiles",
            store["records_in"],
            store["nodes_out"],
            store["edges_out"],
            store["rejected_records"],
            store["top_rejection_reason"],
            "", "", "", "",
        ])
        for source in manifest.get("sources", []):
            source_id = source.get("source_id", "unknown")
            counts = observation_counts[source_id]
            reason_counts = counts["reasons"]
            top_reason = max(reason_counts, key=reason_counts.get) if reason_counts else "none"
            writer.writerow([
                source_id,
                counts["records_in"],
                len(counts["nodes"]),
                counts["edges_out"] + links_by_source.get(source_id, 0),
                counts["rejected_records"],
                top_reason,
                identifier_coverage.get(source_id, {}).get("abn_present", 0),
                identifier_coverage.get(source_id, {}).get("abn_percent", 0.0),
                identifier_coverage.get(source_id, {}).get("acn_present", 0),
                identifier_coverage.get(source_id, {}).get("acn_percent", 0.0),
            ])

    coverage_file = Path(coverage_path) if coverage_path is not None else DEFAULT_COVERAGE_PATH
    coverage_file.parent.mkdir(parents=True, exist_ok=True)
    source_titles = {row.get("source_id"): row.get("title", row.get("source_id")) for row in manifest.get("sources", [])}
    coverage_lines = [
        "# Source Identifier Coverage",
        "",
        "Percentages use loaded observation rows as the denominator. Presence is based on a syntactically plausible digit length, not an external identifier checksum or confirmation that the value is valid.",
        "",
        "| Source | Records | ABN present | ABN % | ACN present | ACN % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source_id, coverage in sorted(identifier_coverage.items()):
        coverage_lines.append(
            f"| {source_titles.get(source_id, source_id)} (`{source_id}`) | {coverage['records_in']} | "
            f"{coverage['abn_present']} | {coverage['abn_percent']:.2f}% | {coverage['acn_present']} | {coverage['acn_percent']:.2f}% |"
        )
    coverage_file.write_text("\n".join(coverage_lines) + "\n", encoding="utf-8")

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(
        "# Graph loading summary\n\n"
        f"- Records ingested: {store['records_in']}\n"
        f"- Canonical entities created: {store['nodes_out']}\n"
        f"- Graph edges created: {store['edges_out']}\n"
        f"- Rejected records: {store['rejected_records']}\n"
        f"- Top rejection reason: {store['top_rejection_reason']}\n\n"
        f"- Kuzu database: `{graph_database}`\n\n"
        f"- Source observations loaded: {len(observations)}\n"
        f"- Upstream evidence links loaded: {len(source_links)}\n"
        f"- Source definitions in manifest: {len(manifest.get('sources', []))}\n\n"
        "Canonical profiles remain authoritative for entity identity; manifest records, source observations, and upstream links are retained as provenance/evidence nodes and do not silently merge entities.\n",
        encoding="utf-8",
    )

    store["database_path"] = str(graph_database)
    store["observations_loaded"] = len(observations)
    store["source_links_loaded"] = len(source_links)
    store["identifier_coverage"] = identifier_coverage
    return store


def _digits(value: object, expected_length: int) -> str | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) != expected_length or len(set(digits)) == 1:
        return None
    return digits


__all__ = ["build_graph_store", "load_profiles_to_graph"]
