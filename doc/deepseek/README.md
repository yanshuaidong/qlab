# DeepSeek API 官方文档（本地镜像）

同步日期：2026-09-19

本目录由 [main.py](./main.py) 从 [DeepSeek API 中文文档](https://api-docs.deepseek.com/zh-cn/) 抓取并转成 Markdown，便于离线查阅。

重新同步：

```bash
python doc/deepseek/main.py
```

官方文档可能随时更新，本地内容以每次同步时的网页为准。

## 快速开始

- [首次调用 API](首次调用API.md) — https://api-docs.deepseek.com/zh-cn/
- [模型 & 价格](快速开始/模型与价格.md) — https://api-docs.deepseek.com/zh-cn/quick_start/pricing
- [Token 用量计算](快速开始/Token用量计算.md) — https://api-docs.deepseek.com/zh-cn/quick_start/token_usage
- [限速与隔离](快速开始/限速与隔离.md) — https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit
- [错误码](快速开始/错误码.md) — https://api-docs.deepseek.com/zh-cn/quick_start/error_codes

## 接入 Agent 工具

- [接入 AstrBot](快速开始/接入工具/接入AstrBot.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/astrbot
- [接入 Claude Code](快速开始/接入工具/接入ClaudeCode.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code
- [接入 Codex](快速开始/接入工具/接入Codex.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex
- [接入 GitHub Copilot CLI](快速开始/接入工具/接入GitHubCopilotCLI.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/copilot_cli
- [接入 Crush](快速开始/接入工具/接入Crush.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/crush
- [集成 Deep Code](快速开始/接入工具/集成DeepCode.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/deepcode
- [接入 GitHub Copilot](快速开始/接入工具/接入GitHubCopilot.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/github_copilot
- [接入 Hermes](快速开始/接入工具/接入Hermes.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/hermes
- [接入 Kilo Code](快速开始/接入工具/接入KiloCode.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/kilo_code
- [接入 Langcli](快速开始/接入工具/接入Langcli.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/langcli
- [接入 nanobot](快速开始/接入工具/接入nanobot.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/nanobot
- [在 Oh My Pi 中使用 DeepSeek](快速开始/接入工具/在OhMyPi中使用.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/oh_my_pi
- [接入 OpenClaw](快速开始/接入工具/接入OpenClaw.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/openclaw
- [接入 OpenCode](快速开始/接入工具/接入OpenCode.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/opencode
- [接入 Pi](快速开始/接入工具/接入Pi.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/pi_mono
- [接入 Qoder](快速开始/接入工具/接入Qoder.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/qoder
- [接入 Reasonix](快速开始/接入工具/接入Reasonix.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/reasonix
- [接入 WorkBuddy/CodeBuddy](快速开始/接入工具/接入WorkBuddy.md) — https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/workbuddy

## API 指南

- [图像理解](指南/图像理解.md) — https://api-docs.deepseek.com/zh-cn/guides/vision
- [思考模式](指南/思考模式.md) — https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
- [多轮对话](指南/多轮对话.md) — https://api-docs.deepseek.com/zh-cn/guides/multi_round_chat
- [对话前缀续写（Beta）](指南/对话前缀续写.md) — https://api-docs.deepseek.com/zh-cn/guides/chat_prefix_completion
- [FIM 补全（Beta）](指南/FIM补全.md) — https://api-docs.deepseek.com/zh-cn/guides/fim_completion
- [JSON Output](指南/JSON输出.md) — https://api-docs.deepseek.com/zh-cn/guides/json_mode
- [Tool Calls](指南/工具调用.md) — https://api-docs.deepseek.com/zh-cn/guides/tool_calls
- [Files API](指南/文件API.md) — https://api-docs.deepseek.com/zh-cn/guides/files_api
- [上下文硬盘缓存](指南/上下文硬盘缓存.md) — https://api-docs.deepseek.com/zh-cn/guides/kv_cache
- [使用 Responses API](指南/使用ResponsesAPI.md) — https://api-docs.deepseek.com/zh-cn/guides/responses_api
- [使用 Anthropic API](指南/使用AnthropicAPI.md) — https://api-docs.deepseek.com/zh-cn/guides/anthropic_api
- [接入 Agent 工具](指南/接入Agent工具.md) — https://api-docs.deepseek.com/zh-cn/guides/coding_agents
- [V3.1-Terminus 对比测试](指南/对比测试.md) — https://api-docs.deepseek.com/zh-cn/guides/comparison_testing

## API 文档

- [Chat Completions API](API文档/对话补全.md) — https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
- [Responses API](API文档/ResponsesAPI.md) — https://api-docs.deepseek.com/zh-cn/api/create-response
- [FIM 补全 API（Beta）](API文档/FIM补全API.md) — https://api-docs.deepseek.com/zh-cn/api/create-completion
- [获取模型列表](API文档/获取模型列表.md) — https://api-docs.deepseek.com/zh-cn/api/list-models
- [查询余额](API文档/查询余额.md) — https://api-docs.deepseek.com/zh-cn/api/get-user-balance
- [上传文件](API文档/上传文件.md) — https://api-docs.deepseek.com/zh-cn/api/create-file
- [列出文件](API文档/列出文件.md) — https://api-docs.deepseek.com/zh-cn/api/list-files
- [查询文件](API文档/查询文件.md) — https://api-docs.deepseek.com/zh-cn/api/retrieve-file
- [删除文件](API文档/删除文件.md) — https://api-docs.deepseek.com/zh-cn/api/delete-file
- [DeepSeek API](API文档/DeepSeekAPI.md) — https://api-docs.deepseek.com/zh-cn/api/deepseek-api

## 其它

- [常见问题](常见问题.md) — https://api-docs.deepseek.com/zh-cn/faq

## 外部链接（未镜像）

- [申请 API Key](https://platform.deepseek.com/api_keys)
- [DeepSeek Harness 入门](https://deepseek-harness.github.io/deepseek-harness/guide/quickstart)
- [官方 FAQ](https://static.deepseek.com/faq/index.html?lang=zh#/category/4)
- [Awesome DeepSeek Integration](https://github.com/deepseek-ai/awesome-deepseek-integration/tree/main)
- [贡献你的 Agent 接入](https://github.com/deepseek-ai/awesome-deepseek-agent/tree/main)

