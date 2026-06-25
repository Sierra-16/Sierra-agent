from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_thresholds(value: str) -> list[float]:
    """Parse a comma-separated cosine threshold list."""
    try:
        thresholds = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("Thresholds must be comma-separated numbers") from exc

    if not thresholds:
        raise ValueError("At least one threshold is required")
    if any(threshold < -1.0 or threshold > 1.0 for threshold in thresholds):
        raise ValueError("Cosine thresholds must be between -1 and 1")
    return sorted(set(thresholds))


def load_recall_fixture(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    fixture_path = Path(path)
    with fixture_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return validate_recall_fixture(data)


def validate_recall_fixture(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Validate and normalize a memory recall benchmark fixture."""
    if not isinstance(data, dict):
        raise ValueError("Recall fixture must be a JSON object")

    memories = data.get("memories")
    queries = data.get("queries")
    if not isinstance(memories, list) or not memories:
        raise ValueError("Recall fixture requires a non-empty memories list")
    if not isinstance(queries, list) or not queries:
        raise ValueError("Recall fixture requires a non-empty queries list")

    normalized_memories = []
    memory_keys = set()
    for index, item in enumerate(memories, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Memory #{index} must be an object")
        key = str(item.get("key") or "").strip()
        user = str(item.get("user") or "").strip()
        assistant = str(item.get("assistant") or "").strip()
        if not key:
            raise ValueError(f"Memory #{index} requires a key")
        if key in memory_keys:
            raise ValueError(f"Duplicate memory key: {key}")
        if not user and not assistant:
            raise ValueError(f"Memory {key} requires user or assistant text")
        memory_keys.add(key)
        normalized_memories.append({
            "key": key,
            "user": user,
            "assistant": assistant,
        })

    normalized_queries = []
    query_ids = set()
    for index, item in enumerate(queries, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Query #{index} must be an object")
        query_id = str(item.get("id") or "").strip()
        query = str(item.get("query") or "").strip()
        relevant = item.get("relevant")
        if not query_id:
            raise ValueError(f"Query #{index} requires an id")
        if query_id in query_ids:
            raise ValueError(f"Duplicate query id: {query_id}")
        if not query:
            raise ValueError(f"Query {query_id} requires query text")
        if not isinstance(relevant, list):
            raise ValueError(f"Query {query_id} requires a relevant list")

        relevant_keys = [str(key).strip() for key in relevant]
        if any(not key for key in relevant_keys):
            raise ValueError(f"Query {query_id} contains an empty relevant key")
        if len(set(relevant_keys)) != len(relevant_keys):
            raise ValueError(f"Query {query_id} contains duplicate relevant keys")
        unknown = sorted(set(relevant_keys) - memory_keys)
        if unknown:
            raise ValueError(
                f"Query {query_id} references unknown memories: {', '.join(unknown)}"
            )

        query_ids.add(query_id)
        normalized_queries.append({
            "id": query_id,
            "query": query,
            "relevant": relevant_keys,
        })

    return {"memories": normalized_memories, "queries": normalized_queries}


def evaluate_rankings(
    queries: list[dict[str, Any]],
    rankings: dict[str, list[str]],
    k: int = 5,
) -> dict[str, Any]:
    """Calculate retrieval metrics from expected and observed memory keys."""
    k = int(k)
    if k <= 0:
        raise ValueError("k must be greater than zero")
    if not queries:
        raise ValueError("At least one query is required")

    total_relevant = 0
    total_hits = 0
    total_retrieved = 0
    positive_queries = 0
    positive_queries_hit = 0
    reciprocal_rank_sum = 0.0
    negative_queries = 0
    negative_queries_clean = 0
    details = []

    for item in queries:
        query_id = str(item["id"])
        relevant = set(item.get("relevant", []))
        ranked = list(dict.fromkeys(rankings.get(query_id, [])))[:k]
        hits = [key for key in ranked if key in relevant]
        total_retrieved += len(ranked)

        reciprocal_rank = 0.0
        if relevant:
            positive_queries += 1
            total_relevant += len(relevant)
            total_hits += len(hits)
            if hits:
                positive_queries_hit += 1
                reciprocal_rank = 1.0 / next(
                    rank
                    for rank, key in enumerate(ranked, start=1)
                    if key in relevant
                )
                reciprocal_rank_sum += reciprocal_rank
        else:
            negative_queries += 1
            if not ranked:
                negative_queries_clean += 1

        details.append({
            "id": query_id,
            "relevant": sorted(relevant),
            "retrieved": ranked,
            "hits": hits,
            "reciprocal_rank": reciprocal_rank,
        })

    recall = total_hits / total_relevant if total_relevant else 0.0
    precision = total_hits / total_retrieved if total_retrieved else 0.0
    hit_rate = (
        positive_queries_hit / positive_queries if positive_queries else 0.0
    )
    mrr = reciprocal_rank_sum / positive_queries if positive_queries else 0.0
    negative_accuracy = (
        negative_queries_clean / negative_queries if negative_queries else 1.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "k": k,
        "query_count": len(queries),
        "positive_query_count": positive_queries,
        "negative_query_count": negative_queries,
        "recall": recall,
        "precision": precision,
        "hit_rate": hit_rate,
        "mrr": mrr,
        "negative_accuracy": negative_accuracy,
        "f1": f1,
        "average_returned": total_retrieved / len(queries),
        "details": details,
    }
