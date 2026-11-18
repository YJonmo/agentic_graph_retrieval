# Graph Queries and Projection

## Bounded provenance traversal

The demonstration walks `Entity -> SourceRecord <- Entity` to retrieve a capped set of other canonical entities observed in the same source. This is useful for provenance coverage and is explicitly not treated as an ownership, control, or identity relationship.

Start key: `abn:11000047950`. Returned: 25 of maximum 25; capped: true.

```cypher
MATCH (origin:Entity {entity_key: $entity_key})-[:HAS_SOURCE]->(source:SourceRecord)<-[:HAS_SOURCE]-(related:Entity)
WHERE related.entity_key <> $entity_key
RETURN DISTINCT related.entity_key, related.canonical_name, source.source_id
LIMIT 25
```

When a query exceeds the cap, the service returns the first distinct graph matches emitted by Kuzu and marks `truncated_or_capped`; callers should not treat the result as complete.

## Projection example

Selection: active entities, at most five rows. Columns: entity key, canonical name, status, ABN.

```json
[
  {
    "abn": "11000047950",
    "canonical_name": "Sydney Missionary & Bible College",
    "entity_key": "abn:11000047950",
    "status": "active"
  },
  {
    "abn": "11000073870",
    "canonical_name": "Integricare Limited",
    "entity_key": "abn:11000073870",
    "status": "active"
  },
  {
    "abn": "11000761571",
    "canonical_name": "AUSTRALIANS IN MISSION TOGETHER",
    "entity_key": "abn:11000761571",
    "status": "active"
  },
  {
    "abn": "11001209490",
    "canonical_name": "THE KILLARNEY SCHOOL LTD",
    "entity_key": "abn:11001209490",
    "status": "active"
  },
  {
    "abn": "11001233790",
    "canonical_name": "The Greek Orthodox Church & Community Of The Holy Apostles City Of Newcastle & District Limited",
    "entity_key": "abn:11001233790",
    "status": "active"
  }
]
```
