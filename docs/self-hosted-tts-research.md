# 中文自部署 TTS 调研

调研日期：2026-10-09。仅查阅官方仓库、官方模型卡、作者论文和推理框架文档；没有部署模型、修改配置或试听比较。下文的用途优先级是工程判断，不能当作统一音质排名。

## 第一批候选

优先试 **Qwen3-TTS 1.7B CustomVoice** 做中文固定音色旁白，再用 **IndexTTS-2.5** 比较角色克隆与情绪控制；需要多方言及服务部署成熟度时比较 **CosyVoice3**。GPT-SoVITS 适合把一个角色长期维护成专用音色的训练工作流。它们都可本地推理，不等同于 Edge TTS 那种在线服务。

| 系列 | 本次核实的开源权重/版本 | 更适合的第一轮用途 | 注意事项 |
| --- | --- | --- | --- |
| Qwen3-TTS | 12Hz 1.7B CustomVoice / VoiceDesign / Base；0.6B CustomVoice / Base | 无参考音频的预置中文旁白；自然语言控制风格 | 克隆使用 Base；声音设计使用 VoiceDesign，不能认为一个权重包办三种模式 |
| CosyVoice3 | Fun-CosyVoice3-0.5B-2512，包含基础与 RL 权重 | 中文/方言、跨语言克隆、流式语音 | 开源 checkpoint 与百炼商业模型名称不是一回事 |
| IndexTTS | 最新 2.5，2026-08-10 发布 | 参考音色克隆、情绪、中文发音修正 | 需要参考音频；长文本按段拼接 |
| GPT-SoVITS | 主分支已有 V5；V2Pro/ProPlus 仍有独立版本 | 固定角色、少量数据微调、成熟 WebUI 工作流 | Releases 页最新 tag 仍为 V2Pro，部署必须记录代码提交与实际权重 |

