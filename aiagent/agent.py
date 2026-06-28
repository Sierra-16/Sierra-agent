import copy
import json
import logging
import os
import time

from .background_jobs import BackgroundJobQueue
from .conversation_store import ConversationStore
from .session_db import SessionDB
from .llm import LLMClient
from .tools.registry import registry
from .tools.path_context import set_tool_workspace
from .system_prompt import build_system_prompt
from .conversation_loop import run_conversation_loop
from .tools.memory_tool import store as memory_store
from .memory import LocalVectorProvider, MemoryManager, MarkdownMemoryProvider
from .skills.loader import SkillLoader, set_skill_loader
from .skills.manager import SkillManager
from .skills.prompt_index import SkillPromptIndex
from .skills.usage_store import SkillUsageStore
from .tools.skill_view_tool import configure_skill_tools
from .mcp import MCPManager
from .safety import SafetyGate
from .permission_policy import PermissionPolicy
from .audit_logger import AuditLogger
from .context_compaction import (
    build_compaction_prompt,
    build_compaction_transcript,
    build_fallback_summary,
    build_summary_message,
    prune_old_tool_results,
    select_compaction_window,
    strip_historical_media,
)
from .context_files import ContextFileLoader
from .checkpoints import CheckpointManager
from .cron import CronStore
from .skill_suggestions import suggest_skill_from_turn
from .tasks import TaskCheckpointStore, TaskManager
from .token_utils import estimate_tokens


logger = logging.getLogger(__name__)


def _resolve_prompt_budget(
    model_context_window,
    max_tokens,
    context_config,
):
    model_window = max(1, int(model_context_window or 1))
    try:
        output_headroom = int(max_tokens or 4096)
    except (TypeError, ValueError):
        output_headroom = 4096
    output_headroom = max(1024, output_headroom)
    model_prompt_budget = max(4096, model_window - output_headroom)

    raw_cap = context_config.get("max_prompt_tokens", 120000)
    if str(raw_cap).strip().lower() in {"", "0", "none", "model", "false"}:
        return model_prompt_budget
    try:
        cap = max(4096, int(raw_cap))
    except (TypeError, ValueError):
        cap = 120000
    return max(4096, min(model_prompt_budget, cap))


def _resolve_compression_window(model_context_window, context_config, prompt_context_window=None):
    model_window = max(1, int(model_context_window or 1))
    raw_window = context_config.get(
        "compression_context_window",
        context_config.get("compression_window_tokens", "model"),
    )
    normalized = str(raw_window).strip().lower()
    if normalized in {"prompt", "budget", "context", "context_budget", "max_prompt_tokens"}:
        return max(1, int(prompt_context_window or model_window))
    if normalized in {"", "0", "none", "model", "false"}:
        return model_window
    try:
        return max(1, int(raw_window))
    except (TypeError, ValueError):
        return model_window


def _coerce_ratio(value, *, default, minimum, maximum):
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        ratio = float(default)
    return max(float(minimum), min(float(maximum), ratio))


