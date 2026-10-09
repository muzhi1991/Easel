# Fork 分支与运行版本维护

2026-10-09 起，本 fork 使用以下约定。官方仓库为 `ZJU-REAL/Easel`（remote `upstream`），个人 fork 为 `muzhi1991/Easel`（remote `origin`）。官方主分支名为 `main`，不是 `master`；暂不计划向官方提交 PR。

## 分支职责

| 分支 | 用途 |
| --- | --- |
| `main` | 官方镜像，只快进同步 `upstream/main`，不放本地功能、修复或配置 |
| `dev` | 已验证的本地完整版本，包含官方代码和本 fork 的全部修改；运行目录使用此分支 |
| `feature/*` | 从 `dev` 创建的独立功能分支，验证后合并到 `dev` |
| `fix/*` | 从 `dev` 创建的独立修复分支，验证后合并到 `dev` |
| `sync/*` | 在独立 worktree 中整合官方更新、解决冲突和验证，完成后合并到 `dev` |
| `gh-pages` | 上游网站内容，不是运行服务代码 |

`dev` 从已运行的 `29a0249` 创建，其中已经包含模型设置/LAN、环境检测、安装脚本、通用媒体适配层、Qwen ASR/对齐和单地址组合服务接入。历史分支 `fixes/model-settings-lan`、`fixes/environment-detection`、`features/media-adapters-qwen-asr` 均被它包含，暂时保留，不需要重复合并，也不作为未来开发的基点。

Fork 的 GitHub 默认分支可以继续是 `main`；运行目录检出 `dev` 与 GitHub 默认分支不是一回事。

## 日常开发

`/Users/muzhi1991/workspace/Easel` 是运行目录，保持在 `dev`。新工作使用独立 worktree，避免开发过程中修改服务正在读取的源码或 editable 安装包。

```bash
git fetch origin
git worktree add -b feature/example ../Easel-feature-example dev
```

修复使用 `fix/example`。在该 worktree 修改、运行与改动相称的测试，并推送对应分支。合并前确认没有遗漏 `dev` 的新提交；未合并的独立工作分支可以 rebase 到最新 `dev`，共享分支重写前需协调。

功能/修复验证完成后，在维护窗口将其合并到运行版本：

```bash
git switch dev
git merge --no-ff feature/example
git push origin dev
```

只有已经通过必要检查的修改才合并到 `dev`。若多个改动并行，在独立整合 worktree 先验证合并结果，再推进运行目录的 `dev`。合并不是完整部署：有代码变更时按下面的运行更新步骤处理。

## 同步官方

`main` 只做 fast-forward；长期发布的 `dev` 用 **merge** 吸收官方更新，不 rebase 或强推它的既有提交。

运行目录保持在 `dev` 时，如果本地 `main` 没有被其他 worktree 检出，可用以下方式只快进移动 `main`，不切换运行目录的文件：

```bash
git fetch upstream
git fetch origin
git merge-base --is-ancestor main upstream/main
# 只有上一条成功时执行；失败表示本地 main 已偏离官方，先排查。
git update-ref refs/heads/main upstream/main main
git push origin main
```

随后在独立 worktree 整合，例如：

```bash
git worktree add -b sync/upstream-YYYYMMDD ../Easel-sync-YYYYMMDD dev
cd ../Easel-sync-YYYYMMDD
git merge --no-ff upstream/main
```

解决冲突、检查上游是否已包含本地补丁，运行检查；验证通过后将该 `sync/*` 分支合并到 `dev`，再推送和部署。上游已有等效修复时审查最终代码，不盲目保留重复实现。官方 `main` 已更新不表示本地运行版本必须立刻更新。

## 检查与运行更新

- 遵循 [CONTRIBUTING.md](../CONTRIBUTING.md) 的必跑检查，以及本次改动需要的专项验证。
- Python 使用当前 Easel `.venv`；适配包需要时重新安装，前端修改后执行 `web/frontend` 的 `npm run build`。
- Web 修改按需要通过 `start-web-lan.sh` 重启并核查 localhost/LAN；无需因切换到相同代码的新分支重启服务。
- Agent 技能仅同步本次有关的文件；完整 `openclaw/sync.sh` 会改 workspace 文件及清空 MEMORY.md，不随普通更新执行。
- `.env`、密钥、用户目录媒体配置及 OpenClaw 实例配置不进 Git。远程 Qwen 网关/模型服务独立部署，不随 Easel 分支合并升级。
- 可以为已验证的部署提交打 tag，记录部署提交和验证证据，方便明确回退目标。回退既有公共 `dev` 修改优先使用 revert，避免强推改写运行历史。
- 每次修改后提交到相应分支，推自己的 fork；`main` 保持官方原样。

媒体接线、迁移及真实识别验证详见 [media-adapters.md](media-adapters.md)。共享 OpenClaw 的旧 GLM user-text 补丁已撤销，不在任何升级步骤中重新应用。
