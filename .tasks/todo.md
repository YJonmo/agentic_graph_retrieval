# GraphRAG Project Task Breakdown

This file defines a six-step plan for building a graph-backed knowledge system that answers user questions through retrieval and agent guidance, then exposes a data-projection workflow for tabular export.

The key idea is to build the graph from the queries and the ontology, not from source-specific code. The agent should be able to resolve messy input, explain the candidate matches, and produce either a refined answer or a clean projection dataset.

---

## Step 1: Scope and system design

Goal: Define the product shape, retrieval modes, and operating assumptions before building the graph.

Requirements:
- Decide the two user-facing modes:
  - Intelligent agent mode for targeted questions
  - Data retriever mode for producing a flat projection dataset
- Define the value proposition of the graph: why a graph is required instead of a flat table alone.
- Set the scope of entities and relationships to model.
- Write down the expected user questions and the data they require.
- Decide what is in scope for the initial slice and what is explicitly deferred.

Deliverables:
- A short design note covering user modes, priorities, and assumptions.
- A list of at least five graph questions the system must answer.
- A project plan that makes the ontology and graph design derive from queries rather than from source structure.

Acceptance criteria:
- The system knows whether it is answering questions or building table-like projections.
- The query set defines the model.
- The repository contains a clear design note explaining what is in scope and what is left out.

Validation:
- Review the design note against the project brief.
- Ensure the ontology is derived from those target questions, not from a random source dump.

---

## Step 2: Build the ontology and schema contract

Goal: Define a machine-readable schema for nodes, properties, edges, and reified relationships.

Requirements:
- Choose a schema format: LinkML, OWL, JSON Schema, typed graph DDL, or another machine-readable schema.
- Define node types for people, organisations, licences, bans, disqualifications, ownership, and other important concepts.
- Decide what must be a node versus a property versus an edge.
- Explicitly model reified relationships where they carry their own attributes, such as ownership %, licence status periods, or bans.
- Decide whether people and organisations share one party type or are separated.
- Capture uniqueness constraints and invariants.
- Include extension points for new relationship types and new entity types.

Deliverables:
- `ontology/schema.<format>`
- `ontology/NOTES.md`
- Supporting diagram or summary if useful

Acceptance criteria:
- The model is machine-readable.
- There is a clear explanation of node/property/edge choices.
- The schema explains reification, invariants, constraints, and extension strategy.

Validation:
- Check that the schema is internally consistent.
- Ensure the model is derived from the target questions and not a direct copy of source fields.

---

## Step 3: Build the graph storage and ingestion pipeline

Goal: Create the graph storage layer and the load process that converts raw source data into canonical entities and relationships.

Requirements:
- Pick storage shape: graph-native, graph + relational, graph + vector/search layer, or another hybrid design.
- Implement ingestion for the selected source slice.
- Transform source records into canonical nodes and edges, with the canonical entity graph built primarily from `outputs/ingestion/profiles.jsonl` and the evidence links from `outputs/ingestion/links.jsonl`.
- Use the source manifest in `outputs/ingestion/source_manifest.json` and the per-source observations in `outputs/ingestion/observations/` for provenance, conflict tracing, and source attribution.
- Record per-source counts: records_in, nodes_out, edges_out, rejected_records, and top rejection reason.
- Ensure the load is idempotent: rerunning the same source should not duplicate entities or relationships.
- Model validity time, not just load time, for temporal facts like bans, licences, cancellations, and status changes.

Deliverables:
- Graph loader code and storage configuration
- `outputs/load_report.csv`
- A small source-to-graph transformation summary

Acceptance criteria:
- A rerun is detectable and safe.
- Record counts are logged explicitly.
- Entities and relationships have temporal semantics where required.

Validation:
- Run the loader twice and confirm idempotence.
- Inspect the load report for obvious skew or missing counts.

---

## Step 4: Resolution, linking, and abstentions