class Agent:
    def __init__(
        self,
        model,
        base_url,
        api_key,
        max_tokens=4096,
        temperature=0.7,
        context_window=1000000,
        mcp_config=None,
        permission_config=None,
        audit_config=None,
        memory_config=None,
        task_config=None,
        skill_config=None,
        session_config=None,
        background_config=None,
        context_config=None,
        cron_config=None,
        checkpoint_config=None,
        workspace=None,
        sierra_dir=None,
    ):
        self.llm = LLMClient(base_url, api_key, model=model, max_tokens=max_tokens, temperature=temperature)
        self.model = model
        self.tools = registry
        self.safety = SafetyGate()
        self.permission_policy = PermissionPolicy(permission_config)
        self.background_jobs = BackgroundJobQueue.from_config(background_config)
        self.sierra_dir = os.path.abspath(
            sierra_dir or os.path.join(os.path.dirname(__file__), "..")
        )
        self.workspace = os.path.abspath(workspace or ".")
        set_tool_workspace(self.workspace)
        self.audit = AuditLogger.from_config(
            audit_config,
            base_dir=self.sierra_dir,
        )
        skill_config = skill_config if isinstance(skill_config, dict) else {}
        self.skill_loader = SkillLoader()
        self.skills = self.skill_loader.load()
        self.skill_index = SkillPromptIndex(skill_config)
        self.skill_usage = SkillUsageStore.from_config(
            skill_config,
            base_dir=self.sierra_dir,
        )
        set_skill_loader(self.skill_loader)
        configure_skill_tools(self.workspace, self.skill_index)
        self.skill_manager = SkillManager(self.skill_loader, self.reload_skills)
        self.mcp = MCPManager.from_config(
            mcp_config or {},
            workspace=self.workspace,
            sierra_dir=self.sierra_dir,
        )
        self.mcp.start_all()
        self.mcp.register_tools(self.tools)
        memory_config = memory_config or {}
        markdown_memory = MarkdownMemoryProvider(memory_store).configure(
            max_memory_chars=memory_config.get("max_memory_chars", 2200),
            max_user_chars=memory_config.get("max_user_chars", 1375),
        )
        self.memory_manager = MemoryManager(markdown_memory)
        vector_config = memory_config.get("vector", {})
        if vector_config.get("enabled", False):
            try:
                vector_memory = LocalVectorProvider.from_config(
                    vector_config,
                    base_dir=self.sierra_dir,
                    workspace=self.workspace,
                )
                self.memory_manager.add_provider(vector_memory)
            except Exception as exc:
                logger.warning("Vector memory disabled: %s", exc)
        self.memory_review_interval = max(
            0,
            int(memory_config.get("review_interval", 10)),
        )
        self.memory_review_max_chars = max(
            1000,
            int(memory_config.get("review_max_chars", 16000)),
        )
        self.store = ConversationStore()
        session_config = session_config if isinstance(session_config, dict) else {}
        self.history_recall_config = (
            session_config.get("recall", {})
            if isinstance(session_config.get("recall", {}), dict)
            else {}
        )
        self.session_db = None
        try:
            self.session_db = SessionDB.from_config(
                session_config,
                base_dir=self.sierra_dir,
            )
        except Exception as exc:
            logger.warning("Session database disabled: %s", exc)
        self._bootstrap_session_db_from_json()
        self.conv_id = None
        self.task_manager = None
        task_config = task_config or {}
        if task_config.get("enabled", True) is not False:
            try:
                task_store = TaskCheckpointStore.from_config(
                    task_config,
                    base_dir=self.sierra_dir,
                )
                self.task_manager = TaskManager(task_store, self.workspace)
                self.task_manager.register_tools(self.tools)
            except Exception as exc:
                logger.warning("Task checkpoints disabled: %s", exc)
        if self.task_manager is None:
            self.tools.unregister("update_plan")
            self.tools.unregister("get_plan")
            self.tools.unregister("resolve_task_execution")
        self._turns_since_memory_review = 0
        context_config = context_config if isinstance(context_config, dict) else {}
        self.context_files = ContextFileLoader.from_config(context_config)
        self.last_context_files = None
        self.checkpoints = CheckpointManager.from_config(
            checkpoint_config,
            base_dir=self.sierra_dir,
        )
        self.cron = CronStore.from_config(cron_config, base_dir=self.sierra_dir)
        self.model_context_window = max(1, int(context_window))
        self.context_window = _resolve_prompt_budget(
            self.model_context_window,
            max_tokens,
            context_config,
        )
        self.compression_context_window = _resolve_compression_window(
            self.model_context_window,
            context_config,
            prompt_context_window=self.context_window,
        )
        self.compression_enabled = context_config.get("enabled", True) is not False
        compression_threshold_ratio = _coerce_ratio(
            context_config.get("compression_threshold", context_config.get("threshold", 0.8)),
            default=0.8,
            minimum=0.1,
            maximum=0.95,
        )
        self.compression_threshold_ratio = compression_threshold_ratio
        compression_target_ratio = _coerce_ratio(
            context_config.get("target_ratio", 0.2),
            default=0.2,
            minimum=0.05,
            maximum=0.8,
        )
        self.compression_target_ratio = compression_target_ratio
        compression_keep_ratio = _coerce_ratio(
            context_config.get("keep_recent_ratio", 0.25),
            default=0.25,
            minimum=0.05,
            maximum=0.9,
        )
        self.compression_keep_ratio = compression_keep_ratio
        self.compression_min_savings_ratio = _coerce_ratio(
            context_config.get("min_savings_ratio", 0.10),
            default=0.10,
            minimum=0.0,
            maximum=0.9,
        )
        self.compression_failure_cooldown_seconds = max(
            0,
            int(context_config.get("failure_cooldown_seconds", 600) or 0),
        )
        self.compression_max_passes = max(
            1,
            min(5, int(context_config.get("max_compression_passes", 3) or 3)),
        )
        self.compression_protect_first_messages = max(
            0,
            int(context_config.get("protect_first_messages", 3) or 0),
        )
        self.compression_protect_last_messages = max(
            0,
            int(context_config.get("protect_last_messages", 8) or 0),
        )
        self.old_tool_result_max_chars = max(
            500,
            int(context_config.get("old_tool_result_max_chars", 2400) or 2400),
        )
        self.recent_tool_result_max_chars = max(
            self.old_tool_result_max_chars,
            int(context_config.get("recent_tool_result_max_chars", 12000) or 12000),
        )
        self.recent_tool_result_message_count = max(
            0,
            int(context_config.get("recent_tool_result_message_count", 8) or 8),
        )
        self.compression_count = 0
        self._ineffective_compression_count = 0
        self._last_compression_savings_ratio = 1.0
        self._summary_failure_cooldown_until = 0.0
        self.compression_events = []
        self.current_context_tokens = 0
        self.context_tokens_estimated = False
        self.model = model
        self.tools.register(
            name="skill_reload",
            description=(
                "Reload all skill packages from disk, validate them, and refresh the active system prompt."
            ),
            parameters={"type": "object", "properties": {}},
            handler=self._reload_skills_tool,
        )
        self.tools.register(
            name="skill_manage",
            description=(
                "Create, update, add resources to, remove resources from, or delete a Sierra skill package. "
                "All actions modify local files, require user approval, and reload skills automatically."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "update",
                            "write_resource",
                            "remove_resource",
                            "delete",
                        ],
                    },
                    "name": {"type": "string", "description": "Skill name"},
                    "category": {
                        "type": "string",
                        "description": "Category for create, such as software-development",
                    },
                    "description": {
                        "type": "string",
                        "description": "Skill description for create or update",
                    },
                    "content": {
                        "type": "string",
                        "description": "SKILL.md body or resource text content",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Resource path under references/, templates/, scripts/, or assets/",
                    },
                },
                "required": ["action", "name"],
            },
            handler=self._manage_skill_tool,
        )
        self.tools.register(
            name="skill_usage_stats",
            description=(
                "Read aggregate Skill usage statistics for the current workspace, including views, "
                "template renders, script runs, failures, and load rate."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum Skill rows to return",
                    }
                },
            },
            handler=self._skill_usage_stats_tool,
        )
        self.tools.register(
            name="cron_list",
            description="List Sierra cron reminders and scheduled prompts.",
            parameters={"type": "object", "properties": {}},
            handler=self._cron_list_tool,
        )
        self.tools.register(
            name="cron_add",
            description=(
                "Create a recurring Sierra reminder. This stores a local schedule; "
                "it does not run unattended unless Sierra is running."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Reminder or task prompt"},
                    "interval_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Interval in minutes",
                    },
                },
                "required": ["prompt", "interval_minutes"],
            },
            handler=self._cron_add_tool,
        )
        self.tools.register(
            name="cron_remove",
            description="Remove a Sierra cron reminder by id.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Cron task id"}},
                "required": ["id"],
            },
            handler=self._cron_remove_tool,
        )
        self.system_prompt = self._build_system_prompt()
        self.messages = []
        self.max_iterations = 15
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._recalculate_compression_budgets()
        self.compression_transcript_chars = max(
            1000,
            min(
                int(context_config.get("transcript_max_chars", 160000) or 160000),
                self.context_window // 2,
            ),
        )

    def _recalculate_compression_budgets(self):
        self.max_compress_tokens = max(
            1,
            int(self.compression_context_window * self.compression_threshold_ratio),
        )
        self.compression_target_tokens = max(
            1,
            int(self.max_compress_tokens * self.compression_target_ratio),
        )
        self.compression_keep_tokens = max(
            1,
            int(self.max_compress_tokens * self.compression_keep_ratio),
        )

    def update_context_window(self, context_window):
        context_window = max(1, int(context_window or 1))
        self.model_context_window = context_window
        self.compression_context_window = context_window
        output_headroom = max(1024, int(getattr(self.llm, "max_tokens", 4096) or 4096))
        self.context_window = min(
            self.context_window,
            max(4096, context_window - output_headroom),
        )
        self._recalculate_compression_budgets()
        return {
            "model_context_window": self.model_context_window,
            "context_window": self.context_window,
            "max_compress_tokens": self.max_compress_tokens,
        }

    def chat(
        self,
        user_message,
        on_status=None,
        on_tool_approval=None,
        on_user_input=None,
    ):
        self.ensure_conversation_id()
        self.refresh_system_prompt()
        return run_conversation_loop(
            self,
            user_message,
            on_status=on_status,
            on_tool_approval=on_tool_approval,
            on_user_input=on_user_input,
        )

    def _build_system_prompt(self):
        memory_text = self.memory_manager.get_prompt_context()
        context_file_text = ""
        try:
            self.last_context_files = self.context_files.load(self.workspace)
            context_file_text = self.last_context_files.text
        except Exception as exc:
            logger.warning("Context files disabled for this prompt: %s", exc)
            self.last_context_files = None
        extra_parts = [
            f"Current model: {self.model}",
            (
                "# Path Context\n"
                f"- workspace: {self.workspace}\n"
                f"- sierra_dir: {self.sierra_dir}\n"
                "- Treat workspace as the user's project/current working directory.\n"
                "- Treat sierra_dir as Sierra's own installation/config directory.\n"
                "- File and shell tools resolve relative paths under workspace unless a user explicitly gives an absolute path."
            ),
        ]
        if context_file_text:
            extra_parts.append(context_file_text)
        if memory_text:
            extra_parts.append(memory_text)
        skills_prompt = self.skill_index.build(
            self.skills,
            available_tools=self.tools.names(),
        )
        return build_system_prompt(
            extra_context="\n\n".join(extra_parts),
            skills_prompt=skills_prompt,
        )

    def refresh_system_prompt(self):
        self.system_prompt = self._build_system_prompt()

    def set_workspace(self, workspace):
        self.workspace = os.path.abspath(workspace or ".")
        set_tool_workspace(self.workspace)
        configure_skill_tools(self.workspace, self.skill_index)
        if getattr(self, "mcp", None) is not None:
            self.mcp.workspace = self.workspace
        if getattr(self, "task_manager", None) is not None:
            self.task_manager.workspace = self.workspace
            self.task_manager.store.mark_interrupted(self.workspace)
            self.task_manager.bind_conversation(getattr(self, "conv_id", None))
        for provider in getattr(self.memory_manager, "providers", ()):
            if hasattr(provider, "workspace"):
                provider.workspace = self.workspace
        self.refresh_system_prompt()
        return self.workspace

    def reload_skills(self):
        self.skills = self.skill_loader.reload()
        self.skill_index.clear_cache()
        set_skill_loader(self.skill_loader)
        self.refresh_system_prompt()
        return {
            "ok": not self.skill_loader.errors,
            "count": len(self.skills),
            "skills": self.skill_summaries(include_unavailable=True),
            "errors": list(self.skill_loader.errors),
        }

    def skill_summaries(self, include_unavailable=False):
        return self.skill_index.summaries(
            self.skills,
            available_tools=self.tools.names(),
            include_unavailable=include_unavailable,
        )

    def _reload_skills_tool(self):
        return json.dumps(self.reload_skills(), ensure_ascii=False)

    def _manage_skill_tool(
        self,
        action,
        name,
        category=None,
        description=None,
        content=None,
        file_path=None,
    ):
        result = self.skill_manager.execute(
            action=action,
            name=name,
            category=category,
            description=description,
            content=content,
            file_path=file_path,
        )
        return json.dumps(result, ensure_ascii=False)

    def skill_usage_stats(self, limit=20):
        return self.skill_usage.stats(workspace=self.workspace, limit=limit)

    def _skill_usage_stats_tool(self, limit=20):
        return json.dumps(self.skill_usage_stats(limit=limit), ensure_ascii=False)

    def cron_status(self):
        if self.cron is None:
            return {"enabled": False, "tasks": []}
        return {"enabled": True, "tasks": self.cron.list()}

    def cron_add(self, prompt, interval_minutes):
        if self.cron is None:
            return {"ok": False, "error": "cron is disabled"}
        if not str(prompt or "").strip():
            return {"ok": False, "error": "prompt is required"}
        return {"ok": True, "task": self.cron.add(prompt, interval_minutes)}

    def cron_remove(self, task_id):
        if self.cron is None:
            return {"ok": False, "error": "cron is disabled"}
        removed = self.cron.remove(task_id)
        return {"ok": removed, "removed": removed}

    def cron_due(self):
        if self.cron is None:
            return []
        return self.cron.due()

    def _cron_list_tool(self):
        return json.dumps(self.cron_status(), ensure_ascii=False)

    def _cron_add_tool(self, prompt, interval_minutes):
        return json.dumps(
            self.cron_add(prompt, interval_minutes),
            ensure_ascii=False,
        )

    def _cron_remove_tool(self, id):
        return json.dumps(self.cron_remove(id), ensure_ascii=False)

    def undo_last_turn(self, count=1):
        count = max(1, int(count or 1))
        if not self.messages:
            return {"ok": False, "error": "no messages to undo", "messages": []}

        start = self._find_user_turn_start(count)
        if start is None:
            return {"ok": False, "error": "no user turn to undo", "messages": self.messages}

        removed = self.messages[start:]
        self.messages = self.messages[:start]
        self.sync_memory_review_state()
        self.refresh_context_estimate()
        self.refresh_system_prompt()
        self.checkpoint_conversation()
        return {
            "ok": True,
            "removed_messages": len(removed),
            "removed_user_turns": sum(1 for message in removed if message.get("role") == "user"),
            "messages": self.messages,
        }

    def retry_last_turn(self):
        start = self._find_user_turn_start(1)
        if start is None:
            return {"ok": False, "error": "no user turn to retry", "messages": self.messages}
        user_message = str(self.messages[start].get("content") or "")
        removed = self.messages[start:]
        self.messages = self.messages[:start]
        self.sync_memory_review_state()
        self.refresh_context_estimate()
        self.refresh_system_prompt()
        self.checkpoint_conversation()
        return {
            "ok": True,
            "user_message": user_message,
            "removed_messages": len(removed),
            "messages": self.messages,
        }

    def _find_user_turn_start(self, count=1):
        remaining = max(1, int(count or 1))
        for index in range(len(self.messages) - 1, -1, -1):
            if self.messages[index].get("role") == "user":
                remaining -= 1
                if remaining == 0:
                    return index
        return None

    def skill_suggestion_for_turn(self, user_message, assistant_message, turn_start_index=0):
        turn_messages = self.messages[max(0, int(turn_start_index or 0)) :]
        suggestion = suggest_skill_from_turn(user_message, assistant_message, turn_messages)
        if suggestion is None:
            return None
        signature = suggestion.title.lower()
        if getattr(self, "_last_skill_suggestion_signature", "") == signature:
            return None
        self._last_skill_suggestion_signature = signature
        return {
            "title": suggestion.title,
            "reason": suggestion.reason,
            "text": suggestion.to_text(),
        }

    def checkpoint_before_tool(self, tool_name, arguments):
        manager = getattr(self, "checkpoints", None)
        if manager is None:
            return None
        if not self._tool_should_checkpoint(tool_name, arguments):
            return None
        return manager.ensure_checkpoint(
            self.workspace,
            reason=self._checkpoint_reason(tool_name, arguments),
        )

    def _tool_should_checkpoint(self, tool_name, arguments):
        name = str(tool_name or "")
        arguments = arguments if isinstance(arguments, dict) else {}
        if name in ("write_file", "patch_file"):
            return self._path_is_in_workspace(arguments.get("file_path"))
        if name in ("delete_path", "make_directory"):
            return self._path_is_in_workspace(arguments.get("path"))
        if name in ("move_path", "copy_path"):
            return (
                self._path_is_in_workspace(arguments.get("source"))
                or self._path_is_in_workspace(arguments.get("destination"))
            )
        if name == "powershell":
            return (
                self._path_is_in_workspace(arguments.get("cwd") or ".")
                and self._powershell_command_may_mutate(arguments.get("command"))
            )
        return False

    def _path_is_in_workspace(self, path):
        workspace = os.path.abspath(self.workspace)
        raw = str(path or ".").strip() or "."
        expanded = os.path.expanduser(os.path.expandvars(raw))
        resolved = (
            os.path.abspath(expanded)
            if os.path.isabs(expanded)
            else os.path.abspath(os.path.join(workspace, expanded))
        )
        try:
            return os.path.commonpath([workspace, resolved]) == workspace
        except ValueError:
            return False

    def _checkpoint_reason(self, tool_name, arguments):
        arguments = arguments if isinstance(arguments, dict) else {}
        if tool_name == "write_file":
            target = str(arguments.get("file_path") or "").strip()
            return f"before write_file {target}"[:200]
        if tool_name == "patch_file":
            target = str(arguments.get("file_path") or "").strip()
            return f"before patch_file {target}"[:200]
        if tool_name in ("delete_path", "make_directory"):
            target = str(arguments.get("path") or "").strip()
            return f"before {tool_name} {target}"[:200]
        if tool_name in ("move_path", "copy_path"):
            source = str(arguments.get("source") or "").strip()
            destination = str(arguments.get("destination") or "").strip()
            return f"before {tool_name} {source} -> {destination}"[:200]
        if tool_name == "powershell":
            command = " ".join(str(arguments.get("command") or "").split())
            return f"before powershell {command}"[:200]
        return f"before {tool_name}"[:200]

    def _powershell_command_may_mutate(self, command):
        command = str(command or "").lower()
        mutating_markers = (
            ">",
            ">>",
            "set-content",
            "add-content",
            "out-file",
            "tee-object",
            "new-item",
            "mkdir",
            "md ",
            "remove-item",
            "rm ",
            "del ",
            "erase ",
            "rmdir",
            "rd ",
            "move-item",
            "mv ",
            "rename-item",
            "ren ",
            "copy-item",
            "cp ",
            "git apply",
            "git checkout",
            "git clean",
            "git reset",
            "git revert",
            "git commit",
            "git merge",
            "git pull",
            "git push",
            "npm install",
            "pnpm install",
            "yarn install",
            "pip install",
        )
        padded = f" {command} "
        return any(marker in padded for marker in mutating_markers)

    def schedule_post_turn_maintenance(
        self,
        user_message,
        assistant_message,
        *,
        messages_snapshot=None,
        on_status=None,
    ):
        """Queue best-effort maintenance work after the user-visible reply."""
        queue = getattr(self, "background_jobs", None)
        if queue is None or not getattr(queue, "enabled", True):
            return self._run_post_turn_maintenance_sync(
                user_message,
                assistant_message,
                messages_snapshot=messages_snapshot,
            )

        conversation_id = getattr(self, "conv_id", None)
        metadata = {
            "conversation_id": conversation_id,
            "model": getattr(self, "model", ""),
            "workspace": getattr(self, "workspace", ""),
        }
        snapshot = (
            copy.deepcopy(messages_snapshot)
            if messages_snapshot is not None
            else copy.deepcopy(getattr(self, "messages", []))
        )
        queued = []

        memory_manager = getattr(self, "memory_manager", None)
        if memory_manager is not None and user_message and assistant_message:
            job = queue.submit(
                "memory_sync",
                lambda: self._sync_memory_turn_now(
                    user_message,
                    assistant_message,
                    metadata,
                ),
                metadata=metadata,
            )
            queued.append(job)

        review_due = getattr(self, "memory_review_due", None)
        review_memory = getattr(self, "review_recent_memory", None)
        if callable(review_due) and callable(review_memory) and review_due():
            job = queue.submit(
                "memory_review",
                lambda: self._run_memory_review_job(snapshot),
                metadata=metadata,
            )
            queued.append(job)

        if on_status and queued:
            try:
                on_status({
                    "type": "background_jobs_queued",
                    "count": len(queued),
                    "names": [job.name for job in queued],
                })
            except Exception:
                pass
        return {"queued": [job.to_dict() for job in queued]}

    def _run_post_turn_maintenance_sync(
        self,
        user_message,
        assistant_message,
        *,
        messages_snapshot=None,
    ):
        metadata = {
            "conversation_id": getattr(self, "conv_id", None),
            "model": getattr(self, "model", ""),
            "workspace": getattr(self, "workspace", ""),
        }
        if getattr(self, "memory_manager", None) is not None:
            self._sync_memory_turn_now(user_message, assistant_message, metadata)
        if self.memory_review_due():
            self.review_recent_memory(messages=messages_snapshot)
        return {"queued": []}

    def _sync_memory_turn_now(self, user_message, assistant_message, metadata):
        memory_manager = getattr(self, "memory_manager", None)
        if memory_manager is None:
            return {"synced": False}
        future = memory_manager.sync_turn(
            user_message,
            assistant_message,
            metadata=dict(metadata or {}),
        )
        if future is not None:
            future.result()
        return {"synced": True}

    def _run_memory_review_job(self, messages_snapshot):
        result = self.review_recent_memory(messages=messages_snapshot)
        saved = result.get("saved", []) if isinstance(result, dict) else []
        errors = result.get("errors", []) if isinstance(result, dict) else []
        summary = {"saved": len(saved)}
        if errors:
            summary["errors"] = len(errors)
        if isinstance(result, dict) and result.get("error"):
            summary["error"] = result.get("error")
        return summary

    def background_jobs_status(self, limit=20):
        queue = getattr(self, "background_jobs", None)
        if queue is None:
            return {
                "enabled": False,
                "text": "Background jobs are not available.",
                "jobs": [],
            }
        status = queue.status(limit=limit)
        return {
            **status,
            "text": self._format_background_jobs_status(status),
        }

    def _format_background_jobs_status(self, status):
        jobs = status.get("jobs", [])
        lines = [
            "Background Jobs",
            (
                f"- pending {status.get('pending_count', 0)} · "
                f"running {status.get('running_count', 0)} · "
                f"failed {status.get('failed_count', 0)}"
            ),
        ]
        if not jobs:
            lines.append("- no jobs yet")
            return "\n".join(lines)

        status_mark = {
            "pending": "·",
            "running": "...",
            "done": "✓",
            "failed": "!",
            "cancelled": "-",
        }
        for job in jobs:
            mark = status_mark.get(job.get("status"), "?")
            duration = int(job.get("duration_ms") or 0)
            summary = job.get("summary") or {}
            summary_text = ""
            if summary:
                summary_text = " · " + ", ".join(
                    f"{key}={value}" for key, value in summary.items()
                )
            if job.get("error"):
                summary_text = f" · error={job['error']}"
            lines.append(
                f"{mark} {job.get('name', '?')} [{job.get('status', '?')}] "
                f"{duration}ms{summary_text}"
            )
        return "\n".join(lines)

    def memory_review_due(self):
        """Record a completed turn and report whether periodic review is due."""
        if self.memory_review_interval <= 0:
            return False
        self._turns_since_memory_review += 1
        return self._turns_since_memory_review >= self.memory_review_interval

    def review_recent_memory(self, messages=None):
        """Review the latest interval of completed turns for durable memories."""
        transcript = self._build_memory_review_transcript(messages)
        self._turns_since_memory_review = 0
        if not transcript:
            return {"saved": []}

        prompt = (
            "你是 Sierra 的长期记忆审查器。判断下面一段近期对话中，是否有值得跨会话长期保存的信息。\n"
            "只返回严格 JSON，不要解释，不要 Markdown。\n"
            "格式: {\"operations\":[{\"action\":\"add|replace|remove\",\"target\":\"user|memory\","
            "\"old_text\":\"替换或删除时填写\",\"content\":\"新增或替换后的内容\"}]}\n\n"
            "保存规则:\n"
            "- target='user': 用户稳定身份、偏好、技能水平、协作习惯、明确要求你记住的信息。\n"
            "- target='memory': 这个项目的稳定事实、架构决策、已完成的重要改动、长期待办。\n"
            "- 新信息补充旧信息时使用 replace，不要再 add 一条含义重复的记忆。\n"
            "- replace/remove 的 old_text 必须取自现有记忆，并能唯一匹配一条记忆。\n"
            "- 只有信息已过期、被明确纠正或不再有效时才 remove。\n"
            "- 只保存用户明确表达或对话中已经确认的信息，不把助手的猜测当作事实。\n"
            "- 不保存临时闲聊、一次性任务、普通事实、搜索结果细节、完整代码、密钥/API key/隐私凭证。\n"
            "- 每条 content 用中文，简短自然，不超过 80 字。\n"
            "- 最多执行 5 个操作；没有需要变更的内容时返回 {\"operations\":[]}。"
        )
        existing_memory = self.memory_manager.get_prompt_context() or "（暂无长期记忆）"
        review_content = (
            "【当前长期记忆】\n"
            f"{existing_memory}\n\n"
            "【近期对话】\n"
            f"{transcript}"
        )

        try:
            response = self.llm.chat([
                {"role": "system", "content": prompt},
                {"role": "user", "content": review_content},
            ])
            self.count_tokens(response["usage"])
            operations = self._parse_memory_operations(response.get("content") or "")
            operation_result = self.memory_manager.apply_operations(operations)
            changes = operation_result.get("changes", [])
            errors = operation_result.get("errors", [])
            if changes:
                self.refresh_system_prompt()
            return {"saved": changes, "errors": errors}
        except Exception as e:
            return {"saved": [], "error": str(e)}

    def _build_memory_review_transcript(self, messages=None):
        turns = []
        current = None

        for message in (messages if messages is not None else self.messages):
            role = message.get("role")
            content = message.get("content")
            if role == "user":
                if current and current.get("assistant"):
                    turns.append(current)
                current = {"user": str(content or ""), "assistant": ""}
            elif role == "assistant" and current and content:
                current["assistant"] = str(content)

        if current and current.get("assistant"):
            turns.append(current)

        recent_turns = turns[-self.memory_review_interval:]
        blocks = []
        used_chars = 0
        for turn in reversed(recent_turns):
            block = (
                f"用户:\n{turn['user'][:1200]}\n"
                f"Sierra:\n{turn['assistant'][:2000]}"
            )
            if blocks and used_chars + len(block) > self.memory_review_max_chars:
                break
            blocks.append(block[:self.memory_review_max_chars])
            used_chars += len(block)

        blocks.reverse()
        return "\n\n---\n\n".join(blocks)

    def sync_memory_review_state(self):
        """Restore the periodic counter after loading or transferring a session."""
        if self.memory_review_interval <= 0:
            self._turns_since_memory_review = 0
        else:
            completed_user_turns = sum(
                1 for message in self.messages if message.get("role") == "user"
            )
            self._turns_since_memory_review = (
                completed_user_turns % self.memory_review_interval
            )

    def _parse_memory_operations(self, text):
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        data = json.loads(raw)
        operations = data.get("operations")
        if isinstance(operations, list):
            return operations

        memories = data.get("memories", [])
        if not isinstance(memories, list):
            return []
        return [
            {
                "action": "add",
                "target": item.get("target", "memory"),
                "content": item.get("content", ""),
            }
            for item in memories
            if isinstance(item, dict)
        ]
    
    def reset(self):
        task_manager = getattr(self, "task_manager", None)
        if task_manager is not None:
            task_manager.pause_active()
            task_manager.bind_conversation(None)
        self.messages = []
        self._turns_since_memory_review = 0
        self.current_context_tokens = 0
        self.context_tokens_estimated = False
        self._ineffective_compression_count = 0
        self._summary_failure_cooldown_until = 0.0

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def update_current_context(self, actual_tokens, estimated_tokens=0):
        actual_tokens = int(actual_tokens or 0)
        if actual_tokens > 0:
            self.current_context_tokens = actual_tokens
            self.context_tokens_estimated = False
            return
        self.current_context_tokens = max(0, int(estimated_tokens or 0))
        self.context_tokens_estimated = self.current_context_tokens > 0

    def refresh_context_estimate(self):
        messages = [{"role": "system", "content": self.system_prompt}] + self.messages
        tools = self.tools.get_definitions()
        self.current_context_tokens = estimate_tokens(messages, tools=tools)
        self.context_tokens_estimated = self.current_context_tokens > 0

    def usage_snapshot(self):
        return {
            "input": self.total_input_tokens,
            "output": self.total_output_tokens,
            "context": self.current_context_tokens,
            "context_window": self.context_window,
            "model_context_window": getattr(self, "model_context_window", self.context_window),
            "context_budget": self.context_window,
            "context_estimated": self.context_tokens_estimated,
            "compression_count": getattr(self, "compression_count", 0),
        }

    def save_conversation(self, usage, title=""):
        self.ensure_conversation_id()
        self.store.save(self.conv_id, self.messages, usage, title)
        self._sync_session_db(usage=usage, title=title)

    def load_conversation(self, conv_id):
        self.conv_id = conv_id
        self.messages, usage = self.store.load(conv_id)
        if not self.messages and self.session_db is not None:
            try:
                self.messages = self.session_db.get_messages(conv_id)
                usage = {}
            except Exception as exc:
                logger.warning("Session database load failed: %s", exc)
        if self.task_manager is not None:
            self.task_manager.bind_conversation(conv_id)
        self._reconcile_uncertain_tool_calls()
        self.sync_memory_review_state()
        if usage:
            self.total_input_tokens = usage.get("input", 0)
            self.total_output_tokens = usage.get("output", 0)
            saved_context = int(usage.get("context", 0) or 0)
            if saved_context > 0:
                self.current_context_tokens = saved_context
                self.context_tokens_estimated = bool(
                    usage.get("context_estimated", False)
                )
            else:
                self.refresh_context_estimate()
        else:
            self.refresh_context_estimate()
        self.refresh_system_prompt()

    def list_conversations(self):
        return self.store.list_all()

    def _bootstrap_session_db_from_json(self):
        if self.session_db is None:
            return
        try:
            conversations = self.store.list_all()
        except Exception as exc:
            logger.warning("Conversation index import skipped: %s", exc)
            return
        for conversation in conversations:
            conv_id = conversation.get("id")
            if not conv_id:
                continue
            try:
                messages, usage = self.store.load(conv_id)
                if not messages:
                    continue
                self.session_db.replace_session(
                    conv_id,
                    messages,
                    title=conversation.get("title", ""),
                    model=self.model,
                    cwd=self.workspace,
                    usage=usage,
                    created_at=conversation.get("created"),
                    updated_at=conversation.get("updated"),
                )
            except Exception as exc:
                logger.warning("Conversation %s import skipped: %s", conv_id, exc)

    def list_sessions(self, limit=20):
        if self.session_db is None:
            return []
        return self.session_db.list_sessions(limit=limit)

    def search_sessions(self, query, limit=10):
        if self.session_db is None:
            return []
        return self.session_db.search_messages(query, limit=limit)

    def load_session(self, session_id):
        if self.session_db is None:
            return {"ok": False, "error": "session database is not enabled"}
        session = self.session_db.get_session(session_id)
        if not session:
            return {"ok": False, "error": f"unknown session: {session_id}"}
        self.conv_id = session_id
        self.messages = self.session_db.get_messages(session_id)
        if self.task_manager is not None:
            self.task_manager.bind_conversation(session_id)
        self._reconcile_uncertain_tool_calls()
        self.sync_memory_review_state()
        self.total_input_tokens = int(session.get("input_tokens", 0) or 0)
        self.total_output_tokens = int(session.get("output_tokens", 0) or 0)
        self.refresh_context_estimate()
        self.refresh_system_prompt()
        return {"ok": True, "session": session, "messages": self.messages}

    def mcp_status(self):
        return self.mcp.status()

    def audit_recent(self, limit=20):
        return self.audit.recent(limit)

    def memory_status(self):
        return {
            "curated": self.memory_manager.get_prompt_context(),
            "providers": self.memory_manager.status(),
        }

    def memory_search(self, query, limit=5):
        return self.memory_manager.search(query, limit=limit)

    def memory_forget(self, memory_id):
        return self.memory_manager.delete(memory_id)

    def memory_clear(self):
        return self.memory_manager.clear()

    def debug_context_status(self):
        turn_context = getattr(self, "last_turn_context", None)
        if turn_context is None:
            return {
                "available": False,
                "summary": {},
                "text": "暂无 TurnContext。先发送一轮普通消息后再查看。",
            }

        summary = turn_context.summary()
        flags = []
        if summary.get("has_memory_context"):
            flags.append(f"memory {summary.get('memory_recall_count', 0)}")
        if summary.get("has_history_context"):
            flags.append(f"history {summary.get('history_recall_count', 0)}")
        if summary.get("has_task_context"):
            flags.append("task_plan")
        if not flags:
            flags.append("none")

        tools = []
        try:
            tools = self.tools.get_definitions()
        except Exception:
            tools = []
        role_counts = {}
        for message in getattr(self, "messages", []):
            role = str(message.get("role") or "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
        blocks = [
            {
                "name": "system_prompt",
                "tokens": estimate_tokens([
                    {"role": "system", "content": getattr(turn_context, "system_prompt", "")}
                ]),
                "note": "persona + model + curated memory + compact skill index",
            },
            {
                "name": "memory_context",
                "tokens": estimate_tokens([
                    {"role": "system", "content": getattr(turn_context, "memory_context", "")}
                ]),
                "note": "per-turn vector recall",
            },
            {
                "name": "history_context",
                "tokens": estimate_tokens([
                    {"role": "system", "content": getattr(turn_context, "history_context", "")}
                ]),
                "note": "session DB recall when the user asks for old context",
            },
            {
                "name": "task_context",
                "tokens": estimate_tokens([
                    {"role": "system", "content": getattr(turn_context, "task_context", "")}
                ]),
                "note": "current plan/checkpoint state",
            },
            {
                "name": "conversation_messages",
                "tokens": estimate_tokens(getattr(self, "messages", [])),
                "note": f"{len(getattr(self, 'messages', []))} persisted messages",
            },
            {
                "name": "tools_schema",
                "tokens": estimate_tokens([], tools=tools),
                "note": f"{len(tools)} callable tools",
            },
        ]
        summary["blocks"] = blocks
        summary["message_roles"] = role_counts
        summary["context_budget"] = getattr(self, "context_window", 0)
        summary["model_context_window"] = getattr(
            self,
            "model_context_window",
            getattr(self, "context_window", 0),
        )

        lines = [
            "TurnContext",
            f"- user: {str(getattr(turn_context, 'user_message', '') or '')[:80]}",
            f"- injected: {', '.join(flags)}",
            f"- estimated tokens: {summary.get('estimated_context_tokens', 0)}",
            (
                f"- budget: {summary['context_budget']} "
                f"(model window {summary['model_context_window']})"
            ),
            "- structure:",
        ]
        for index, block in enumerate(blocks, 1):
            lines.append(
                f"  {index}. {block['name']}: ~{block['tokens']} tokens"
                f" · {block['note']}"
            )
        if role_counts:
            role_text = ", ".join(
                f"{role}={count}" for role, count in sorted(role_counts.items())
            )
            lines.append(f"- message roles: {role_text}")
        lines.extend([
            "- controls:",
            f"  compression threshold: {getattr(self, 'max_compress_tokens', 0)}",
            f"  compression target: {getattr(self, 'compression_target_tokens', 0)}",
            f"  keep recent target: {getattr(self, 'compression_keep_tokens', 0)}",
            (
                "  tool result caps: "
                f"old {getattr(self, 'old_tool_result_max_chars', 0)} chars, "
                f"recent {getattr(self, 'recent_tool_result_max_chars', 0)} chars"
            ),
        ])
        errors = summary.get("errors") or []
        if errors:
            lines.append("- errors:")
            for error in errors:
                lines.append(f"  - {error}")
        return {
            "available": True,
            "summary": summary,
            "text": "\n".join(lines),
        }

    def ensure_conversation_id(self):
        if not self.conv_id:
            self.conv_id = self.store.new_id()
        task_manager = getattr(self, "task_manager", None)
        if task_manager is not None:
            task_manager.bind_conversation(self.conv_id)
        return self.conv_id

    def checkpoint_conversation(self):
        if not self.messages or not hasattr(self, "store"):
            return False
        self.ensure_conversation_id()
        title = next(
            (
                str(message.get("content") or "")[:30]
                for message in self.messages
                if message.get("role") == "user"
            ),
            "",
        )
        try:
            self.store.save(
                self.conv_id,
                self.messages,
                usage=self.usage_snapshot(),
                title=title,
            )
            self._sync_session_db(usage=self.usage_snapshot(), title=title)
            return True
        except Exception as exc:
            logger.warning("Conversation checkpoint failed: %s", exc)
            return False

    def _sync_session_db(self, usage=None, title=""):
        if self.session_db is None or not self.conv_id:
            return False
        try:
            self.session_db.replace_session(
                self.conv_id,
                self.messages,
                title=title,
                model=self.model,
                cwd=self.workspace,
                usage=usage or self.usage_snapshot(),
            )
            return True
        except Exception as exc:
            logger.warning("Session database sync failed: %s", exc)
            return False

    def _reconcile_uncertain_tool_calls(self):
        task_manager = getattr(self, "task_manager", None)
        task = task_manager.recovery_task() if task_manager is not None else None
        uncertain_by_call_id = {
            str(execution.get("tool_call_id") or ""): execution
            for execution in (task or {}).get("uncertain_executions", [])
        }
        existing_tool_ids = {
            str(message.get("tool_call_id") or "")
            for message in self.messages
            if message.get("role") == "tool"
        }
        pending_tool_calls = []
        for message in self.messages:
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = str(tool_call.get("id") or "")
                if not tool_call_id or tool_call_id in existing_tool_ids:
                    continue
                function = tool_call.get("function") or {}
                pending_tool_calls.append({
                    "tool_call_id": tool_call_id,
                    "tool_name": str(function.get("name") or "tool"),
                })

        appended = False
        for pending in pending_tool_calls:
            tool_call_id = pending["tool_call_id"]
            if tool_call_id in existing_tool_ids:
                continue
            execution = uncertain_by_call_id.get(tool_call_id)
            uncertain = execution is not None
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "error": (
                        "工具执行被中断，实际结果不确定"
                        if uncertain
                        else "工具调用在返回结果前中断"
                    ),
                    "tool": (
                        execution.get("tool_name", pending["tool_name"])
                        if execution
                        else pending["tool_name"]
                    ),
                    "status": "uncertain" if uncertain else "interrupted",
                    "recovery": (
                        "先验证外部状态；无法验证时询问用户，不要直接重跑"
                        if uncertain
                        else "该调用没有结果记录；根据任务状态决定是否重新发起"
                    ),
                }, ensure_ascii=False),
            })
            existing_tool_ids.add(tool_call_id)
            appended = True
        if appended:
            self.checkpoint_conversation()

    def task_status(self):
        return self.task_manager.current_task() if self.task_manager is not None else None

    def task_recovery(self, task_id=None):
        if self.task_manager is None:
            return None
        return self.task_manager.recovery_task(task_id)

    def resume_task(self, task_id):
        if self.task_manager is None:
            return {"ok": False, "error": "任务模块未启用"}
        return self.task_manager.resume(task_id)

    def abandon_task(self, task_id):
        if self.task_manager is None:
            return {"ok": False, "error": "任务模块未启用"}
        return self.task_manager.abandon(task_id)

    def close(self, preserve_task=False):
        try:
            if self.task_manager is not None:
                self.task_manager.close(preserve_active=preserve_task)
        finally:
            try:
                self.background_jobs.close(wait=False)
            except Exception:
                pass
            self.tools.unregister("update_plan")
            self.tools.unregister("get_plan")
            self.tools.unregister("resolve_task_execution")
            self.tools.unregister("skill_reload")
            self.tools.unregister("skill_manage")
            self.tools.unregister("skill_usage_stats")
            self.tools.unregister("cron_list")
            self.tools.unregister("cron_add")
            self.tools.unregister("cron_remove")
            self.memory_manager.close()
            self.skill_usage.close()
            self.mcp.close_all()
            if self.session_db is not None:
                self.session_db.close()
    
    def compress_messages(self, force=False, keep_tokens=None):
        """Summarize old complete turns and keep recent turns verbatim."""
        before_messages = len(self.messages)
        before_tokens = estimate_tokens(self.messages)
        now = time.time()
        summary_failure_cooldown_until = getattr(
            self,
            "_summary_failure_cooldown_until",
            0.0,
        )
        if not force and summary_failure_cooldown_until > now:
            return {
                "compressed": False,
                "reason": "summary_failure_cooldown",
                "cooldown_remaining_seconds": int(
                    summary_failure_cooldown_until - now
                ),
                "before_messages": before_messages,
                "after_messages": before_messages,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
            }
        if not force and getattr(self, "_ineffective_compression_count", 0) >= 2:
            return {
                "compressed": False,
                "reason": "ineffective_compression_backoff",
                "before_messages": before_messages,
                "after_messages": before_messages,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "last_savings_ratio": getattr(
                    self,
                    "_last_compression_savings_ratio",
                    0.0,
                ),
            }
        if keep_tokens is None:
            keep_tokens = self.compression_keep_tokens
        pruned_messages, pruned_tool_results = prune_old_tool_results(
            self.messages,
            protect_tail_count=getattr(self, "compression_protect_last_messages", 8),
            max_chars=getattr(self, "old_tool_result_max_chars", 2400),
        )
        if pruned_tool_results:
            self.messages = pruned_messages
        window = select_compaction_window(
            self.messages,
            keep_tokens=keep_tokens,
            protect_first_n=getattr(self, "compression_protect_first_messages", 0),
            protect_last_n=getattr(self, "compression_protect_last_messages", 0),
            force=force,
        )
        if window is None:
            after_tokens = estimate_tokens(self.messages)
            if pruned_tool_results and after_tokens < before_tokens:
                self.refresh_context_estimate()
                result = {
                    "compressed": True,
                    "reason": "pruned_tool_results",
                    "before_messages": before_messages,
                    "after_messages": len(self.messages),
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "pruned_tool_results": pruned_tool_results,
                }
                self._record_compression_result(result)
                return result
            return {
                "compressed": False,
                "reason": "insufficient_history",
                "before_messages": before_messages,
                "after_messages": before_messages,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
            }

        compress_start, compress_end = window
        head_messages = self.messages[:compress_start]
        old_messages = self.messages[compress_start:compress_end]
        recent_messages = self.messages[compress_end:]
        transcript = build_compaction_transcript(
            old_messages,
            max_chars=self.compression_transcript_chars,
        )
        if not transcript:
            return {
                "compressed": False,
                "reason": "empty_transcript",
                "before_messages": before_messages,
                "after_messages": before_messages,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
            }

        summary_prompt = build_compaction_prompt()

        try:
            summary_response = self.llm.chat([
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": transcript},
            ])
            usage = summary_response.get("usage") or {}
            self.count_tokens({
                "input": int(usage.get("input", 0) or 0),
                "output": int(usage.get("output", 0) or 0),
            })
            summary_message = build_summary_message(
                summary_response.get("content") or ""
            )
            compacted_messages = [*head_messages, summary_message, *recent_messages]
            compacted_messages, stripped_media = strip_historical_media(compacted_messages)
            after_tokens = estimate_tokens(compacted_messages)
            if after_tokens >= before_tokens:
                self._ineffective_compression_count = (
                    getattr(self, "_ineffective_compression_count", 0) + 1
                )
                self._last_compression_savings_ratio = 0.0
                return {
                    "compressed": False,
                    "reason": "no_token_savings",
                    "before_messages": before_messages,
                    "after_messages": before_messages,
                    "before_tokens": before_tokens,
                    "after_tokens": before_tokens,
                }

            self.messages = compacted_messages
            self.refresh_context_estimate()
            result = {
                "compressed": True,
                "reason": "compressed",
                "before_messages": before_messages,
                "after_messages": len(self.messages),
                "summarized_messages": len(old_messages),
                "protected_head_messages": len(head_messages),
                "kept_messages": len(recent_messages),
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "pruned_tool_results": pruned_tool_results,
                "stripped_media_messages": stripped_media,
            }
            self._record_compression_result(result)
            return result
        except Exception as exc:
            logger.warning("Context compaction failed: %s", exc)
            failure_cooldown = getattr(
                self,
                "compression_failure_cooldown_seconds",
                0,
            )
            if failure_cooldown:
                self._summary_failure_cooldown_until = (
                    time.time() + failure_cooldown
                )
            fallback_error = ""
            try:
                fallback_summary = build_fallback_summary(old_messages)
                summary_message = build_summary_message(fallback_summary)
                compacted_messages = [*head_messages, summary_message, *recent_messages]
                compacted_messages, stripped_media = strip_historical_media(compacted_messages)
                after_tokens = estimate_tokens(compacted_messages)
                if after_tokens >= before_tokens:
                    self._ineffective_compression_count = (
                        getattr(self, "_ineffective_compression_count", 0) + 1
                    )
                    self._last_compression_savings_ratio = 0.0
                    return {
                        "compressed": False,
                        "reason": "summary_failed",
                        "error": str(exc),
                        "fallback_error": "fallback produced no token savings",
                        "before_messages": before_messages,
                        "after_messages": before_messages,
                        "before_tokens": before_tokens,
                        "after_tokens": before_tokens,
                }
                self.messages = compacted_messages
                self.refresh_context_estimate()
                result = {
                    "compressed": True,
                    "reason": "summary_fallback",
                    "fallback": True,
                    "error": str(exc),
                    "before_messages": before_messages,
                    "after_messages": len(self.messages),
                    "summarized_messages": len(old_messages),
                    "protected_head_messages": len(head_messages),
                    "kept_messages": len(recent_messages),
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "pruned_tool_results": pruned_tool_results,
                    "stripped_media_messages": stripped_media,
                }
                self._record_compression_result(result)
                return result
            except Exception as fallback_exc:
                logger.warning(
                    "Fallback context compaction failed: %s",
                    fallback_exc,
                )
                fallback_error = str(fallback_exc)
            return {
                "compressed": False,
                "reason": "summary_failed",
                "error": str(exc),
                "fallback_error": fallback_error,
                "before_messages": before_messages,
                "after_messages": before_messages,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
            }

    def _record_compression_result(self, result):
        if not result.get("compressed"):
            return
        before = max(1, int(result.get("before_tokens", 0) or 0))
        after = max(0, int(result.get("after_tokens", 0) or 0))
        savings_ratio = max(0.0, (before - after) / before)
        self._last_compression_savings_ratio = savings_ratio
        if savings_ratio < getattr(self, "compression_min_savings_ratio", 0.10):
            self._ineffective_compression_count = (
                getattr(self, "_ineffective_compression_count", 0) + 1
            )
        else:
            self._ineffective_compression_count = 0
        self.compression_count = getattr(self, "compression_count", 0) + 1
        event = {
            "count": self.compression_count,
            "created_at": time.time(),
            "reason": result.get("reason", ""),
            "before_tokens": before,
            "after_tokens": after,
            "savings_ratio": savings_ratio,
            "before_messages": result.get("before_messages", 0),
            "after_messages": result.get("after_messages", 0),
        }
        if not hasattr(self, "compression_events"):
            self.compression_events = []
        self.compression_events.append(event)
        self.compression_events = self.compression_events[-50:]
