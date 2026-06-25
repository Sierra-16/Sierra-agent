---
name: sierra-skill-authoring
description: 当用户要求为 Sierra 新建、迁移、修改或审查 SKILL.md，设计触发描述、工作流和工具映射时使用。生成仓库内可被 SkillLoader 加载的简洁技能，并完成本地校验。
---

# Sierra Skill 编写

## 放置与格式

将技能放在：

```text
skills/<category>/<skill-name>/SKILL.md
```

目录名和 `name` 使用小写字母、数字与连字符。Frontmatter 只要求：

```yaml
---
name: skill-name
description: 说明能力，以及哪些用户请求应触发它。
---
```

description 是路由依据，要同时写清“做什么”和“何时使用”。触发信息不要只放在正文，因为模型加载正文之前只能看到 metadata。

## 流程

1. 阅读目标分类下 2-3 个现有技能，避免重复或冲突。
2. 列出 Sierra 当前真实工具，删除来源技能中的专属 CLI、路径、账号和不存在的工具。
3. 保留模型不容易稳定记住的流程、边界、失败处理和验证要求。
4. 正文使用命令式表达，控制长度；长参考资料放入同目录 `references/`，并在正文说明何时读取。
5. 使用 `write_file` 创建或更新文件。
6. 运行 loader 与测试，检查重复名称、分类、正文和分页读取。

## Sierra 适配规则

- 文件操作使用 `read_file`、`write_file`、`search_files`、`list_directory`。
- 本地命令使用 `powershell`，并接受权限确认。
- 多步骤执行使用 `update_plan`，不要用 skill 模拟另一套任务状态。
- 缺少关键信息使用 `request_user_input`。
- 外部能力优先使用当前可用 MCP；不要硬编码某个服务器一定存在。
- 新技能在 Agent 创建时加载，当前已运行进程需要重新启动才能看到。

## 校验

```powershell
.\.venv\Scripts\python.exe -c "from aiagent.skills.loader import SkillLoader; loader=SkillLoader(); skills=loader.load(); print(len(skills)); print(*loader.errors, sep='\n')"
.\.venv\Scripts\python.exe -m unittest tests.test_skill_loader -v
```

确认名称唯一、分类正确、`loader.errors` 为空，并通过 `skill_view` 完整读取正文。

