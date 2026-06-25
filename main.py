from aiagent.encoding import ensure_utf8_stdio

ensure_utf8_stdio()

from aiagent.agent import Agent
from aiagent.tools.memory_tool import store as memory_store
from aiagent.memory.config import resolve_memory_config
import os
import json

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

LINE = "─" * 54


def main():
    model_cfg = config["models"][config["active_model"]]
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
    )

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
    elif cmd == "/help":
        print("""
/quit       退出
/help       帮助
/new        新对话
/list       对话列表
/load <n>   加载第 n 个对话
/reset      清空
/compress   压缩上下文
/task       查看当前任务计划
/task-cancel 放弃当前任务
/skills     查看技能索引与就绪状态
/skills-reload 重新扫描技能包
/skills-stats 查看技能使用统计
/memory     查看记忆
/audit      查看最近工具审计""")
    elif cmd == "/new":
        _auto_save(agent)
        agent.reset()
        agent.conv_id = None
        print("✅ 已开始新对话")
    elif cmd == "/list":
        convs = agent.list_conversations()
        print("📋 对话列表:")
        for i, c in enumerate(convs, 1):
            print(f"  [{i}] {c['title'][:40]}")
    elif cmd.startswith("/load "):
        arg = cmd.split(" ", 1)[1]
        convs = agent.list_conversations()
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(convs):
                _auto_save(agent)
                agent.load_conversation(convs[idx]["id"])
                print(f"✅ 已加载: {convs[idx]['title'][:40]}")
        else:
            _auto_save(agent)
            agent.load_conversation(arg)
            print(f"✅ 已加载: {arg}")
    elif cmd == "/reset":
        agent.reset()
        agent.conv_id = None
        print("✅ 已清空当前对话")
    elif cmd == "/compress":
        old = len(agent.messages)
        result = agent.compress_messages(force=True)
        if result.get("compressed"):
            print(
                f"🔧 压缩完成: {old} → {len(agent.messages)} 条，"
                f"约 {result['before_tokens']} → {result['after_tokens']} tokens"
            )
        else:
            print("ℹ️ 当前没有可安全压缩的完整历史轮次，消息未改变。")
        _auto_save(agent)
    elif cmd == "/task":
        task = agent.task_status()
        if not task:
            print("当前没有任务计划")
        else:
            print(f"📌 {task.get('objective', '')} [{task.get('status', '')}]")
            for step in task.get("steps", []):
                icon = {
                    "completed": "✓",
                    "in_progress": "›",
                    "pending": "·",
                }.get(step.get("status"), "?")
                print(f"  {icon} {step.get('step', '')}")
    elif cmd == "/task-cancel":
        task = agent.task_status()
        if not task or task.get("status") not in ("active", "interrupted"):
            print("当前没有可放弃的任务")
        else:
            agent.abandon_task(task["id"])
            print("已放弃当前任务")
    elif cmd == "/skills":
        _print_skills(agent.skill_summaries(include_unavailable=True))
    elif cmd == "/skills-reload":
        result = agent.reload_skills()
        print(f"已重新加载 {result['count']} 个技能")
        _print_skills(result["skills"])
        for error in result["errors"]:
            print(f"  ! {error}")
    elif cmd == "/skills-stats":
        _print_skill_stats(agent.skill_usage_stats(limit=20))
    elif cmd == "/memory":
        text = memory_store.get_all_for_prompt()
        print(f"📝 记忆:\n{text}" if text else "📝 暂无记忆")
    elif cmd == "/audit":
        records = agent.audit_recent(20)
        if not records:
            print("暂无工具审计记录")
        for record in records:
            status = "ok" if record.get("success") else "blocked/failed"
            print(
                f"{record.get('timestamp', '')} "
                f"{record.get('tool', '?')} "
                f"[{record.get('decision', '?')}] {status} "
                f"{record.get('duration_ms', 0)}ms"
            )
    else:
        print(f"未知命令: {cmd}")


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
