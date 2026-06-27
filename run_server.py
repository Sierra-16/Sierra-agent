"""Server mode entry point — spawned by TUI."""
import sys
sys.path.insert(0, ".")
from aiagent.encoding import ensure_utf8_stdio

ensure_utf8_stdio()

from aiagent.server import run_server
from aiagent.agent import Agent
from aiagent.memory.config import resolve_memory_config
from aiagent.config_validation import (
    StartupConfigError,
    format_config_issues,
    load_and_validate_config,
    validate_model_config,
)
import os

config_path = os.path.join(os.path.dirname(__file__), "config.json")
sierra_dir = os.path.dirname(config_path)
try:
    config = load_and_validate_config(config_path)
except StartupConfigError as exc:
    print(format_config_issues(exc.issues), file=sys.stderr)
    raise SystemExit(2)

workspace = os.environ.get("SIERRA_WORKSPACE")
if workspace:
    try:
        os.chdir(workspace)
    except OSError:
        pass

def make_agent(model_key):
    validate_model_config(config, model_key)
    model_cfg = config["models"][model_key]
    return Agent(
        model=model_cfg["name"],
        base_url=model_cfg["base_url"],
        api_key=model_cfg["api_key"],
        max_tokens=model_cfg.get("max_tokens", 4096),
        temperature=model_cfg.get("temperature", 0.7),
        context_window=model_cfg.get("context_window", 1000000),
        mcp_config=config,
        audit_config=config.get("audit", {}),
        memory_config=resolve_memory_config(config),
        task_config=config.get("tasks", {}),
        skill_config=config.get("skills", {}),
        session_config=config.get("sessions", {}),
        # companion_config=config.get("companion", {}),
        background_config=config.get("background_jobs", {}),
        context_config=config.get("context", {}),
        workspace=os.getcwd(),
        sierra_dir=sierra_dir,
        permission_config=config.get("permissions", {}),
    )


agent = make_agent(config["active_model"])

run_server(agent, config=config, config_path=config_path, make_agent=make_agent)
