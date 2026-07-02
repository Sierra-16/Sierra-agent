from aiagent.encoding import ensure_utf8_stdio

ensure_utf8_stdio()

from aiagent.agent import Agent
from aiagent.tools.memory_tool import store as memory_store
from aiagent.memory.config import resolve_memory_config
from aiagent.auxiliary_config import resolve_auxiliary_config
from aiagent.config_validation import (
    StartupConfigError,
    format_config_issues,
    load_and_validate_config,
)
import os
import sys

SIERRA_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(SIERRA_DIR, "config.json")

try:
    config = load_and_validate_config(CONFIG_PATH)
except StartupConfigError as exc:
    print(format_config_issues(exc.issues), file=sys.stderr)
    raise SystemExit(2)

LINE = "─" * 54


def main():
    model_cfg = config["models"][config["active_model"]]

    # ── 欢迎横幅 ──
    logo = "\n".join([
        " ███████╗██╗███████╗██████╗ ██████╗  █████╗",
        " ██╔════╝██║██╔════╝██╔══██╗██╔══██╗██╔══██╗",
        " ███████╗██║█████╗  ██████╔╝██████╔╝███████║",
        " ╚════██║██║██╔══╝  ██╔══██╗██╔══██╗██╔══██║",
        " ███████║██║███████╗██║  ██║██║  ██║██║  ██║",
        " ╚══════╝╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝",
    ])
    print(logo)
    print(f"\n🤖 模型: {model_cfg['name']}    📂 工作区: {os.getcwd()}")
    print(LINE)
    # ── 确认工作区 ──
    cwd = os.getcwd()
    print(f"📂 当前工作区: {cwd}")
    path = input("按 Enter 确认，或输入新路径: ").strip()
    if path:
        try:
            os.chdir(path)
            print(f"📂 已切换到: {os.getcwd()}")
        except Exception as e:
            print(f"❌ 无法切换: {e}")
            print(f"📂 使用当前目录: {cwd}")
    print(LINE)

    agent = Agent(
        model=model_cfg["name"],
        base_url=model_cfg["base_url"],
        api_key=model_cfg["api_key"],
        max_tokens=model_cfg.get("max_tokens", 4096),
        temperature=model_cfg.get("temperature", 0.7),
        context_window=model_cfg.get("context_window", 1000000),
        permission_config=config.get("permissions", {}),
        audit_config=config.get("audit", {}),
        memory_config=resolve_memory_config(config),
        task_config=config.get("tasks", {}),
        skill_config=config.get("skills", {}),
        session_config=config.get("sessions", {}),
        background_config=config.get("background_jobs", {}),
        context_config=config.get("context", {}),
        cron_config=config.get("cron", {}),
        checkpoint_config=config.get("checkpoints", {}),
        tools_config=config.get("tools", {}),
        auxiliary_config=resolve_auxiliary_config(config),
        workspace=os.getcwd(),
        sierra_dir=SIERRA_DIR,
    )

    # ── 自动恢复上次对话 ──
    convs = agent.list_conversations()
    if convs:
        agent.load_conversation(convs[0]["id"])
        title = ""
        for m in agent.messages:
            if m["role"] == "user":
                title = m["content"][:30]
        print(f"📋 上次询问: {title}")
        print(f"💡 输入 /help 查看命令    Ctrl+C 退出")
        print(LINE)
    else:
        print("💡 输入 /help 查看命令    Ctrl+C 退出")
        print(LINE)

    recovery_task = agent.task_recovery()
    if recovery_task:
        completed = sum(
            step.get("status") == "completed"
            for step in recovery_task.get("steps", [])
        )
        print(
            f"⏸ 发现未完成任务: {recovery_task.get('objective', '')} "
            f"({completed}/{len(recovery_task.get('steps', []))})"
        )
        uncertain = recovery_task.get("uncertain_executions", [])
        if uncertain:
            print(f"⚠️ 有 {len(uncertain)} 个工具调用结果不确定，恢复后需要先验证。")
        answer = input("继续上次任务？[Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            agent.resume_task(recovery_task["id"])
            print("✅ 已恢复任务")
        else:
            agent.abandon_task(recovery_task["id"])
            print("已放弃上次任务")

    # ── 交互循环 ──
    try:
        while True:
            user_input = input("👤 你: ")
            if user_input.startswith("/"):
                _handle_command(user_input, agent)
                continue
            agent.chat(
                user_input,
                on_tool_approval=_confirm_tool_call,
                on_user_input=_request_user_input,
            )
            print()
            total = agent.total_input_tokens + agent.total_output_tokens
            context_window = model_cfg.get("context_window", 1000000)
            msg_tokens = agent.current_context_tokens
            pct = msg_tokens / context_window * 100
            estimate_mark = "~" if agent.context_tokens_estimated else ""
            print(
                f"📊 当前上下文: {estimate_mark}{msg_tokens} / {context_window} "
                f"({pct:.1f}%)  |  累计消耗: {total} tokens"
            )
            _auto_save(agent)
    except KeyboardInterrupt:
        _auto_save(agent)
        agent.close()
        print(f"\n\n👋 再见。")


def _handle_command(cmd, agent):
    if cmd in ("/quit", "/exit"):
        _auto_save(agent)
        agent.close()
        exit(0)
    if cmd == "/help":
        print("""
/quit, /exit          exit
/help                 show commands
/new, /reset          start a new conversation
/list                 list saved conversations
/load <n|id>          load a saved conversation
/sessions             list SQLite sessions
/session-search <q>   search session history
/session-load <id>    load a SQLite session
/undo [n]             undo recent user turns
/retry                retry the previous user turn
/compress             compress conversation history
/task                 show current task plan
/task-cancel          abandon current task
/debug-context        show last TurnContext summary
/jobs                 show background jobs
/cron                 list scheduled reminders
/cron-add <min> <p>   add scheduled reminder
/cron-remove <id>     remove scheduled reminder
/skills               list skills
/skills-reload        reload skills
/skills-stats         show skill stats
/memory               show curated memory
/audit                show recent tool audit
""")
        return
    if cmd in ("/new", "/reset"):
        _auto_save(agent)
        agent.reset()
        agent.conv_id = None
        print("started a new conversation")
        return
    if cmd == "/list":
        for index, conv in enumerate(agent.list_conversations(), 1):
            print(f"[{index}] {conv['title'][:60]}  {conv['id']}")
        return
    if cmd.startswith("/load "):
        arg = cmd.split(" ", 1)[1].strip()
        convs = agent.list_conversations()
        conv_id = arg
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(convs):
                conv_id = convs[idx]["id"]
        _auto_save(agent)
        agent.load_conversation(conv_id)
        print(f"loaded {conv_id}")
        return
    if cmd == "/sessions":
        for session in agent.list_sessions(limit=20):
            print(f"{session.get('id')} · {session.get('message_count', 0)} messages · {session.get('title') or '(untitled)'}")
        return
    if cmd.startswith("/session-search "):
        for result in agent.search_sessions(cmd.split(" ", 1)[1].strip(), limit=10):
            snippet = " ".join(str(result.get("snippet") or result.get("content") or "").split())
            print(f"{result.get('session_id')} · {result.get('role')}\n  {snippet[:220]}")
        return
    if cmd.startswith("/session-load "):
        _auto_save(agent)
        result = agent.load_session(cmd.split(" ", 1)[1].strip())
        print("loaded" if result.get("ok") else result.get("error", "load failed"))
        return
    if cmd.startswith("/undo"):
        parts = cmd.split()
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        result = agent.undo_last_turn(count)
        print(
            f"undid {result.get('removed_user_turns', count)} turn(s)"
            if result.get("ok") else result.get("error", "nothing to undo")
        )
        return
    if cmd == "/retry":
        result = agent.retry_last_turn()
        if not result.get("ok"):
            print(result.get("error", "nothing to retry"))
            return
        print("retrying previous turn...")
        agent.chat(
            result.get("user_message", ""),
            on_tool_approval=_confirm_tool_call,
            on_user_input=_request_user_input,
        )
        _auto_save(agent)
        return
    if cmd == "/compress":
        result = agent.compress_messages(force=True)
        print("compressed" if result.get("compressed") else result.get("reason", "unchanged"))
        _auto_save(agent)
        return
    if cmd == "/task":
        task = agent.task_status()
        if not task:
            print("no active task")
        else:
            print(f"{task.get('objective', '')} [{task.get('status', '')}]")
            for step in task.get("steps", []):
                print(f"- {step.get('status')}: {step.get('step')}")
        return
    if cmd == "/task-cancel":
        task = agent.task_status()
        if task and task.get("status") in ("active", "interrupted"):
            agent.abandon_task(task["id"])
            print("task abandoned")
        else:
            print("no active task")
        return
    if cmd == "/debug-context":
        print(agent.debug_context_status().get("text", "no TurnContext"))
        return
    if cmd == "/jobs":
        print(agent.background_jobs_status().get("text", "no background jobs"))
        return
    if cmd == "/cron":
        status = agent.cron_status()
        tasks = status.get("tasks", [])
        if not status.get("enabled"):
            print("cron disabled")
        elif not tasks:
            print("no scheduled reminders")
        else:
            for task in tasks:
                print(f"{task.get('id')} · every {task.get('interval_minutes')} min · {task.get('prompt')}")
        return
    if cmd.startswith("/cron-add "):
        rest = cmd.split(" ", 1)[1].strip()
        pieces = rest.split(" ", 1)
        if len(pieces) != 2 or not pieces[0].isdigit():
            print("usage: /cron-add <minutes> <prompt>")
        else:
            result = agent.cron_add(pieces[1], int(pieces[0]))
            print("created" if result.get("ok") else result.get("error", "failed"))
        return
    if cmd.startswith("/cron-remove "):
        result = agent.cron_remove(cmd.split(" ", 1)[1].strip())
        print("removed" if result.get("ok") else "not found")
        return
    if cmd == "/skills":
        _print_skills(agent.skill_summaries(include_unavailable=True))
        return
    if cmd == "/skills-reload":
        result = agent.reload_skills()
        print(f"reloaded {result['count']} skills")
        _print_skills(result["skills"])
        for error in result["errors"]:
            print(f"! {error}")
        return
    if cmd == "/skills-stats":
        _print_skill_stats(agent.skill_usage_stats(limit=20))
        return
    if cmd == "/memory":
        text = memory_store.get_all_for_prompt()
        print(text if text else "no memory")
        return
    if cmd == "/audit":
        for record in agent.audit_recent(20):
            status = "ok" if record.get("success") else "blocked/failed"
            print(f"{record.get('timestamp', '')} {record.get('tool', '?')} [{record.get('decision', '?')}] {status}")
        return
    print(f"unknown command: {cmd}")
def _print_skills(skills):
    current_category = None
    for skill in skills:
        if skill["category"] != current_category:
            current_category = skill["category"]
            print(f"\n[{current_category}]")
        status = skill.get("readiness_status", "available")
        mark = "+" if status == "available" else "!" if status == "setup_needed" else "-"
        reason = skill.get("readiness_reason")
        suffix = f" - {reason}" if reason else ""
        print(f"  {mark} {skill['name']} [{status}]{suffix}")


def _print_skill_stats(stats):
    if not stats.get("enabled"):
        print("Skill 使用追踪未启用")
        return
    load_rate = stats.get("skill_load_rate")
    success_rate = stats.get("success_rate")
    print(
        f"Skill 使用统计: {stats.get('total_turns', 0)} turns · "
        f"{stats.get('total_events', 0)} events"
    )
    print(
        "加载率 " + (f"{load_rate:.1%}" if load_rate is not None else "暂无")
        + " · 成功率 "
        + (f"{success_rate:.1%}" if success_rate is not None else "暂无")
    )
    for item in stats.get("skills", []):
        print(
            f"  {item['skill_name']}: view {item['views']} · "
            f"template {item['renders']} · script {item['script_runs']} · "
            f"failed {item['failures']}"
        )


def _confirm_tool_call(request):
    print("\n⚠️  工具调用需要确认")
    print(f"工具: {request.get('name', 'tool')}")
    print(f"风险: {request.get('risk', 'medium')}")
    print(f"原因: {request.get('reason', '')}")
    print(f"参数:\n{request.get('arguments', '{}')}")
    answer = input("是否允许执行？[y=本次/a=本会话/N=拒绝]: ").strip().lower()
    if answer == "y":
        return "once"
    if answer == "a":
        return "session"
    return "deny"


def _request_user_input(request):
    question = request.get("question", "请补充你的需求")
    options = request.get("options", [])
    allow_free_text = request.get("allow_free_text", True)

    print(f"\n❓ {question}")
    for index, option in enumerate(options, 1):
        description = option.get("description", "")
        suffix = f" - {description}" if description else ""
        print(f"  [{index}] {option.get('label', '')}{suffix}")

    while True:
        prompt = "选择编号"
        if allow_free_text:
            prompt += "或输入其他需求"
        answer = input(f"{prompt}，直接回车取消: ").strip()
        if not answer:
            return {"cancelled": True}
        if answer.isdigit():
            index = int(answer) - 1
            if 0 <= index < len(options):
                option = options[index]
                return {
                    "value": option.get("value") or option.get("label", ""),
                    "label": option.get("label", ""),
                    "free_text": False,
                    "cancelled": False,
                }
        if allow_free_text:
            return {
                "value": answer,
                "label": answer,
                "free_text": True,
                "cancelled": False,
            }
        print("请输入有效的选项编号。")


def _auto_save(agent):
    if not agent.messages:
        return
    title = ""
    for m in agent.messages:
        if m["role"] == "user":
            title = m["content"][:30]
    agent.save_conversation(usage=agent.usage_snapshot(), title=title)


if __name__ == "__main__":
    main()