Goal: Build the entity resolution logic and produce corpus-level matching evidence for downstream use.

Requirements:
- Implement exact and semantic matching as separate named paths.
- Produce one link record per pair with:
  - left source and record id
  - right source and record id
  - canonical key
  - match type
  - confidence
  - evidence
- Use the graph edge layer to represent these link records as explicit relationship evidence, rather than treating them as ad hoc table rows only.
- Maintain a queue of records believed to be businesses but refused to link, including reason codes.
- Define threshold rules and explain the trade-off between precision and recall.
- Hand-check at least 50 links and report precision and recall by source pair and tier.
- Document blocking strategy and the recall cost it imposes.

Deliverables:
- `outputs/retrieval/links.jsonl`
- `outputs/retrieval/abstentions.jsonl`
- `outputs/retrieval/evaluation.md`
- matching and blocking logic in source code

Acceptance criteria:
- Every link is traceable to evidence.
- Abstentions are explicit and explainable.
- There is a quantified precision/recall assessment for a labelled sample.

Validation:
- Inspect a sample of links and ensure they carry evidence.
- Review abstentions to confirm they represent real unresolved cases, not just missing data.

---

## Step 5: Lookup service, traversal, and GraphRAG retrieval

Goal: Create the query-facing layer that resolves messy references and answers graph queries. This is the part that turns the graph into a useful retrieval system.

Requirements:
- Implement a `resolve` call that accepts a messy reference and returns ranked candidates with:
  - canonical key
  - match type
  - score
  - evidence
  - traversal/query path
- Implement a dataset projection service that accepts a selection criteria and produces a flat table-like output.
- Build at least one traversal requiring the graph, such as ultimate parent, all entities within two hops of a person or disqualified entity, or a multi-hop relationship query.
- Cap traversal output size and define the selection policy when a result set is too large for context.
- Measure p50 and p95 latency and estimate cloud cost per thousand resolutions.

Deliverables:
- `resolve` API/service
- graph traversal logic for multi-hop queries
- `outputs/resolve_results.jsonl`
- `outputs/graph_queries.md`
- `outputs/performance.md`

Acceptance criteria:
- A messy name or reference resolves to ranked candidates with evidence.
- A graph query can answer something that a flat table cannot.
- Traversals are bounded and explainable.
- Performance is measured and clearly separated into measured vs estimated values.

Validation:
- Run the resolve service on a known messy input.
- Test one graph-only question and one projection query.
- Confirm traversal caps and latency measurements exist.

---

## Step 6: Demo, documentation, and final submission

Goal: Make the output runnable, transparent, and reviewable.

Requirements:
- Build a small demo interface (Streamlit, Gradio, or equivalent) that shows:
  - resolve results
  - evidence behind them
  - entity details
  - graph traversal results
  - abstentions
- Provide a README with clean-checkout instructions and the demo URL or local run instructions.
- Write the final two-page assessment in `WRITEUP.md`.
- Include a project summary of sources used, sources skipped, and the slice applied.
- Ensure outputs and artifacts follow the required naming and structure.

Deliverables:
- `README.md`
- `WRITEUP.md`
- `demo/` app
- final outputs directory with required files
- repository ready for review

Acceptance criteria:
- A reviewer can run the project from a clean checkout in under 10 minutes.
- The demo is legible and shows the graph reasoning.
- The repo contains all required output artifacts and a concise assessment.

Validation:
- Run the full project locally.
- Confirm the demo loads and representative queries work.
- Check the output layout matches the assignment format.

---

## Final project summary

This six-step structure is intentionally cumulative:

1. model the problem and the questions,
2. define the ontology,
3. load the graph,
4. resolve entities and separate abstentions,
5. turn the graph into a retrieval and projection service,
6. demonstrate and document the result.

The main success criterion is not whether one source is parsed correctly, but whether the system builds a graph that can support agentic retrieval, honest abstention, and explainable resolution.
