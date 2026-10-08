# 通用媒体适配层设计

状态：2026-10-08 的原始设计。转写首阶段已经实现，实际安装、配置和扩展契约见 [media-adapters.md](media-adapters.md)；本文件保留完整目标与调研基线。

## 目标与术语

让语音转写、配音、生图、视频、音乐共享供应商配置、能力发现、任务生命周期和错误处理；各能力保留自己的输入与结果类型。具体 Qwen Image/H3 的 ComfyUI 或直连接口方案留待后续选择。

- **通道**：界面分类，如转写、生图；不是供应商。
- **能力**：具体操作，如转写、时间对齐、文生图、图像编辑、首尾帧视频。一个通道可包含多种能力。
- **供应商实例（provider）**：用户配置的一项服务，具有唯一 ID、名称、适配器、连接配置、模型和能力。可以是商业平台，也可以是自部署服务；同一协议可以配置多个实例，一个实例可以服务多个通道。
- **适配器（adapter）**：把某种协议转换为统一请求、任务状态和结果的实现代码。与供应商实例分离。
- **模型**：实例提供的具体模型或模型别名；能力应按模型声明和校验，不能只按供应商品牌推断。

例如“内网 Qwen 转写”是一个供应商实例。当前采用独立组合服务，由服务端串联 ASR 和对齐；Easel 通过通用 OpenAI 转写适配器只配置一个 Base URL。初版两个端点的直连适配器保留为可选方式。

## 改造前的调研基线

| 部位 | 已有设计 | 限制 |
| --- | --- | --- |
| `skills/shared/scripts/model_registry.py` | 图片、视频、音乐、配音共用静态供应商元数据 | 不是动态执行插件系统；没有转写组 |
| `web/app.py` 的模型读取/保存 | 媒体配置读取注册表，保存到 `.env` | 未注册的媒体 ID 被拒绝；转写行单独写死 |
| `SettingsPanel.tsx` | 通道分别显示供应商行 | 添加供应商只作用于聊天；媒体行不能动态添加 |
| `ai_video.py`、`ai_music.py`、`voice_clone.py` | 已有协议处理函数 | 执行分发表或分支仍固定，需要修改代码才能增加协议 |
| `ai_image.py` | 同步 OpenAI 风格及部分异步服务 | 有专门服务分支，不是所有图片服务通用 |
| `asr.py` 与 video-pipeline SDK | 本地 Whisper 与 SiliconFlow 云转写 | 调用入口分散，尚无统一转写适配层 |

关键源码：`model_registry.py:24`、`web/app.py:1414,1636`、`SettingsPanel.tsx:338,638`、`ai_video.py:647`、`ai_music.py:405`。

目前“provider”已经是 Easel 代码里的术语，但有时混合指供应商品牌、协议实现和默认选择。本设计将三者分开。聊天自定义供应商保存在 OpenClaw 配置；媒体配置主要属于 Easel 脚本，两者不是同一条执行链。

## 推荐边界

```text
设置页 / 字幕与视频业务脚本
            ↓
Easel media bridge：实例选择、类型检查、结果落盘
            ↓
独立媒体适配包：注册表、能力、任务、协议转换
            ↓
直接 HTTP 服务 / 外部兼容网关 / 工作流服务
```

Easel 只依赖稳定的 bridge 接口，不知道 Qwen/H3 的模型加载方式或工作流节点。适配器可以调用直接 API，也可以调用外部 server；这两种部署方式共用上层接口。

建议先维护一个独立 Python 适配包，Easel 内只留薄桥接模块。通过受信任的安装包注册适配器，网页不能上传或指定任意 Python 代码。具体包名和配置路径在实现时确定，不能将设计示例当作已经存在的接口。

### 公共接口

- `describe()`：实例/模型支持的能力、参数、限制和配置字段，供设置页与调用前验证使用。
- `probe()`：连接、鉴权、模型可用性检查；与真正的效果测试分别报告。
- `submit(request)`：接受有类型的能力请求，返回已完成结果或可查询的任务句柄。
- `get_job(handle)`：查询进行中的任务和最终结果。
- `collect(result, destination)`：收集产物到本地路径，供现有流水线消费。

请求不是一个任意字段的大字典：分别定义 `TranscriptionRequest`、`SpeechRequest`、`ImageGenerationRequest`、`ImageEditRequest`、`VideoRequest`、`MusicRequest` 等类型。共用字段包括实例 ID、模型、超时和请求 ID；音频、参考图、首尾帧等字段属于对应类型。服务特有参数放在适配器声明并校验的扩展字段中。

结果也分别保留语义：转写是文本、segments、words、语言、时间轴来源；生成是文件、格式、时长或尺寸。同步接口立即返回完成，异步接口保存任务 ID 后轮询，调用者无需了解底层差别。

任务状态统一为 queued/running/succeeded/failed/cancelled，取消仅在适配器声明支持时开放。记录实际模型、实际 backend（上游提供时）、请求 ID、上游任务 ID、错误和时间；上游不暴露 backend 时明确为 unknown，不猜测。

