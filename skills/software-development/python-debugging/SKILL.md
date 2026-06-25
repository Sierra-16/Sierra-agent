---
name: python-debugging
description: 当 Python 测试失败、状态变化难以解释、需要检查运行时局部变量、异步任务或长驻进程时使用。结合 traceback、pdb 和 debugpy 定位根因；简单日志足够时不要启动交互调试器。
---

# Python 运行时调试

## 选择工具

按成本从低到高选择：

1. 完整 traceback、失败测试和 `--showlocals`。
2. 临时日志或断言。
3. `breakpoint()` / `python -m pdb`。
4. 长驻、子进程或 IDE 附加场景使用 `debugpy`。

先使用 `debug` 技能建立可复现步骤和假设，再用本技能检查运行时状态。

## pdb 常用命令

- `w`：调用栈
- `u` / `d`：切换栈帧
- `n` / `s` / `r`：越过、进入、返回
- `p expr` / `pp expr`：查看值
- `a`：当前参数
- `b file:line`：断点
- `c`：继续
- `q`：退出

## Sierra / Windows 工作流

```powershell
.\.venv\Scripts\python.exe -m pdb path\to\script.py
.\.venv\Scripts\python.exe -m pytest tests\test_file.py -x --pdb
.\.venv\Scripts\python.exe -m debugpy --listen 127.0.0.1:5678 --wait-for-client script.py
```

执行前先确认项目是否使用 `unittest`、`pytest` 或自定义 runner，不要照搬不存在的命令。远程调试仅监听 `127.0.0.1`，除非用户明确要求并理解暴露端口的风险。

## 收尾

1. 用观察到的变量和调用栈解释根因。
2. 实施最小修复并重新运行原始复现。
3. 移除 `breakpoint()`、`set_trace()`、`debugpy.listen()` 和临时日志。
4. 再运行相关测试，确认调试代码没有进入提交。

