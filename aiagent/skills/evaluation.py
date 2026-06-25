from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_skill_evaluation_cases(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("Skill evaluation fixture must contain a cases array")

    cases = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"Case {index + 1} must be an object")
        case_id = str(raw.get("id") or f"case-{index + 1}").strip()
        query = str(raw.get("query") or "").strip()
        expected = _skill_names(raw.get("expected_skills"))
        forbidden = _skill_names(raw.get("forbidden_skills"))
        if not query:
            raise ValueError(f"Case '{case_id}' has no query")
        if not expected:
            raise ValueError(f"Case '{case_id}' has no expected_skills")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id: {case_id}")
        overlap = set(expected) & set(forbidden)
        if overlap:
            raise ValueError(
                f"Case '{case_id}' lists skills as both expected and forbidden: "
                + ", ".join(sorted(overlap))
            )
        seen_ids.add(case_id)
        cases.append({
            "id": case_id,
            "query": query,
            "expected_skills": expected,
            "forbidden_skills": forbidden,
        })
    return cases


def evaluate_skill_selections(
    cases: Iterable[dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    offered_skill_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    offered = set(offered_skill_names) if offered_skill_names is not None else None
    details = []
    total_expected = 0
    total_selected = 0
    true_positives = 0
    forbidden_hits = 0
    observed_cases = 0
    exact_cases = 0
    index_missing: set[str] = set()

    for case in cases:
        query_key = normalize_query(case["query"])
        observation = observations.get(query_key, {})
        observed = bool(observation.get("observed"))
        selected = set(observation.get("skills") or []) if observed else set()
        expected = set(case["expected_skills"])
        forbidden = set(case.get("forbidden_skills") or [])
        missing = expected - selected
        unexpected = selected - expected
        forbidden_selected = selected & forbidden
        unavailable = expected - offered if offered is not None else set()
        index_missing.update(unavailable)

        if observed:
            observed_cases += 1
            total_expected += len(expected)
            total_selected += len(selected)
            true_positives += len(selected & expected)
            forbidden_hits += len(forbidden_selected)
            if not missing and not unexpected and not forbidden_selected:
                exact_cases += 1

        details.append({
            "id": case["id"],
            "query": case["query"],
            "observed": observed,
            "expected": sorted(expected),
            "selected": sorted(selected),
            "missing": sorted(missing) if observed else [],
            "unexpected": sorted(unexpected) if observed else [],
            "forbidden_selected": sorted(forbidden_selected),
            "index_missing": sorted(unavailable),
        })

    case_count = len(details)
    precision = true_positives / total_selected if total_selected else None
    recall = true_positives / total_expected if total_expected else None
    return {
        "cases": case_count,
        "observed_cases": observed_cases,
        "trace_coverage": round(observed_cases / case_count, 4) if case_count else None,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "exact_match_rate": (
            round(exact_cases / observed_cases, 4) if observed_cases else None
        ),
        "forbidden_hits": forbidden_hits,
        "index_coverage": (
            round((case_count - sum(bool(item["index_missing"]) for item in details)) / case_count, 4)
            if case_count and offered is not None
            else None
        ),
        "index_missing_skills": sorted(index_missing),
        "details": details,
    }


def normalize_query(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _skill_names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return names
