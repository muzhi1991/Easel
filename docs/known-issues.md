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

## 代理 Fake-IP 导致模型列表被判为内网

若域名解析到代理的 `198.18.0.0/15` Fake-IP 网段，「拉取模型」或「自测」可能被地址校验拦截。`start-web-lan.sh` 会从 Easel 实例配置中收集所有已保存 API 供应商的精确 origin（协议、域名、端口），通过 `EASEL_FAKE_IP_ORIGINS` 允许这些域名的 Fake-IP；不再依赖主模型是否有 API 地址，因此主模型为 Codex 时也能检查备用供应商。真实私网、回环等地址仍被拒绝。显式设置该环境变量时使用显式值；新增或更改供应商地址后需重启 Web 更新列表。
