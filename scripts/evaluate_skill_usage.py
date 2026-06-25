"""Evaluate Sierra's runtime Skill selections against a JSON fixture."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiagent.skills.evaluation import (  # noqa: E402
    evaluate_skill_selections,
    load_skill_evaluation_cases,
)
from aiagent.skills.loader import SkillLoader  # noqa: E402
from aiagent.skills.prompt_index import SkillPromptIndex  # noqa: E402
from aiagent.skills.usage_store import SkillUsageStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=str(PROJECT_ROOT / "tests" / "fixtures" / "skill_selection_cases.json"),
        help="Evaluation fixture path",
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config.json"),
        help="Sierra config path",
    )
    parser.add_argument("--db", help="Override the telemetry SQLite path")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace filter")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless all cases have traces and exact selections",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    skill_config = config.get("skills", {})
    cases = load_skill_evaluation_cases(args.cases)

    loader = SkillLoader()
    skills = loader.load()
    if loader.errors:
        raise SystemExit("Skill validation failed:\n" + "\n".join(loader.errors))
    known_names = {skill.name for skill in skills}
    fixture_names = {
        name
        for case in cases
        for name in [*case["expected_skills"], *case["forbidden_skills"]]
    }
    unknown = sorted(fixture_names - known_names)
    if unknown:
        raise SystemExit("Fixture references unknown skills: " + ", ".join(unknown))

    if args.db:
        store = SkillUsageStore(args.db)
    else:
        store = SkillUsageStore.from_config(skill_config, base_dir=PROJECT_ROOT)
    try:
        observations = store.evaluation_observations(
            [case["query"] for case in cases],
            workspace=args.workspace,
        )
        index = SkillPromptIndex(skill_config)
        offered = {
            skill.name
            for skill in index.offered_skills(skills, available_tools=[])
        }
        report = evaluate_skill_selections(cases, observations, offered)
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    if args.strict and (
        report["trace_coverage"] != 1.0
        or report["exact_match_rate"] != 1.0
        or report["forbidden_hits"]
        or report["index_coverage"] != 1.0
    ):
        return 1
    return 0


def _print_report(report: dict) -> None:
    def metric(value):
        return "n/a" if value is None else f"{value:.1%}"

    print("Sierra Skill Evaluation")
    print(f"  index coverage : {metric(report['index_coverage'])}")
    print(f"  trace coverage : {metric(report['trace_coverage'])}")
    print(f"  precision      : {metric(report['precision'])}")
    print(f"  recall         : {metric(report['recall'])}")
    print(f"  exact match    : {metric(report['exact_match_rate'])}")
    print(f"  forbidden hits : {report['forbidden_hits']}")
    for item in report["details"]:
        if not item["observed"]:
            print(f"  ? {item['id']}: no matching runtime trace")
        elif item["missing"] or item["unexpected"] or item["forbidden_selected"]:
            print(
                f"  ! {item['id']}: selected={item['selected']} "
                f"missing={item['missing']} unexpected={item['unexpected']}"
            )
        else:
            print(f"  + {item['id']}: {item['selected']}")


if __name__ == "__main__":
    raise SystemExit(main())
