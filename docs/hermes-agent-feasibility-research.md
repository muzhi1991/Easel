# Hermes Agent 替换 OpenClaw：可行性调研

调研日期：2026-10-09。范围：本机安装源码、Easel 当前代码和 Hermes 官方文档；未创建 profile、修改实例配置、启动服务或调用模型。本文是静态兼容性判断，不是完成迁移后的运行验证。

## 结论

可以替换，Hermes 已具备独立 profile、HTTP Agent API、会话、流式输出、工具执行和技能加载能力。并非只改 URL：Easel 对 OpenClaw 的会话、事件、配置、进程管理和交互提问存在专门适配。最小聊天原型工作量中等；完整保留当前功能属于中等偏高的改造。

建议先增加可切换的 Hermes 后端，保留 OpenClaw 作为回退；采用一个专用 Hermes `easel` profile，继续由 Easel 管理自媒体画像和账号目录。是否进一步按账号划分 Hermes profile，应由隔离需求决定。

## Hermes 能力核验

| 问题 | 核验结果 | 一手依据 |
| --- | --- | --- |
| 可否启动独立实例 | 可以。profile 是独立状态目录，包含配置、技能、记忆、会话和网关状态；不同 profile 可以运行独立 gateway，API 端口应分开 | [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/)、[API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/) |
| profile 命令 | `hermes profile create easel --no-skills` 创建空技能 profile；`hermes -p easel ...` 显式选择。macOS 本机创建 profile 不启动网关 | 本机 `hermes_cli/profiles.py:1094,1276`；官方 Profiles、Skills 文档 |
| 后端入口 | gateway 可开启 API Server，提供 `/v1/chat/completions`、`/v1/responses`、`/v1/runs`、`/api/sessions/*`；无需导入 Hermes Python 私有实现 | [Programmatic Integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration/)、API Server |
| 会话和流式事件 | Chat Completions 默认无状态，需要完整 messages；Responses 支持 previous_response_id；Sessions API 提供持久会话和 `chat/stream`；Runs 提供事件、停止与审批 | 本机 `website/docs/user-guide/features/api-server.md:60,117,432,533` |
| 技能复用 | 支持 SKILL.md 开放格式及 `skills.external_dirs`。Easel 技能可作为迁移基础，但需检查 OpenClaw 特定工具名、路径和调用约定 | [Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)；本机同名文档 `:373` |
| 单网关多 profile | 支持 `gateway.multiplex_profiles`，HTTP 路径可用 `/p/<profile>/...`，认证使用目标 profile 自己的 API key | [Running Many Gateways](https://hermes-agent.nousresearch.com/docs/user-guide/multi-profile-gateways/)；本机 API 文档 `:611` |

本机版本由主调研进程核验为 `v0.20.5 (2026.8.19)`，源码提交前缀 `999703fd`。官方在线文档已有比本机更晚的变化，例如 clone 行为，不能把在线最新描述一概当成本机行为。采用新建空 profile 更容易避免继承私人记忆、技能或渠道配置。

`hermes serve` 与 gateway API Server 是两条入口。当前本机 `serve`/dashboard 默认可能转向机器级服务；如果选择 `serve` 构建专用服务，需要 `--isolated`。源码依据：`hermes_cli/main.py:11295–11350`。profile 隔离是状态隔离，不是文件系统沙箱；本地终端仍拥有当前系统用户的文件访问权限。

## 自媒体账号与记忆隔离

可以在一个专用 Hermes profile 内切换 Easel 自媒体画像：每个画像使用独立 Easel 会话，逐轮注入当前画像路径，由技能读取 `profiles/<画像>/`。这与每个账号运行一个 Agent 进程是两个不同设计。

但 Hermes 默认的 `memories/MEMORY.md` 和 `USER.md` 在同一 Hermes profile 内跨会话共享。仅分 session ID 或关闭 memory 工具，不足以确保这些内容不会进入其他画像的上下文。[官方记忆文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)说明其注入机制；本机 `agent/agent_init.py:1842` 显示正常初始化路径与工具禁用列表并非同一开关。

保留 Easel 自己的账号记忆时，应显式关闭两种内建记忆注入，并单独处理外部记忆 provider 和 `session_search` 的跨会话访问：

```yaml
memory:
  memory_enabled: false
  user_profile_enabled: false
```

依据：本机 `tools/memory_tool.py:1198`、`agent/system_prompt.py:820`。外部 provider 的上下文另行注入（同文件 `:831`）。`X-Hermes-Session-Key` 主要用于 Honcho 等 provider 的稳定范围，不能据此声称内建 MEMORY.md 已按账号隔离。

若需要每个账号独立长期记忆和工具配置，可以将自媒体账号映射到独立 Hermes profile；由单网关 multiplex 路由或多个网关承载。它增强状态隔离，但引入配置和生命周期管理成本。

另一个必须区分的概念是平台登录账号。Easel 当前多画像不等于任意同平台账号的独立登录：`web/app.py:218` 的 LOGIN_RUNNERS 使用按平台固定的浏览器 profile，`:4012` 的 B 站使用根目录 cookies.json。若需求包括两个小红书号、两个 B 站号切换发布，需要额外建立账号到浏览器 profile/cookie 的映射；替换 Agent 本身不会自动解决。

## Easel 的改造边界

可复用 React 工作台、Easel profiles/persona、outputs、媒体适配器和大部分领域脚本。

需要适配的关键位置：

- `web/app.py:2513,2565`：当前仅发送本轮用户消息，并依靠 `x-openclaw-session-key` / ID 和 `openclaw/default` 保持服务端上下文。直接转发给 Hermes Chat Completions 会丢失历史。优先评估 Sessions API；也可使用 Responses 或由 Easel 管完整 messages。
- 对话进度：当前读取 OpenClaw 原始 JSONL 获取 thinking/tool 事件，还有 `_heal_openclaw_session` 等恢复逻辑。Hermes 应通过官方 SSE/API 重新映射，不能继续读取旧格式。
- 交互提问：`easel/gateway_questions.py` 的 question bridge 需要核验与新工具链的衔接；有停止、审批 API 不意味着与现有提问机制完全兼容。
- 配置：模型设置和 workspace 解析经 `local_agents.py` 等绑定 `openclaw.json`，需要后端接口。
- 命令与生命周期：`cli.py`、`commands/skill.py` 调 OpenClaw CLI；`gateway.sh`、`sync.sh` 负责启动和提示词/技能同步，需要 Hermes 对应实现。
- 技能：审核 OpenClaw 工具名称和 shell 约定；保持现有发布前预览、检查和用户确认语义。

推荐验证顺序：独立专用实例健康检查 → 两轮对话保持上下文 → 技能执行并产生产物 → 两画像切换不串历史/记忆 → SSE 与取消/提问 → 媒体调用和发布预览 → 最后才评估替换默认运行后端。

## 仍未验证

未测试实际模型调用、并发行为、崩溃恢复、媒体工具运行或发布；没有据此保证两种 Agent 的任务效果相同。需要原型验证 API 和技能行为，再估算完整迁移工期。
