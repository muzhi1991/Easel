# Easel 图片文字识别

- 来源：Easel 自研 CLI 与技能；调用用户独立部署的 RapidOCR HTTP 服务，不复制或安装服务端模型代码。
- 执行：项目 `.venv` Python → `skills/shared/scripts/ocr.py` → `easel.media` → `easel_media_adapters.rapidocr`。
- 配置：用户目录 media-providers.json 中的 OCR 实例；维护与迁移见 `docs/media-adapters.md`。
- 不修改 GLM 图片理解或共享 OpenClaw 安装包。
