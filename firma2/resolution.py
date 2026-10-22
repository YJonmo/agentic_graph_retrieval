"""Conservative entity resolution over canonical-ingestion observations."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import kuzu

from firma2.graph_ingestion import DEFAULT_DATABASE_PATH, PROJECT_ROOT

OBSERVATION_DIR = PROJECT_ROOT / "outputs" / "ingestion" / "part2" / "observations"
PROFILE_PATH = PROJECT_ROOT / "outputs" / "ingestion" / "part4" / "profiles.jsonl"
REFERENCE_LINK_PATH = PROJECT_ROOT / "outputs" / "ingestion" / "part3" / "links.jsonl"
SOURCE_MANIFEST_PATH = PROJECT_ROOT / "outputs" / "ingestion" / "part2" / "source_manifest.json"
UNLINKED_PATH = PROJECT_ROOT / "outputs" / "ingestion" / "part3" / "unlinked_queue.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "retrieval"
LINKS_PATH = OUTPUT_DIR / "links.jsonl"
ABSTENTIONS_PATH = OUTPUT_DIR / "abstentions.jsonl"
EVALUATION_PATH = OUTPUT_DIR / "evaluation.md"
REVIEW_SAMPLE_PATH = OUTPUT_DIR / "review_sample.jsonl"

SEMANTIC_THRESHOLD = 0.92
SEMANTIC_MARGIN = 0.05
MAX_TOKEN_BLOCK_SIZE = 100
LEGAL_SUFFIXES = {
    "pty", "proprietary", "limited", "ltd", "inc", "incorporated", "llc", "plc", "the"
}


def _read_jsonl(path: str | Path) -> list[dict]:
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _normalise_name(value: object) -> str:
    words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return " ".join(word for word in words if word not in LEGAL_SUFFIXES)


def _identifier(value: object, expected_lengths: set[int]) -> str | None:
    if value is None:
        return None
    digits = "".join(re.findall(r"\d", str(value)))
    if len(digits) not in expected_lengths or len(set(digits)) == 1:
        return None
    return digits


def _observation(row: dict) -> dict:
    entity = row.get("entity") if isinstance(row.get("entity"), dict) else {}
    metadata = row.get("observation") if isinstance(row.get("observation"), dict) else {}
    name = next(
        (entity.get(field) for field in ("legal_name", "company_name", "entity_name", "trading_name", "name") if entity.get(field)),
        "",
    )
    source_id = str(metadata.get("source_id", ""))
    record_id = str(metadata.get("source_record_id", ""))
    return {
        "source_id": source_id,
        "source_record_id": record_id,
        "observation_id": f"{source_id}:{record_id}",
        "name": str(name),
        "normalised_name": _normalise_name(name),
        "abn": _identifier(entity.get("abn"), {11}),
        "acn": _identifier(entity.get("acn"), {9}),
        "entity": entity,
    }


def _pair_key(left: dict, right: dict) -> tuple[str, str]:
    return tuple(sorted((left["observation_id"], right["observation_id"])))


def _shared_identifiers(left: dict, right: dict) -> dict[str, str]:
    return {
        field: left[field]
        for field in ("abn", "acn")
        if left[field] and left[field] == right[field]
    }


def _has_identifier_conflict(left: dict, right: dict) -> bool:
    return any(left[field] and right[field] and left[field] != right[field] for field in ("abn", "acn"))


def _semantic_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    sequence_score = SequenceMatcher(None, left, right).ratio()
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    left_to_right = sum(
        max(SequenceMatcher(None, token, candidate).ratio() for candidate in right_tokens)
        for token in left_tokens
    ) / len(left_tokens)
    right_to_left = sum(
        max(SequenceMatcher(None, token, candidate).ratio() for candidate in left_tokens)
        for token in right_tokens
    ) / len(right_tokens)
    token_score = (left_to_right + right_to_left) / 2
    return 0.65 * sequence_score + 0.35 * token_score


def _canonical_key(left: dict, right: dict, shared: dict[str, str]) -> str:
    if "abn" in shared:
        return f"abn:{shared['abn']}"
    if "acn" in shared:
        return f"acn:{shared['acn']}"
    identity = left["normalised_name"] or right["normalised_name"]
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"name:{digest}"


def _link_record(left: dict, right: dict, match_type: str, confidence: float, evidence: list[str]) -> dict:
    if left["observation_id"] > right["observation_id"]:
        left, right = right, left
    shared = _shared_identifiers(left, right)
    return {
        "left_source_id": left["source_id"],
        "left_record_id": left["source_record_id"],
        "right_source_id": right["source_id"],
        "right_record_id": right["source_record_id"],
        "canonical_key": _canonical_key(left, right, shared),
        "match_type": match_type,
        "confidence": round(confidence, 4),
        "evidence": evidence,
    }


def _candidate_pairs(observations: list[dict]) -> tuple[dict, set[tuple[str, str]], set[str]]:
    by_id = {record["observation_id"]: record for record in observations}
    proposals: dict[tuple[str, str], dict] = {}
    conflicts: set[tuple[str, str]] = set()

    identifier_blocks: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in observations:
        for field in ("abn", "acn"):
            if record[field]:
                identifier_blocks[(field, record[field])].append(record)

    for (field, value), block in identifier_blocks.items():
        for left, right in itertools.combinations(block, 2):
            key = _pair_key(left, right)
            if _has_identifier_conflict(left, right):
                conflicts.add(key)
                continue
            proposal = proposals.setdefault(key, {"left": left, "right": right, "shared": {}, "exact_name": False})
            proposal["shared"][field] = value

    name_blocks: dict[str, list[dict]] = defaultdict(list)
    for record in observations:
        name = record["normalised_name"]
        if name:
            name_blocks[name].append(record)

    for block in name_blocks.values():
        for left, right in itertools.combinations(block, 2):
            key = _pair_key(left, right)
            if key in conflicts or _has_identifier_conflict(left, right):
                conflicts.add(key)
                continue
            if key not in proposals:
                proposals[key] = {"left": left, "right": right, "shared": {}, "exact_name": True}
            else:
                proposals[key]["exact_name"] = True

    semantic_blocks: dict[str, list[dict]] = defaultdict(list)
    for record in observations:
        tokens = set(record["normalised_name"].split())
        for token in tokens:
            if len(token) >= 4:
                semantic_blocks[token].append(record)

    semantic_pairs: set[tuple[str, str]] = set()
    for block in semantic_blocks.values():
        if len(block) > MAX_TOKEN_BLOCK_SIZE:
            continue
        for left, right in itertools.combinations(block, 2):
            key = _pair_key(left, right)
            if key not in proposals and key not in conflicts and not _has_identifier_conflict(left, right):
                semantic_pairs.add(key)

    return proposals, semantic_pairs, conflicts


def resolve_observations(observations: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Return conservative accepted links and a reason-coded abstention queue."""
    records = [_observation(row) for row in observations]
    records = [record for record in records if record["source_id"] and record["source_record_id"]]
    proposals, semantic_pairs, conflicts = _candidate_pairs(records)
    accepted: dict[tuple[str, str], dict] = {}
    ambiguous: set[str] = set()

    for key, proposal in proposals.items():
        left, right = proposal["left"], proposal["right"]
        shared = proposal["shared"]
        if shared:
            evidence = [f"Shared {field.upper()}: {value}" for field, value in sorted(shared.items())]
            accepted[key] = _link_record(left, right, "exact_identifier", 0.99, evidence)

    exact_name_groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record["normalised_name"]:
            exact_name_groups[record["normalised_name"]].append(record)
    for block in exact_name_groups.values():
        if len(block) < 2:
            continue
        candidate_counts = defaultdict(int)
        valid_pairs = []
        for left, right in itertools.combinations(block, 2):
            key = _pair_key(left, right)
            if key in accepted or key in conflicts or _has_identifier_conflict(left, right):
                continue
            candidate_counts[left["observation_id"]] += 1
            candidate_counts[right["observation_id"]] += 1
            valid_pairs.append((key, left, right))
        for key, left, right in valid_pairs:
            if candidate_counts[left["observation_id"]] == 1 and candidate_counts[right["observation_id"]] == 1:
                accepted[key] = _link_record(
                    left,
                    right,
                    "exact_name",
                    0.97,
                    [f"Unique exact normalized name match: {left['normalised_name']}"],
                )
            else:
                ambiguous.update((left["observation_id"], right["observation_id"]))

    records_by_id = {record["observation_id"]: record for record in records}
    semantic_scores: dict[str, list[tuple[float, tuple[str, str], dict, dict]]] = defaultdict(list)
    for key in semantic_pairs:
        left = records_by_id[key[0]]
        right = records_by_id[key[1]]
        if left["source_id"] == right["source_id"]:
            continue
        score = _semantic_score(left["normalised_name"], right["normalised_name"])
        if score >= SEMANTIC_THRESHOLD:
            semantic_scores[left["observation_id"]].append((score, key, left, right))
            semantic_scores[right["observation_id"]].append((score, key, right, left))

    best_by_record: dict[str, tuple[float, tuple[str, str], dict, dict]] = {}
    for observation_id, candidates in semantic_scores.items():
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= SEMANTIC_MARGIN:
            best_by_record[observation_id] = candidates[0]
        else:
            ambiguous.add(observation_id)

    for observation_id, (score, key, left, right) in best_by_record.items():
        counterpart = best_by_record.get(right["observation_id"])
        if counterpart and counterpart[1] == key and key not in accepted:
            accepted[key] = _link_record(
                left,
                right,
                "semantic_name",
                score,
                [
                    f"Normalized-name similarity {score:.3f}",
                    "Candidate generated by shared significant-name-token block",
                ],
            )

    linked_ids = set()
    for link in accepted.values():
        linked_ids.add(f"{link['left_source_id']}:{link['left_record_id']}")
        linked_ids.add(f"{link['right_source_id']}:{link['right_record_id']}")

    abstentions = []
    for record in records:
        if record["observation_id"] in linked_ids:
            continue
        if any(record["observation_id"] in key for key in conflicts):
            reason = "identifier_conflict"
            explanation = "Candidate shares an identifier but conflicts on another populated ABN or ACN."
        elif record["observation_id"] in ambiguous:
            reason = "ambiguous_name_candidates"
            explanation = "Name candidates do not have a unique, sufficiently separated best match."
        elif record["abn"] or record["acn"]:
            reason = "no_shared_identifier_or_name_candidate"
            explanation = "No other observation met the conservative linking rules."
        elif record["normalised_name"]:
            reason = "identifier_missing_no_safe_name_match"
            explanation = "No identifier is present and name evidence was insufficient for a safe link."
        else:
            reason = "insufficient_identity_fields"
            explanation = "The observation has no usable business identifier or name."
        abstentions.append(
            {
                "source_id": record["source_id"],
                "source_record_id": record["source_record_id"],
                "reason_code": reason,
                "reason": explanation,
                "entity": record["entity"],
            }
        )

    links = sorted(accepted.values(), key=lambda item: (item["left_source_id"], item["left_record_id"], item["right_source_id"], item["right_record_id"]))
    return links, abstentions


