---
name: code-review
description: "当用户要求审查代码、diff、提交或代码修改，查找 bug、行为回归、安全与性能问题、缺少的测试，并给出具体文件行号反馈时使用。"
version: 1.0.0
author: Sierra (adapted from Hermes Agent)
license: MIT
metadata:
  sierra:
    triggers: ["review", "审查", "看看代码", "检查这段", "code review", "帮我看下", "审阅"]
---

# 代码审查

你正在审查代码。系统性地检查，给出具体到行号的反馈。

**核心原则:** 不确定的地方标"[建议]"，确定的问题标"[严重]"。

## 适用场景

- 实现功能或修 bug 之后
- 用户说"看看"、"检查"、"审查"
- 完成了涉及多个文件的改动
- 跳过: 纯文档改动、纯配置修改

## 第一步 — 获取改动

```bash
git diff --cached
```

如果为空，尝试 `git diff` 再 `git diff HEAD~1 HEAD`。

如果 `git diff --cached` 为空但 `git diff` 有内容，告诉用户先 `git add <files>`。

如果 diff 超过 15,000 字符，按文件拆分：
```bash
git diff --name-only
git diff HEAD -- specific_file.py
```

## 第二步 — 静态安全扫描

扫描新增行。任何匹配都是安全关注点：

```bash
# 硬编码密钥
git diff --cached | grep "^+" | grep -iE "(api_key|secret|password|token|passwd)\s*=\s*['\"][^'\"]{6,}['\"]"

# Shell 注入
git diff --cached | grep "^+" | grep -E "os\.system\(|subprocess.*shell=True"

# 危险的 eval/exec
git diff --cached | grep "^+" | grep -E "\beval\(|\bexec\("

# 不安全的反序列化
git diff --cached | grep "^+" | grep -E "pickle\.loads?\("

# SQL 注入
git diff --cached | grep "^+" | grep -E "execute\(f\"|\.format\(.*SELECT|\.format\(.*INSERT"
```

## 第三步 — 自审清单

- [ ] 无硬编码密钥、API Key 或凭证
- [ ] 用户输入有验证
- [ ] SQL 查询使用参数化
- [ ] 文件操作验证了路径
- [ ] 外部调用有错误处理
- [ ] 无残留的 debug print / console.log
- [ ] 无被注释掉的代码
- [ ] 新代码有测试覆盖

## 第四步 — 逐文件审查

对每个改动的文件：

1. `read_file` 读完整文件获取上下文
2. 逐段检查改动
3. 按维度验证

### 审查维度

**1. 正确性**
- 逻辑有没有 bug
- 边界条件是否处理（空值、大数据量、并发）
- 错误路径是否优雅降级

**2. 安全性**
- 无硬编码凭证
- 输入验证
- SQL 注入、XSS、路径遍历防护
- 权限检查是否完备

**3. 代码质量**
- 命名是否清晰表达意图
- 无不必要的复杂度
- 函数是否专注单一职责
- 无重复逻辑

**4. 性能**
- 无 N+1 查询或多余循环
- 无重复的网络/磁盘 IO
- 无阻塞操作在异步路径中

## 输出格式

```
## 代码审查总结

### 🔴 严重
- **文件:行号** — 问题描述
  建议: 修复方案

### ⚠️ 警告
- **文件:行号** — 问题描述
  建议: 修复方案

### 💡 建议
- **文件:行号** — 建议

### ✅ 看起来不错
- 值得肯定的地方
```

## Python 常见问题参考

```python
# Bad: SQL 注入
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# Good: 参数化
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# Bad: Shell 注入
os.system(f"ls {user_input}")
# Good: 安全的 subprocess
subprocess.run(["ls", user_input], check=True)

# Bad: 密码明文
password = "admin123"
# Good: 从环境变量读取
password = os.getenv("DB_PASSWORD")
```

## JavaScript 常见问题参考

```javascript
// Bad: XSS
element.innerHTML = userInput;
// Good: 安全的
element.textContent = userInput;
```
