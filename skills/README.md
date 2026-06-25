# Sierra Skill System

Skill 是按需加载的能力包。系统提示词只注入紧凑索引；模型决定采用某个 skill 后，才读取完整规则和相关资源，避免每轮对话携带全部内容。索引采用与 Hermes 相同的模型语义选择方式，不使用关键词分数替模型做最终判断。

## 目录结构

```text
skills/
  <category>/
    <skill-name>/
      SKILL.md
      references/   # 按需读取的规范、知识和检查表
      templates/    # 含 {{variable}} 占位符的文本模板
      scripts/      # 可执行的 .py、.ps1、.js 脚本
      assets/       # 图片、示例数据等静态素材
```

目录名必须与 frontmatter 中的 `name` 一致。`name` 只能包含小写字母、数字和连字符。

```markdown
---
name: example-skill
description: 说明何时使用以及它能解决什么问题。
metadata:
  sierra:
    triggers: [示例, example]
    platforms: [windows]
    prerequisites:
      commands: [python]
---

# Example Skill

写清工作流程、工具选择、验证步骤和输出要求。
```

## 模型工具

- `skills_list`：按分类或关键词查看元数据，不加载完整正文。
- `skill_view`：分页读取 `SKILL.md` 或四个资源目录中的 UTF-8 文本。
- `skill_render_template`：替换模板中的 `{{variable}}`，并报告未填变量。
- `skill_run_script`：执行 skill 自带脚本；始终按高风险操作向用户确认并写入审计日志。
- `skill_reload`：重新扫描、校验技能并刷新系统提示词。
- `skill_manage`：创建、更新或删除技能及资源；始终按高风险操作确认。
- `skill_usage_stats`：读取当前工作区的 Skill 加载率、成功率和分类调用次数。

TUI 中使用 `/skills` 查看当前能力包，使用 `/skills-reload` 加载磁盘上的修改，使用 `/skills-stats` 查看使用统计。

## 紧凑索引

在 `config.json` 中配置 Skill 的 offer-time 行为：

```json
{
  "skills": {
    "disabled": [],
    "compact_categories": [],
    "active_environments": [],
    "description_max_chars": 280,
    "telemetry": {
      "enabled": true,
      "path": "logs/skill_usage.sqlite3",
      "store_queries": true,
      "max_query_chars": 1000
    }
  }
}
```

- `disabled`：不向模型展示且不允许加载的 Skill 名称。
- `compact_categories`：分类仍展示所有 Skill 名称，但省略描述。适合 Skill 较多时压缩当前非重点领域。
- `active_environments`：只展示与当前运行环境相符的条件 Skill；空列表表示不按环境过滤。
- `description_max_chars`：限制索引中单条描述的长度，不影响 `SKILL.md` 正文。

`platforms`、`metadata.sierra.conditions.requires_tools` 和 `fallback_for_tools` 会在构建索引时检查。缺少 `prerequisites.commands` 或环境变量的 Skill 仍会展示，但状态为 `setup_needed`，脚本在依赖补齐前不会执行。

## 使用追踪与评测

每轮对话记录一个 turn；`skill_view`、模板渲染和脚本执行作为事件关联到该 turn。记录不包含 Skill 正文、模板内容或脚本输出。用户问题会先进行密钥脱敏并截断；不希望保存问题文本时将 `store_queries` 设为 `false`，此时统计仍可用，但无法进行查询级召回评测。

执行离线评测：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_skill_usage.py
```

评测用例位于 `tests/fixtures/skill_selection_cases.json`。依次把其中的 `query` 原样发送给 Sierra 后再次运行脚本，可查看索引覆盖率、运行轨迹覆盖率、precision、recall、精确匹配率和误选结果。加入 `--strict` 可在覆盖不足或选择不精确时返回非零退出码。

也可以直接调用当前模型进行无副作用的实时选择测试：

```powershell
.\.venv\Scripts\python.exe scripts\run_live_skill_eval.py --output logs\skill_eval_latest.json
```

实时 runner 只允许执行 `skills_list` 和 `skill_view`。模型一旦请求 PowerShell、文件、网络、MCP 或其他工具，runner 会记录该工具并立即停止，不执行其参数。

## 安全边界

- 资源路径不接受绝对路径、`..` 或逃逸 skill 目录的链接。
- 单个资源最多 512 KiB，单个 `SKILL.md` 最多 256 KiB。
- 脚本使用参数数组执行，不经过 shell 拼接，最长运行 120 秒。
- 脚本只继承有限的系统环境变量，不自动暴露 API key、token 等凭据。
- 模板渲染只返回文本；保存结果仍需单独调用 `write_file` 并确认。
