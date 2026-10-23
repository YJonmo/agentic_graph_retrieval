"""Step 1 design contract for the GraphRAG project.

This module captures the project scope in a machine-readable form so the
rest of the system can derive the ontology and retrieval logic from the target
questions rather than source-specific code.
"""

from __future__ import annotations


def get_user_modes() -> dict[str, str]:
    """Return the two user-facing modes for the system."""
    return {
        "agent": "Intelligent agent mode for targeted questions and evidence-backed answers.",
        "projection": "Data retriever mode for flat table-like projection datasets.",
    }


def get_graph_questions() -> list[str]:
    """Return core graph questions that drive the ontology and retrieval model."""
    return [
        "Which canonical entity best matches this messy company name and what evidence supports it?",
        "Does this organisation have an active licence, and what is the current licence status for that record?",
        "Is this business connected to a disqualified or banned person or entity, and what is the path of evidence?",
        "What is the ultimate parent or holding company for this entity within the graph?",
        "Which businesses are connected to a person through officer, ownership, or control relationships?",
        "Which entities are believed to be businesses but cannot be confidently linked to a canonical profile?",
        "Which source records disagree on the same entity's status, name, or relationship?",
    ]


def get_initial_scope() -> dict[str, list[str] | list[dict[str, str]]]:
    """Describe the initial in-scope slice and explicitly deferred work."""
    return {
        "in_scope": [
            "Australian business and company entities with active status and identity backbone coverage",
            "Tier 1 identity backbone sources including ABR and ASIC master records",
            "Tier 2 keyed attachment sources with strong identifiers or reliable linkage",
            "Canonical entity graph built from data/input/ingestion profiles and evidence links",
            "A bounded subset of name-based Tier 3 evidence where the risk of false link is low",
        ],
        "deferred": [
            "Open-web scale crawling and unstructured document inference",
            "Unqualified fuzzy matching across weakly attributed source records",
            "Global graph expansion without provenance and confidence checks",
            "Unbounded multi-hop traversal with no explainability or result caps",
        ],
        "assumptions": [
            {
                "name": "prefer_abstention_over_false_positive",
                "description": "If evidence is not strong enough, the system should refuse to link rather than risk a wrong business match.",
            },
            {
                "name": "entity_graph_is_evidence_first",
                "description": "Canonical entities and relationships are built from evidence and provenance, not just raw source dumps.",
            },
            {
                "name": "temporal_semantics_matter",
                "description": "Status, bans, and licence validity are modelled with start and end time semantics where required.",
            },
        ],
    }
