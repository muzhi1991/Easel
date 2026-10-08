# 媒体适配器：安装、迁移与扩展

本文件描述实际实现。最初设计见 [media-provider-adapter-design.md](media-provider-adapter-design.md)。

## 已实现的范围

- 独立安装包 `integrations/media-adapters/`：实例配置、能力描述、可信安装包注册、输入验证和执行分发。
- 两个转写适配器：`openai-transcription`（单地址、真实时间戳的兼容接口，当前内网默认），`qwen-asr-aligner`（保留的两个地址直连方式）。
- 设置页“语音转写”在同一张原供应商表中显示“自带字幕”和自定义实例，可以添加、编辑、探活、选择默认转写供应商，以及删除非默认实例；已有字幕仍优先。
- 同一份供应商配置同时用于共享字幕脚本和视频流水线；已有转录稿/字幕优先，失败不自动切换或下载 Whisper。
- `MediaProviders.tsx` 根据适配器描述生成配置字段，可以复用于其他媒体通道。

本阶段仅接通转写执行入口。配音、生图、视频、音乐原有供应商仍然照旧运行，尚未迁移它们的执行分发表；Qwen Image、H3、ComfyUI 没有接入。它们的首个适配器仍需把对应业务脚本接到统一入口，然后服务特有改动才能全部留在适配包中。不能把通用配置 UI 当作已有全部执行能力。

## 安装

在项目根运行；不必重新运行完整 `setup.sh` 或升级 OpenClaw：

```bash
.venv/bin/python -m pip install -e integrations/media-adapters
.venv/bin/python -m easel.media providers
```

基础依赖仅 `httpx`，沿用现有 FFmpeg；不下载 ASR 模型，不需要为远程 Qwen 再下载 Whisper 模型。Easel 本身也需安装在同一 Python 环境（现有官方 setup 已满足）。

包独立于 Easel，迁移时可直接从该目录构建 wheel：

```bash
.venv/bin/python -m pip wheel --no-deps integrations/media-adapters -w /tmp/easel-media-wheels
```

在目标机器的 Easel Python 环境安装生成的 wheel，或将目录复制后 editable 安装。开发机器 editable 安装指向当前目录，移动仓库后需要重新安装。

## 配置与设置页

默认位置：`~/.config/easel/media-providers.json`。可通过 **进程环境变量** `EASEL_MEDIA_CONFIG` 指向其他路径。Web 和 Agent/CLI 必须使用同一个路径；默认同一用户目录时无需额外设置。

配置结构：

```json
{
  "schema_version": 1,
  "providers": [{
    "id": "internal-qwen-asr",
    "name": "内网 Qwen ASR + 对齐",
    "adapter": "openai-transcription",
    "settings": {
      "base_url": "http://GATEWAY_HOST:18082/v1",
      "model": "qwen3-asr-aligned",
      "timestamp_granularity": "word+segment",
      "timeout_seconds": 1900,
      "use_proxy": false,
      "transport": "httpx"
    }
  }],
  "defaults": {"transcribe": "internal-qwen-asr"}
}
```

地址是迁移占位值；实际用户地址写在用户目录配置中，不提交 Git。当前组合服务只填一个含 `/v1` 的 Base URL，不在 Easel 中填 ASR 和对齐两个地址。数字/布尔字段由适配器描述校验，不要把 false 写成字符串。

设置页：模型配置 → 语音转写 → 添加供应商 → 选择适配器 → 填写实例 ID/名称及字段 → 保存并设为默认。每行独立保存，下一次任务读取新配置，不要求重启 Gateway。默认实例删除前先将另一个实例设为默认。

配置文件采用原子替换，权限 0600。它只存凭证环境变量的名称，不存密钥。无鉴权 Qwen 服务不需要伪造 Key；OpenAI 兼容服务可以填写 `api_key_env`，例如 `EASEL_MEDIA_TRANSCRIPTION_KEY`，由进程环境提供真实值。网页只允许专用 `EASEL_MEDIA_*` 凭证引用，不能转发任意既有进程秘密。把 Key 写入 `.env` 并不保证每种 CLI 启动方式都会读取，应在启动环境明确导出并重启需要使用它的进程。

内网访问是对配置实例的显式授权，不会放开旧聊天自测的 SSRF 策略。仅安装管理员信任的适配包，不从网页导入代码；HTTP 请求不跟随跳转，避免凭证被转发到另一个地址。

### 单地址组合服务（当前推荐）

