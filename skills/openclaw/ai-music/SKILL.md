---
name: ai-music
description: "AI 音乐与歌曲生成：按曲风和歌词生成带演唱歌曲，或使用支持纯音乐的供应商生成 BGM；可用 ABC 乐谱规划与修改。支持参考录音转谱翻唱和器乐改编。用户说“翻唱”“纯音乐改编”“生成歌曲”“写首歌”“AI 音乐”“AI 配乐”“生成 BGM”“背景音乐”“原创音乐”“AI 作曲”“纯音乐”“给视频配乐”时使用。使用默认音乐供应商；口播、旁白、朗读用 tts-voiceover。"
layer: produce
---

# AI 音乐与歌曲

共享入口 `skills/shared/scripts/ai_music.py`：提交任务 → 查询 → 下载音频。

**配置检查路径铁律**：先 `cd` 到实例 AGENTS.md 给出的 Easel 项目根，使用项目 `.venv/bin/python`；不要改用 workspace 的共享脚本副本，也不要打印 `.env` 或凭证。

## 选择与输入

- 显式 `--provider 实例ID或旧供应商名` → 媒体配置 music 默认 → `.env MUSIC_PROVIDER`。有默认直接使用，不再因存在多个供应商而反复询问。
- 先运行 `check`。它是离线配置检查，不表示服务就绪或音质通过。
- 用户要求歌曲而没给歌词时，可按主题创作歌词，写到 `outputs/<具体主题>/lyrics.txt`，以 `[Verse]` / `[Chorus]` 分段；保留完整歌词和风格提示词。
- YuE2 支持歌曲、纯 BGM、ABC 乐谱与参考录音转谱翻唱。歌曲/有人声翻唱要求非空歌词；纯 BGM 使用 `--instrumental` 且省略歌词，不虚构歌词或偷偷切换供应商。
- 用户说“约30秒”时用 `--duration 30`（10–180秒），表示目标生成长度；交付同时报告目标、实际与偏差，不声称严格定长。服务不裁剪或拉伸；用户明确要求严格长度时另用音频后处理，保留原件。
- 纯 BGM 不能用 cot=off。给定目标时长的器乐改编会缩短或重复乐谱，可能改变原曲结构；用户只要求保留旋律时默认不指定时长。
- 翻唱用 `--reference-audio` 指向用户附件的真实本地路径，不捏造路径。它是 SheetSage2/MERT 转谱后重新编曲生成，不能承诺克隆歌手、保留原伴奏或所有节奏细节。有人声翻唱须提供或创作与旋律匹配的歌词；缺少歌词时可用 ASR 辅助，再检查，不把识别当成逐字准确。
- 录音需可解码、时长大于0且不超过180秒，上传整个请求不超过40MiB（客户端预留256KiB）。超限说明原因，不擅自截断用户录音。录音翻唱不能同时传 `--abc-file` / `--cot`；服务自动转谱。
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

# 约30秒纯 BGM，无唱词；实际时长可能有偏差
python skills/shared/scripts/ai_music.py generate \
  --prompt "Instrumental, warm piano and strings, no vocals, 100 BPM" \
  --instrumental --duration 30 -o outputs/钢琴配乐/bgm.mp3

# 上传旋律转谱翻唱；歌词另存UTF-8文件
python skills/shared/scripts/ai_music.py generate \
  --prompt "Mandarin acoustic folk, female vocal, acoustic guitar" \
  --reference-audio outputs/翻唱/source.flac --lyrics-file outputs/翻唱/lyrics.txt \
  -o outputs/翻唱/song.mp3

# 上传旋律改编为器乐，默认不指定时长以尽量保留结构
python skills/shared/scripts/ai_music.py generate \
  --prompt "Instrumental, solo piano, no vocals" --instrumental \
  --reference-audio outputs/器乐改编/source.mp3 -o outputs/器乐改编/song.mp3

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
- `<音频文件>.job.json` 保存任务 ID、幂等键、原请求和状态；翻唱额外保存参考路径/摘要/时长，不含 Key。输出已有文件或记录时拒绝新提交，避免覆盖或重复生成。
- 有 ID 的超时/断线用相同供应商与输出 `--resume` 继续查询/下载，无需原参考录音，也不再次上传。若提交结果未知、没有 ID，停止并让维护者按已保存幂等键核查服务，不换键盲目重发。
- 仅 succeeded 且没有截断标记才交付。truncated、failed、cancelled 明确报错；HTTP 200 或可播放音频不代表完整歌曲/歌词质量通过。纯 BGM 仍需听审类人声；无听音能力不能宣称已确认无人声或旋律完全保真。
- 下载使用同一服务的认证接口，不跟随服务返回的外部 URL；完成后及时本地保存，远端有清理策略。
- 不自动重试提交，不自动换供应商。音乐与视频可能共享远端资源，建议错峰。
- 用户要试听时交付可播放音频；需要歌词字幕时另用 ASR/对齐，不按歌词长度伪造时间戳。

裁剪、响度归一化与配视频复用 `audio_ops.py` / `video_ops.py`；裁剪属于后处理，不宣称模型精确生成了指定秒数。
