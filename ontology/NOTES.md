# Ontology notes

## Design philosophy

The ontology is derived from the questions the system must answer rather than from the raw source structure. The central design goal is to support identity resolution, evidence-backed claims, and multi-hop retrieval for Australian business and compliance data.

## Node-vs-property decisions

- Nodes represent entities that can participate in relationships and can be canonicalised.
- Properties hold scalar attributes such as ABN, ACN, status, and dates.
- Edges represent relationship semantics such as ownership, licensing, regulation, and source support.
- Reified relationships model cases where relationship records carry their own attributes, such as ownership percentage or licence validity windows.

## Entity split

People and organisations remain separate classes. This keeps the model clear and reduces false assumptions in identity resolution. A shared party abstraction can be introduced later if a particular retrieval or linkage task requires it.

## Constraints and invariants

- Every canonical entity should have a stable identifier and a canonical name.
- Evidence is required before a match is treated as a strong link.
- Temporal constraints are stored when the fact is time bound (such as bans or licences).
- New relationship types and entity types should be added with explicit source and target class definitions and provenance requirements.

## Scope fit

This step is intentionally limited to the query-driven slice required for the GraphRAG system: businesses, people, licences, regulatory actions, evidence, and provenance sources.
