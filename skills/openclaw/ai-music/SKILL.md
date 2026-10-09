---
name: ai-music
description: "AI 音乐与歌曲生成：按曲风和歌词生成带演唱歌曲，或使用支持纯音乐的供应商生成 BGM；可用 ABC 乐谱规划与修改。用户说“生成歌曲”“写首歌”“AI 音乐”“AI 配乐”“生成 BGM”“背景音乐”“原创音乐”“AI 作曲”“纯音乐”“给视频配乐”时使用。使用默认音乐供应商；口播、旁白、朗读用 tts-voiceover。"
layer: produce
---

# AI 音乐与歌曲

共享入口 `skills/shared/scripts/ai_music.py`：提交任务 → 查询 → 下载音频。

**配置检查路径铁律**：先 `cd` 到实例 AGENTS.md 给出的 Easel 项目根，使用项目 `.venv/bin/python`；不要改用 workspace 的共享脚本副本，也不要打印 `.env` 或凭证。

## 选择与输入

- 显式 `--provider 实例ID或旧供应商名` → 媒体配置 music 默认 → `.env MUSIC_PROVIDER`。有默认直接使用，不再因存在多个供应商而反复询问。
- 先运行 `check`。它是离线配置检查，不表示服务就绪或音质通过。
- 用户要求歌曲而没给歌词时，可按主题创作歌词，写到 `outputs/<具体主题>/lyrics.txt`，以 `[Verse]` / `[Chorus]` 分段；保留完整歌词和风格提示词。
- YuE2 当前要求非空歌词，首期仅接入歌曲与已有 ABC 乐谱；不支持 `--instrumental`、固定生成秒数或参考录音上传。用户要纯 BGM 时明确说明当前默认不支持，不偷偷改用付费服务或生成有唱词的歌曲。
- YuE2 的 `--prompt` 描述语言、曲风、乐器、歌声和 BPM，最多2000字符；歌词最多16000字符。
- `--cot full`（默认）规划旋律与和弦，`melody` 仅旋律，`off` 不规划乐谱。`--abc-file` 提供已有 UTF-8 ABC，不能与 off 同用。
- 每次新请求默认产生新种子，`--seed` 可固定；保存种子有助对照，但不是跨环境音频字节复现保证。

## 执行

```bash
python skills/shared/scripts/ai_music.py check

# 默认音乐供应商；歌词文件放在项目产物目录
python skills/shared/scripts/ai_music.py generate \
  --prompt "Mandarin, warm piano pop, clear female vocal, gentle drums, 88 BPM" \
  --lyrics-file outputs/晚风与星光/lyrics.txt \
  -o outputs/晚风与星光/song.mp3

# 修改 ABC 后重新生成整首录音，不是局部保留原波形
python skills/shared/scripts/ai_music.py generate \
  --prompt "Mandarin, acoustic pop, guitar and piano, warm vocal" \
  --lyrics-file outputs/晚风与星光/lyrics.txt \
  --abc-file outputs/晚风与星光/edited.abc --cot full --seed 42 \
  -o outputs/晚风与星光/rearranged.flac

# 超时后按相同输出位置恢复；不重复提交
python skills/shared/scripts/ai_music.py generate --resume \
  -o outputs/晚风与星光/song.mp3
```

不传 `--timeout` 使用媒体实例等待预算（含排队）；它不是服务端执行超时。等待期间让 exec 进入后台会话，定期查询进程输出，不因工具一次等待结束就重新提交。

旧 `dashscope` / `suno-compatible` 可以显式选择，仍依赖 `.env` 配置；它们是尚未用真实服务验证的旧实现，不把兼容格式称为行业标准。

## 交付与任务恢复

- 音频支持 FLAC、MP3、WAV、M4A；转码使用 FFmpeg。保留原生 FLAC、有规划时的 `.abc` 和 `.music.json` 元数据。
- `<音频文件>.job.json` 保存任务 ID、幂等键、原请求和状态；不含 Key。输出已有文件或记录时拒绝新提交，避免覆盖或重复生成。
- 有 ID 的超时/断线用相同供应商与输出 `--resume` 继续查询/下载。若提交结果未知、没有 ID，停止并让维护者按已保存幂等键核查服务，不换键盲目重发。
- 仅 succeeded 且没有截断标记才交付。truncated、failed、cancelled 明确报错；HTTP 200 或可播放音频不代表完整歌曲/歌词质量通过。
- 下载使用同一服务的认证接口，不跟随服务返回的外部 URL；完成后及时本地保存，远端有清理策略。
- 不自动重试提交，不自动换供应商。音乐与视频可能共享远端资源，建议错峰。
- 用户要试听时交付可播放音频；需要歌词字幕时另用 ASR/对齐，不按歌词长度伪造时间戳。

裁剪、响度归一化与配视频复用 `audio_ops.py` / `video_ops.py`；裁剪属于后处理，不宣称模型精确生成了指定秒数。
