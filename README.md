# Sierra
Sierra 是一个陪伴型工作智能体。她会记住你的习惯，陪你讨论想法，也能在获得允许后亲自使用工具把事情做完。

当前版本主要运行在 Windows，提供 TUI 和 Web UI，仍处于活跃开发阶段。

## Sierra 能做什么

### 把模糊的想法变成能执行的事情

你不需要一开始就把需求想得很完整。可以只告诉 Sierra 一个目标，让她和你一起梳理方向、补充条件、比较方案，再把复杂任务拆成可以逐步完成的计划。需要你做决定时，她会停下来询问，而不是替你擅自拍板。

### 陪你完成手头的工作

当任务涉及项目和文件时，Sierra 不只会给出一段建议。她可以进入你的工作区，阅读现有内容，修改代码或文档，运行测试，检查结果，并在失败后继续寻找原因。涉及删除、终端执行或其他高风险操作时，她会先征求你的允许。

### 帮你理解陌生的信息

你可以让 Sierra 调查一个话题、比较资料、浏览网页，也可以把图片、PDF、Word、表格或演示文稿交给她。她会先阅读材料，再与你讨论重点、整理结论或继续完成后续工作，而不是只把搜索结果堆在面前。

### 记住你们怎样一起做事

Sierra 会从长期对话中整理值得保留的信息，例如你的偏好、项目背景和希望她采用的协作方式。下次继续时，她可以自然地用上这些信息，减少重复说明；你也可以查看、搜索或删除这些记忆。

### 接着做没有完成的任务

长任务可以保存计划和进度。会话被中断、程序意外退出或上下文过长时，Sierra 会尽量保留必要状态，让你回来后继续推进，而不是重新讲一遍前因后果。她也可以承担定时提醒和部分后台维护工作。

### 按你的需要继续扩展

Sierra 可以通过 Skill 学习新的工作方法，通过插件增加运行时能力，也可以使用 MCP 连接外部服务。工具较多时，她会按当前意图寻找需要的能力，避免每轮对话都携带全部工具说明。

## 开始使用

### 运行要求

- Windows 10 或 Windows 11
- Python 3.11 或更高版本
- Node.js 20 或更高版本
- 一个兼容 OpenAI Chat Completions 接口的模型服务

### 1. 获取项目

```powershell
git clone https://github.com/Sierra-16/Sierra-agent.git
cd Sierra-agent
```

### 2. 安装 Python 依赖

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 阻止激活虚拟环境，也可以不激活，后续直接使用 `.\.venv\Scripts\python.exe`。

### 3. 安装前端依赖

```powershell
npm install
npm --prefix tui install
npm --prefix web install
```

### 4. 创建配置文件

```powershell
Copy-Item config.example.json config.json
```

打开 `config.json`，至少配置一个模型，并将它设为当前模型：

```json
{
  "models": {
    "deepseek": {
      "name": "deepseek-chat",
      "base_url": "https://api.deepseek.com",
      "api_key": "YOUR_API_KEY",
      "max_tokens": 8192,
      "temperature": 0.7,
      "context_window": 128000,
      "supports_vision": false
    }
  },
  "active_model": "deepseek"
}
```

`config.example.json` 包含模型、搜索、视觉、记忆、权限、MCP、插件和其他完整配置示例。

### 5. 启动 TUI

在 Sierra 目录中运行：

```powershell
.\sierra.bat
```

如果已经把 Sierra 目录加入 `PATH`，可以在任意工作目录运行：

```powershell
sierra
```

Sierra 会把启动命令所在目录作为用户工作区。

### 6. 启动 Web UI

```powershell
.\sierra.bat web
```

或在已配置 `PATH` 的情况下运行：

```powershell
sierra web
```

构建完成后访问：

```text
http://127.0.0.1:8765
```

Web UI 支持聊天、历史会话、文件上传、工具确认、Plan Mode，以及模型、记忆、Skill、插件、MCP、安全策略、任务和审计等设置。

## 常用操作

直接输入消息即可与 Sierra 对话。在输入框中输入 `/` 可以查看命令补全，输入 `@` 可以引用当前工作区内容。

常用命令包括：

