# 音乐生成服务与开放模型调研

核查日期：2026-10-09。本次只调研，没有部署、购买服务、生成试听音频或修改运行配置。性能数字来自项目官方资料，不能直接作为本机或内网服务器性能承诺。

## 结论

若后续需要长期通过 Easel 自动生成音乐，优先评估 **ACE-Step 1.5**：歌曲和纯 BGM 都能做，模型 MIT 许可，官方直接提供异步 HTTP 服务，较适合目前独立媒体适配层。若主要做视频背景音乐，增加 **Stable Audio 3 Small Music** 对照试听；它有更轻的 CPU/GPU 路径，但权重许可有条件。完整人声歌曲还应将 **YuE2** 与 **MiniMax Music 3** 纳入试听：YuE2 特别适合需要乐谱规划、翻唱和编辑的个人创作者，但官方 NVIDIA 24GB 路径不适用于现有 AMD 环境，公司商用需另获授权。这里按接入和资源条件筛选，未作独立音质排名。

未找到可直接承诺“长期免费、可商用、有稳定自动化 API”的主流在线服务。免费网页、试用额度、开放权重是三种不同条件；自行部署仍占用算力、内存、存储和运维时间。此结论不等于市场上完全不存在此类服务，而是本次一手资料不足以验证。

## 在线免费与 API 的区别

