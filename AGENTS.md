# Agent 工作约定

开始修改前，阅读 [Fork 维护流程](docs/fork-maintenance.md) 和 [贡献指南](CONTRIBUTING.md)。分支职责、官方同步、验证和运行更新以维护文档为准。

- 本仓库是官方 Easel 的 fork；`upstream` 是官方，`origin` 是用户的 fork。
- `main` 只跟随官方；`dev` 汇总已经验证的本地修改，是当前运行分支。
- 项目根目录是运行目录，保持在 `dev`。功能和修复从 `dev` 创建独立 `feature/*` / `fix/*` worktree，验证后合并回 `dev`。
- 官方更新在独立 `sync/*` worktree 中整合和验证，再合并到 `dev`；不要 rebase 或强推公共 `dev`。
- 配置、密钥和用户实例状态不提交 Git；不要覆盖已有未提交文件或无关服务配置。

媒体适配、迁移与效果验证另见 [媒体适配器维护文档](docs/media-adapters.md)。修改维护规则时更新对应文档，避免在此重复维护完整操作步骤。
