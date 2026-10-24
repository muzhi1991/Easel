# vphone 手机端验证

用于 Safari / 桌面 PWA 的键盘、分享和应用切换测试。复用已有虚拟 iPhone；先读宿主机安装包自带的 `Skills/vphone-guest-control/SKILL.md`，以当前 CLI 帮助和 RPC 文档为准。

## 接入与操作

通过 SSH 在宿主机运行 `vphone-launchpad-cli`（非交互 SSH 可能需要绝对路径）。先执行 `status`、`vm list`，记录机器名、系统和 bundle 版本。以下 `PHONE` 代表选定的已有机器：

```sh
vphone-launchpad-cli guest rpc PHONE screen.unlock
vphone-launchpad-cli guest rpc PHONE apps.open_url '{"url":"https://example.com"}'
vphone-launchpad-cli guest rpc PHONE ui.tree '{"max_elements":60}'
vphone-launchpad-cli guest send PHONE '{"t":"screenshot","path":"/tmp/mobile-test.png"}'
```

截图保存在宿主机，可用 SCP 取回。每次点击后读 UI 或截图确认；RPC `input.tap` 用屏幕点，socket `tap` 用截图像素，不能混用。系统分享面板的 AX 坐标可能相对面板，应结合截图核对。黑屏先查锁屏状态。

若焦点只有输入附件栏、没有软键盘，可发送 Eject：`guest rpc PHONE input.hid '{"page":12,"usage":184}'`，再截图确认；这是显示/隐藏切换，不要盲目重复。无需重启或修改硬件键盘配置。

## 宿主机能访问、虚拟机不能访问

1. 分别检查域名解析、直接访问和宿主机已有代理。NAT 客体不会自动继承宿主机的代理/VPN 路由。优先保留原 HTTPS 域名与证书，不关闭 TLS 校验。
2. 如宿主机代理只监听 loopback，在 **NAT 宿主接口**临时开 TCP 转发。例如客体代理设置为 `192.168.64.1:17890`，转发到宿主 `127.0.0.1:7890`；实际地址、端口应现场确认。仅绑定客体可达接口，记录进程 PID，不改宿主代理服务的配置。
3. 修改前用 `files.plist` 导出客体 `/var/preferences/SystemConfiguration/preferences.plist`，另存 `network.hostname.get`；如需改静态解析，也备份 `network.static_names.get`。备份留在临时目录，不入 Git。
4. 在 `NetworkServices` 中按 `Interface.DeviceName` 找实际网卡（通常 `en0`），仅合并其 `Proxies`：`HTTPEnable/HTTPSEnable=1`、`HTTPProxy/HTTPSProxy=宿主NAT地址`、`HTTPPort/HTTPSPort=转发端口`。通过 `files.plist_set` 写回 `NetworkServices`，保留其它键和网卡。
5. 当前 bundle 如没有单独的网络 apply 方法，可调用 `network.hostname.set` 临时设置测试名，再立即恢复原来的 hostname 管理状态；此调用会提交并应用 SystemConfiguration。原本 `managed:false` 时用空参数 `{}` 撤销临时名字；原本受管理则显式写回原名。读回核对，并在 Safari 验证访问。

这类测试通常不需要改 DNS、`/etc/hosts` 或虚拟机持久配置。`vm config --forward` 是宿主端口到客体服务的方向，不能直接替代上述客体访问宿主代理的转发。

## 验证与恢复

- Safari 打开测试地址，再“添加到主屏幕”，开启作为 Web App 打开。从桌面图标进入；检查无浏览器地址栏、前台为 `com.apple.webapp`。Safari 测试不能代替 PWA 测试。
- 键盘至少连续弹出/收起 8 次，覆盖聊天输入、侧栏重命名、长内容、切到其它应用再返回；检查输入框和页面仍在可视区域、草稿未丢失。不向真实对话发送测试消息。
- 保存文件要验证实际落盘、大小及打开/播放；分享菜单出现只说明入口可用。第三方输入法未安装时，明确区分通用前后台恢复测试与该输入法专属回跳测试。
- **先恢复客体，再停转发**：只还原本次修改的代理字段（保留其它并发改动），按上面方式 apply，恢复 hostname 和改过的静态解析，读回与备份比对。再按记录的 PID 停止临时转发/SSH 隧道，确认端口不再监听，删除临时脚本。
- 截图和简短结果放 `outputs/_verification/`；记录系统版本、测试范围和未验证项。是否保留测试 PWA/下载文件写入结果，不清理用户其它数据。
