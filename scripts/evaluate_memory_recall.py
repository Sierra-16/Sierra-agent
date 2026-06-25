#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from aiagent.memory.config import resolve_memory_config
from aiagent.memory.embedding import OpenAICompatibleEmbeddingClient
from aiagent.memory.evaluation import (
    evaluate_rankings,
    load_recall_fixture,
    parse_thresholds,
)
from aiagent.memory.vector_store import SQLiteVectorStore
from aiagent.safety import sanitize_text


DEFAULT_THRESHOLDS = "0.25,0.30,0.35,0.40,0.45,0.50,0.55"
EVALUATION_WORKSPACE = "__sierra_memory_recall_evaluation__"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Sierra vector-memory recall with the configured embedding model.",
    )
    parser.add_argument(
        "--fixture",
        default=str(ROOT_DIR / "tests" / "fixtures" / "memory_recall_cases.json"),
        help="Recall benchmark JSON file.",
    )
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config.json"),
        help="Sierra config file used to resolve the embedding provider.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Maximum results per query.")
    parser.add_argument(
        "--thresholds",
        default=DEFAULT_THRESHOLDS,
        help="Comma-separated cosine thresholds to compare.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the fixture and embedding configuration without calling the API.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the report table.",
    )
    return parser


def load_embedding_settings(config_path: str | Path) -> dict[str, Any]:
    with Path(config_path).open("r", encoding="utf-8") as file:
        app_config = json.load(file)

    memory_config = resolve_memory_config(app_config)
    vector_config = memory_config.get("vector", {})
    if not isinstance(vector_config, dict):
        raise ValueError("config.json does not contain memory.vector.embedding")
    embedding_config = vector_config.get("embedding", {})
    if not isinstance(embedding_config, dict):
        raise ValueError("config.json does not contain memory.vector.embedding")
    if embedding_config.get("provider", "openai_compatible") != "openai_compatible":
        raise ValueError("The evaluator currently supports openai_compatible embeddings only")

    required = ("base_url", "api_key", "model")
    missing = [key for key in required if not embedding_config.get(key)]
    if missing:
        raise ValueError(f"Missing embedding configuration: {', '.join(missing)}")

    return {
        "base_url": embedding_config["base_url"],
        "api_key": embedding_config["api_key"],
        "model": embedding_config["model"],
        "dimensions": embedding_config.get("dimensions"),
        "batch_size": embedding_config.get("batch_size", 10),
        "timeout": embedding_config.get("timeout", 20.0),
        "configured_threshold": float(vector_config.get("recall_min_score", 0.35)),
        "max_turn_chars": int(vector_config.get("max_turn_chars", 6000)),
    }


def create_embedding_client(settings: dict[str, Any]) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        base_url=settings["base_url"],
        api_key=settings["api_key"],
        model=settings["model"],
        dimensions=settings["dimensions"],
        batch_size=settings["batch_size"],
        timeout=settings["timeout"],
    )


def memory_content(memory: dict[str, str], max_length: int) -> str:
    return sanitize_text(
        f"用户: {memory['user']}\nSierra: {memory['assistant']}",
        max_length=max_length,
    )


