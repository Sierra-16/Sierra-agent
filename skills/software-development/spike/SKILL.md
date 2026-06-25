---
name: spike
description: "快速探索——写一次性代码验证可行性，得出验证/不通过/部分可用的结论，不写正式代码。"
version: 1.0.0
author: Sierra (adapted from Hermes Agent / GSD)
license: MIT
metadata:
  sierra:
    triggers: ["spike", "探索", "试试", "验证", "原型", "prototype", "能不能", "可行性", "试一下"]
---

# Spike — 快速技术探索

用一次性代码验证想法。Spike 的目的是**得出证据支持的结论**，不是写生产代码。

**核心原则:** 验证完就扔。Spike 的价值在于它给你的信息，不在于它产生的代码。

## 适用场景

- "用这个库试试能不能跑通"
- "这两种方案哪个更好？"
- "这个技术栈能不能实现我的需求？"
- "做正式开发之前先摸清坑"

## 不适用场景

- 查文档就能回答 → 直接搜索，不用写代码
- 已经验证过 → 直接实现
- 生产代码 → 用 plan 技能

## 核心流程

```
拆解 → 研究 → 构建 → 结论
  ↑________________________________↓
          循环迭代
```

### 1. 拆解

把想法拆成 2-5 个独立的可行性问题。按风险排序——最可能杀死想法的最先验证：

| # | Spike | 验证问题 | 风险 |
|---|-------|---------|------|
| 001 | websocket-streaming | WebSocket 连接下 LLM 流能否 <100ms 到达？ | 高 |
| 002a | pdf-parse-libA | libA 能否提取中文 PDF？ | 中 |
| 002b | pdf-parse-libB | libB 能否提取中文 PDF？ | 中 |

对比类型用相同编号 + 字母后缀。

### 2. 研究（每个 spike 开始前）

1. 写 2-3 句概要：这个 spike 是什么、为什么重要
2. 对比可选方案：

| 方案 | 工具/库 | 优点 | 缺点 | 维护状态 |
|------|--------|------|------|---------|
| A | ... | ... | ... | 活跃/停滞 |
| B | ... | ... | ... | 活跃/停滞 |

3. 选一个（或两个都做对比）
4. 纯逻辑无外部依赖的跳过

用 Sierra 工具做研究：
- `web_search("python websocket streaming 方案")`
- `web_fetch("库的文档 URL")`

### 3. 构建

一个 spike 一个目录，保持独立：

```
spikes/
├── 001-websocket-streaming/
│   ├── README.md
│   └── main.py
├── 002a-pdf-parse-libA/
│   └── parse.py
└── 002b-pdf-parse-libB/
    └── parse.py
```

**构建原则:**
- 优先产出可交互的结果（CLI、最小网页、能跑的测试），而不是只 print 一行
- 深入测试边界情况，不要只跑 happy path
- 硬编码一切，不搞配置系统、不写 Docker
- 对比类型（002a/002b）前后脚构建，然后面对面比较

**典型构建流程:**
```
write_file("spikes/001-xxx/README.md", "# 001: X 可行性...")
write_file("spikes/001-xxx/main.py", "...")
terminal("cd spikes/001-xxx && python main.py")
# 观察输出，迭代
```

### 4. 结论

每个 spike 的 README.md 末尾：

```markdown
## 结论: ✅ 验证通过 | ⚠️ 部分可行 | ❌ 不可行

### 有效的
- ...

### 无效的
- ...

### 意外发现
- ...

### 对正式开发的建议
- ...
```

- **✅ 验证通过** = 核心问题得到了肯定的回答，有证据
- **⚠️ 部分可行** = 在约束 X、Y、Z 下可以，记录约束
- **❌ 不可行** = 不行，原因是。这也是成功的 spike。

## 对比 Spike（002a vs 002b）

```markdown
## 面对面比较: libA vs libB

| 维度 | libA | libB |
|------|------|------|
| 中文提取质量 | 9/10 | 7/10 |
| 安装复杂度 | pip install, 1 行 | pip + 额外依赖 |
| 100 页 PDF 耗时 | 3s | 18s |

**结论:** 选 libA。如果之后需要表格提取再考虑 libB。
```