提交超时不自动重交可能收费的任务；先用已有任务 ID 恢复查询。明确区分未提交、已提交结果未知和已失败。HTTP 200、健康检查或 tool success 都不能直接代表效果正确。

### 配置与界面

实例配置独立于源码和共享 `IMG_*` 等单实例变量，包含：

```json
{
  "schema_version": 1,
  "providers": [{
    "id": "internal-transcription",
    "name": "内网 Qwen 转写",
    "adapter": "qwen-asr-aligner",
    "connection": {
      "asr_url": "http://ASR_HOST:8080",
      "aligner_url": "http://ALIGNER_HOST:8081"
    },
    "auth": {"mode": "none"},
    "models": [{"id": "qwen-asr-aligned", "capabilities": ["transcribe", "align"]}]
  }],
  "defaults": {"transcribe": "internal-transcription"}
}
```

这是建议格式，不是现有可运行配置。密钥通过凭证引用保存，不进入 Git，也不回传浏览器。显式支持无鉴权内网服务，不要求伪造 API Key。内网地址只允许管理员配置的目标，不放开所有内网 URL；客户端代理和超时由连接配置控制。

各媒体选项卡增加“添加供应商”：选择已安装的适配器，填写名称、连接和模型，保存后生成一行，支持默认选择、修改和删除。字段由适配器描述生成，当前单地址组合转写服务显示 Base URL/凭证引用，复杂的可选直连方式在编辑表单显示 ASR/对齐两个地址。一个实例仅出现在它实际支持的通道中，不能注册一次就自动宣称五种能力。

原有供应商以兼容适配器接入；迁移现有 `.env` 时保留用户配置，不将历史 key 和默认回退顺序无意改变。已有字幕属于业务输入优先规则，不应伪装成一个模型供应商。

## 外部兼容 server 能否零改代码

可以复用某些现有调用链，但必须兼容脚本实际协议，不能只修改 Base URL。

| 通道 | 当前入口期望 | 外部 server 的责任 |
| --- | --- | --- |
| 云转写 | `/audio/transcriptions`，multipart file/model/language/verbose_json，Bearer | 接收完整源文件，处理切片、ASR、对齐并返回有效 segments；旧代码要求 Key |
| OpenAI 风格配音 | `/audio/speech`，JSON，音频二进制 | 兼容 model/voice/input/格式/速度等实际字段 |
| 常规生图 | `/images/generations` 等 | 兼容对应请求及 URL/base64 响应；编辑与异步流程另查 |
| OpenAI 风格视频 | `/videos` 创建/查询任务 | 兼容当前字段、状态及结果视频 URL，不能只提供不同格式的 `/content` |
| Suno 风格音乐 | `/generate` 与对应任务查询 | 实现现有 Suno 兼容协议；不是一个统一的 OpenAI 音乐接口 |

转写尤其有以下差距：

1. `transcribe_api.py` 读取 `SILICONFLOW_BASE_URL`，但通用字幕 `asr.py` 仍直接调用 Whisper；改地址不会覆盖所有路径。
2. 当前设置页的 SiliconFlow 名称、模型和显示地址写死，不等于真实 `.env` 全部内容；复用旧行不会得到新的“内网 Qwen”行。
3. 当前云转写要求非空 Key、请求 verbose_json，而现有 Qwen ASR 只提供 JSON 文本。server 必须真正补齐对齐，不应编造比例时间轴。
4. 当前 `normalize_response()` 会把一个 segment 的正文转换成一个 word，不保留返回的真实逐词列表。因此仅换 server 仍不能完整利用逐词对齐。
5. 现有自测请求 `/models` 且限制内网目标，与服务 `/health` 和实际效果测试不是一回事。

所以外部 server 是合理的模型适配位置，但不是动态供应商 UI 的替代品。推荐通过通用 bridge 接入它，而非长期冒用 SiliconFlow 名称和配置。

## 升级与实施范围

首次仍需少量核心改动：统一注册与配置 API、设置页动态添加、各媒体调用入口接到 bridge，以及流水线的转写选择和结果转换。不能仅改一个文件便覆盖所有现有路径。

之后新增同协议实例只改配置；新增协议只安装/扩展适配包；模型特有切片、轮询和工作流留在适配器或外部 server。新增一种此前未定义的能力仍可能需要扩展接口和界面，不能承诺无限通用。

保留一个集中的 bridge 目录及明确调用边界，把不可避免的 Easel 接线改动维护为小范围独立提交。升级检查接口版本和最小端到端识别/生成，不要求随模型重新修改业务脚本。若希望官方升级完全没有补丁重放成本，仍需争取上游合并这套扩展机制。

首个实施切片建议仅做转写：已有可信字幕直接用，否则配置的 Qwen ASR + aligner；失败明确返回，不自动下载或切回 Whisper。Whisper 可保留手动选择的可选适配器。其余通道先统一配置和能力契约，再逐个接入，具体模型方案另议。