def run_benchmark(
    fixture: dict[str, list[dict[str, Any]]],
    settings: dict[str, Any],
    thresholds: list[float],
    top_k: int,
    quiet: bool = False,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("--top-k must be greater than zero")

    client = create_embedding_client(settings)
    with tempfile.TemporaryDirectory(prefix="sierra-recall-") as temp_dir:
        store = SQLiteVectorStore(
            str(Path(temp_dir) / "evaluation.sqlite3"),
            max_records=len(fixture["memories"]) + 10,
        )
        try:
            contents = [
                memory_content(memory, settings["max_turn_chars"])
                for memory in fixture["memories"]
            ]
            if not quiet:
                print(
                    f"Embedding {len(contents)} memories with {settings['model']}...",
                    flush=True,
                )
            memory_vectors = client.embed(contents)
            for memory, content, vector in zip(
                fixture["memories"], contents, memory_vectors, strict=True
            ):
                store.add(content, vector, {
                    "workspace": EVALUATION_WORKSPACE,
                    "conversation_id": memory["key"],
                    "model": settings["model"],
                })

            query_texts = [query["query"] for query in fixture["queries"]]
            if not quiet:
                print(f"Embedding {len(query_texts)} benchmark queries...", flush=True)
            query_vectors = client.embed(query_texts)

            reports = []
            for threshold in thresholds:
                rankings = {}
                for query, vector in zip(
                    fixture["queries"], query_vectors, strict=True
                ):
                    results = store.search(
                        vector,
                        limit=top_k,
                        workspace=EVALUATION_WORKSPACE,
                        min_score=threshold,
                    )
                    rankings[query["id"]] = [
                        result["conversation_id"] for result in results
                    ]
                metrics = evaluate_rankings(fixture["queries"], rankings, k=top_k)
                reports.append({"threshold": threshold, **metrics})
        finally:
            store.close()
            client.close()

    best = max(
        reports,
        key=lambda report: (
            report["f1"],
            report["mrr"],
            report["negative_accuracy"],
        ),
    )
    best_recall = max(report["recall"] for report in reports)
    recall_preserving = max(
        (
            report
            for report in reports
            if abs(report["recall"] - best_recall) < 1e-9
        ),
        key=lambda report: (report["precision"], report["threshold"]),
    )
    configured = min(
        reports,
        key=lambda report: abs(
            report["threshold"] - settings["configured_threshold"]
        ),
    )
    return {
        "model": settings["model"],
        "memory_count": len(fixture["memories"]),
        "query_count": len(fixture["queries"]),
        "top_k": top_k,
        "configured_threshold": settings["configured_threshold"],
        "best_threshold": best["threshold"],
        "recall_preserving_threshold": recall_preserving["threshold"],
        "reports": reports,
        "configured_report": configured,
    }


def print_report(result: dict[str, Any], fixture: dict[str, Any]) -> None:
    print()
    print(
        f"Model: {result['model']} | Memories: {result['memory_count']} | "
        f"Queries: {result['query_count']} | K: {result['top_k']}"
    )
    print(
        "Threshold  Recall@K  Hit@K  Precision@K  MRR    Neg.Acc  Avg.Returned"
    )
    print("---------  --------  -----  -----------  -----  -------  ------------")
    for report in result["reports"]:
        marker = "*" if abs(
            report["threshold"] - result["configured_threshold"]
        ) < 1e-9 else " "
        print(
            f"{marker}{report['threshold']:>7.2f}  "
            f"{report['recall']:>8.1%}  "
            f"{report['hit_rate']:>5.1%}  "
            f"{report['precision']:>11.1%}  "
            f"{report['mrr']:>5.3f}  "
            f"{report['negative_accuracy']:>7.1%}  "
            f"{report['average_returned']:>12.2f}"
        )

    configured = result["configured_report"]
    print()
    print("* configured threshold")
    print(
        f"Best balanced threshold by retrieval F1: {result['best_threshold']:.2f}"
    )
    print(
        "Highest-precision threshold preserving best recall: "
        f"{result['recall_preserving_threshold']:.2f}"
    )

    query_text = {query["id"]: query["query"] for query in fixture["queries"]}
    misses = []
    false_positives = []
    irrelevant_results = 0
    for detail in configured["details"]:
        expected = set(detail["relevant"])
        if expected:
            missing = sorted(expected - set(detail["retrieved"]))
            irrelevant_results += sum(
                key not in expected for key in detail["retrieved"]
            )
            if missing:
                misses.append((detail, missing))
        elif detail["retrieved"]:
            false_positives.append(detail)

    print(
        f"Configured threshold diagnostics: {len(misses)} queries with misses, "
        f"{irrelevant_results} distractor results, "
        f"{len(false_positives)} negative queries with false positives."
    )
    for detail, missing in misses:
        print(
            f"  MISS {detail['id']}: missing={','.join(missing)} "
            f"returned={','.join(detail['retrieved']) or '-'}"
        )
        print(f"       {query_text[detail['id']]}")
    for detail in false_positives:
        print(
            f"  FALSE+ {detail['id']}: returned={','.join(detail['retrieved'])}"
        )
        print(f"         {query_text[detail['id']]}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixture = load_recall_fixture(args.fixture)
        settings = load_embedding_settings(args.config)
        thresholds = parse_thresholds(args.thresholds)
        configured_threshold = settings["configured_threshold"]
        if configured_threshold not in thresholds:
            thresholds = sorted(set([*thresholds, configured_threshold]))
        if args.top_k <= 0:
            raise ValueError("--top-k must be greater than zero")

        if args.validate_only:
            validation = {
                "valid": True,
                "fixture": str(Path(args.fixture).resolve()),
                "model": settings["model"],
                "memory_count": len(fixture["memories"]),
                "query_count": len(fixture["queries"]),
                "positive_queries": sum(
                    bool(query["relevant"]) for query in fixture["queries"]
                ),
                "negative_queries": sum(
                    not query["relevant"] for query in fixture["queries"]
                ),
                "thresholds": thresholds,
            }
            if args.json:
                print(json.dumps(validation, ensure_ascii=False, indent=2))
            else:
                print(
                    "Recall fixture is valid: "
                    f"{validation['memory_count']} memories, "
                    f"{validation['positive_queries']} positive queries, "
                    f"{validation['negative_queries']} negative queries, "
                    f"model {validation['model']}."
                )
            return 0

        result = run_benchmark(
            fixture=fixture,
            settings=settings,
            thresholds=thresholds,
            top_k=args.top_k,
            quiet=args.json,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_report(result, fixture)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Recall evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