独立的 Qwen 转写组合服务负责调用原 ASR 和 ForcedAligner。Easel 使用通用 `openai-transcription`，不新增 Qwen 专属网关适配器：

- 模型 `qwen3-asr-aligned`；POST `/v1/audio/transcriptions`，multipart `file/model/language/response_format=verbose_json`。
- “时间戳粒度”选择 `word+segment`，实际发送两个同名 `timestamp_granularities[]` 字段。兼容适配器缺省是 `segment`；只有支持词时间戳的服务才选择 word。明确请求 word 却没返回 words 时失败，不将段级结果伪装成词级成功。
- Easel 仅提取/标准化完整音轨并上传一次，不再客户端切片或直接访问两个模型端点。服务端负责约30秒静音附近切分、串行 ASR/对齐及全局偏移合并；客户端验证真实时间戳，再按字幕行长度聚合。
- 保留服务端 `timestamp_source=forced_alignment` 和 warnings；若服务明确标记为估算时间轴，拒绝作为真实时间戳。模型未提供的置信度不伪造。
- 服务同步等待上限当前1860秒，实例超时设置1900秒（大于服务等待上限）；旧实例若仍600秒需在设置页更新。不得在超时或未知提交状态后自动重交推理。
- GET `/v1/models` 仅探测接口连接/鉴权；服务端 `/health` 检查上游及队列，两者都不代表识别质量已经验证。

服务端启动/部署由独立项目维护，不随 Easel 升级重启或重新加载模型。其固定 wheel 仍来自 Easel 提交 `7cf2a23` /适配包0.1.0；本轮客户端0.1.1增加请求粒度等能力，不要求远端换 wheel。远端维护说明仍标记试验进程、尚未安装正式系统服务，不能把端点可用写成已完成 systemd 正式部署。

### 保留两个地址直连的可选方式

`qwen-asr-aligner` 仍可显式选择，字段为 `asr_url`、`aligner_url`（均不含 `/v1`）、`model=qwen3-asr`、`chunk_seconds=30`、`timeout_seconds=180`，以及通用 transport/use_proxy。此方式由客户端执行分片和对齐，不是当前默认网关方式。现有默认实例已原地切换为单地址，实例 ID 保持不变，不残留第二条默认或备选实例。切换前个人配置备份为同目录 `media-providers.before-transcription-gateway.json`，不提交 Git；回退需显式恢复配置而非自动 fallback。

### macOS HTTP 传输

默认 `httpx`；可显式选择 `curl`。本机观察到 Python 直接访问 LAN 返回 `Errno 65 No route to host`，而 `/usr/bin/curl` 同一端点可以正常访问，所以当前用户实例选择 `curl`。根因未进一步证实，不能据此说服务未部署或全网不可达。

`curl` 路径要求系统安装 curl。两种方式都支持 multipart，不自动重试上传、不跟随重定向；凭证通过 curl stdin 配置传入，不出现在进程命令参数中。其他机器优先测试 httpx，不需要沿用本机传输选择。

## 使用与字幕行为

统一 JSON 入口：

```bash
.venv/bin/python -m easel.media probe internal-qwen-asr
.venv/bin/python -m easel.media transcribe --src input.mp4 --out transcript.json --lang zh
```

字幕入口：

```bash
.venv/bin/python skills/shared/scripts/asr.py transcribe \
  -i input.mp4 -o outputs/example/input.srt --language zh

.venv/bin/python skills/shared/scripts/asr.py transcribe \
  -i input.mp4 -o outputs/example/input.json --format json --language zh
```

`--provider 实例ID` 手动选择其他已配置实例；不传则使用默认值。字幕脚本的 `--provider-model` / 统一入口的 `--model` 可以覆盖远程模型。字幕脚本旧 `--model base` 等参数仅用于显式选择 `--provider whisper`，默认不会下载或调用 Whisper。

视频流水线保留 `--transcript` 的 JSON/SRT/VTT 优先规则。无现成稿时调用 `python -m easel.media transcribe`；使用安装了 Easel 和适配包的 Python 环境。仅安装 faster-whisper 不表示其模型已经下载。

### Qwen 直连适配器的切片与对齐（可选旧方式）

