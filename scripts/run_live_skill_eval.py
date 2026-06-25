"""Run live, side-effect-free Skill selection evaluation against Sierra's active model."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiagent.agent import Agent  # noqa: E402
from aiagent.skills.evaluation import (  # noqa: E402
    evaluate_skill_selections,
    load_skill_evaluation_cases,
    normalize_query,
)


SAFE_DISCOVERY_TOOLS = {"skills_list", "skill_view"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=str(PROJECT_ROOT / "tests" / "fixtures" / "skill_selection_cases.json"),
    )
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.json"))
    parser.add_argument("--rounds", type=int, default=3, help="Maximum discovery rounds per case")
    parser.add_argument(
        "--ids",
        help="Optional comma-separated case IDs to run",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--output", help="Optional JSON report output path")
    args = parser.parse_args()

    with Path(args.config).open("r", encoding="utf-8") as file:
        config = json.load(file)
    model_key = config["active_model"]
    model_config = config["models"][model_key]
    skill_config = copy.deepcopy(config.get("skills", {}))
    skill_config["telemetry"] = {"enabled": False}
    agent = Agent(
        model=model_config["name"],
        base_url=model_config["base_url"],
        api_key=model_config["api_key"],
        max_tokens=min(2048, int(model_config.get("max_tokens", 4096))),
        temperature=0,
        context_window=model_config.get("context_window", 1000000),
        mcp_config={},
        permission_config={"allow": ["skills_list", "skill_view"]},
        audit_config={"enabled": False},
        memory_config={"review_interval": 0, "vector": {"enabled": False}},
        task_config={"enabled": False},
        skill_config=skill_config,
        workspace=str(PROJECT_ROOT),
        sierra_dir=str(PROJECT_ROOT),
    )
    cases = load_skill_evaluation_cases(args.cases)
    if args.ids:
        requested_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
        known_ids = {case["id"] for case in cases}
        unknown_ids = sorted(requested_ids - known_ids)
        if unknown_ids:
            raise SystemExit("Unknown case IDs: " + ", ".join(unknown_ids))
        cases = [case for case in cases if case["id"] in requested_ids]
    observations = {}
    raw_results = []
    available_tools = set(agent.tools.names())
    try:
        for index, case in enumerate(cases, 1):
            selected, stopped_on, usage = _evaluate_case(
                agent,
                case["query"],
                max_rounds=max(1, min(5, args.rounds)),
            )
            observations[normalize_query(case["query"])] = {
                "observed": True,
                "skills": set(selected),
            }
            raw_results.append({
                "id": case["id"],
                "query": case["query"],
                "selected_skills": selected,
                "stopped_on_tool": stopped_on,
                "usage": usage,
            })
            if not args.json:
                suffix = f" · stopped on {stopped_on}" if stopped_on else ""
                print(f"[{index}/{len(cases)}] {case['id']}: {selected or ['none']}{suffix}")
    finally:
        agent.close()

    offered = {
        skill.name
        for skill in agent.skill_index.offered_skills(
            agent.skills,
            available_tools=available_tools,
        )
    }
    report = evaluate_skill_selections(cases, observations, offered)
    report["model_key"] = model_key
    report["model"] = model_config["name"]
    report["raw_results"] = raw_results
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)
    return 0


def _evaluate_case(agent: Agent, query: str, max_rounds: int):
    messages = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": query},
    ]
    selected: set[str] = set()
    stopped_on = ""
    usage = {"input": 0, "output": 0}
    tools = agent.tools.get_definitions()
    for _ in range(max_rounds):
        response = agent.llm.chat(messages, tools=tools)
        usage["input"] += int(response.get("usage", {}).get("input", 0) or 0)
        usage["output"] += int(response.get("usage", {}).get("output", 0) or 0)
        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            break
        messages.append({
            "role": "assistant",
            "content": response.get("content"),
            "tool_calls": tool_calls,
        })
        can_continue = True
        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            try:
                arguments = json.loads(tool_call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if name not in SAFE_DISCOVERY_TOOLS:
                stopped_on = name
                can_continue = False
                break
            if name == "skill_view" and arguments.get("name"):
                selected.add(str(arguments["name"]))
            result = agent.tools.execute(name, arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result,
            })
        if not can_continue:
            break
        if selected:
            break
    return sorted(selected), stopped_on, usage


def _print_summary(report: dict) -> None:
    def metric(value):
        return "n/a" if value is None else f"{value:.1%}"

    print("\nLive Skill Selection Summary")
    print(f"  model       : {report['model']}")
    print(f"  precision   : {metric(report['precision'])}")
    print(f"  recall      : {metric(report['recall'])}")
    print(f"  exact match : {metric(report['exact_match_rate'])}")
    print(f"  index       : {metric(report['index_coverage'])}")
    print(f"  forbidden   : {report['forbidden_hits']}")
    total_input = sum(item["usage"]["input"] for item in report["raw_results"])
    total_output = sum(item["usage"]["output"] for item in report["raw_results"])
    print(f"  tokens      : {total_input} input · {total_output} output")
    for item in report["details"]:
        if item["missing"] or item["unexpected"]:
            print(
                f"  ! {item['id']}: selected={item['selected']} "
                f"missing={item['missing']} unexpected={item['unexpected']}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
