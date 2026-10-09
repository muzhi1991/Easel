# 媒体适配器：安装、迁移与扩展

本文件描述实际实现。最初设计见 [media-provider-adapter-design.md](media-provider-adapter-design.md)。

## 已实现的范围

- YuE2 音乐：歌词歌曲、纯 BGM、目标生成时长、录音转谱翻唱/器乐改编；`MusicRequest`、异步作业、原音乐列表配置及任务恢复。
- Qwen3-TTS 配音：独立 `openai-speech` 适配器与原配音列表配置。
- RapidOCR 图片文字识别：独立适配器、共享 CLI、对话技能及“文字识别”供应商通道。
- 独立安装包 `integrations/media-adapters/`：实例配置、能力描述、可信安装包注册、输入验证和执行分发。
- H3视频适配器：同一个 `h3-video` 对应 FL2VA/Ref2VA 两个实例，支持关键帧与多模态参考、任务恢复及原生内容下载。
- 两个转写适配器：`openai-transcription`（单地址、真实时间戳的兼容接口，当前内网默认），`qwen-asr-aligner`（保留的两个地址直连方式）。
- 设置页“语音转写”在同一张原供应商表中显示“自带字幕”和自定义实例，可以添加、编辑、探活、选择默认转写供应商，以及删除非默认实例；已有字幕仍优先。
- 同一份供应商配置同时用于共享字幕脚本和视频流水线；已有转录稿/字幕优先，失败不自动切换或下载 Whisper。
- `MediaProviders.tsx` 根据适配器描述生成配置字段，可以复用于其他媒体通道。

统一适配层已接通转写、H3 视频、OCR、Qwen3-TTS 和 YuE2 音乐执行入口。各频道原有供应商仍然照旧运行，原有供应商执行分发表仍保留。Qwen Image 文生图已通过原生图脚本的兼容接口接入（见下文），不是新注册的媒体适配器；H3 已通过原生 SGLang 接入，ComfyUI 执行入口尚未迁移到适配包。未来频道或供应商需确认执行入口已接通统一请求，服务特有改动才可留在适配包中。不能把通用配置 UI 当作已有全部执行能力。

## 安装

在项目根运行；不必重新运行完整 `setup.sh` 或升级 OpenClaw：

```bash
.venv/bin/python -m pip install -e integrations/media-adapters
.venv/bin/python -m easel.media providers
```

基础依赖为 `httpx` 与 `Pillow`，沿用现有 FFmpeg；不下载 ASR 模型，不需要为远程 Qwen 再下载 Whisper 模型。Easel 本身也需安装在同一 Python 环境（现有官方 setup 已满足）。

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

配置文件采用原子替换，权限 0600。它只存凭证环境变量的名称，不存密钥。无鉴权 Qwen 服务不需要伪造 Key；OpenAI 兼容服务可以填写 `api_key_env`，例如 `EASEL_MEDIA_TRANSCRIPTION_KEY`，由进程环境提供真实值。网页只允许专用 `EASEL_MEDIA_*` 凭证引用，不能转发任意既有进程秘密。`easel web` 启动时读取项目 `.env` 中的 `EASEL_MEDIA_*` 字段，继承的进程变量优先；音乐脚本也读取项目 `.env`。独立适配包直接调用不读取 `.env`，需显式导出凭证。更换 Web 使用的凭证后重启 Web；不必因此重启 Gateway。

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

