"""Machine-readable ontology contract for the firm graph model.

The schema is intentionally query-driven: it models the entity and relationship
patterns required for identity resolution, ownership traversal, and compliance
reasoning rather than copying raw source fields.
"""

from __future__ import annotations


def load_schema() -> dict:
    """Return the project ontology as a machine-readable dictionary."""
    return {
        "schema_name": "firma2_graph_ontology",
        "version": "0.1.0",
        "classes": {
            "Entity": {
                "description": "Top-level canonical entity class.",
                "attributes": ["id", "canonical_name", "status", "created_at", "updated_at"],
            },
            "Organisation": {
                "inherits": "Entity",
                "description": "Registered company, business, or organisation.",
                "attributes": ["abn", "acn", "state", "anzsic", "entity_type"],
            },
            "Person": {
                "inherits": "Entity",
                "description": "Individual person involved in company operations or compliance events.",
                "attributes": ["given_name", "family_name", "dob"],
            },
            "Licence": {
                "inherits": "Entity",
                "description": "Regulatory licence held by an organisation or person.",
                "attributes": ["licence_number", "licence_type", "status", "start_date", "end_date"],
            },
            "RegulatoryAction": {
                "inherits": "Entity",
                "description": "Ban, disqualification, notice, or enforcement event.",
                "attributes": ["action_type", "start_date", "end_date", "jurisdiction"],
            },
            "SourceRecord": {
                "inherits": "Entity",
                "description": "Raw source payload or observation used as provenance evidence.",
                "attributes": ["source_name", "source_record_id", "source_url"],
            },
            "Evidence": {
                "inherits": "Entity",
                "description": "A traceable evidence object linking records and entities.",
                "attributes": ["evidence_type", "confidence", "notes"],
            },
        },
        "relationships": {
            "HAS_NAME": {
                "source": "Entity",
                "target": "Entity",
                "description": "Entity has an alternative or canonical name.",
            },
            "HAS_LICENCE": {
                "source": "Organisation",
                "target": "Licence",
                "description": "Organisation holds a particular licence.",
            },
            "HAS_PARENT": {
                "source": "Organisation",
                "target": "Organisation",
                "description": "Organisation is controlled by or owned by a parent organisation.",
            },
            "HAS_EVIDENCE": {
                "source": "Entity",
                "target": "Evidence",
                "description": "Entity is backed by an evidence record.",
            },
            "IS_SUBJECT_OF": {
                "source": "Entity",
                "target": "RegulatoryAction",
                "description": "Entity is subject of a regulatory action.",
            },
            "HAS_SOURCE": {
                "source": "Entity",
                "target": "SourceRecord",
                "description": "Entity is connected to a source record that supports it.",
            },
        },
        "reified_relationships": {
            "OwnershipRelation": {
                "attributes": ["ownership_percent", "start_date", "end_date", "confidence"],
            },
            "LicenceStatus": {
                "attributes": ["status", "start_date", "end_date", "source"],
            },
            "BanStatus": {
                "attributes": ["ban_type", "start_date", "end_date", "reason"],
            },
        },
        "invariants": [
            "Each canonical entity must have a stable id and a canonical_name.",
            "A link must be backed by at least one Evidence object before it is accepted as a strong match.",
            "Ownership, ban, and licence status are temporal and must include validity windows when known.",
            "Person and Organisation remain distinct entity classes unless a future use case requires a shared party abstraction.",
        ],
        "extension_points": {
            "new_entity_types": "Add a subclass under Entity with a clear identity and provenance semantics.",
            "new_relationship_types": "Add a new relationship key under relationships with explicit source/target classes and evidence requirements.",
        },
    }


def get_node_types() -> set[str]:
    """Return the canonical node types used by the graph."""
    return {
        "Entity",
        "Organisation",
        "Person",
        "Licence",
        "RegulatoryAction",
        "SourceRecord",
        "Evidence",
    }


def get_edge_types() -> set[str]:
    """Return the core relationship types used by the graph."""
    return {
        "HAS_NAME",
        "HAS_LICENCE",
        "HAS_PARENT",
        "HAS_EVIDENCE",
        "IS_SUBJECT_OF",
        "HAS_SOURCE",
    }