| 服务 | 核查到的免费条件 | 对 Easel 自动化的意义 |
| --- | --- | --- |
| Suno 网页 | 每天 50 积分；无商业使用权、无每月下载额度；FAQ 允许最多 7 次终身试用下载 | 可试听，不等于免费 API。[套餐](https://suno.com/pricing)、[2026 年下载规则](https://help.suno.com/en/articles/13614785) |
| Suno Platform | 官方域名有音乐开发者平台和登录入口；未在公开页面核实免费 API 额度 | 不能再笼统说“没有官方 API”，也不能把网页积分用于 API。[官方平台](https://platform.suno.com/) |
| Mubert Render | 免费 Ambassador 每月 25 首生成、5 次 MP3 下载，非商用，使用时需署名 | 偏 BGM 网页体验；API 单独提供，FAQ 将 API 试用与付费开通关联。[套餐](https://mubert.com/render/pricing)、[FAQ](https://mubert.com/render/faq) |
| ACE Music / ACE-Step 官方 Space | ACE-Step README 宣传免费网页；另有官方 Hugging Face Demo | 可先试听，未核实该网页提供长期免费 API；Demo 的排队/额度不能当生产 SLA。[README](https://github.com/ace-step/ACE-Step-1.5)、[Space](https://huggingface.co/spaces/ACE-Step/Ace-Step-v1.5) |
| YuE2 / NOIZ Demo | 官方链接免费在线体验；本次公开页面显示歌曲生成、识别歌词和翻唱各“3 left” | 未查到额度重置周期、账户适用条件或免费 API 合约，不能写成每天免费 3 首或无限调用。[Demo](https://yue.noizai.net/)、[官方入口](https://github.com/multimodal-art-projection/YuE) |
| MiniMax 音乐 API | 自 2026-08-20 停止 Music-3.0-free、Music-2.6-free 和 music-cover-free；付费音乐 API 不再向新用户开放，已有付费用户可继续使用 | 网上旧“免费音乐 API”教程已经过时；官方建议网页体验或使用开放 Music 3 模型。[官方价格公告](https://platform.minimax.io/docs/pricing/overview) |

## 开放模型对比

| 模型 | 用途 | 许可与商用 | 官方推理/接入路径 |
| --- | --- | --- | --- |
| ACE-Step 1.5 / XL | 完整人声歌、纯 BGM、参考音频、局部修改 | 官方权重标 MIT，可用于商用，保留许可声明；其他组件按各自许可 | 官方 HTTP 异步服务，适合直接写媒体适配器 |
| YuE2-3B | 歌词与风格生成完整歌、符号乐谱规划、翻唱、编辑；官方另提供纯音乐工作流 | 代码 Apache-2.0；权重 CC BY-NC 4.0 加个人创作者许可，允许个人销售/商业发布输出，公司商用权重需授权 | 官方 Python/CLI；官方推荐 NOIZ YuE2-Turbo 异步 HTTP 服务，NVIDIA BF16 24GB 级路径 |
| Stable Audio 3 Small Music / Medium | 优先作为音乐/BGM、音效和音频编辑候选；不是已验证的中文歌词逐字演唱服务 | 权重 Community 许可；符合年收入低于 100 万美元等条件的个人/小企业有免费商用许可；企业/API 提供方需审查对应授权和组件条款 | Python API、CLI、Gradio；本次未确认官方独立 REST 作业服务 |
| MiniMax Music 3 | 最长约 5 分钟完整歌曲，歌词与风格分别输入 | Community 许可，允许符合条件的商业使用；需显示模型名，超过相关收入门槛需单独书面授权 | SGLang-Omni `/v1/audio/speech`；Diffusers 与 ComfyUI 路径 |
| 腾讯 SongGeneration / LeVo 2 | 中文/英文歌曲、纯 BGM、纯人声及分轨 | 仓库许可证明确限学术/研究/教育，禁止商业或生产用途 | 推理脚本和 Gradio，需额外服务封装 |
| Meta MusicGen | 文本生成音乐、旋律参考；偏纯音乐/BGM | 代码 MIT，**权重 CC-BY-NC 4.0**，不适合直接作为商用内容生产默认模型 | Python AudioCraft、Gradio，需 HTTP 封装 |
| Stable Audio Open 1.0 / Small | 音效、短乐段、loop；并非完整歌曲首选 | 权重按 Stability 条款，不能仅按推理库 MIT 判断 | `stable-audio-tools` / Diffusers；旧版 47 秒，Small 11 秒；Small 明确不能生成真实人声 |

### ACE-Step 1.5

官方标准模型约 2B，支持 50 多种语言、歌词、BPM/调性/时长及参考音频。官方介绍最长 10 分钟；XL 是更大模型，不应将 XL 与低显存标准版混为一谈。[项目说明](https://github.com/ace-step/ACE-Step-1.5)、[官方标准版模型与 MIT 许可](https://huggingface.co/ACE-Step/Ace-Step1.5)

低显存资料明确：≤4GB 档要禁用 LM、INT8 量化并 CPU/DiT 卸载；6–8GB 可选择 0.6B LM；XL 约需至少 12GB 配合激进卸载/量化，20GB 以上更合适。低显存可运行不代表完整模块常驻，也不代表能与已有模型同时运行。项目有 CUDA、ROCm、MPS/MLX、CPU 路径，具体 AMD 型号兼容仍需实测。[官方显存分档](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/GPU_COMPATIBILITY.md)

官方 REST 流程为 `POST /release_task` → `POST /query_result` → 下载返回的 `/v1/audio?path=...`；有健康检查、模型列表、队列和认证。请求支持提示词、歌词、时长及参考音频上传，结果可能将数组作为 JSON 字符串返回，需要适配解析。[官方 API 文档](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md)

### YuE2：补充重点候选

**首次调研遗漏 YuE2，现补入主要候选**。当前官方仓库 `main` 已是 2026 年 9 月发布的 YuE2，旧 YuE 1 的代码和许可保留在 `YuE-v1` 分支，不能套用旧版资源和许可结论。YuE2-3B 可先产生旋律/和弦 ABC 乐谱，再生成歌曲，并支持谱面修改、参考歌曲转谱翻唱；官方纯音乐技能把人声旋律移入乐器声部，仍需试听是否漏出人声。基础运行要求 Linux、Python 3.12、支持 BF16 的 NVIDIA GPU、24GB 显存，输出 48kHz 双声道。[官方项目与新旧版本说明](https://github.com/multimodal-art-projection/YuE)

权重不是简单 Apache 开源商用：`YuE2-3B`、两种 VAE 的许可证是 CC BY-NC 4.0，并额外允许以个人身份创作的用户、内容创作者和音乐人免费生成、发布、销售或向客户许可输出，无需模型方版税；生成作品署名可选，但分享权重仍需署名。此额外权限不授权公司商业使用权重，也不授权商业转卖权重，公司需联系作者；第三方素材权利仍由使用者自行处理。代码/文档/技能 Apache-2.0 与模型许可应分开记录。[完整模型许可](https://github.com/multimodal-art-projection/YuE/blob/main/MODEL_LICENSE)

基础 Python 包的官方预热基准：RTX 4090 24GB 的完整规划模式，214.85 秒音频耗时 71.04 秒，峰值 11.18GiB；最大上下文测试峰值 14.08GiB。官方仍建议 24GB GPU 及至少 24GB 可用主机 RAM，不能据某个样例的 11GiB 就承诺小显存部署。模型卡描述旧 wheel 支持 Python 3.10+，当前 GitHub 快速开始使用 3.12；应按选定包/提交的安装要求复现。[官方模型卡与资源基准](https://huggingface.co/m-a-p/YuE2-3B#-speed-and-resources)

官方推荐的 NOIZ **YuE2-Turbo** 保留相同模型权重与生成配方，提供 Bearer 认证、幂等任务提交 `POST /v1/jobs`、状态轮询、取消、FLAC/ABC 下载和翻唱上传接口，不需要另建 ComfyUI 包装。24GB 卡需降低并发或关闭常驻；默认按 32GB RTX 5090 调优。该卡预热后单请求官方 RTF 0.173，约为 60 秒音频耗时 10 秒；默认静态约 18GB、4 路负载峰值低于 25GB。数字不是 24GB/H20 或用户机器的实测承诺。[官方链接的 Turbo 实现、API 和资源说明](https://github.com/NoizAI/YuE2-Turbo)

质量证据需审慎解释：作者 WildSongBench 的普通 YuE2 行是两次生成后筛选，best-of-8 行筛八次；不同指标排名不一，最高均值的小差距没有证明统计显著。不能据宣传直接写成“已证明音质超过 Suno”。适配前应在同一提示词/歌词、相同候选次数下，与 ACE-Step、MiniMax 进行中文歌试听。[官方评测协议](https://github.com/multimodal-art-projection/YuE#benchmarks)

### Stable Audio 3

Small Music 官方模型卡列 0.6B、英文提示词、120 秒生成示例，使用 T5Gemma，因此还要遵守 Gemma 组件条款。它已不同于旧 Stable Audio Open 只能生成短片段的定位。参数口径需注意：官方 GitHub 模型表另列 433M，不能把不同组件统计视为同一口径。[Small Music 模型卡](https://huggingface.co/stabilityai/stable-audio-3-small-music)、[官方模型表](https://github.com/Stability-AI/stable-audio-3#models)

**Small 有 CPU-only 路径，不必占用 AMD GPU 显存**；官方 TFLite/LiteRT 路径覆盖 x86/ARM 的 Linux、Windows、macOS，并有 Apple Silicon 优化。实机耗时、CPU/RAM 占用尚未测。官方 H200 基准：Small 在 5–120 秒输出时峰值显存约 1.69–2.40GB，Medium 在 5–380 秒约 5.07–6.52GB；这是 GPU 路线测试，不是 CPU 路线必须配 GPU，也不是通用最低硬件保证。提供 Python/CLI 和 Gradio，后续 HTTP 封装可独立部署。[官方实现与性能表](https://github.com/Stability-AI/stable-audio-3)

商用需按模型许可证确认资格，Stability 许可页区分低于 100 万美元年收入的社区方案，以及企业/API 提供方方案；下载权重需同意条件，不能说无条件 MIT 商用。[官方许可页](https://stability.ai/license)

### MiniMax Music 3

输入歌词及音乐描述，输出 32kHz 16-bit 双声道 WAV。官方 GitHub 的 SGLang 服务示例是双 CUDA GPU，接口 `/v1/audio/speech` 中 `input` 放歌词、`instructions` 放风格，当前非流式。[官方服务示例](https://github.com/MiniMax-AI/MiniMax-Music3)

较新的官方 Hugging Face 文档增加 Diffusers 路径：24GB 级 GPU 常规运行，自动 CPU 卸载约 22GB，再对语言模型逐层卸载可压至 8GB，但更慢、依赖文档指定的开发版本；因此不能将“双卡”写成所有实现都必需，也不能拿 8GB 当高吞吐常驻配置。官方目前要求 CUDA，不能作为现成 AMD 部署方案。尚未在用户硬件验证；歌词执行和音质也未试听。[最新模型卡](https://huggingface.co/MiniMaxAI/MiniMax-Music3)

许可证要求商业产品 UI 显著显示 MiniMax-Music3；相关产品/服务的合计年度收入超过 2,000 万美元时需事先书面授权，向第三方提供生成服务还有防护要求。它是开放权重的定制社区许可，不是 MIT。[模型 LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE)

### 腾讯、Meta 与旧 Stable Audio Open

LeVo 2 作者发布页列 Medium 12GB/18GB、Large 22GB/28GB，前后分别为不带/带参考音频；最长约 4 分 30 秒，支持歌曲与分轨。腾讯组织的旧地址本次访问失败，作者页面及权重页仍可访问；部署前需复核原始分发来源与权重许可。[作者发布页](https://github.com/levo-demo/LeVo)、[仓库许可证](https://github.com/levo-demo/LeVo/blob/main/LICENSE)。该许可证的学术/研究/教育限定包含代码和权重，不因为能生成 BGM 就变成可生产使用。

MusicGen 的 300M Small 适合降低资源需求，1.5B Medium 官方建议至少 16GB 显存；提供 Python 接口和 Gradio，不是现成通用音乐 HTTP 标准。其非商用权重许可是本次不把它作为 Easel 生产首选的主要原因。[官方推理说明](https://github.com/facebookresearch/audiocraft/blob/main/docs/MUSICGEN.md)、[代码与权重许可](https://github.com/facebookresearch/audiocraft)

Stable Audio Open 1.0 最长 47 秒双声道，Small 最长 11 秒且官方说明无法生成真实人声；适合短音效/loop，新增部署时应先与最新 Stable Audio 3 对比。[1.0 模型卡](https://huggingface.co/stabilityai/stable-audio-open-1.0)、[Small 模型卡](https://huggingface.co/stabilityai/stable-audio-open-small)

## 与 Easel 的接入边界

研究建议及当前落实状态：

1. 先试听 30–60 秒纯 BGM 和中文歌词歌各若干条，确认无意外人声、歌词准确性、音质和真实时长。
2. 默认先采用模型官方服务；ACE-Step 已有任务提交/轮询/下载，不必为了接入额外部署 ComfyUI。YuE2 可评估官方推荐的 YuE2-Turbo 服务；Stable Audio 3 若入选，可以独立包装 HTTP 服务；Music 3 可用官方 SGLang 服务。
3. 已实现 `MusicRequest` 和独立 `yue2-music` 适配器，实例在原音乐配置列表显示。请求统一包含提示词、歌词、纯音乐标志、时长、输出路径及恢复选项；YuE2 对不支持的纯音乐/指定时长明确拒绝，协议留在适配包。
4. `/v1/audio/speech` 只是 Music 3 使用的传输路径，不能因此把歌曲加入 TTS 配音频道。TTS 的逐句切分/拼接会破坏音乐结构，需音乐独立语义。
5. 验收应记录实际模型、任务 ID、生成参数及音频时长，检查失败/超时/下载行为。HTTP 200 不等于音质、歌词或纯音乐要求已满足。

当前 Easel 旧 `dashscope` / `suno-compatible` 音乐实现是通用模板，不能只填任意新服务的 Base URL 就认定兼容。后续用户批准的 YuE2 接入已实现，配置、迁移与验证见 [媒体适配器维护文档](media-adapters.md#yue2-歌词歌曲适配包-050)。
