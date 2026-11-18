# Resolution evaluation

## Method and thresholds

- Exact identifier matches require a shared valid ABN or ACN and no conflict in any other populated identifier (confidence 0.99).
- Exact normalized-name matches are accepted only when each endpoint has a unique counterpart and no identifier conflict (confidence 0.97).
- Semantic-name matches use a shared significant-token block, a score of at least 0.92, mutual best-candidate selection, and a best-versus-next margin of 0.05.
- Blocking is by exact identifier, exact normalized name, or shared significant name token; pairs outside these blocks are not compared. This improves candidate cost but can miss aliases with no shared token or identifier.
- High thresholds and abstention favor precision over recall; they intentionally leave many name-only records unresolved.

## Weak-reference comparison

The supplied `ingestion/links.jsonl` is treated only as a weak reference set, not ground truth. Pair overlap: 2576; predicted links: 2578; reference links: 2646.
Weak-reference precision: 0.9992. Weak-reference recall: 0.9735.
These are agreement metrics against the upstream linker and must not be interpreted as measured real-world precision/recall.

## By source pair

| Source pair | Predicted | Reference | Overlap | Weak-reference precision | Weak-reference recall |
|---|---:|---:|---:|---:|---:|
| ACNC 2021 Annual Information Statement (AIS) Data / ACNC 2021 Annual Information Statement (AIS) Data | 0 | 16 | 0 | 0.0000 | 0.0000 |
| ACNC 2021 Annual Information Statement (AIS) Data / ACNC 2023 Annual Information Statement (AIS) Data | 1103 | 1135 | 1103 | 1.0000 | 0.9718 |
| ACNC 2023 Annual Information Statement (AIS) Data / ACNC 2023 Annual Information Statement (AIS) Data | 0 | 16 | 0 | 0.0000 | 0.0000 |
| ASIC - Business Names Dataset / ASIC - Business Names Dataset | 87 | 85 | 85 | 0.9770 | 1.0000 |
| ASIC - Company Dataset / ACNC 2021 Annual Information Statement (AIS) Data | 0 | 1 | 0 | 0.0000 | 0.0000 |
| ASIC - Company Dataset / ACNC 2023 Annual Information Statement (AIS) Data | 0 | 1 | 0 | 0.0000 | 0.0000 |
| ASIC - Company Dataset / ASIC - Company Dataset | 1377 | 1378 | 1377 | 1.0000 | 0.9993 |
| ASIC - Company Dataset / ASIC – Credit Licensee Dataset | 6 | 6 | 6 | 1.0000 | 1.0000 |
| ASIC – Australian Financial Services Authorised Representative Dataset / ASIC – Australian Financial Services Authorised Representative Dataset | 2 | 5 | 2 | 1.0000 | 0.4000 |
| ASIC – Australian Financial Services Authorised Representative Dataset / ASIC – Credit Licensee Dataset | 3 | 3 | 3 | 1.0000 | 1.0000 |

## By source tier pair

| Tier pair | Predicted | Reference | Overlap | Weak-reference precision | Weak-reference recall |
|---|---:|---:|---:|---:|---:|
| Tier 1 | 1377 | 1378 | 1377 | 1.0000 | 0.9993 |
| Tier 1 / Tier 2 | 6 | 8 | 6 | 1.0000 | 0.7500 |
| Tier 2 | 1195 | 1260 | 1193 | 0.9983 | 0.9468 |

## Evidence Spot-Check

A deterministic, source-pair-stratified sample of 50 links was manually inspected against the original observation rows; see `review_sample.jsonl`. 48 sample pairs show a shared ABN/ACN and 2 are name-only; 29 pairs have different displayed names.
This manual spot-check assesses whether links carry the evidence claimed, not whether the records are the same real-world entity. Name differences may reflect historical legal names or trading names, but require independent adjudication. Accordingly, the spot-check is not converted into precision/recall labels.
The reviewer template `review_labels.csv` includes accepted and withheld blocked candidates. Explicitly labeled pairs: 0.

## Independently Labeled Precision and Recall


No independent identity labels have been entered, so true precision/recall are not estimable yet. Fill `review_same_entity` with true/false in `review_labels.csv` after source adjudication and rerun Step 4.
The weak-reference tables above are upstream agreement metrics only; no ground-truth scores are fabricated.
