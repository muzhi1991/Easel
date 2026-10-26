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
- Agent 技能仅同步本次有关的文件；完整 `agents/sync.sh` 会改 workspace 文件及清空 MEMORY.md，不随普通更新执行。
- `.env`、密钥、用户目录媒体配置及 OpenClaw 实例配置不进 Git。远程 Qwen 网关/模型服务独立部署，不随 Easel 分支合并升级。
- 可以为已验证的部署提交打 tag，记录部署提交和验证证据，方便明确回退目标。回退既有公共 `dev` 修改优先使用 revert，避免强推改写运行历史。
- 每次修改后提交到相应分支，推自己的 fork；`main` 保持官方原样。

媒体接线、迁移及真实识别验证详见 [media-adapters.md](media-adapters.md)。共享 OpenClaw 的旧 GLM user-text 补丁已撤销，不在任何升级步骤中重新应用。

## dev CI 与部署包

`Dev CI` 在推送 `dev`、向 `dev` 提交 PR 或手动触发时运行。Linux 和 macOS 执行 Python 测试与维护校验；Linux 构建前端并运行前端测试。PR 只检查，不生成完整部署包；推送和手动运行在所有检查通过后生成 `easel-dev-<完整提交号>` artifact，保留30天。临时前端 artifact 保留7天。

在 GitHub Actions 的对应运行页面下载部署包 artifact，里面包含 `easel-dev-<短提交号>.tar.gz` 和 `SHA256SUMS`。也可使用运行摘要中的 `gh run download` 命令下载。Mac 上用 `shasum -a 256 -c SHA256SUMS` 校验，然后解压到独立目录检查；包内 `BUILD-INFO.json` 记录提交号和前端文件校验值。

部署包包括该提交的运行源码和预构建的前端资源，适用于 macOS。打包时排除纯宣传素材 `assets/readme/`、`web/static/showcase/` 及对应宣传页 `web/static/main.html`；这些文件仍保留在 Git 中，但部署包不提供该宣传页。应用图标、PWA 资源、技能字体等运行资源保留，排除清单记录在 `BUILD-INFO.json` 中。它不是独立可执行程序，不包含 Python 虚拟环境、Node 依赖、模型权重、用户目录配置或未跟踪文件。部署时仍需在目标 Mac 安装 Python 依赖和本地媒体适配包；配置与会话数据保留在原位置。不要把整份归档直接覆盖运行目录。

此工作流仅检查、打包和上传，不连接本地机器、不配置 SSH 或自托管 runner、不部署、不重启服务。产物准备好不代表运行版本已经更新；实际部署另按维护窗口安排。

本 fork 不使用 Windows，日常检查以 `Dev CI` 的 Linux/macOS 结果为准；`dev` 的 Native tool budget acceptance 专项验收只跑 Linux。`main` 中官方工作流文件保持原样，但在本 fork 的 GitHub Actions 设置中停用名为 `CI` 的工作流，避免官方 Windows 测试和每日真实安装任务重复报错。此设置不影响官方仓库，也不影响 `Dev CI` 的测试、前端构建和部署包。停用命令为 `gh workflow disable ci.yml --repo muzhi1991/Easel`；未来需要验证官方完整矩阵时，可用 `gh workflow enable ci.yml --repo muzhi1991/Easel` 恢复。同步上游后检查该工作流仍处于停用状态。

## 统一 Web 启动入口

macOS 本机统一使用 `bash start-web-lan.sh`，同时允许局域网访问和可选的反向代理域名访问。域名放在本机未跟踪的 `.env` 中：

```dotenv
EASEL_PUBLIC_URL=https://your-domain.example:8443
```

该值必须是完整的 HTTP/HTTPS origin，可带端口，不含账号、业务路径或查询参数；末尾 `/` 可省略。进程环境变量优先于 `.env`，未配置或留空时只添加局域网地址。脚本将域名和 origin 加入访问允许列表，保留已有 `EASEL_EXTRA_HOSTS` / `EASEL_EXTRA_ORIGINS`；不执行 `.env` 中的 shell 命令。HTTPS 证书和 TLS 仍由 Caddy 等反向代理处理。

以后部署及自启均应直接调用仓库根目录的 `start-web-lan.sh`，不再依赖 outputs 里的实例包装脚本。旧包装脚本在切换启动入口前可以继续调用统一脚本；配置修改需下次启动才生效。`.env` 仍不提交，仓库仅提交空值配置示例。

### macOS 登录自启与专用网关

LaunchAgent 使用项目根目录的 `start-web-lan.sh` 作为统一入口。入口按当前 Agent 设置，仅在使用 OpenClaw 时先调用 `scripts/gateway.sh start`，复用已经健康的 `easel` profile 网关，并确认健康检查通过后启动 Web；不会启动或停止默认 OpenClaw profile。非交互启动自动查找 NVM 等位置的命令。网关启动失败时入口退出，由 LaunchAgent 的 KeepAlive 重试。OpenClaw 模式下入口保留监督进程，每 5 秒检查专用网关；失联时自动尝试恢复，不重放已经提交的对话。恢复使用 `scripts/gateway.sh start --no-force`，不强杀仍占用端口的忙碌或退出中的网关，失败后下一轮再试。其它执行引擎不启动这项监测。

实例的 LaunchAgent plist 位于用户 `~/Library/LaunchAgents/`，不提交 Git。它属于登录后自启，非登录前的系统服务。Web 与专用网关由同一入口启动；网关仍按既有脚本在后台运行，入口退出时只向 Web 进程组转发停止信号，不主动停止网关。macOS 重启 LaunchAgent 时可能同时终止该任务下的后台网关；旧网关尚未退出就被新入口判为健康的时序由持续监测兜底恢复。部署后使用 `launchctl kickstart -k gui/$(id -u)/com.limuzhi.easel` 重启托管服务前，先确认没有生成中的会话；不要另起一份 Web 进程。部署验收必须同时检查 Web 页面和专用网关 `/healthz`，并在首次检查后至少跨过一个监测周期再次确认；只有页面正常不足以证明对话可用。日志在实例配置指定的 `~/Library/Logs/Easel/` 和 `/tmp/easel-gateway.log`。
