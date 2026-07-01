from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

from aiagent.agent import Agent
from aiagent.config_validation import (
    StartupConfigError,
    format_config_issues,
    load_and_validate_config,
    validate_model_config,
)
from aiagent.dashboard_api import create_dashboard_app
from aiagent.encoding import ensure_utf8_stdio
from aiagent.memory.config import resolve_memory_config


ensure_utf8_stdio()

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SIERRA_DIR = ROOT

try:
    CONFIG = load_and_validate_config(CONFIG_PATH)
except StartupConfigError as exc:
    print(format_config_issues(exc.issues), file=sys.stderr)
    raise SystemExit(2)

workspace = os.environ.get("SIERRA_WORKSPACE")
if workspace:
    try:
        os.chdir(workspace)
    except OSError:
        pass


def make_agent(model_key: str) -> Agent:
    validate_model_config(CONFIG, model_key)
    model_cfg = CONFIG["models"][model_key]
    return Agent(
        model=model_cfg["name"],
        base_url=model_cfg["base_url"],
        api_key=model_cfg["api_key"],
        max_tokens=model_cfg.get("max_tokens", 4096),
        temperature=model_cfg.get("temperature", 0.7),
        context_window=model_cfg.get("context_window", 1000000),
        mcp_config=CONFIG,
        audit_config=CONFIG.get("audit", {}),
        memory_config=resolve_memory_config(CONFIG),
        task_config=CONFIG.get("tasks", {}),
        skill_config=CONFIG.get("skills", {}),
        session_config=CONFIG.get("sessions", {}),
        background_config=CONFIG.get("background_jobs", {}),
        context_config=CONFIG.get("context", {}),
        cron_config=CONFIG.get("cron", {}),
        checkpoint_config=CONFIG.get("checkpoints", {}),
        tools_config=CONFIG.get("tools", {}),
        workspace=os.getcwd(),
        sierra_dir=str(SIERRA_DIR),
        permission_config=CONFIG.get("permissions", {}),
    )


agent = make_agent(CONFIG["active_model"])
app = create_dashboard_app(
    agent,
    config=CONFIG,
    config_path=CONFIG_PATH,
    make_agent=make_agent,
    static_dir=ROOT / "web" / "dist",
    sierra_dir=SIERRA_DIR,
)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Sierra Web Dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--log-level",
        default="warning",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level. Defaults to warning to keep Sierra Web quiet.",
    )
    parser.add_argument(
        "--access-log",
        action="store_true",
        help="Print one HTTP access log line per request.",
    )
    args = parser.parse_args()
    print(f"Sierra Web running at http://{args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=args.access_log,
    )


if __name__ == "__main__":
    main()
