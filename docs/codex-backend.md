# 本机 Codex 对话后端

设置 → 模型配置 → 对话 → 本机 Agent → Codex。选择 GPT 模型并点击「一键接入」，会接入并设为当前对话模型；已接入后按钮为「使用此模型」。切回 API 供应商时，在相应行设为主并保存。

## 前置条件与状态

- 本机 PATH 中有 `codex` 与 `openclaw`，Codex 已登录。
- 当前实例或主实例中已经可信安装官方 `@openclaw/codex` 插件。若仅主实例安装，一键接入会通过 OpenClaw 在 Easel 实例安装同版本官方 npm 包（首次需要联网，最多等待 5 分钟）。
- OpenClaw OpenAI 插件提供可读取的 GPT 模型目录。目录表示底座认识这些模型，不保证当前账户拥有每个模型的使用权限。
- 「可接入」表示发现 CLI、插件及模型目录；「已接入」表示专用实例已配置 Codex；「当前使用」表示默认对话模型正路由到 Codex。
- 接入前执行 `codex login status`，写入前用 OpenClaw 校验临时配置。它们不是实际推理测试，按钮返回信息明确区分。

## 配置边界

只修改 `easel.openclaw_workspace.config_path()` 指向的 Easel 专用配置（默认 `~/.openclaw-easel/openclaw.json`）。也会在该实例的状态目录安装和登记官方插件。不修改项目 `.env`、主 OpenClaw 配置或 Codex 的登录文件。

接入启用 `codex`/`openai` 插件，并检查 Easel 自己的可信安装登记。不能仅通过 `plugins.load.paths` 引用主实例目录：这会丢失官方来源验证，使 Codex harness 拒绝注册。旧版接入留下的主实例目录引用会移除并刷新登记，然后安装官方包；其他插件路径保留。两边插件安装与登记独立，共用本机 Codex CLI。使用检测到的 Codex 命令及 `appServer.homeScope: user` 复用用户登录。原有远程 app-server 配置不会被本机接入覆盖。关闭 Easel 内的用户 Codex 会话目录展示；这不构成用户 Codex home 的文件系统隔离。

模型配置采用 `openai/<模型>` 与 `agentRuntime.id: codex`，并设为默认主模型。已有 fallback 保留；已有模型允许列表追加所选模型。全局 `agents.defaults.params`（例如 `maxTokens`）会干扰原生 Codex 路由，因此接入将其迁移到已有 API 模型的独立 `params`，保留各模型自己的覆盖值，避免 GLM 参数影响 GPT。main Agent 或所选 GPT 存在独立请求参数时拒绝接入，要求先解决冲突。默认优先 `gpt-6.1-sol`，不在本机目录中时使用目录首项。

## 旧 OpenAI 兼容槽位

旧 `.env` 槽位可能名为 OpenAI、实际指向 GLM/其他兼容供应商。首次接入将已配置的 `models.providers.openai` 完整移动到保留名称 `easel-openai`，同时迁移其显式模型在 agents 配置中的引用。发生命名冲突时拒绝操作，不覆盖已有供应商。

网页仍通过 `.env` 展示该 API 槽位，但后续保存会写入 `easel-openai`，不会重新覆盖原生 `openai/*` Codex 路由。普通保存保留这个迁移后的供应商。`.env` 的媒体配置和兼容回退不变。

接入后前端重新读取真实模型状态；保存请求携带页面读取时的主模型，若期间在其他页面切换了模型则拒绝过期保存，防止悄悄切回 GLM。

## 写入与验证

临时配置权限 0600，经 `openclaw config validate --json` 验证后，检查原文件未被并发修改，再备份为 `openclaw.json.bak-codex` 并原子替换。失败不提交配置；异常输出不回显 CLI stderr 或凭证。重复应用相同配置不重写文件。

自动回归使用临时配置和模拟插件安装，不调用模型或发布平台。2026-10-09 经用户要求执行真实对话验收：通过 Easel `/api/chat/stream` 调用 GPT-6.1 Sol，并核对实例会话记录与 Codex app-server 执行日志；不能仅凭回复成功判定，因为 GPT 失败时可能回退到 GLM。插件安装是独立准备阶段；后续配置校验失败时可能保留已安装的官方插件，但不会因此切换主模型。前端需构建，Web 通过 `start-web-lan.sh` 重启；该脚本兼容没有 API baseUrl 的原生 runtime。

参考：[OpenClaw Codex 路由](https://docs.openclaw.ai/plugins/codex-harness/routing)、[app-server 策略](https://docs.openclaw.ai/plugins/codex-harness/app-server)。
