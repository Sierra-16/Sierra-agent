---
name: github-pr-workflow
description: 当用户要求创建分支、整理提交、推送、创建或检查 GitHub Pull Request、处理 CI、请求评审或合并时使用。优先使用已认证的 gh CLI；所有发布、推送和合并操作遵循 Sierra 权限确认。
---

# GitHub Pull Request 工作流

## 前置检查

1. 使用 `powershell` 检查 `git status --short`、当前分支和远程地址。
2. 检查 `gh --version` 与 `gh auth status`，不要读取 `.git-credentials`、环境文件或打印 token。
3. 确认仓库基线分支及用户期望的 PR 范围。
4. 工作区存在用户未提交改动时，只处理本任务文件，不覆盖或混入无关修改。

## 执行流程

1. 对复杂改动调用 `update_plan`。
2. 在新分支完成代码和测试；分支名使用 `feat/`、`fix/`、`docs/`、`refactor/` 等清晰前缀。
3. 查看 diff，只暂存相关文件，避免无条件 `git add .`。
4. 运行与改动风险匹配的测试、格式和静态检查。
5. 提交信息描述真实行为变化，不声称未运行的测试。
6. 用户明确要求发布时执行 `git push -u origin HEAD`。
7. 使用 `gh pr create` 创建 PR，正文包含 Summary、Testing、风险或迁移说明。
8. 使用 `gh pr checks` / `gh run view --log-failed` 检查 CI；先理解失败原因，再修复和推送。
9. 仅在用户明确要求且检查通过时合并。

## 安全边界

- 不自动提取或拼接 GitHub token；认证缺失时说明并让用户自行完成 `gh auth login`。
- push、创建 PR、评论、关闭、合并、删除分支都属于外部状态变更，必须服从权限确认。
- 不使用强制推送，除非用户明确要求并确认影响。
- CI 最多连续修复三轮；仍失败时汇报根因和阻塞信息。

## PR 正文

```markdown
## Summary
- 真实完成的变化

## Testing
- 实际运行的命令和结果

## Risks
- 风险、迁移或回滚方式
```