1. FFmpeg 将音/视频转换为 16kHz、单声道、PCM WAV；不改原文件。
2. 默认目标 30 秒（可配置），优先选目标前后约 10 秒内的静音中点；无静音按目标切。片段无重叠、无空缺，最大不超过 120 秒，低于对齐服务的 300 秒上限。
3. 同一 WAV 切片先送 ASR，清理 `language …<asr_text>` 等标记，再送对齐；不拿翻译文本对齐。
4. 请求服务加回 offset。服务返回已经是全局时间，客户端不会再次加 offset。
5. 保留每个真实字/词时间戳，按标点/长度聚合字幕，不按字数比例估算时间。零时长单位保留在 words 中并合入有效字幕，同时发出警告；全零、倒序、非有限或明显越界结果直接失败。
6. ASR 使用部署接口支持的 temperature=0 和随音频时长限制的 max_tokens；异常过长文本或生成量达到上限时明确失败，防止截断内容被当作完整字幕。
7. 服务 429/422/503、连接失败或未知提交结果明确返回错误，不换供应商、不自动重交。完整成功后才原子写入 JSON；中途失败不产生部分成功结果。

同一个 ASR 根地址的实例使用共同文件锁，串行执行本机这套适配器发起的 ASR＋对齐任务。其他机器或外部客户端不受本机锁保护，远端 429 仍需人工或调度层处理。请求超时是单请求超时，不是整段视频总耗时限制；等待本机任务锁也可能增加总耗时。

输出包含 `provider/adapter/model/language/text/segments/words/duration`、`timestamp_source`、`approx_timeline=false`、warnings 和切片信息。上游不暴露实际 backend 时记录 unknown，不根据模型别名推测路由。

## 从旧版本迁移

- 以前的 SiliconFlow 配置不会自动变成新默认实例。可以在设置页添加 OpenAI 兼容转写实例，使用真实支持的模型与地址，并配置专用凭证引用；旧 `SILICONFLOW_*` 保留，不会擅自删除或覆盖。
- 默认供应商缺失会明确报错，不再因缺 Key 自动进入 Whisper。已有可信字幕照常优先。
- 当前 OpenAI 兼容转写要求真实 words 或 segments；word 模式必须有真实 words，只返回纯文本的服务会失败，不再生成比例估算时间轴。
- 旧 SDK 的 `transcribe.py` / `transcribe_api.py` 文件仍保留用于历史和手动调用，正常流水线不再经过它们。
- 切换机器时复制用户配置，调整地址/传输并提供必要凭证；不要把配置或密钥复制进 Git。

## 新增服务：实例与适配器分别处理

### 同协议新增实例

直接在设置页添加另一行，无需改代码。例如另一个单地址 Qwen 组合服务，或另一家真正兼容的转写 API。单地址实例使用 `openai-transcription`，不需要新写一个适配器。

### 新协议新增适配器

在独立包中新增实现，或者维护另一个可信 Python 包，通过以下 entry point 注册：

```toml
[project.entry-points."easel.media_adapters"]
my-transcription = "my_media_package.adapter:MyAdapter"
```

实现契约（当前 interface_version=1）：

```python
class MyAdapter:
    descriptor = {
        "name": "自建转写服务",
        "interface_version": 1,
        "channels": ["transcribe"],
        "capabilities": ["transcribe"],
        "fields": [
            {"key": "base_url", "label": "根地址", "type": "url", "required": True}
        ],
    }

    def probe(self, provider):
        # Return {"ok": bool, "detail": str}; never equate health with recognition success.
        ...

    def submit(self, provider, capability, request):
        # Current transcription request is TranscriptionRequest.
        # Return the normalized completed transcript, including real segments.
        ...
```

字段类型支持 text/url/number/boolean/secret_ref，支持 choices；数字声明 min/max。连接地址/模型字段名是适配器内部约定，UI 不硬编码它们。可选 `concurrency_key(provider)` 返回共享资源标识，避免同资源多个实例相互抢占。

注册来自已经安装的 Python 包。新增 entry point 后重启 Web，使其发现新包；CLI 下一次启动即可发现。不要重复占用已有适配器 ID。

当前执行契约是同步完成的 `submit`，不是一个已经实现的通用持久化异步队列。后续图片/视频需要远端任务句柄与恢复查询时，先版本化扩展契约，再由各适配器实现提交、轮询和产物收集；不要在调用方临时加 ComfyUI 节点或 H3 特有请求字段。

### 新媒体能力的接线

其他媒体通道首次迁移时：定义有类型的请求/结果 → 注册适配器 → 对应脚本只接 bridge → 加契约及效果测试。模型专属参数、工作流 JSON、切片/轮询留在独立适配包或外部 server。音乐不能假设存在与其他媒体相同的 OpenAI 协议。

## Easel 升级时关注的文件

核心接线集中在以下文件；供应商实现集中在独立包中：