| 命令 | 作用 |
| --- | --- |
| `/help` | 查看全部可用命令 |
| `/new` | 创建新会话 |
| `/sessions` | 查看历史会话 |
| `/model` | 查看或切换模型 |
| `/compress` | 手动压缩当前会话上下文 |
| `/memory` | 查看记忆状态 |
| `/memory-search <问题>` | 搜索长期记忆 |
| `/task` | 查看当前任务计划与进度 |
| `/cron` | 查看定时提醒 |
| `/mcp` | 查看 MCP 连接状态 |
| `/plugins` | 查看插件状态 |
| `/skills` | 查看可用 Skill |
| `/audit` | 查看工具审计记录 |
| `/quit` | 退出 Sierra |

当 Sierra 请求执行中高风险操作时，请确认工具名称、参数和目标路径，再选择允许或拒绝。终端、代码执行和文件写入能力可能直接改变你的工作区，请勿在不了解影响的情况下批准操作。

## 未来计划

Sierra 的最终目标是一套能够长期运行、跨平台交流并持续成长的大型陪伴智能体。下面是当前进度和接下来的方向：

| 方向 | 已经完成 | 目前还没完成 | 接下来打算做 |
| --- | --- | --- | --- |
| 基础对话体验 | TUI 与 Web UI；历史会话管理；流式回复；中断、撤回和重试；Plan Mode | 多窗口并发仍需继续验证；首次使用引导不够完整 | 加强并发与异常场景测试，完善配置向导和错误诊断 |
| 上下文与长任务 | 自动上下文压缩；旧工具结果裁剪；任务计划、检查点和恢复；后台任务 | 极长会话下仍可能出现模型差异；跨设备任务接续尚未实现 | 建立真实模型长会话评测，继续降低 Token 消耗并提高恢复可靠性 |
| 长期记忆 | Markdown 记忆；定期后台审查；本地向量检索；历史会话召回 | 记忆冲突、过期和合并策略仍较基础；缺少直观的记忆管理体验 | 增加可解释的整理、遗忘和冲突处理，并完善 Web 记忆管理 |
| 工具与安全 | 文件、终端、代码、浏览器、搜索和文档工具；风险确认；审计日志 | 更强的进程隔离和系统级沙箱尚未完成 | 细化权限范围、敏感信息保护和工具运行隔离 |
| Skill 与扩展生态 | 渐进式 Skill；脚本、模板和资源；插件系统；MCP stdio 与 HTTP 接入 | 缺少统一的安装市场、版本管理和依赖处理 | 提供扩展脚手架、安装更新流程、兼容性检查和安全审计 |
| 图片与文档 | 图片上传与理解；独立视觉模型回退；PDF、Office 和 RTF 解析 | 音频、视频理解仍未完成；图像生成只有配置入口 | 完成可替换的视觉与图像生成 Provider，增强长文档和多媒体处理 |
| 语音交互 | 已预留 STT 与 TTS 配置和插件接口 | 尚未形成可用的实时语音对话 | 实现语音输入、语音回复、播放控制和自然打断 |
| 外部聊天平台 | 已完成统一 Gateway，TUI 与 Web 共用同一运行时 | Telegram、飞书、QQ、微信尚未接入 | 依次实现平台适配器，并统一附件、权限和工具确认流程 |
| 主动陪伴 | 长期偏好、定时提醒和基础任务跟进 | 缺少成熟的日程协助、目标跟进和主动关怀策略 | 在明确边界和用户可控的前提下，加入日程、目标与生活记录能力 |
| 发布与跨平台 | 当前可在 Windows 本地运行 | 没有一键安装包；macOS 和 Linux 尚未正式支持 | 制作 Windows 发行版，完善升级机制，再逐步适配 macOS 与 Linux |

## 致谢

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)：Sierra 在智能体循环、上下文管理、Skill、工具按需披露和长期任务能力方面参考了 Hermes 的设计思路。
- [Model Context Protocol](https://modelcontextprotocol.io/)：为 Sierra 接入外部工具和服务提供了开放协议基础。
- [FastAPI](https://fastapi.tiangolo.com/)、[Vue](https://vuejs.org/)、[Ink](https://github.com/vadimdemedes/ink) 与 [GSAP](https://gsap.com/)：分别支撑 Sierra 的后端服务、Web UI、终端界面和交互动效。
- OpenAI Compatible API 生态及所有模型、搜索、嵌入和多模态服务提供方。
- 所有参与测试、反馈问题、贡献想法和陪伴 Sierra 成长的人。

Sierra 还没有走到终点。她现在已经能陪你工作，也会继续学习怎样更可靠地陪你走得更远。
