# Step 1: Scope and system design

## 1. Product shape and user-facing modes

This project is designed to support two distinct retrieval modes, each serving a different user need:

### A. Intelligent agent mode
This mode answers targeted, evidence-driven questions about business identity, relationships, and compliance. The user is not asking for a spreadsheet; they are asking a question such as:
- "Which entities are connected to this disqualified person?"
- "Who is the ultimate parent of this licensee?"
- "Is this company record the same company referenced in an enforcement notice?"

The system should return:
- the ranked candidate entity or entities,
- confidence and match type,
- the evidence that supports the match,
- the graph path or traversal used to reach the answer,
- a clear abstention when the evidence is insufficient.

### B. Data retriever mode
This mode produces a flat projection for downstream analysis, reporting, and tabular export. The user is asking for a dataset rather than a narrative answer, for example:
- "Give me all active Australian companies in manufacturing with their ABN, ACN, state, and ultimate parent."
- "Export all entities with a current licence and an associated ban or disqualification."
- "Build a company-to-owner table for all entities under a given group."

This mode is optimized for structured output and filter logic rather than conversational reasoning.

---

## 2. Why a graph is required

A flat table alone is not sufficient for this task because the underlying problem is relationship-heavy and evidence-sensitive.

A graph is required to model:
- canonical entities that may appear in multiple sources under different names,
- identity resolution with uncertainty and explicit abstentions,
- source provenance and conflicting claims,
- temporal status changes such as bans, licence cancellations, and company status transitions,
- multi-hop relationships such as parent company, subsidiary, officer, regulator notice, or licensed entity,
- explainability: every answer should be traceable to records and relationship evidence.

A table can answer a direct lookup quickly, but it breaks down when the answer depends on linked evidence, multi-hop traversal, or ambiguous identity. In this domain, a wrong link is worse than no link, and the graph is the place where we can enforce that rule.

---

## 3. Entities and relationships in scope

### Core entity types
- Organisation
  - company, business, subsidiary, group, registered entity
- Person
  - director, officer, liquidator, disqualified person, beneficial owner, key person
- Licence
  - AFS licence, credit licence, or regulatory licence
- Regulatory action
  - ban, disqualification, notice, sanction, enforcement event
- Ownership / control relationship
  - direct ownership, parent-child, shared control, ultimate parent
- Source record
  - provenance record from a source snapshot or extracted observation
- Evidence record
  - the link between two records or between a record and a canonical entity

### Relationship types
- organisation has_name / has_alias
- person is_officer_of / works_for
- organisation has_licence
- organisation is_subject_of / has_regulatory_action
- person is_banned / is_disqualified
- organisation owns / is_owned_by
- organisation has_ultimate_parent
- source record supports_entity / supports_link
- evidence links record A to canonical entity B

### Node vs property vs edge decisions
- Nodes: canonical people, organisations, licences, bans, disqualifications, notices, and evidence objects
- Properties: names, status, licence number, dates, state, ANZSIC, source identifiers, confidence scores
- Edges: ownership, employment, regulatory action, source provenance, and resolved link evidence

This keeps the graph expressive while ensuring that raw database-like fields remain properties rather than being inflated into first-class entities unless they carry meaningful relationship semantics.

---

## 4. Expected user questions and data requirements

The system should answer questions that derive from the graph, not from source dumps. At least five target questions are required; the initial system should support these and others in the same family.

1. Which canonical entity matches this messy company name and which source evidence supports it?
2. Does this company have an active AFS or credit licence, and what is the record status and validity period?
3. Is this organisation linked to a disqualified or banned person or entity, and what is the evidence path?
4. What is the ultimate parent or final holding entity for this entity within the graph?
5. Which businesses are connected to a given person through officer, ownership, or control relationships?
6. Which entities have a source record that identifies them as a business but cannot be confidently linked to a canonical profile?
7. Which companies appear in multiple sources and which source claims differ on status, name, or relationship?
8. Which entities are active in a specific state or ANZSIC slice and also connected to a regulatory event or licence?

These questions require a combination of identity resolution, evidence traversal, temporal checks, and honest abstention.

---

## 5. Scope for the initial slice

The first implementation should be intentionally narrow so the graph remains tractable, explainable, and auditable.

### In scope
- Australian business and company entities with active status and a stable identity backbone
- Tier 1 identity backbone sources, especially ABR bulk extract and ASIC company register
- Selected Tier 2 keyed attachment sources with strong identifiers or clear record linkage patterns:
  - ASIC AFS Licencee
  - ASIC Credit Licensee
  - ASIC banned and disqualified organisations
  - ASIC liquidator records
  - GLEIF legal entity hierarchy where useful
- A restricted subset of name-based Tier 3 evidence where the source is explicit and the risk of false linkage is manageable
- A canonical entity graph built primarily from the pre-ingested inputs under `data/input/ingestion` rather than from raw source snapshots alone

### Explicitly deferred
- Full web-scale crawling and unstructured document extraction
- All Tier 3 sources that rely on fuzzy textual matching without a reliable identifier
- Broad open-world enrichment without provenance or confidence checks
- Unbounded graph expansion beyond the agreed entity slice
- Global multi-hop traversal with no cap or no explanation

The initial slice is the disciplined part: enough to test leadership questions, entity resolution, and graph reasoning without pretending the whole registry is solved in one sprint.

---

## 6. Project plan derived from the query set

The ontology and graph design should not be extracted from source structure. They should be derived from the questions the system is designed to answer.

### Step sequence
1. Define the target questions and user modes
2. Convert those questions into entity types, relationship types, and constraints
3. Create a schema contract for canonical nodes, edges, and reified relationships
4. Load canonical profiles and evidence into the graph store
5. Implement exact and semantic resolution paths with explicit evidence and abstentions
6. Expose the graph via a resolve service and a projection service
7. Demonstrate the answer in a local app with explainable outputs

### Design principle
The model should evolve from observed queries and retrieval needs:
- if a question requires a parent-company chain, model ownership as a first-class edge and support a traversal path
- if a question requires validity windows, model temporal semantics on the edge or node
- if a question requires a confident but uncertain match, use evidence objects and a thresholded matching layer
- if a question requires an abstention, do not merge silently

This keeps the ontology grounded in user value rather than in raw source fields.

---

## 7. Initial assumptions and constraints

- The graph should be built on canonical entities and evidence, not on raw dump ingestion alone.
- Matching should be explicit and auditable; every accepted link must carry evidence.
- All relationship claims must be time-aware when they represent a temporal fact.
- We will prefer abstention over false certainty.
- The minimum viable slice is a manageable active-business subset rather than the entire open web.

---

## 8. Step 1 completion summary

This step establishes the product contract for the project:
- two user modes,
- a graph-based value proposition,
- a bounded and explainable entity model,
- a clear relationship ontology driven by target questions,
- and a disciplined scope boundary that avoids overpromising.

The repository is now set up so that the next stages — ontology schema, ingestion, matching, and graph retrieval — can be built in a way that is traceable to real user questions rather than source-specific implementation choices.
