---
name: ai-image-gen
description: "通用 AI 生图：文生图 / 图生图 / 图像变体。当用户说 AI 生图、AI 画图、文生图、图生图、生成图片、生成配图、图像生成、AI 出图、AI 作图、换图、改图、图像编辑、给我画一张、生成一张图 时使用。支持 OpenAI 兼容 API 与 apimart 异步 API，用户自备 API key。"
layer: produce
---

# ai-image-gen Skill

> 通用 AI 文生图 / 图生图 / 图像变体。用户自备图像生成 API key（OpenAI 兼容 或 apimart 异步），产物写入 `outputs/`。

调用共享脚本 `skills/shared/scripts/ai_image.py`（纯标准库，无第三方依赖）。
本 SKILL 不索要、不回显、不写入、不提交任何真实 API key —— key 只存在于用户自己的 `.env`。

## 边界（和相邻 SKILL 区分）

- **ai-image-gen（本 SKILL）**：通用 AI 生图，任意题材，文生图 / 图生图 / 变体。
- **ecom-details-image**：电商详情页 / 商品主图专用出图（25 场景模板、PDP 序列）。要做电商商品图走它。
- **card-\* / poster-\***：HTML+CSS 渲染截图（金句卡、小红书卡、海报），**非 AI 生成**，是确定性设计出图。
- **image-editing**：已有图片的确定性处理（改尺寸/裁剪/加水印/压缩），不生成新画面。

## 配置（执行前必读）

> **配置检查路径铁律**：先 `cd` 到运行时说明给出的 Easel 项目根，确认当前目录有 `.env` 和 `skills/shared/scripts/ai_image.py`，再运行下列命令。不得在任何执行引擎的 workspace 或共享脚本副本中检查，也不得用 `env` / `printenv` 代替读取项目 `.env`；否则会把已配置的 `IMG_BASE_URL`/Key 误判为缺失。

优先查询 `.venv/bin/python -m easel.media providers`，其中 image 实例保存模型、地址与能力，`defaults.image` 是设置页默认。一个 Skill 调用多个实例，不为每个模型建 Skill。

### 模型选择规则

- 用户明确指定模型时优先遵从；未指定时使用 image 默认实例（本部署默认 GPT Image Flare）。用 `--provider <实例ID>` 只影响本次任务，不修改全局默认。
- Flare 返回明确额度耗尽标记 `IMAGE_QUOTA_EXHAUSTED` 时，可改用已配置的自部署 Qwen Image，并告知用户实际模型。普通429限流、超时、网络错误或提交状态未知不等于额度不足，不重交或自动切换。
- 用户要求更多图片做对比时，可用同一需求同时调用 Flare 和自部署 Qwen；分别指定实例、输出文件名并标注模型。不因普通生图请求擅自生成多份。
- 用户对质量不满意或明确要求重新生成，且未指定模型时，优先 GPT Image Sunburst；这是用户发起的新一轮生成，保留原图。传输故障后的恢复不属于质量重跑。
- 通过查询结果的模型名匹配实例 ID，不假定固定 ID；所需模型未配置就说明。Qwen 支持文生图及普通单图编辑；编辑前确认实例 supports_edit，不得丢掉参考图改成文生图。文生图对比使用1024x1024、每次1张；Qwen 不传 quality 或 mask，不用于多参考图任务。
- 参数和能力以实例为准：`supports_edit=false` 不调用 img2img；模型名不能代替实际效果验证。失败不循环重试；Sunburst失败也不要自动再换一圈。

没有 image 默认实例时沿用 `.env` 的 `IMG_BASE_URL`、`IMG_MODEL`、`IMG_API_KEY`。显式 `--provider legacy` 也可调用该旧配置；OpenAI 兼容走同步接口，apimart 走异步接口。

## 执行步骤

### 1. 先确认配置（离线，不发请求）

```bash
python skills/shared/scripts/ai_image.py check
```

打印当前默认实例及能力；旧配置则打印脱敏配置和自动检测模式。可加 `--provider <实例ID>` 检查指定模型。**配置未就绪就不要往下走**，直接把缺什么、怎么配告诉用户。

### 2. 文生图 text2img

先把用户诉求写成一条清晰的图像 Prompt（主体 + 风格 + 构图 + 光线 + 画质），再执行：

```bash
python skills/shared/scripts/ai_image.py text2img \
  --prompt "一只戴墨镜的柴犬，扁平插画风，明亮撞色背景，高细节" \
  --size 1024x1024 --n 1 \
  --output outputs/主题名/ai-image
```

- `--size`：同步模式用像素（`1024x1024` / `1536x1024` / `1024x1536`…）；异步模式用比例（`1:1` / `16:9` / `9:16`…）。
- `--n`：生成张数（多张时按序号自动命名）。
- `--output`：目录（多张自动编号）或含扩展名的单文件；统一放 `outputs/主题名/`。
- `--provider`：指定媒体实例；省略时使用 image 默认实例。
- `--timeout`：同步生成请求或异步轮询超时秒；媒体实例使用自身配置（默认1800），旧配置默认180；不包含下载时间。慢速同步服务可显式传 `--timeout 1800`，超时先检查服务端状态，不自动重交。
- 同步可加 `--quality low|medium|high`（仅限支持该参数的服务）；异步可加 `--resolution 1k|2k|4k`。
- 若当前模型为 `qwen-image-2.1-uc-bf16`：使用 `--timeout 1800 --n 1`。文生图尺寸限512/768/1024/1536/2048的正方形，默认1024x1024。普通单图编辑使用 img2img，实例须开启 supports_edit 与 edit_size_auto；适配器发送 size=auto，保留原图比例、使用服务默认 resolution=1024，不承诺输出为指定像素尺寸。不传 `--quality`、`--mask`，不使用多参考图或 variations。服务繁忙429或超时不重复提交。

### 3. 图生图 / 图像编辑 img2img

基于一张输入图 + 指令生成新图（OpenAI 走 `/images/edits` multipart，可选 `--mask` 局部编辑；apimart 把输入图作参考图走生成端点）：

```bash
python skills/shared/scripts/ai_image.py img2img \
  --prompt "把背景换成夜晚霓虹街道，保留主体" \
  --image path/to/input.png \
  --output outputs/主题名/edited.png
```

### 4. 图像变体 variations

由一张图生成多个变体：

```bash
python skills/shared/scripts/ai_image.py variations \
  --image path/to/input.png --n 3 \
  --output outputs/主题名/variations
```

### 5. 交付

确认文件存在后，用 `![模型说明](URL)`（URL 使用 `outputs/主题名/图片.png`） 逐张返回；对比图标明各自模型，保留旧版本。告诉用户生成参数（模型/尺寸/张数）。如需再改尺寸/加水印/压缩，转 `image-editing`。

## 产物

统一输出到 `outputs/主题名/`。脚本会自动创建目录，多张按时间戳 + 序号命名。

## Profile 感知

有账号 Profile（`=== EASEL ACCOUNT PROFILE ===`）时，把品牌视觉风格（配色 / 调性 / 元素偏好）融入 Prompt，保持系列图统一；无 Profile 时按用户描述走通用生成。

## 常见问题

- **缺 key / 缺配置**：`check` 会明确指出缺哪项及 `.env` 示例；报错为友好中文，不抛 traceback。
- **同步 vs 异步用错尺寸格式**：同步用像素、异步用比例。用 `--mode` 可强制模式。
- **不要把真实 key 写进任何产物或提交**。
