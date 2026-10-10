# 已知问题

本页记录目前已知、且与 Easel 使用相关的问题，以及推荐的规避方式。遇到未列出的问题，欢迎提交 [Issue](https://github.com/ZJU-REAL/Easel/issues)。

---

## CLI 终端对话中「问答题」后回复重复显示

- **影响范围**：仅 `easel chat`（终端对话）。**Web 工作台不受影响**。
- **表现**：当 Agent 触发一次 `ask_user` 问答题、用户回答之后，Agent 的下一条回复在终端里可能被重复渲染一次（内容正确，只是显示了两遍）。
- **性质**：这是**纯显示层**问题，不影响实际对话内容、产物生成或发布结果。

### 根因

问题位于上游 [OpenClaw](https://www.npmjs.com/package/openclaw) 本体的**会话投影（session projection）**逻辑，不在 Easel 仓库内。

`easel chat` 底层调用 `openclaw tui`，由 OpenClaw 的 gateway-client 负责在终端重建对话记录。当一条实时回复与另一行（例如 `ask_user` 的问答行）发生错误匹配、且两者不共享 transcript identity 时，投影逻辑会把该回复重新插入一次，导致重复渲染。

我们已核实该根因，并在上游的回归测试中复现（修复前 3 条相关用例失败，修复后全部通过）。

### 上游修复进展

修复已提交至 OpenClaw，跟踪 PR：

- openclaw#144730
- openclaw#144892

修复采用四层策略：全内容唯一匹配、要求终端证据、暂定恢复记录、以及在暂定恢复无法表示时保留后续独立 final 可见。

### 规避与升级

- **推荐**：使用 **Web 工作台**（`easel web`，默认 `http://localhost:7860`）。Web 后端从原始事件流自行渲染，不经过上述会话投影逻辑，因此**不受此问题影响**，并且提供比 CLI 更完整的会话、素材、账号、画像、内容库与发布管理能力。
- 若坚持使用 `easel chat`：待上游发布含修复的版本后，升级 OpenClaw 即可解决：

  ```bash
  npm i -g openclaw@latest
  ```

- Easel 安装的是 OpenClaw 全局 CLI（预构建产物），因此我们**不在 Easel 仓库内内置该补丁**，而是跟随上游最新版本。`easel doctor` 已加入 OpenClaw 最低版本检查（≥ 2026.6.11），版本过旧会直接提示升级。

---

## 第三方代理 / 兼容端点 LLM 一直超时（#9、#11）

- **影响范围**：配置第三方代理或 Anthropic/OpenAI-compatible 端点的安装。
- **表现**：`easel ping` 或小请求可能正常，但稍大、带思考的请求持续超时；部分版本上 `setup.sh` 还会报 `baseUrl: expected string, received undefined` 或 `Unrecognized key: "timeoutSeconds"`。

### 根因（已修复）

- 旧版 OpenClaw（如 2026.3.x）的 provider schema 要求 anthropic 配置**原子写入**；逐字段写入时中间态缺 `baseUrl`，整份校验失败。`setup.sh` 已改为整块一次性写入。
- 旧版本不认识 `timeoutSeconds` 字段，单次请求 600 秒空闲超时写不进去，回落到默认短超时，首个 token 稍慢即超时。该写入在老版本上已降级为尽力而为，不再中断安装。

### 建议

```bash
npm i -g openclaw@latest
git pull
bash setup.sh
```

升级后 `easel doctor` 会校验 OpenClaw ≥ 2026.6.11。不升级时安装不再报错，但请求超时受旧版默认超时限制；请确认模型名带 provider 前缀（如 `anthropic/claude-sonnet-4-6`），具体卡在哪一步可看 `easel gateway logs`。

## 对话推理强度

「设置 → 模型配置 → 对话」可保存默认推理强度；对话输入框旁可选择当前会话的强度，或「跟随默认」。会话选择保存在浏览器本地，刷新、重试时沿用；选择在下一次发送时生效，生成期间不可修改。

默认值读取 Easel 实例的 `agents.defaults.thinkingDefault`；未配置时使用 `EASEL_THINKING_LEVEL`，再回退到 `medium`。会话显式选择优先，两种对话传输均使用同一个解析结果。HTTP 接口本身不读取 `reasoning_effort`，因此通过网关 `sessions.patch` 应用强度，再发起同一会话的 HTTP 请求；CLI 使用 `--thinking`。应用失败会报错，不会静默以其他强度继续。可用档位由当前模型和网关决定，选择不支持的档位时需改选。

## 模型接口地址策略

「拉取模型」和「自测」允许用户指定任意合法 HTTP(S) 模型端点，包括本机、内网和代理 Fake-IP，不再按解析 IP 所属网段拦截。`EASEL_FAKE_IP_ORIGINS` 白名单及启动脚本的自动收集逻辑已移除。请求会携带配置的 API Key 发送到目标地址；URL 格式检查、禁止跟随重定向，以及 Web 写入来源校验仍保留。OpenClaw 独立管理网络策略：如需放开模型请求，设置每个 `models.providers.<id>.request.allowPrivateNetwork: true`；浏览器、网页抓取和定时任务 Webhook 分别设置 `browser.ssrfPolicy`、`tools.web.fetch.ssrfPolicy`、`cron.webhookSsrfPolicy` 下的 `dangerouslyAllowPrivateNetwork: true`，并移除 `blockedHostnames`。实例配置不提交 Git。

当前 OpenClaw 2026.9.8 没有覆盖所有出站请求的总开关。HTTP 输入附件的 URL 下载路径仍固定使用 `allowPrivateNetwork: false`，上述开关不覆盖它；应优先用本地上传或 Base64 输入，不能将配置放开描述成所有底层检查都已移除。

## OpenAI 兼容接口的模型切换

Web 保存模型时，按 ID 复用 `models.providers.<provider>.models` 中的定义，保留已有 `input`、`reasoning` 等字段，不再覆盖 `models[0]`。新模型追加定义，默认 `name=id`、`input: ["text", "image"]`、`reasoning: true`，不写 `contextWindow` 或 `maxTokens`；同时向 `agents.defaults.models` 登记空条目，已有别名、参数和运行时设置保持不变。这些默认能力是配置约定，实际支持取决于上游模型。

OpenAI 兼容接口的 UI 选择仍由现有 `.env` 的 `OPENAI_MODEL` 保存，无需新增配置文件。切换选择后需明确点击「设为主」再保存，才更新 `agents.defaults.model.primary`；仅保存选择不切换实际主模型。图片模型和备用模型引用保持不变。
