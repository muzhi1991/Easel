# React + TypeScript + Vite

Easel 的会话摘要、消息分页与浏览器验证见[会话历史说明](../../docs/conversation-history.md)。

## 手机 PWA 保存文件

支持系统文件分享的 PWA 优先提供“准备分享/保存”：先接收文件，再由用户点击“分享/保存”唤起系统菜单，选择保存视频或存储到文件。第二次点击保留系统分享所需的用户激活。普通网页下载的内存上限为 32 MiB，显式准备分享的上限为 64 MiB；临时文件在 60 秒后清理，取消、离开页面或分享结束也会释放。

超过上限时使用浏览器下载。PWA 中该入口可能无法启动下载，可复制下载链接到 Safari、Chrome 等浏览器打开；剪贴板不可用时提供可手动复制的链接。“使用浏览器下载”只表示尝试移交，不代表系统已成功保存。

下载逻辑回归：在项目根目录运行 `node --test tests/frontend/download.test.mjs`。按钮流程回归：启动 Vite 后，在项目根目录运行 `.venv/bin/python tests/frontend/download_browser.py http://127.0.0.1:5173`。后者使用 Chromium/WebKit、模拟 PWA 与系统分享接口，不替代真机的最终保存验证。

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
