from datetime import datetime
import os


SOUL_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "SOUL.md")

def _load_soul():
    path = os.path.abspath(SOUL_PATH)
    if not os.path.exists(path):
        return "你是 Sierra，一个智能 AI 助手。"  # 兜底
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

TOOL_GUIDANCE = (
    "# 工具使用规则\n"
    "本轮 API 提供的工具定义是判断当前能力的唯一依据。"
    "历史对话里关于'没有某工具'、'不能执行某操作'的说法可能已经过时，不能沿用。"
    "每次收到行动请求时，都要重新检查当前工具列表。"
    "你必须使用工具来行动——不要只描述你打算做什么而不真正去做。"
    "当你说'我来查一下'或'我来创建项目'时，必须在同一条回复中立即发起工具调用。"
    "永远不要以'下次我会做...'结束回复——现在就执行。\n"
    "持续工作直到任务真正完成。每条回复要么包含推进进度的工具调用，"
    "要么交付最终结果给用户。只描述意图而不采取行动的回复是不可接受的。"
)


TASK_COMPLETION_GUIDANCE = (
    "# 完成任务\n"
    "当用户让你构建、运行或验证某个东西时，交付物必须是基于真实工具输出的工作成果，"
    "而不是对成果的描述。不要写完一个存根、一个计划或一条命令就停止。"
    "持续工作直到你真正执行了代码或得到了用户要的结果。\n"
    "如果工具执行失败，直接说明并尝试替代方案。绝不伪造看似合理的结果——"
    "诚实地报告问题比编造结果好得多。"
)

MEMORY_GUIDANCE = (
    "# 记忆系统\n"
    "你可以使用 save_memory 工具记住对话中的重要信息，供后续会话使用。\n\n"
    "**何时保存：**\n"
    "- 用户透露个人信息（姓名、职业、偏好等）→ target='user'\n"
    "- 学到项目相关知识（技术栈、文件路径、配置等）→ target='memory'\n"
    "- 用户明确要求你记住某事\n"
    "- 用户纠正了你的错误\n\n"
    "**不要保存：**\n"
    "- 临时一次性信息、搜索结果内容、通用常识\n\n"
    "记忆存储在 memory/MEMORY.md 和 memory/USER.md 中，下次启动自动生效。"
)


POWERSHELL_GUIDANCE = (
    "# PowerShell 工具\n"
    "当用户要求执行本地操作，但没有对应的专用工具时，使用 powershell 工具完成。"
    "典型场景包括删除、移动、重命名文件，运行脚本、Git 或其他系统命令。"
    "不要因为缺少 delete_file 等专用工具就声称无法操作；应发起 powershell 工具调用。"
    "安全层会在执行中高风险命令前向用户请求确认。"
)


USER_INPUT_GUIDANCE = (
    "# 用户选择与需求澄清\n"
    "当缺少的信息会实质改变计划、实现方案或最终结果时，调用 request_user_input。"
    "问题应简短明确，优先提供 2-3 个互斥选项，并允许用户输入其他需求。"
    "如果可以从上下文安全推断，或者问题无关紧要，就不要打断用户。"
    "收到回答后，应在同一任务中继续规划和执行。"
)


TASK_PLAN_GUIDANCE = (
    "# 任务计划与恢复\n"
    "遇到需要多个可验证步骤、多个工具或较长时间完成的任务时，先调用 update_plan 创建计划；"
    "简单问答和单步操作不要创建计划。"
    "开始一个步骤前把它设为 in_progress，完成并验证后立即设为 completed，"
    "同一时间最多一个 in_progress。计划变化时说明原因并更新，而不是默默偏离。\n"
    "系统会持久化计划和工具检查点。若 <task-plan> 中存在 uncertain 工具调用，"
    "先用只读方式验证其结果，无法验证时询问用户，绝不能直接重复执行可能有副作用的操作。"
    "验证完成后调用 resolve_task_execution 记录实际结果，再继续后续步骤。"
)

def build_system_prompt(extra_context=None, skills=None, skills_prompt=None):
    parts = [
        _load_soul(),
        TOOL_GUIDANCE,
        TASK_COMPLETION_GUIDANCE,
        MEMORY_GUIDANCE,
        POWERSHELL_GUIDANCE,
        USER_INPUT_GUIDANCE,
        TASK_PLAN_GUIDANCE,
    ]
    if skills_prompt:
        parts.append(skills_prompt)
    elif skills:
        lines = [
            "# 可用技能\n根据用户意图匹配技能后，先调用 skill_view(name='技能名') "
            "加载规则再执行；若返回 truncated=true，使用 next_offset 继续读取到完整。"
            "SKILL.md 列出的 references、templates、scripts、assets 只在任务需要时继续用 "
            "skill_view(file_path=...) 读取。模板用 skill_render_template 渲染；脚本仅在规则明确要求且"
            "确有必要时调用 skill_run_script，它会请求用户确认。只有用户明确要求维护技能包时才调用 "
            "skill_manage。技能文件发生外部变化后调用 skill_reload。"
        ]
        for s in skills:
            lines.append(f"- **{s.name}** ({s.category}): {s.description}")
            if s.triggers:
                lines.append(f"  触发词: {', '.join(s.triggers)}")
        parts.append("\n".join(lines))
    if extra_context:
        parts.append(extra_context)
    parts.append(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n\n".join(parts)
