# Firma Entity Graph

Evidence-first entity resolution and agentic retrieval for Australian business and compliance data. Canonical identities and source evidence are persisted in a local Kuzu graph. The LangGraph agent plans bounded calls to deterministic graph tools and answers only from their retrieved evidence.

## Requirements

- Python 3.11 or newer
- The provided `outputs/ingestion/` artifacts
- An OpenAI API key only for model-backed agent answers; deterministic graph tools and tests do not require one

## Setup

```sh
uv sync
source .venv/bin/activate
```

For the model-backed agent, create `.env` in the repository root:

```text
OPENAI_API_KEY=your-key
```

Do not commit `.env`. Tests inject a fake model and do not call OpenAI.

## Build the local graph

The loader consumes canonical profiles, source manifest metadata, per-source observations, and upstream link evidence. Source records and upstream links are retained as evidence; upstream links do not silently merge canonical identities.

```sh
python -c "from firma2.graph_ingestion import load_profiles_to_graph; print(load_profiles_to_graph())"
python -m firma2.step4_resolution
python -m firma2.step5_retrieval --iterations 100
```

By default the Kuzu database is stored at `outputs/retrieval/firma_graph.kuzu`. Generated outputs are ignored by Git.

## Run the demo

```sh
streamlit run demo/app.py
```

The demo includes LangGraph agent Q&A, deterministic candidate resolution, flat projection, bounded shared-provenance traversal, and an abstention queue. Shared provenance is not ownership or proof of common identity.

Run one agent query from a terminal:

```sh
python -m firma2.agent_cli "Which entity best matches Sydney Missionary Bible College?"
```

## Tests

```sh
pytest -q
```

## Main outputs

- `outputs/load_report.csv` and `outputs/graph_loading_summary.md`: ingestion counts and storage summary
- `outputs/retrieval/source_coverage.md`: per-source observation coverage for plausible ABN/ACN values
- `outputs/retrieval/links.jsonl`, `abstentions.jsonl`, `evaluation.md`: resolution decisions and evaluation
- `outputs/retrieval/review_labels.csv`: blank accepted/withheld pair labels for independent reviewer adjudication
- `outputs/retrieval/resolve_results.jsonl`, `graph_queries.md`, `performance.md`: lookup and traversal examples and measured local latency

## Evidence and limitations

Exact identifier matches are rejected when another populated identifier conflicts. Name-only links use blocking, high similarity thresholds, unique/mutual candidate rules, and explicit abstention. The upstream link file is used only as a weak agreement reference, not ground truth. `review_labels.csv` contains no invented labels; true precision and recall are reported only after reviewers enter independent same-entity judgments and Step 4 is rerun.

Source licenses in the provided manifest are marked unknown or approval pending. This implementation uses only the provided local ingestion artifacts and does not independently verify downstream redistribution rights. Confirm each source's license and permissions before publishing the data or demo.