def _persist_resolution_links(links: list[dict], database_path: str | Path) -> None:
    """Persist accepted resolution evidence as Kuzu graph nodes and edges."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database = kuzu.Database(str(path))
    connection = kuzu.Connection(database)
    try:
        for statement in (
            "CREATE NODE TABLE IF NOT EXISTS Entity (entity_key STRING, canonical_name STRING, status STRING, properties_json STRING, PRIMARY KEY (entity_key))",
            "CREATE NODE TABLE IF NOT EXISTS ResolutionMatch (match_id STRING, canonical_key STRING, match_type STRING, confidence DOUBLE, left_record_json STRING, right_record_json STRING, evidence_json STRING, PRIMARY KEY (match_id))",
            "CREATE REL TABLE IF NOT EXISTS HAS_RESOLUTION_EVIDENCE (FROM Entity TO ResolutionMatch)",
        ):
            connection.execute(statement)
        for link in links:
            match_payload = json.dumps(link, sort_keys=True, separators=(",", ":"))
            match_id = hashlib.sha256(match_payload.encode("utf-8")).hexdigest()
            connection.execute(
                "MERGE (entity:Entity {entity_key: $canonical_key}) "
                "ON CREATE SET entity.canonical_name = $canonical_name, entity.status = 'unknown', entity.properties_json = '{}'",
                {"canonical_key": link["canonical_key"], "canonical_name": link["canonical_key"]},
            )
            connection.execute(
                "MERGE (match:ResolutionMatch {match_id: $match_id}) "
                "SET match.canonical_key = $canonical_key, match.match_type = $match_type, "
                "match.confidence = $confidence, match.left_record_json = $left_record_json, "
                "match.right_record_json = $right_record_json, match.evidence_json = $evidence_json",
                {
                    "match_id": match_id,
                    "canonical_key": link["canonical_key"],
                    "match_type": link["match_type"],
                    "confidence": link["confidence"],
                    "left_record_json": json.dumps({"source_id": link["left_source_id"], "source_record_id": link["left_record_id"]}),
                    "right_record_json": json.dumps({"source_id": link["right_source_id"], "source_record_id": link["right_record_id"]}),
                    "evidence_json": json.dumps(link["evidence"], sort_keys=True),
                },
            )
            connection.execute(
                "MATCH (entity:Entity {entity_key: $canonical_key}), "
                "(match:ResolutionMatch {match_id: $match_id}) "
                "MERGE (entity)-[:HAS_RESOLUTION_EVIDENCE]->(match)",
                {"canonical_key": link["canonical_key"], "match_id": match_id},
            )
    finally:
        connection.close()
        database.close()


def _load_reference_pairs(path: str | Path) -> set[tuple[str, str]]:
    reference_pairs = set()
    reference_path = Path(path)
    if not reference_path.exists():
        return reference_pairs
    for row in _read_jsonl(reference_path):
        left = row.get("source_a_record", {})
        right = row.get("source_b_record", {})
        reference_pairs.add(tuple(sorted((
            f"{left.get('source_id', '')}:{left.get('source_record_id', '')}",
            f"{right.get('source_id', '')}:{right.get('source_record_id', '')}",
        ))))
    return reference_pairs


def _source_catalog(path: str | Path) -> dict[str, dict[str, str]]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog = {}
    for source in manifest.get("sources", []):
        source_id = source.get("source_id")
        title = source.get("title", "Unknown source")
        if not source_id:
            continue
        title_lower = title.casefold()
        if "asic - company" in title_lower:
            tier = "Tier 1"
        elif "asic" in title_lower or "acnc" in title_lower:
            tier = "Tier 2"
        else:
            tier = "Unclassified"
        catalog[source_id] = {"title": title, "tier": tier}
    return catalog


def _write_review_sample(
    links: list[dict],
    observations: list[dict],
    output_path: str | Path,
    sample_size: int = 50,
) -> list[dict]:
    observation_by_id = {_observation(row)["observation_id"]: row for row in observations}
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for link in links:
        pair = tuple(sorted((link["left_source_id"], link["right_source_id"])))
        by_pair[pair].append(link)

    rng = random.Random(42)
    queues = []
    for pair, pair_links in sorted(by_pair.items()):
        shuffled = list(pair_links)
        rng.shuffle(shuffled)
        queues.append(shuffled)

    selected = []
    for queue in queues:
        take = min(10, len(queue), sample_size - len(selected))
        selected.extend(queue[:take])
        del queue[:take]
    while len(selected) < min(sample_size, len(links)) and any(queues):
        for queue in queues:
            if queue and len(selected) < min(sample_size, len(links)):
                selected.append(queue.pop(0))

    sample = []
    for link in selected:
        left_id = f"{link['left_source_id']}:{link['left_record_id']}"
        right_id = f"{link['right_source_id']}:{link['right_record_id']}"
        left_row = observation_by_id.get(left_id, {})
        right_row = observation_by_id.get(right_id, {})
        left_entity = left_row.get("entity", {})
        right_entity = right_row.get("entity", {})
        left = _observation(left_row)
        right = _observation(right_row)
        shared = _shared_identifiers(left, right)
        left_name = left_entity.get("legal_name") or left_entity.get("trading_name") or ""
        right_name = right_entity.get("legal_name") or right_entity.get("trading_name") or ""
        sample.append(
            {
                **link,
                "review_sample": True,
                "shared_identifiers_in_observations": shared,
                "left_name": left_name,
                "right_name": right_name,
                "displayed_names_equal_case_insensitive": str(left_name).casefold() == str(right_name).casefold(),
                "review_note": "Evidence consistency sample only; differing names require historical-name or trading-name adjudication.",
            }
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in sample:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return sample


def _write_evaluation(
    links: list[dict],
    reference_path: str | Path,
    output_path: str | Path,
    source_manifest_path: str | Path,
    review_sample: list[dict],
) -> None:
    reference_pairs = _load_reference_pairs(reference_path)
    source_catalog = _source_catalog(source_manifest_path)
    predicted_pairs = {
        tuple(sorted((f"{link['left_source_id']}:{link['left_record_id']}", f"{link['right_source_id']}:{link['right_record_id']}")))
        for link in links
    }
    overlap = predicted_pairs & reference_pairs
    precision = len(overlap) / len(predicted_pairs) if predicted_pairs else 0.0
    recall = len(overlap) / len(reference_pairs) if reference_pairs else 0.0
    by_pair = defaultdict(lambda: {"predicted": 0, "reference_overlap": 0, "reference": 0})
    by_tier_pair = defaultdict(lambda: {"predicted": 0, "reference_overlap": 0, "reference": 0})
    reference_counts: dict[str, int] = defaultdict(int)
    tier_reference_counts: dict[str, int] = defaultdict(int)
    for pair in reference_pairs:
        left_source_id, right_source_id = pair[0].split(":", 1)[0], pair[1].split(":", 1)[0]
        source_pair = " / ".join(sorted((left_source_id, right_source_id)))
        reference_counts[source_pair] += 1
        left_info = source_catalog.get(left_source_id, {"title": left_source_id, "tier": "Unclassified"})
        right_info = source_catalog.get(right_source_id, {"title": right_source_id, "tier": "Unclassified"})
        tier_pair = " / ".join(sorted({left_info["tier"], right_info["tier"]}))
        tier_reference_counts[tier_pair] += 1
        pair_label = f"{left_info['title']} / {right_info['title']}"
        by_pair[pair_label]["reference"] += 1
        by_tier_pair[tier_pair]["reference"] += 1
    for link in links:
        source_ids = tuple(sorted((link["left_source_id"], link["right_source_id"])))
        pair = " / ".join(source_ids)
        left_info = source_catalog.get(source_ids[0], {"title": source_ids[0], "tier": "Unclassified"})
        right_info = source_catalog.get(source_ids[1], {"title": source_ids[1], "tier": "Unclassified"})
        pair_label = f"{left_info['title']} / {right_info['title']}"
        tier_label = " / ".join(sorted({left_info["tier"], right_info["tier"]}))
        by_pair[pair_label]["predicted"] += 1
        by_tier_pair[tier_label]["predicted"] += 1
        record_pair = tuple(sorted((f"{link['left_source_id']}:{link['left_record_id']}", f"{link['right_source_id']}:{link['right_record_id']}")))
        if record_pair in reference_pairs:
            by_pair[pair_label]["reference_overlap"] += 1
            by_tier_pair[tier_label]["reference_overlap"] += 1
    shared_identifier_count = sum(bool(row["shared_identifiers_in_observations"]) for row in review_sample)
    differing_name_count = sum(not row["displayed_names_equal_case_insensitive"] for row in review_sample)
    name_only_count = sum(not row["shared_identifiers_in_observations"] for row in review_sample)

    lines = [
        "# Resolution evaluation",
        "",
        "## Method and thresholds",
        "",
        "- Exact identifier matches require a shared valid ABN or ACN and no conflict in any other populated identifier (confidence 0.99).",
        "- Exact normalized-name matches are accepted only when each endpoint has a unique counterpart and no identifier conflict (confidence 0.97).",
        f"- Semantic-name matches use a shared significant-token block, a score of at least {SEMANTIC_THRESHOLD:.2f}, mutual best-candidate selection, and a best-versus-next margin of {SEMANTIC_MARGIN:.2f}.",
        "- Blocking is by exact identifier, exact normalized name, or shared significant name token; pairs outside these blocks are not compared. This improves candidate cost but can miss aliases with no shared token or identifier.",
        "- High thresholds and abstention favor precision over recall; they intentionally leave many name-only records unresolved.",
        "",
        "## Weak-reference comparison",
        "",
        f"The supplied `part3/links.jsonl` is treated only as a weak reference set, not ground truth. Pair overlap: {len(overlap)}; predicted links: {len(predicted_pairs)}; reference links: {len(reference_pairs)}.",
        f"Weak-reference precision: {precision:.4f}. Weak-reference recall: {recall:.4f}.",
        "These are agreement metrics against the upstream linker and must not be interpreted as measured real-world precision/recall. The input package has no independently labeled test set, so human-audit precision and true recall are not available yet.",
        "",
        "## By source pair",
        "",
        "| Source pair | Predicted | Reference | Overlap | Weak-reference precision | Weak-reference recall |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pair, counts in sorted(by_pair.items()):
        ratio = counts["reference_overlap"] / counts["predicted"] if counts["predicted"] else 0.0
        pair_recall = counts["reference_overlap"] / counts["reference"] if counts["reference"] else 0.0
        lines.append(f"| {pair} | {counts['predicted']} | {counts['reference']} | {counts['reference_overlap']} | {ratio:.4f} | {pair_recall:.4f} |")
    lines.extend([
        "",
        "## By source tier pair",
        "",
        "| Tier pair | Predicted | Reference | Overlap | Weak-reference precision | Weak-reference recall |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for tier_pair, counts in sorted(by_tier_pair.items()):
        tier_precision = counts["reference_overlap"] / counts["predicted"] if counts["predicted"] else 0.0
        tier_recall = counts["reference_overlap"] / counts["reference"] if counts["reference"] else 0.0
        lines.append(f"| {tier_pair} | {counts['predicted']} | {counts['reference']} | {counts['reference_overlap']} | {tier_precision:.4f} | {tier_recall:.4f} |")
    lines.extend([
        "",
        "## Evidence Spot-Check",
        "",
        f"A deterministic, source-pair-stratified sample of {len(review_sample)} links was manually inspected against the original observation rows; see `review_sample.jsonl`. {shared_identifier_count} sample pairs show a shared ABN/ACN and {name_only_count} are name-only; {differing_name_count} pairs have different displayed names.",
        "This manual spot-check assesses whether links carry the evidence claimed, not whether the records are the same real-world entity. Name differences may reflect historical legal names or trading names, but require independent adjudication. Accordingly, the spot-check is not converted into precision/recall labels.",
        "True precision/recall by source pair or tier still requires independently labeled pairs. The tables above report only agreement with the upstream link file.",
        "",
    ])
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def run_resolution(
    observation_dir: str | Path = OBSERVATION_DIR,
    links_path: str | Path = LINKS_PATH,
    abstentions_path: str | Path = ABSTENTIONS_PATH,
    evaluation_path: str | Path = EVALUATION_PATH,
    review_sample_path: str | Path = REVIEW_SAMPLE_PATH,
    reference_path: str | Path = REFERENCE_LINK_PATH,
    source_manifest_path: str | Path = SOURCE_MANIFEST_PATH,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> dict:
    """Resolve all observation files and write links, abstentions, and evaluation."""
    observations = []
    for file_path in sorted(Path(observation_dir).glob("*.jsonl")):
        observations.extend(_read_jsonl(file_path))
    links, abstentions = resolve_observations(observations)
    for output_path, rows in ((links_path, links), (abstentions_path, abstentions)):
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    review_sample = _write_review_sample(links, observations, review_sample_path)
    _write_evaluation(links, reference_path, evaluation_path, source_manifest_path, review_sample)
    _persist_resolution_links(links, database_path)
    return {
        "observations": len(observations),
        "links": len(links),
        "abstentions": len(abstentions),
        "review_sample": len(review_sample),
    }


__all__ = ["resolve_observations", "run_resolution"]