版本依据：[Qwen 官方发布表](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)、[CosyVoice 官方模型卡](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)、[IndexTTS 官方版本说明](https://github.com/index-tts/index-tts#-news)、[GPT-SoVITS V5 说明](https://github.com/RVC-Boss/GPT-SoVITS#v5-release-notes)与[发布页](https://github.com/RVC-Boss/GPT-SoVITS/releases)。

## 千问具体怎么选

**有专门的 Qwen3-TTS，自部署不需要部署 Qwen3-Omni 大型多模态模型。** 已发布权重有 0.6B/1.7B 两个规模，覆盖中文等 10 种语言。CustomVoice 有 9 个预置音色，其中包括普通话、北京和四川声音；1.7B 支持风格指令。VoiceDesign 按文字描述生成新声音；Base 从参考音频克隆，标准路径同时传参考文字，只用声纹、不传文字会降低克隆质量。[官方模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)

Qwen 技术报告还讨论 25Hz 系列和 VoiceEditing，但截至本次核查，仓库正式下载表只列上述 5 个 12Hz TTS checkpoint；不能把论文里的每个变体都当成已可下载。代码为 Apache-2.0，官方 12Hz 模型卡也标 Apache-2.0。[代码许可证](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE)、[模型发布表](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)

百炼的 `qwen3-tts-flash`、`qwen3-tts-instruct-flash`、`qwen-audio-3.1-tts-flash` 等是商业 API 名称，不能据此寻找完全同名的自部署权重；商业 CosyVoice v3.5 也不等于开源 Fun-CosyVoice3 checkpoint。选型时应写清 HF 模型 ID。[百炼模型清单](https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide)

## 中文效果与 SOTA 的边界

没有发现一份能够把截至今天所有新模型、同一个中文音色、相同推理配置和盲听条件统一比较的独立结论。WER/CER 衡量是否读对，声音相似度衡量是否像参考人，MOS/盲听衡量听感；它们不能互相替代。

Qwen 作者报告在 Seed-TTS 中文测试中，12Hz-1.7B-Base 错误率 0.77%，0.6B 为 0.92%，同表 CosyVoice3 为 0.71%；因此这张表也不能用来宣称 Qwen 在中文所有方面第一。报告长文本最佳结果来自 25Hz 1.7B 和特定微调音色/内部测试，不能直接归到已发布 12Hz CustomVoice。[Qwen 技术报告 Table 5 与长文本章节](https://arxiv.org/html/2601.15621v1)

CosyVoice 官方当前表中，实际开源 Fun-CosyVoice3-0.5B-2512 中文 CER 为 1.21%，RL 为 0.81%，与论文里较早的完整 CosyVoice3 实验数值不同。RL 提升读字准确率，但表中声纹相似度略降低，不能把 RL 当作所有维度均更好。[官方评测表](https://github.com/QwenAudio/CosyVoice#evaluation)

IndexTTS-2.5 支持音色情感分离、中文拼音/英语音素/日语假名修正、0.5–2.0 duration_factor；情绪文本控制需额外开启 QwenEmotion，长文本跨段韵律不连续。它很适合列入中文角色配音试听，而不是仅凭参数量判断音质。[官方模型卡及限制](https://huggingface.co/IndexTeam/IndexTTS-2.5)

GPT-SoVITS 官方支持中文/粤语等语言，约 5 秒参考音频零样本合成，也有约 1 分钟数据微调路径；V5 改善无 SoVITS 微调的相似度与声码器伪影。这里没有统一对其他新模型的中文盲听证据，因此推荐它的理由是角色训练生态与工作流。[官方仓库](https://github.com/RVC-Boss/GPT-SoVITS)

## 社区规模

2026-10-09 通过 GitHub 官方 API 实际获取的 Star 数：

| 仓库 | Stars |
| --- | ---: |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 62,560 |
| [IndexTTS](https://github.com/index-tts/index-tts) | 24,372 |
| [CosyVoice](https://github.com/QwenAudio/CosyVoice) | 23,894 |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | 13,703 |

这些是整个项目累计关注度，不是某个新 checkpoint 的真实部署量，也不是中文音质排名。CosyVoice 仓库已从 FunAudioLLM 迁到 QwenAudio，原地址仍重定向。

## 代码、权重与部署要求

| 候选 | 代码许可证 | 官方权重许可证 | 本次核实的硬件说明 |
| --- | --- | --- | --- |
| Qwen3-TTS | Apache-2.0 | 官方 12Hz 模型卡 Apache-2.0 | 官方推荐独立 Python 3.12、BF16/FP16 和 FlashAttention 2；未找到承诺的最低推理显存 |
| CosyVoice3 | Apache-2.0 | 2512 模型卡 Apache-2.0 | 官方环境 Python 3.10；可用本身 FastAPI/gRPC、vLLM；未找到统一最低显存 |
| IndexTTS-2.5 | 当前仓库为 bilibili Model Use License | 模型卡同样 bilibili-model-license | 官方模型卡写 NVIDIA、Python 3.10–3.11、推理大约 6GB VRAM；长文本、附加模型、并发需要实测 |
| GPT-SoVITS | MIT | 官方 lj1995/GPT-SoVITS 标 MIT | 官方列 CUDA、CPU、Apple Silicon 环境；不同版本负担不同，不能拿某个旧版低显存数字保证 V5 |

许可证依据：[Qwen 代码](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE)/[权重](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)、[CosyVoice 代码](https://github.com/QwenAudio/CosyVoice/blob/main/LICENSE)/[权重](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)、[Index 代码协议](https://github.com/index-tts/index-tts/blob/main/LICENSE)/[权重](https://huggingface.co/IndexTeam/IndexTTS-2.5)、[GPT 代码](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/LICENSE)/[权重](https://huggingface.co/lj1995/GPT-SoVITS)。部署说明见上述模型卡与官方仓库。

Index 当前协议覆盖代码和权重，不是 MIT/Apache；有大规模企业门槛、禁止用其改善其他商业 AI 模型等条件，不能笼统标为“无限制商用”。依赖或另行下载的辅助模型也应单独记录版本与许可证；这里只核对各项目主代码和指定主权重。[Index 正式协议](https://github.com/index-tts/index-tts/blob/main/LICENSE)

建议在现有 NVIDIA 服务端独立环境验收，先一模型、一进程、并发 1、短中文稿，记录空闲/峰值 VRAM、首音频时间、总耗时及长文完整度。以上不是部署命令；没有假定某张卡已有可用显存，也没有更改 H3/Qwen Image 的 GPU 安排。

## 接入 Easel 的工程方向

先核实成熟推理服务，不急着自行包装。**vLLM-Omni 官方现在有 Qwen3-TTS 的 OpenAI 兼容 `POST /v1/audio/speech` 在线服务**，包括 CustomVoice、VoiceDesign、Base；扩展字段支持 instructions、language 和参考音频。模型的能力比标准 OpenAI 基础字段多，Easel 普通配音路径可先验收，克隆/情绪扩展再经统一媒体适配器表达。[官方在线 TTS 文档](https://docs.vllm.ai/projects/vllm-omni/en/stable/user_guide/examples/online_serving/text_to_speech/)

注意文档版本差异：Qwen 自己的 README 仍写 vLLM-Omni 仅离线，但推理框架当前在线文档已更新。部署应 pin 具体版本并实测；CosyVoice 在通用 Speech API 中列支持，但在线 examples 又说没有其 example，不据此保证所有模式已完整。原项目本身也提供 FastAPI/gRPC，若需要专有参数，可以由 Easel 独立适配器调用。[vLLM-Omni Speech API](https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/speech_api/)、[CosyVoice 原生服务](https://github.com/QwenAudio/CosyVoice#build-for-deployment)

第一轮验收使用同一批中文稿、固定音色，包含多音字、人名、金额日期、英文缩写、情绪转折和 3–5 分钟解说。既听自然度，也用现有 Qwen ASR/对齐检查漏字重复；ASR 有自身误差，最终需要人工听读核对。

## Fish 与其他补充候选

| 候选 | 为什么值得比较 | 部署及许可边界 |
| --- | --- | --- |
| Fish Speech S2-Pro | 中文、多语种、短参考音频克隆和富表现力配音；可下载自部署 | 官方标准安装说明要求推理 24GB GPU 显存；Research License 允许研究/非商业使用，商业用途需另获授权 |
| MOSS-TTS-v1.5 / Local-Transformer-v1.5 | 长文、多语种及克隆；多人对话另有 MOSS-TTSD | 分别为 8B / 4B，家族模型 Apache-2.0；低显存优化路线不能代替默认推理配置的实际验收 |
| MOSS-TTS-Nano | 约 100M 参数，CPU 优先、实时流式和克隆，适合另做轻量服务对照 | 官方称四核 CPU 可实时；这是作者结果，自己的语种、并发与 CPU 必须实测 |
| Breeze TTS 2 | 中文/英文、自然语言声音设计、克隆、情绪及非语言声音 | 官方建议普通推理 12GB、加速路径 24GB；代码 Apache-2.0，但权重和自部署输出限研究/非商业，不能因代码许可宽松就按无限制商用处理 |

Fish 自部署权重 S2-Pro 与上一轮讨论的云端 `s2.1-pro-free` 不是同一个交付物；不能把云端免费接口当成开源自部署许可。官方原生服务为 `/v1/tts`，也不能未经验证当成 OpenAI `/v1/audio/speech` 即插即用。[Fish 模型卡](https://huggingface.co/fishaudio/s2-pro)、[安装要求](https://speech.fish.audio/install/)、[原生服务](https://speech.fish.audio/server/)、[正式许可证](https://github.com/fishaudio/fish-speech/blob/main/LICENSE)

MOSS 当前完整模型家族及不同推理架构应分别选型：普通旁白没有必要一开始就部署多人对话、实时语音或音效模型。vLLM-Omni/SGLang-Omni 的支持随架构不同；官方列出的 8GB 方案依赖量化、分阶段加载等特定路线，不表示默认 BF16 8B 服务占用仅 8GB。[MOSS 官方仓库与模型表](https://github.com/OpenMOSS/MOSS-TTS)、[Nano 官方仓库](https://github.com/OpenMOSS/MOSS-TTS-Nano)

Breeze 的模型卡宣称开放权重榜第一，但特定榜单的语种、音色、版本与试听规则不能替代我们自己的中文配音验收；其模型卡同时明确商业托管订阅并不授予开放权重或自部署输出的商业权利。[Breeze 官方模型卡与硬件/许可说明](https://huggingface.co/BreezeBlue/Breeze-TTS-2)

## 针对本环境的结论

先做 **Qwen3-TTS 1.7B CustomVoice** 的固定中文旁白服务；若目标是复制指定声音，则改选 **1.7B Base**，不是让 CustomVoice 直接接参考音频。对情绪/角色有明显要求，再拿 **IndexTTS-2.5** 同稿试听；方言、流式及既有服务生态优先看 **CosyVoice3**。Fish 可以作为效果对照，选择它之前要接受其推理显存和许可条件。轻量 CPU 部署另外评估 MOSS-TTS-Nano。

这是候选顺序，不是宣称中文统一 SOTA。Gemini TTS 没有在本次查到可下载的同款自部署权重，Edge TTS 客户端仍调用微软在线服务，二者不属于本次自部署候选。既有 H20 机器是否适合新增服务，要依据实际剩余显存与 H3/Qwen Image 的并发负载，不能只看显卡型号。

只完成调研与文档记录；本次没有安装模型、启停远端服务、调整 GPU、修改 Easel 配音默认项或写入任何密钥。
