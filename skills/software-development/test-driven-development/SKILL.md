---
name: test-driven-development
description: "TDD：红-绿-重构循环，测试先行，不写没有失败测试的生产代码。"
version: 1.0.0
author: Sierra (adapted from Hermes Agent)
license: MIT
metadata:
  sierra:
    triggers: ["tdd", "测试驱动", "写测试", "先写测试", "红绿重构", "test first"]
---

# 测试驱动开发 (TDD)

## 核心原则

**如果你没看到测试失败，你就不知道它测对了没有。**

```
生产代码 → 必须有对应的失败测试先行
否则 → 不是 TDD
```

## 适用场景

**总是使用:**
- 新功能
- Bug 修复
- 重构
- 行为变更

**例外（先问用户）:**
- 一次性原型
- 生成的代码
- 纯配置文件

## 红-绿-重构循环

### RED — 写失败测试

写一个最小测试，展示期望行为。

**好测试:**
```python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception('fail')
        return 'success'
    result = retry_operation(operation)
    assert result == 'success'
    assert attempts == 3
```
清晰的名称，测试真实行为，只测一件事。

**坏测试:**
```python
def test_retry_works():
    mock = MagicMock()
    mock.side_effect = [Exception(), Exception(), 'success']
    result = retry_operation(mock)
    assert result == 'success'  # 重试次数呢？
```
模糊的命名，测 mock 不测真实代码。

### 验证 RED — 看着它失败

```bash
pytest tests/test_feature.py::test_specific_behavior -v
```

确认：测试失败（不是语法错误）、失败信息符合预期、失败是因为功能缺失。

### GREEN — 最小代码

写最简代码通过测试。不多写一行。

```python
# Good
def add(a, b):
    return a + b

# Bad
def add(a, b):
    result = a + b
    logging.info(f"Adding {a} + {b} = {result}")  # 多余！
    return result
```

### 验证 GREEN — 看着它通过

```bash
pytest tests/test_feature.py::test_specific_behavior -v
pytest tests/ -q  # 全量回归
```

### REFACTOR — 清理

通过后：去重、改命名、提取辅助函数、简化表达式。保持全绿。

## 常见借口 vs 现实

| 借口 | 现实 |
|------|------|
| "太简单不用测" | 简单代码也会坏。测试只花 30 秒。 |
| "之后再加测试" | 之后加的测试直接通过，什么都证明不了。 |
| "手动测过了" | 临时 ≠ 系统化。没有记录，不能重跑。 |
| "TDD 太慢" | TDD 比调试快多了。 |
| "已经花了 X 小时，删了浪费" | 沉没成本谬误。留着不可信的代码才是浪费。 |

## 停止并重来的红旗信号

- 代码先于测试
- 测试第一次运行就通过
- 说不清测试为什么失败
- "这次情况特殊..."
- "已经花了 X 小时..."
- "留着参考..."

**以上任何一条 = 删代码，用 TDD 重来。**

## 验证清单

- [ ] 每个新函数/方法有测试
- [ ] 每个测试都先看到失败
- [ ] 每个测试失败原因正确（功能缺失，不是拼写错）
- [ ] 写了最简代码通过每个测试
- [ ] 全部测试通过
- [ ] 边界情况和错误已覆盖
