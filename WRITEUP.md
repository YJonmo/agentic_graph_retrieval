# Entity Graph Assessment

## What was built

The repository now contains a local Kuzu graph built primarily from canonical entity profiles, with source definitions, raw observations, source-level evidence, and upstream link proposals retained as separate records. Keeping observations and match decisions separate from canonical entities makes decisions traceable and reversible. The graph schema is driven by identity, compliance, provenance, and projection questions rather than copied wholesale from a source format.

Resolution separates exact identifier, exact normalized-name, and semantic-name paths. Populated identifier conflicts reject a candidate pair. Name-based links use blocking and conservative thresholds; unresolved records receive reason-coded abstentions. The provided upstream link file is compared as a weak reference only. A 50-link sample was inspected for evidence consistency, but name discrepancies can be historical names or trading names and are not a ground-truth error label.

The query surface includes deterministic Kuzu-backed candidate resolution, projections, and a bounded shared-source traversal. A LangGraph agent chooses among these allowlisted tools and abstention search, then produces an answer from retrieved evidence. It is capped at three calls, and tests inject a fake model so they do not incur API charges. The Streamlit demo exposes the agent, resolver, projection, traversal, and abstention queue.

## Source slice and provenance

The supplied artifacts include an ASIC company sample, ASIC credit licensee and authorised representative samples, ASIC business names, and ACNC annual information statement data for 2021 and 2023. The observation set contains 7,200 rows. Tier 1 identifiers anchor canonical profiles; keyed datasets attach when available; name-only cases remain conservative. Records in the manifest with ingestion errors or unsupported formats are not represented as successfully parsed sources. No new external sources were fetched for this implementation.

The manifest reports source licenses as unknown or approval pending. Local availability is not a license grant. Redistribution or public hosting must wait for source-by-source license and terms verification. No source content or API key is published by this project.

## Evaluation and observed performance

The current resolver produces 2,578 links and 3,997 abstentions from 7,200 observations. These totals are pipeline outputs, not measures of accuracy. Its pair-level overlap with the upstream link file is documented in `outputs/retrieval/evaluation.md`; this is weak-reference agreement, not real-world precision or recall. A source-stratified 50-link evidence consistency spot-check was performed. The generated `review_labels.csv` contains accepted and withheld candidates for independent same-entity adjudication. It is blank by design; true precision and recall cannot be claimed until those labels are completed.

The deterministic Kuzu resolver was measured over 100 sequential local calls. The saved report gives p50 and p95, including graph open/close and local candidate scoring but excluding model and network time. One live agent demonstration used 1,315 input and 71 output tokens. This is observed usage for one call, not a total-project cost statement; actual dollar spend depends on account pricing and any other calls.

## Risks and next work

Shared-source traversal demonstrates provenance coverage and is deliberately not described as ownership or control. The supplied slice lacks adequate ownership, officer, enforcement, and license-validity edges for those graph questions. A next data pass should add a licensed hierarchy or keyed regulatory source and model temporal validity from authoritative dates. The 50-pair label sheet should be adjudicated, with sampling expanded for source/tier strata that contain too few cases. Search indexing and a larger graph benchmark are also needed before claiming production-scale performance.

The central design choice is to preserve uncertainty. The model can choose retrieval steps and explain results, but it cannot authorize identity merges: deterministic evidence rules and explicit abstention remain the trust boundary.