| 接线位置 | 作用 |
| --- | --- |
| `easel/media.py` | 薄桥接、CLI、结果原子落盘 |
| `web/app.py` 的 `/api/settings/media*` | 通用配置与探活入口 |
| `MediaProviders.tsx`、`api.ts`、`SettingsPanel.tsx` | 按描述生成表单及选项卡接入 |
| `skills/shared/scripts/asr.py` | 字幕调用 bridge，保留 SRT/ASS 渲染及显式 Whisper |
| SDK `pipeline/run.py` 的 `st_transcribe` | 字幕优先及统一转写选择 |
| `video_pipeline.py`、SDK `pipeline/doctor.py` | 报告默认实例配置，不再提示自动 Whisper 兜底 |
| `auto-subtitle/SKILL.md`、`video-production/SKILL.md` | Agent 运行约定 |

独立分支 rebase 官方升级时检查这些接线点。配置仍留用户目录；重新安装适配包并构建前端，重启 Web 加载代码，不需修改共享 OpenClaw 安装包。旧 GLM user-text 补丁已经退役，此接入不涉及该补丁，也不需要在任何升级中重打。

更新 Agent 技能时同步相关 SKILL 与脚本副本。完整 `openclaw/sync.sh` 还会改 workspace 文件和清空 MEMORY.md，若只更新本功能应仅同步相关文件，避免无关状态变化。

## 验证

```bash
.venv/bin/python -m pytest -q tests/test_media_adapters.py
cd web/frontend && npm run build
```

同时对短中文、英文及超过 5 分钟的音频进行真实识别，核对文本、逐词时间、切片连续性与服务错误。不仅检查 HTTP 200；重复音频用于时长容量验证，不作为一般准确率或性能保证。


### 本轮验证记录（2026-10-08）

- 根目录测试：`pytest -q tests`，405 passed / 3 skipped；前端 tsc + Vite 构建通过，pip check 无依赖冲突。
- 真实中文 4.204 秒：识别“甚至出现交易几乎停滞的情况。”，13 个对齐单位，SRT/ASS/JSON 及视频流水线入口均通过。
- 真实英文 15.051 秒：37 个对齐单位，文本与语音样本匹配。
- 310 秒重复英文容量样本：默认约 30 秒目标，10 个连续切片，207 条字幕、763 个对齐单位，约 33.8 秒；时间戳边界与切片连续性检查通过。29 个零时长单位保留并标注警告。这是重复素材容量验证，不代表一般质量或性能。
- 前一轮约 60 秒切片的末段约 69 秒，ASR 返回 30,466 字符重复文本，对齐服务因超过 16,000 字符限制返回 422。不是音频超过 5 分钟；已加生成预算、文本异常/截断拒绝，并将本机默认目标设为 30 秒。没有修改服务器或以 HTTP 200 当作完整识别成功。
- 浏览器实际检查：默认实例行、编辑字段、添加表单、连接探活均正常，无页面脚本错误；localhost 和 LAN 页面 HTTP 200。
- 本地验证产物在 `/tmp/easel-media-validation/`，未提交 Git；用户实例仍在用户目录配置文件。

### 单地址组合服务接入验证（2026-10-08）

- 本地默认实例使用 `openai-transcription` / `qwen3-asr-aligned` / `word+segment`，只配置组合服务 Base URL；适配包客户端版本0.1.1。
- 根目录测试407 passed / 3 skipped，前端 tsc + Vite 构建通过，pip check 无冲突。回归覆盖完整310秒音频只上传一次、重复 multipart 粒度字段、服务端警告保留、缺词时间戳及估算结果拒绝。
- 经 Easel 统一入口真实中文：4.204秒，13个对齐单位，识别“甚至出现交易几乎停滞的情况。”；英文：15.051秒，37个单位。
- 经 Easel 单地址接口真实310秒重复英文：763个单位、207条字幕，末词结束310秒，约16.9秒；零时长单位保留并诊断。这是容量与偏移验证，不是一般长音频质量评测。
- 共享字幕脚本通过默认组合接口生成正确SRT；已有字幕优先回归通过。
- 浏览器验证同一表格显示“自带字幕”及默认内网实例，编辑只有一个Base URL、粒度与1900秒超时；添加表单、连接探活正常，无页面脚本错误。Web重启后localhost和LAN可访问。
- 验证产物 `/tmp/easel-gateway-validation/` 为本地临时文件，不提交；未改动远端两个模型服务、网关部署方式或共享OpenClaw。
