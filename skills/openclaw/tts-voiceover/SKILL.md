---
name: tts-voiceover
description: "文字转语音配音：把文案/脚本合成为 AI 语音口播、旁白、朗读音频。优先使用设置页配音默认媒体供应商；未配置时沿用 VOICE_PROVIDER/Edge。明确选择的媒体供应商失败时不得切换。同步输出分句 SRT 字幕、mp3/wav/m4a。合成后可与 BGM 混音或加到视频作旁白。当用户说“配音”“文字转语音”“TTS”“AI 配音”“口播语音”“旁白”“朗读”“把这段文字读出来”“生成语音”“语音合成”时使用。"
layer: produce
---

# 文字转语音配音（TTS Voiceover）

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和 `skills/shared/scripts/`。媒体实例先用项目根的 `.venv/bin/python -m easel.media providers` / `tts.py voices` 核查；旧云 TTS 配置用项目根的 `model_registry.py configured --group voice --env-file .env` 和 `voice_clone.py check ... --env-file .env` 判断；不得在 workspace 跑 `./shared/scripts/...`，也不得用 `env` / `printenv` 推断 Key/URL 缺失。

把文案 / 脚本合成为 AI 语音（口播、旁白、朗读）。共享脚本 `skills/shared/scripts/tts.py speak`：
**默认顺序**：显式引擎/媒体实例 → 设置页配音默认媒体实例 → 旧 `VOICE_PROVIDER` → Edge。
媒体实例失败就报错，不自动调用 Fish、Gemini 或 Edge。未配置媒体默认时，旧云端 auto 路径失败仍可能回退 Edge；`--engine closed` 则明确报错。
音色以该供应商设置为默认，`--voice vivian` 等显式参数可覆盖；不得混用 Edge/CosyVoice 音色名。
内网 Qwen 当前仅 CustomVoice 预置音色和风格控制，不能通过 task_type 自动切换权重。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| text / file | 是 | 待配音的文本，或文本文件路径（长文本推荐 --file） |
| voice | 否 | 媒体服务使用实例默认；Edge 默认晓晓 |
| rate/volume/pitch | 否 | Edge 专用；媒体服务用 instructions |
| output | 否 | 默认 `outputs/主题名/{name}.mp3` |

## 输出

- 配音音频文件（mp3，可选 wav/m4a），放入 `outputs/主题名/`
- 可选同步输出 SRT 字幕（`--subtitle`），供视频烧字幕用
- 打印实际执行的 edge-tts 命令 + 输出文件时长/大小/音色

## Edge 专用：外网代理

edge-tts 调微软在线服务，**必须能访问外网**。内网环境先设代理：

```bash
export https_proxy=http://<代理host>:<端口> http_proxy=http://<代理host>:<端口>
```

脚本会自动读环境变量代理并透传给 edge-tts（也可用 `--proxy` 覆盖）。

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/tts.py`。每个子命令支持 `-h`。

### 0. 挑音色（可选）

```bash
python skills/shared/scripts/tts.py voices          # 默认媒体服务音色；未配置时为 Edge
python skills/shared/scripts/tts.py voices --engine edge --all    # Edge 全量中文音色（需外网）
```

### 1. 合成配音 speak

```bash
# 最简：一句话 → mp3
python skills/shared/scripts/tts.py speak --text "欢迎来到本期内容" \
  -o outputs/主题名/intro.mp3

# 手动选择 Edge：长文本 + 换音色 + 加速 10%
python skills/shared/scripts/tts.py speak --engine edge --file script.txt \
  -o outputs/主题名/narration.mp3 --voice zh-CN-YunxiNeural --rate +10%

# 同步出 SRT 字幕（视频烧字幕用）
python skills/shared/scripts/tts.py speak --file script.txt \
  -o outputs/主题名/vo.mp3 --subtitle outputs/主题名/vo.srt

# 输出 wav（需 ffmpeg，便于后续无损处理）
python skills/shared/scripts/tts.py speak --text "……" \
  -o outputs/主题名/vo.wav --format wav
```

Edge 专用参数：`--rate +10%`（语速）、`--volume +20%`（音量）、`--pitch +2Hz`（音调）。

### 2. 后处理（可选，复用已有共享脚本）

配音出来后按需接下游脚本，无需在本 SKILL 重造能力：

```bash
# ① 配音 + BGM 混音（原声 1.0 / BGM 0.3）→ 用 audio_ops concat / video_ops bgm
python skills/shared/scripts/video_ops.py bgm -i vo.mp3 -o vo_bgm.mp3 \
  --music bgm.mp3 --voice-volume 1.0 --music-volume 0.3

# ② 配音音量归一化到社媒响度（-14 LUFS）
python skills/shared/scripts/audio_ops.py normalize vo.mp3 -o vo_norm.mp3

# ③ 把配音作为旁白加到视频
python skills/shared/scripts/video_ops.py bgm -i clip.mp4 -o clip_vo.mp4 \
  --music vo.mp3 --voice-volume 0.4 --music-volume 1.0
```

## 常用中文音色

| 音色 | 特点 |
|------|------|
| `zh-CN-XiaoxiaoNeural` | 晓晓 · 女声，温暖亲和，通用首选（默认） |
| `zh-CN-XiaoyiNeural` | 晓伊 · 女声，活泼年轻，口播/种草 |
| `zh-CN-YunxiNeural` | 云希 · 男声，清朗自然，旁白/解说 |
| `zh-CN-YunyangNeural` | 云扬 · 男声，专业沉稳，新闻/播报 |
| `zh-CN-YunjianNeural` | 云健 · 男声，浑厚有力，激情内容 |

粤语用 `zh-HK-HiuMaanNeural`（曉曼），台式用 `zh-TW-HsiaoChenNeural`（曉臻）。

## 规则

1. **绝不覆盖原始素材** — 只写新文件到 `outputs/主题名/`。
2. **长文本走 --file** — 避免命令行过长 / 换行转义问题。
3. **先设代理** — edge-tts 需外网，网络失败脚本会给明确提示。
4. **不重造能力** — 混音/归一化/加视频旁白复用 audio_ops.py / video_ops.py。
5. **无 Profile 也能用** — 无画像时用默认音色晓晓。

## Profile 感知

有 Profile 时可读取平台调性；偏好音色必须属于当前供应商，不得把 Edge 音色传给内网服务。
无 Profile 使用当前媒体实例的默认音色；明确选择 Edge 时才使用晓晓。

## 内网配音与手动选择

```bash
python skills/shared/scripts/tts.py speak --text "欢迎收听本期内容。" -o outputs/中文解说/voice.mp3 --subtitle outputs/中文解说/voice.srt
python skills/shared/scripts/tts.py speak --provider internal-qwen-tts --voice vivian --instructions "自然亲切" --text "你好。" -o outputs/中文解说/voice.wav
python skills/shared/scripts/tts.py speak --engine closed --text "你好。" -o outputs/中文解说/fish.mp3
python skills/shared/scripts/tts.py speak --engine edge --text "你好。" -o outputs/中文解说/edge.mp3
```

`closed` 调用旧 VOICE_PROVIDER（当前用户 Fish）；不是固定指向 Fish。内网服务每段最多200字符，按句合成 WAV，按真实段时长写句级字幕，最后转目标格式。`.tts.json` 记录实际供应商、模型、音色及时间戳来源；不宣称逐字对齐。Edge 的 rate/volume/pitch 不适用于此适配器，使用 instructions 描述风格。输出写 `outputs/<具体主题>/`。