默认 `httpx`，当前用户实例也已恢复为 `httpx`（2026-10-09）；不再使用 curl 绕行。此前同一 Python 在系统 Terminal 中可访问 LAN，在 Paseo Agent 和内置终端中报 `Errno 65 No route to host`，系统 curl 则正常。Paseo 环境恢复后，Python TCP、HTTP 探活和真实 ASR/对齐均成功，确认应先检查启动进程链的局域网权限与 daemon 生命周期，而不是更改服务接口。现象与 Paseo [issue #6173](https://github.com/getpaseo/paseo/issues/6173) 相似，但本机未取得该报告中“已退出的 responsible process”证据，不将其具体根因写成已证实。

`curl` 仍是可显式选择的传输方式，要求系统安装 curl；不会自动 fallback 到它。两种方式都支持 multipart，不自动重试上传、不跟随重定向；凭证通过 curl stdin 配置传入，不出现在进程命令参数中。迁移时优先使用 httpx，不需要沿用旧绕行配置。配置变更在下一次任务读取，无需重启服务。

## Qwen Image：现有兼容生图接口接入

本轮沿用原“模型配置 → 生图”的 OpenAI 兼容供应商行，不新增独立 Qwen 行或适配器。用户部署的外部图像服务包装既有 ComfyUI，Easel 无需加载模型或处理工作流 JSON。

项目 `.env` 配置（实际地址和本地配置不提交）：

```dotenv
IMG_BASE_URL=http://IMAGE_GATEWAY_HOST:18190/v1
IMG_MODEL=qwen-image-2.1-uc-bf16
IMG_API_KEY=local-no-auth
IMG_NO_PROXY=1
IMG_API_KEY_HEADER=
IMG_API_VERSION=
```

服务无鉴权，但现有脚本要求非空 Key，因此使用占位值；必须显式填写它，避免将真实聊天 Key 作为别名发送给新地址。设置页保存 Base URL、模型和 Key；高级配置可设置内网直连及清除旧鉴权头/API版本。切换服务前本机 `.env` 备份在用户配置目录 `env.before-qwen-image-20261009`，权限0600，不提交 Git。

```bash
python skills/shared/scripts/ai_image.py text2img \
  --prompt "一只橘猫坐在窗边，温暖的阳光，自然摄影，无文字" \
  --size 1024x1024 --n 1 --timeout 1800 \
  --output outputs/接口验收/qwen-easel-python.png
```

- `--timeout` 控制同步生成请求或异步轮询，缺省仍180秒；不是包括下载在内的整任务总超时。没有新增 UI 超时字段或隐式供应商超时，Agent 技能说明要求该 Qwen 模型显式传1800秒。
- 当前接口只实现 `/images/generations`，一次一张，尺寸为512/768/1024/1536/2048的正方形。不传 `quality` 等未支持字段，不使用 img2img/variations。图片编辑后续单独接入。
- 请求、下载均使用 Python 标准库，直接处理原有 URL/base64 返回；无需 curl 或新 Python 依赖。
- 繁忙429、生成失败502、超时504或连接中断均不自动重交。超时不代表远端取消，应先按服务日志或返回的 prompt_id 检查 ComfyUI history/queue。
- 代码改动集中在共享脚本中将同步请求预算接到已有参数；地址、模型仅留在本地配置。同步相关 `ai-image-gen/SKILL.md` 和共享脚本副本，不运行完整 OpenClaw 同步。

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

## H3 视频：两套原生服务

适配包0.2.0新增 `h3-video`；一个适配器、两个实例。`variant=fl2va` 使用文生/首帧/尾帧/首尾帧；`variant=ref2va` 使用图片、视频、音频及混合参考。不能把不同能力作为自动降级或备用模型。

### 配置与默认选择

视频设置页原供应商表同时保留原服务和 H3 实例的编辑、探活、默认选择。添加供应商选择“H3 原生视频”，填写带 `/v1` 的 Base URL、模型类型和实例名称。模型名留空按类型默认，部署服务使用 `MiniMax-H3-Turbo` / `MiniMax-H3-Ref2VA-Turbo`；无鉴权时凭证引用留空。地址写用户配置，下面仅为迁移模板：

```json
{
  "id": "h3-fl2va",
  "name": "H3 FL2VA Turbo",
  "adapter": "h3-video",
  "settings": {
    "base_url": "http://H3_FL_HOST:18191/v1",
    "variant": "fl2va",
    "model": "MiniMax-H3-Turbo",
    "timeout_seconds": 1800,
    "poll_seconds": 3,
    "use_proxy": false,
    "api_key_env": ""
  }
}
```

Ref实例使用独立ID `h3-ref2va`、类型 `ref2va`、REF地址18192及模型 `MiniMax-H3-Ref2VA-Turbo`。只将FL实例设为 video 默认，保留原 transcribe 默认。选择顺序：显式 `--provider` → 媒体配置的 video 默认 → 旧 `.env` 的 `VIDEO_PROVIDER`。选择原供应商“主”并保存将清除 video 适配器默认，其他通道保持不变；单纯编辑非主行不清除默认。

### 调用与素材

```bash
# 文生视频
.venv/bin/python skills/shared/scripts/ai_video.py text2video --provider h3-fl2va \
  --prompt "A cat gently blinks. Audio: quiet room ambience." \
  --duration 5 --ratio 16:9 -o outputs/示例/text.mp4

# 首尾帧；仅首帧省略 last-frame，仅尾帧用 text2video --last-frame
.venv/bin/python skills/shared/scripts/ai_video.py image2video --provider h3-fl2va \
  --image outputs/示例/first.png --last-frame outputs/示例/last.png \
  --prompt "A smooth camera movement connects the frames." \
  --duration 5 --ratio 16:9 -o outputs/示例/keyframes.mp4

# 多模态参考；各类参数都可重复
.venv/bin/python skills/shared/scripts/ai_video.py reference2video --provider h3-ref2va \
  --ref-image outputs/示例/person.png --ref-video outputs/示例/motion.mp4 \
  --ref-audio outputs/示例/audio.wav \
  --prompt "Use <Picture 1> as subject, <Video 1> for motion, <Audio 1> for sound." \
  --duration 5 --ratio 16:9 -o outputs/示例/reference.mp4
```

- 请求使用类型化 `VideoRequest`，`easel.media.generate_video` 是薄桥接；模型专属 `task/conditions/target`、Turbo参数和下载流程仅在 `h3.py`。两套服务都使用steps9，FL shift6/3、REF shift12/3，不将旧供应商字段直接发送给H3。
- 本轮素材为本地文件，ffprobe检查内容类型，准确MIME的Base64 data URI通过JSON发送，无需SSH或额外上传服务。不接受Agent本地路径作为H20的 file URI。
- 输出4–15秒，短边768；本轮允许16:9、9:16、1:1、4:3、3:4。视频/音频参考每段2–15秒，同类总时长不超过15秒；最多9图片/3视频/3音频、合计12份。客户端文件上限单份128MiB、合计256MiB。复杂极限组合未做压力测试。
- Ref任务至少有一份参考；本轮首尾帧属于FL实例，不接受Ref首尾帧混用。H3默认带音频；未确认关闭字段，因此 audio=off 明确拒绝。能力声明不等于对白逐字忠实或参考音轨精确保留。

### 任务记录、恢复与交付

生成仍采用同步 bridge，但适配器内部使用原生异步任务生命周期。提交前原子保存 `<输出>.job.json`，收到ID后立即更新，记录provider、实际服务地址、model、task、seed和非Base64请求参数。POST失败、超时或服务失败不自动重新提交。

轮询 `/videos/{id}`，仅completed后从同一个配置服务 `/videos/{id}/content` 下载；不跟随跳转、不使用响应中服务器本地路径。下载临时文件经ffprobe确认有效视频后原子替换输出。任务等待上限来自实例或显式 `--timeout`，下载独立300秒。

输出位置已有任务记录时拒绝新提交。带ID的任务可使用相同实例/输出路径加 `--resume` 继续查询、重新下载；恢复时不发送POST。没有ID意味着提交结果未知，应查服务日志，不盲目重交。远端任务历史未承诺跨服务重启持久化，不代表记录能恢复已丢失的任务。

```bash
.venv/bin/python skills/shared/scripts/ai_video.py image2video --provider h3-fl2va \
  --image outputs/示例/first.png --prompt "Resume the existing task" \
  --ratio 16:9 --resume -o outputs/示例/keyframes.mp4
```

旧供应商显式选择时仍走原实现，不支持新参考/恢复参数时明确报错。H3实例共用本地文件锁串行调度；其他机器及Qwen生图不受此锁控制，GPU资源协调仍属于远端运维。

### 安装、升级

重新安装适配包，构建前端，重启Easel Web发现新实现；只同步 `ai-video-gen/SKILL.md` 和 `shared/scripts/ai_video.py`，不运行完整workspace同步。不改OpenClaw源码、共享主实例或远端模型部署。配置和备份只留用户目录。

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

当前执行契约是同步完成的 `submit`；H3在适配器内部保存可恢复的原生任务记录，但不是一个通用持久化异步队列。后续新增图片/视频适配器需要通用远端任务句柄与恢复查询时，先版本化扩展契约，再由各适配器实现提交、轮询和产物收集；不要在调用方临时加 ComfyUI 节点或 H3 特有请求字段。

### 新媒体能力的接线

其他媒体通道首次迁移时：定义有类型的请求/结果 → 注册适配器 → 对应脚本只接 bridge → 加契约及效果测试。模型专属参数、工作流 JSON、切片/轮询留在独立适配包或外部 server。音乐不能假设存在与其他媒体相同的 OpenAI 协议。

## Easel 升级时关注的文件

核心接线集中在以下文件；供应商实现集中在独立包中：

| 接线位置 | 作用 |
| --- | --- |
| `easel/media.py` | 薄桥接、CLI、结果原子落盘 |
| `web/app.py` 的 `/api/settings/media*` | 通用配置与探活入口 |
| `MediaProviders.tsx`、`api.ts`、`SettingsPanel.tsx` | 按描述生成表单及选项卡接入 |
| `skills/shared/scripts/ai_video.py` | 视频调用 bridge，保留旧供应商、增加关键帧/参考参数 |
| `skills/shared/scripts/asr.py` | 字幕调用 bridge，保留 SRT/ASS 渲染及显式 Whisper |
| SDK `pipeline/run.py` 的 `st_transcribe` | 字幕优先及统一转写选择 |
| `video_pipeline.py`、SDK `pipeline/doctor.py` | 报告默认实例配置，不再提示自动 Whisper 兜底 |
| `auto-subtitle/SKILL.md`、`video-production/SKILL.md` | Agent 运行约定 |

官方升级先快进同步 `main`，在独立 `sync/*` 分支合并官方更新并检查这些接线点，验证后合并到运行分支 `dev`；长期 `dev` 不 rebase 或强推，具体流程见 [fork-maintenance.md](fork-maintenance.md)。配置仍留用户目录；需要时重新安装适配包、构建前端并重启 Web 加载代码，不需修改共享 OpenClaw 安装包。旧 GLM user-text 补丁已经退役，此接入不涉及该补丁，也不需要在任何升级中重打。

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

### 恢复 Python 直连验证（2026-10-09）

- 默认实例 `internal-qwen-asr` 的 `transport` 从 `curl` 改为 `httpx`，其他设置保持不变；变更前配置备份在用户配置目录的 `media-providers.before-python-transport-20261009.json`，权限0600，不提交 Git。
- 当前 Agent 环境 Python 到转写网关的 TCP 连接三次成功，统一入口探活成功；实际传输对象为 `httpx.Client`。
- 经默认统一入口重新转写4.204秒中文样本，正确识别“甚至出现交易几乎停滞的情况。”，13个对齐单位、1段字幕，`timestamp_source=forced_alignment`、`approx_timeline=false`，时间戳在音轨范围内，无警告。
- 结果 `/tmp/easel-asr-httpx-validation/chinese.json` 为本地临时产物。此次仅调整实例传输配置和维护说明，无需重新安装适配包或重启 Web/Gateway，未改动远端服务。

### Qwen Image 兼容接口接入验证（2026-10-09）

- 本地“生图”原供应商行已配置内网图片网关和 `qwen-image-2.1-uc-bf16`，Key使用本地占位值、关闭环境代理；设置接口返回已配置，不提交用户 `.env`。
- 经共享 `ai_image.py text2img`，显式传 `--timeout 1800`，Python直接提交并下载1024×1024 PNG；图片校验和视觉检查通过，画面为窗边阳光中的橘猫，无文字。产物 `outputs/接口验收/qwen-easel-python.png`，不提交 Git。
- 回归覆盖同步 JSON/multipart 请求将180/1800秒预算传到 urllib、Agnes兼容路径，以及超时只提交一次、不产生成功产物；全量416 passed / 3 skipped，技能与命令校验通过。
- 仅同步 Easel workspace 中的生图 SKILL 与共享脚本，未运行完整同步、未改主 OpenClaw 或远端模型服务；无需重启 Web/Gateway。

### H3 原生视频接入验证（2026-10-09）

- 两个实例原生health和探活均成功。FL2VA通过当前生视频脚本发送一张橘猫首帧，生成并下载H.264视频，1344×768、约5.18秒，含AAC音轨，抽帧可见橘猫眨眼。
- Ref2VA经相同脚本发送图片、FL视频及从该视频提取的音频混合参考，任务完成并通过 `/content` 下载；ffprobe检查和抽帧检查通过。输出不代表参考音轨被精确复刻或逐字对白能力。
- 回归覆盖文生、首/尾/首尾帧与混合条件，数量/时长/能力校验，超时恢复只提交一次，未知提交状态不重交，失败不交付文件，下载原子性，以及视频默认切换不影响ASR。
- 用户配置中保留原ASR实例，新增 h3-fl2va / h3-ref2va，默认video为FL；配置备份在用户配置目录 `media-providers.before-h3-20261009.json`。产物 `outputs/接口验收/h3-fl2va.mp4` 与 `h3-ref2va.mp4` 不提交Git。
- 全量436 passed / 3 skipped，前端tsc/Vite构建、技能/命令校验通过；浏览器自动化连接因request-header policy获取失败未完成视觉验收，配置接口已确认两行及默认状态。

## RapidOCR 图片文字识别（2026-10-09）

适配包0.3.0新增 `rapidocr`，通道 `ocr`、能力 `recognize_text`。设置页“模型配置 → 文字识别”使用同一供应商表，支持添加、编辑、探活及设为默认。首次增加通道仅在薄桥接/设置页接线，RapidOCR 协议全部留在独立 `rapidocr.py`；不修改 OpenClaw 源码或 GLM 图片模型。

迁移时安装适配包（新增 Pillow 用于真实图片格式、尺寸和 EXIF 校验），重新构建前端并重启 Web；仅同步新 `image-ocr/SKILL.md` 与共享 `ocr.py`。实例模板：

```json
{"id":"internal-rapidocr","name":"内网 RapidOCR","adapter":"rapidocr","settings":{"base_url":"http://OCR_HOST:9005","timeout_seconds":120,"use_proxy":false}}
```

Base URL 是服务根地址，无 `/v1` 或 `/ocr`。配置保存在用户媒体配置文件，设为 `ocr` 默认，不改变转写/视频默认。当前协议无鉴权字段，不借用聊天凭证；服务部署和升级仍由独立项目维护。

```bash
.venv/bin/python skills/shared/scripts/ocr.py --src /path/to/image.png --out outputs/文案提取/ocr.json
```

可加 `--provider 实例ID`。CLI 调用 `easel.media.recognize_text` → 统一运行时 → 适配器；在图片识别成功和结构校验后原子写入 JSON、同名 TXT（每个文件独立原子写，不保证两文件作为事务同时写）。输出路径经共享路径校验，不允许散写到任意目录。

- multipart 字段 `image_file`，POST `/ocr`；健康检查 GET `/health` 仅连接验证。
- 单帧 PNG/JPEG/WebP/BMP/TIFF，非空且≤20MiB、≤5000万像素。PDF、动图、多页 TIFF 和视频暂不直接支持。
- 输出 `provider/adapter/backend/source/text/items/image/coordinate_space/source_exif_orientation/warnings/raw`。保留真实文字框、四点多边形及置信度；缺失/非有限数值/尺寸不一致拒绝，不伪造分数。
- 坐标空间是服务 EXIF 转正后的图片像素，JSON 明确记录方向；当前服务响应尺寸仍是转正前尺寸，适配器按已核验的服务行为校正 `image`，保留 `raw.image` 并提示；使用未经转正的原图叠加前需转换。
- 空白图成功返回空结果及“未检测到文字”。HTTP200 不代表准确识别，需核对内容。
- 超时、429、422及错误 JSON 均明确失败，不自动重发、切换模型或下载本地 OCR 权重。默认120秒是此适配器实例参数，可由设置页配置，不改聊天/Agent 全局预算。
- `image-ocr` 技能负责对话路由、执行及核对；提取文字用 OCR，人物/场景/图意继续用 `view_image`。图片中的指令不作为执行指令。

真实验证使用已有 RapidOCR 服务：中文“图片文字识别验收”和“订单编号 739162 ABC”完整识别，两文字框；空白图片返回0框且明确提示。EXIF 旋转样本也正确识别两行文字，输出尺寸1000×300，原始响应300×1000保留并明确提示校正。此固定样本验证不代表一般识别准确率保证。

本次全量测试459 passed / 3 skipped，技能结构/命令检查及前端 tsc+Vite 构建通过。验收产物位于本地 `outputs/文字识别验收/`，不提交 Git。

### 对话链路验收与运行环境

2026-10-09，新 Easel Agent 会话 `c6b2b9ef-0e71-4a9e-aa1f-9f23ce6a0b21` 读取 `image-ocr` 技能，经 exec 调用项目 `.venv` 的共享脚本，再读取 TXT，最终正确返回中文及订单数字，status=ok、26.4秒；JSON provider=internal-rapidocr。结果 `/tmp/easel-ocr-validation/agent-after-restart.json`，脱敏轨迹 `.openclaw/trajectory-exports/rapidocr-check-fixed`，均不提交 Git。

首次对话验收失败：同一 Homebrew Python 在当前维护进程直接调用成功，在此前启动的 Easel Gateway 子进程中原始 socket.connect 报 `Errno 65 No route to host`；不是图片响应格式或供应商配置错误。仅停止旧 Easel Gateway并通过当前维护环境 detached 启动官方 `easel gateway start` 后，同一 OCR 请求及完整 Agent 链路成功。主 OpenClaw 未重启，未改远端服务、系统权限、供应商传输或聊天模型。证据支持启动进程环境影响局域网访问；具体 macOS responsible-process 权限机制未单独证实，不把它写成已确诊系统根因。

后续若终端成功而对话访问 LAN 失败，应在真正执行任务的 Gateway 子进程复测，而不是仅凭终端结果判断服务可用。先检查进程生命周期/权限上下文，不重新引入自动 curl 绕行。重启需要等旧 Gateway 排空退出；停止接收连接不表示已释放状态目录，新实例应在旧进程退出后启动。原失败轨迹 `rapidocr-check` 保留用于对照。

## Fish 官方在线 TTS（2026-10-09）

现有 `voice_clone.py` 的 `fish-audio` 路径支持 `FISH_API_KEY`、`FISH_BASE_URL`、`FISH_TTS_MODEL`，模型参数优先级为 CLI `--model`、环境变量、默认 `s2.1-pro-free`。模型放 HTTP `model` header，而非音色 `reference_id`；未知模型名在本地拒绝，避免上游静默回退付费。设置页原 Fish 行显示模型选择，无新供应商列表。省略音色使用官方默认，也支持参考音频和已有音色 ID。

用户账户网页显示每月 8,000 积分、最多 7 分钟，这是用户看到的页面额度；不能未经账户核实当作 API 免费模型额度。公开 API 文档把 `s2.1-pro-free` 标为零价、受公平使用限制，未公布固定总量；后续核查 Fish 官方公告称免费访问已延长至 2026 年 11 月，不是永久承诺（[公告](https://www.reddit.com/r/FishAudio_Official/comments/1wpo2hc/we_made_s21_pro_free_heres_how_we_cut_the_gpu_cost/)）。网页订阅额度和 API 计费需分别确认。不宣称无限量或永久免费。密钥仅写本机 `.env`，不提交。

依据：[Fish API 快速开始](https://docs.fish.audio/developer-guide/getting-started/quickstart)、[TTS 模型 header](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech)、[API 价格](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits)。

本次真实验收：明确选择 `s2.1-pro-free`，使用官方默认音色生成一句中文，返回 44KB MP3、ffprobe 时长 2.795 秒。未核查调用前后账户积分，不推断是否扣网页积分。离线验证 463 passed / 3 skipped，技能与命令验证通过。

## OpenAI 兼容 TTS / 内网 Qwen3-TTS（2026-10-09）

适配包 0.4.0 新增 `openai-speech`，通道 `speech`，能力 `generate_speech`。请求、可选语言/风格字段、音色查询、权重校验、WAV 校验都在独立 `speech.py`；Easel 仅增加 SpeechRequest/薄桥接，`tts.py` 负责分句、拼接、转码与字幕。设置页原“配音”列表内添加实例，不增加单独供应商列表。

用户配置示例（不是仓库内置个人地址）：

```json
{"id":"internal-qwen-tts","name":"内网 Qwen3-TTS","adapter":"openai-speech","settings":{"base_url":"http://TTS_HOST:18193/v1","model":"qwen3-tts","voice":"vivian","language":"Chinese","expected_model_root":"CustomVoice","timeout_seconds":300,"use_proxy":false,"api_key_env":""}}
```

无鉴权服务不要求占位 key，也不借用聊天凭证。`api_key_env` 是专用环境变量名，需要鉴权才设置。语言是可选服务扩展，普通 OpenAI TTS 可留空；风格来自实例默认或 CLI `--instructions`。`expected_model_root` 非空时，生成前核对 `/models` 对应模型的 root；本实例设 CustomVoice，避免共享别名切到 Base/VoiceDesign 后错误调用。此检查不能把权重检查与请求绑定为事务，切换服务须安排维护窗口。音色查询 `/audio/voices` 为可选扩展，不保证所有 OpenAI 服务支持。

```bash
.venv/bin/python skills/shared/scripts/tts.py voices --provider internal-qwen-tts
.venv/bin/python skills/shared/scripts/tts.py speak --provider internal-qwen-tts --voice vivian --instructions "自然亲切" --text "欢迎收听本期内容。" -o outputs/中文解说/voice.mp3 --subtitle outputs/中文解说/voice.srt
```

实际优先顺序：显式 `--engine` / 媒体 `--provider` → 媒体配置 `defaults.speech` → 旧 `.env VOICE_PROVIDER` → Edge。这不是多供应商自动 fallback 列表。明确选择/默认使用媒体实例后，超时、429、错误响应均不自动重试，也不切 Fish/Edge。旧 `--engine closed` 路径仍调用 VOICE_PROVIDER；本机该变量保留 Fish，故可手动选 Fish。`--engine edge` 手动用 Edge。设置页选旧供应商为主并保存，会清除 speech 媒体默认；新增/切换 speech 默认不改变转写、视频、OCR 默认及用户聊天模型。

第一阶段仅预置音色/风格，不开放 Base 参考音频克隆、VoiceDesign 或实时 PCM 流。服务端一次只加载一个模式，task_type 不会自行换模型。请求使用非流式 WAV、可配置单请求300秒、无自动重试、默认不读取环境代理。每句及超长无标点文本按最多200字符拆段；句间韵律可能不连续。校验非空完整 PCM WAV 后原子保存分段音频；拼接和转码成功才替换最终音频。音频、SRT、元数据分别保存，不承诺多文件事务。

SRT 是合成段真实帧数/采样率累积的句级字幕；不运行 ASR、不估算逐字时间戳。`.tts.json` 记录供应商、模型、音色、段落和 `timestamp_source=synthesized_chunk_duration`。后续如需逐字对齐，应另调用已有对齐服务。Edge rate/volume/pitch 在此适配器明确拒绝，避免静默忽略；使用 instructions。输出遵守 outputs 目录契约。

迁移：安装 `integrations/media-adapters`，配置实例及 `defaults.speech`，前端 build 并重启 Web；仅更新 tts-voiceover 技能的相关段落，保留实例项目路径说明，不执行完整 workspace 同步。其他兼容 TTS 服务新增实例即可；协议不同时新增独立适配器，不在 tts.py 增加服务专有分支。不修改远端模型服务或 OpenClaw 源码。

真实短句验收（隔离临时配置）：服务 `/models` 确認 1.7B CustomVoice，音色查询10项；显式 `serena` 和自然亲切指令生成两句中文，总时长4.56秒。WAV拼接转MP3后 ffprobe 同为4.56秒，SRT两段连续覆盖0–4.56秒。已有 Qwen ASR/对齐回读“欢迎收听千问配音测试，本次验证码是八三六二。”完整，与输入文字一致（标点有差异）。这只验证固定短样本，不代表所有音色、长文、情绪或并发性能。

提交前验证：473 passed / 3 skipped；115 个技能契约、271 条命令校验通过；前端 tsc + Vite build 通过。


### 部署与对话验收

已合并至 dev，运行目录安装适配包0.4.0，Web更新 production bundle并重启；仅同步 tts-voiceover，未重启主OpenClaw、未修改远端服务、未执行全量workspace同步。speech默认实例为internal-qwen-tts、vivian、Chinese，自然亲切；旧VOICE_PROVIDER仍为fish-audio、s2.1-pro-free，以便明确 `--engine closed` 手动调用。其他媒体默认保持原值。用户配置备份 `~/.config/easel/media-providers.before-qwen-tts-20261009-170000.json`。

新真实 Agent session `0956e0cb-2a85-46e8-824a-1d16ec7efab7`，status=ok、100.76秒（完整Agent耗时，不是模型生成速度），输出 `outputs/千问对话配音验收/agent.mp3` / `agent.srt` / `agent.tts.json`；provider=internal-qwen-tts、model=qwen3-tts、voice=vivian、音频5.2秒、两条字幕覆盖0–5.2秒。独立Qwen ASR回读“欢迎收听内网配音。今天的验证码是五九七四。”正确；对齐报告一单位零时长，不影响此处合成段字幕，未据此宣传逐字精度。CLI结果 `/tmp/easel-qwen-tts-agent.json`；真实素材及实例状态不进Git。

Chrome实查设置→配音：内网Qwen和Fish同一列表，Qwen为默认、Fish为备/手动可选；点击Qwen探活显示连接正常。这里“备”不意味着自动降级链。localhost/LAN均200，pip check通过。当前音色字段可编辑为服务返回的名称，`tts.py voices` 可列出服务音色。


## YuE2 音乐（适配包 0.6.0）

设置页“模型配置 → 音乐”原供应商表内添加 `yue2-music`，名称如“内网 YuE2”，设为默认。服务根地址不含 `/v1`，例如 `http://MUSIC_HOST:18194`；模型填 `YuE2-3B`，凭证引用 `EASEL_MEDIA_MUSIC_KEY`，实际 Bearer Key 放本机 `.env` 或启动环境。等待超时默认3600秒（包含排队），查询间隔5秒。迁移时复制用户配置中的实例和 defaults.music、单独迁移凭证，再安装适配包、重启 Web、同步本次 ai-music 技能；不会部署模型或修改远程路由。

调用路径是对话 `ai-music` 技能 → `skills/shared/scripts/ai_music.py` → `easel.media.generate_music` → 通用 `MusicRequest` → 独立 `yue2.py`。CLI 与 Web 的通用接线已经完成；后续音乐服务注册自己的适配器和描述即可复用它们，不应把特有协议写进 Web 或技能脚本。显式 `--provider` 优先，其次用户配置 defaults.music，最后旧 MUSIC_PROVIDER。选择原内置音乐供应商会清除媒体音乐默认值，不影响转写/配音等默认值。失败不自动切至付费服务。

支持歌词歌曲、纯 BGM、可选 ABC、目标生成时长及上传录音转谱翻唱/器乐改编。风格1–2000字符，歌曲歌词1–16000字符，纯 BGM 省略歌词；ABC最长64000字符，cot=full/melody/off（off 不接 ABC、纯 BGM）。界面模型名记录部署约定，不能仅凭探活确认模型身份。当前内网部署返回 backend=torch，不代表启用了 vLLM Turbo 加速。

```bash
.venv/bin/python skills/shared/scripts/ai_music.py check
.venv/bin/python skills/shared/scripts/ai_music.py generate --prompt "中文温柔钢琴流行歌曲" --lyrics-file outputs/my-song/lyrics.txt -o outputs/my-song/song.mp3
# 已知作业继续查询/下载；不再提交推理，不需要重复歌词：
.venv/bin/python skills/shared/scripts/ai_music.py generate --resume -o outputs/my-song/song.mp3
```

生成前先保存 `.job.json` 与 Idempotency-Key，POST `/v1/jobs` 后立即保存 job ID；GET 轮询后从同一服务固定地址下载，不跟随返回的任意 URL。服务 succeeded 且两个 truncated 标志明确 false 才交付；truncated/failed/cancelled 均失败。提交网络中断而未拿到 ID 时保留记录、停止重投，需用记录的 Idempotency-Key 在服务日志核查，不得因重复运行自动产生新收费或算力作业。已拿到 ID 的超时用同一输出路径 `--resume`，远端需仍保留该作业（当前7天或20GiB清理）。恢复要求实例、地址和输出路径一致。没有接入取消 CLI，不用删除本地记录代替远端取消。

保留原生 FLAC、ABC（cot!=off）、`.music.json` 元数据、`.job.json` 恢复记录；指定 MP3/WAV/M4A 时额外用 FFmpeg 转码。下载有大小限制，检查 FLAC 标识、真实音轨、完整解码及服务报告时长，再检查转码结果；不能把 HTTP200 或下载文件存在作为歌曲成功。

本轮隔离测试覆盖原生下载、转码、截断、错误、凭证、恢复和切换默认值；真实服务 seed=2026100920 作业 d9fdd4bc3d2a432f9541e15835d877c0 生成42.60秒48kHz双声道中文歌词歌曲，调用约20.69秒。音频技术校验通过不等同于人工音质评价。


### 本轮运行验收（2026-10-09）

- 分支 `feature/yue2-music` 验证后合并到运行 `dev`；适配包升级至0.5.0，重启 Web，仅同步 ai-music 技能。主 OpenClaw和 Easel Gateway无需为此次 CLI 接线重启。
- 用户配置新增 `internal-yue2`、defaults.music；转写、视频、OCR、配音默认值保留。凭证只在本机 `.env`，配置/环境备份保存在用户配置目录，不提交。页面原音乐列表显示新实例、默认与“连接正常”；localhost/LAN均200。
- 全套测试500 passed/3 skipped；115技能契约、269文档命令验证与 TypeScript/Vite构建通过。
- 新 Agent session `29e9fef2-9d31-4966-a3cb-50125b72d9cb` status=ok，约89.9秒完成整轮写歌词、生成及自检。作业 `87ca6fc987244c72850fff2dd87d25da` succeeded，原生 FLAC 42.678667秒、48000Hz、双声道；abc/semantic均未截断，后端报告 torch。产物 `outputs/YuE2对话验收/`，结果 `/tmp/easel-yue2-agent-check.json`；页面截图 `/tmp/easel-yue2-settings.png`。这些本机验收产物不进入 Git，不宣称人工试听已通过。


### 纯 BGM、目标时长与录音翻唱扩展

复用原 `yue2-music` 实例、地址和 Key，无新增供应商配置。远端需已部署第八章新版 API；更新客户端不会自动升级服务。0.6.0 安装后同步 ai-music 技能及重建前端，旧歌曲任务记录仍可 `--resume`。

- `--instrumental` 映射 `/v1/jobs` 的 instrumental=true，省略歌词；cot=off 明确拒绝。服务端负责将人声乐谱转换到器乐，不在 Easel 实现模型规划/转谱算法。
- `--duration 30` 映射 duration_seconds=30、duration_mode=target，支持10–180秒（含小数）。保存并报告目标、实测时长与偏差；偏差本身不判定作业失败，不自动裁剪、补静音、循环成品或拉伸。严格定长另用音频后处理且保留原件。
- `--reference-audio` 扩展通用 MusicRequest，经同一 generate_music 入口由适配器选择 `/v1/covers` multipart；不额外创建“翻唱供应商”。有演唱时必须提供歌词，器乐改编则传 instrumental 并省略歌词；不能同时给 cot/ABC，因为该接口自己转谱。默认不指定时长以尽量保留结构。
- 参考素材须为真实本地可解码音频，时长大于0且不超过180秒；客户端文件上限为40MiB减256KiB，给 UTF-8 字段与 multipart 留空间。先做受限临时快照、完整解码与时长校验，记录原路径、SHA256、字节数和媒体信息，再提交该快照，避免记录与上传内容不同。临时副本任务结束清理；用户原件不改动。无远程 URL 拉取，不自动截断超长录音。
- 翻唱不是歌手音色克隆或伴奏分离，而是录音转谱后重新编曲。器乐改编指定目标时长可能缩短/重复谱面并改变结构；不声称逐音或节奏细节完全保留。服务端上传录音/转谱文本与音频制品清理策略不同，不能认为全部7天自动删除。
- 作业记录增加 operation=generate/cover 和参考摘要。两种操作均先记录幂等键再 POST、立即持久化返回 ID、复用原查询/下载。已知 ID 恢复不读取原音频或歌词文件、不再上传；提交结果未知仍停止盲目重投。旧记录没有 operation 时按 generate 处理。

```bash
.venv/bin/python skills/shared/scripts/ai_music.py generate --prompt "Instrumental, gentle piano and strings, 100 BPM" --instrumental --duration 30 -o outputs/my-bgm/bgm.mp3
.venv/bin/python skills/shared/scripts/ai_music.py generate --prompt "Mandarin acoustic folk, female vocal" --reference-audio outputs/my-cover/source.flac --lyrics-file outputs/my-cover/lyrics.txt -o outputs/my-cover/song.mp3
.venv/bin/python skills/shared/scripts/ai_music.py generate --prompt "Instrumental solo piano" --reference-audio outputs/my-cover/source.flac --instrumental -o outputs/my-cover/instrumental.mp3
```

字段限制、上传协议、目标长度策略等特有行为继续集中在 `yue2.py`。CLI 只传递通用输入并报告时长；Skill 决定何时调用，Web 原表只展示实例与能力说明。旧 DashScope/Suno 实现不支持参考录音，传入时明确失败，不忽略输入；没有自动 fallback。


本轮接口验收（2026-10-09，分支 feature/yue2-music-extensions）：44项 YuE2 专项测试通过，全套517 passed/3 skipped，技能契约与272条文档命令校验、TypeScript/Vite构建通过。真实 CLI 请求统一 seed=2026100930，录音参考沿用先前生成的原创验收歌曲。结果保存在本机 `outputs/YuE2扩展验收/`（ignored）：

| 场景 | 作业ID | 目标 / 实际秒数 |
| --- | --- | --- |
| 纯 BGM | 36587cccb4c84741a8b32a6f0e671631 | 30 / 33.198667 |
| 歌词歌曲 | f45f5061ea764fa18c57117851698cba | 30 / 39.958667 |
| 录音转谱翻唱 | d8af3e87e1bd469689be6f00acae9315 | 未指定 / 43.398667 |
| 录音转器乐 | 9b66e9e5d2e44618ab4c6e2c21a10ee5 | 30 / 39.958667 |

四项均 succeeded、无截断、48kHz双声道，原生FLAC和MP3完整解码通过；两个器乐作业服务记录 vocal_notes=0，但尚未人工听审类人声或旋律保真。歌曲首次调用发生请求/保存异常，保留原 ID 后恢复查询/下载成功，没有提交新作业；此次未确认该瞬时异常的具体原因。上传翻唱29.87秒、器乐改编29.47秒（单次 CLI 端到端），不作吞吐承诺。
