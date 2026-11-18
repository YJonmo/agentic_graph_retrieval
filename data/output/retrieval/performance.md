# Retrieval Performance

Measured locally against the Kuzu file graph over 100 sequential `resolve_reference` calls. Timings include database open/close and candidate scoring; they exclude network, UI, and LLM latency.

- p50 latency: 124.98 ms
- p95 latency: 180.27 ms
- Number of measured calls: 100
- LLM model calls in this deterministic lookup service: 0

## Agent model usage and cost

The deterministic resolver makes no model calls. One successful live LangGraph demonstration reported 1,315 input tokens and 71 output tokens (1,386 total). This is observed usage for one question, not a representative average. A dollar cost per 1,000 calls is not stated because provider pricing was not verified for the account/model configuration; calculate it from billed model rates and measured agent usage. Hosting, retries, and graph infrastructure are excluded.
