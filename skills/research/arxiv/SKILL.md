---
name: arxiv
description: "搜索 arXiv 学术论文——按关键词、作者、分类或 ID 检索。"
version: 1.0.0
author: Sierra (adapted from Hermes Agent)
license: MIT
metadata:
  sierra:
    triggers: ["arxiv", "论文", "paper", "学术", "研究论文", "文献"]
---

# arXiv 学术搜索

通过 arXiv 免费 API 搜索和检索学术论文。无需 API Key，无需依赖。

## 搜索语法

| 前缀 | 搜索范围 | 示例 |
|------|---------|------|
| `all:` | 全部字段 | `all:transformer+attention` |
| `ti:` | 标题 | `ti:large+language+models` |
| `au:` | 作者 | `au:vaswani` |
| `abs:` | 摘要 | `abs:reinforcement+learning` |
| `cat:` | 分类 | `cat:cs.AI` |

运算符: `+`(AND), `OR`(或), `ANDNOT`(排除)

## 使用 web_fetch

直接用 `web_fetch` 调 arXiv API，返回 XML 格式。从结果中提取标题、作者、摘要、PDF 链接。

### 搜索论文

```
web_fetch("https://export.arxiv.org/api/query?search_query=all:GRPO+reinforcement+learning&max_results=5&sortBy=submittedDate&sortOrder=descending")
```

可选参数:
- `max_results` — 返回数量 (1-100)
- `start` — 偏移量
- `sortBy` — `relevance` / `lastUpdatedDate` / `submittedDate`
- `sortOrder` — `ascending` / `descending`

### 获取特定论文

```
web_fetch("https://export.arxiv.org/api/query?id_list=2402.03300")
# 多篇用逗号分隔
web_fetch("https://export.arxiv.org/api/query?id_list=2402.03300,2401.12345")
```

### 读论文内容

```
# 摘要页（快速）
web_fetch("https://arxiv.org/abs/2402.03300")

# 完整 PDF
web_fetch("https://arxiv.org/pdf/2402.03300")
```

## 常见分类

| 分类 | 领域 |
|------|------|
| `cs.AI` | 人工智能 |
| `cs.CL` | 自然语言处理 |
| `cs.CV` | 计算机视觉 |
| `cs.LG` | 机器学习 |
| `cs.CR` | 密码学与安全 |
| `stat.ML` | 机器学习（统计） |

完整分类: https://arxiv.org/category_taxonomy

## 完整体验流

1. **发现**: 搜索关键词
2. **筛选**: 按日期/相关性排序
3. **读摘要**: web_fetch 摘要页
4. **读全文**: web_fetch PDF
5. **交叉验证**: 用 Semantic Scholar 查引用量（可选）

### Semantic Scholar（论文引用查询，免费免 Key）

```
web_fetch("https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300?fields=title,citationCount,year,abstract")
```

## 注意事项

- arXiv 限速约 1 次/3 秒
- 旧格式 ID: `hep-th/0601001`，新格式: `2402.03300`
- 必要时注明论文是预印本（未经过同行评审）
