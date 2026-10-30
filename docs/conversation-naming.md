# 对话命名

首条输入仍使用前端原有规则生成临时名称。交付完整成果时，当前模型通过 `name_conversation` 登记成果标题；公众号、小红书等使用正式标题，朋友圈等无标题成果由本轮模型顺带概括名称，不额外调用模型。后台仅在本轮正常完成后自动应用，失败、停止和中断不应用。

用户主动命名优先级最高：侧栏“重命名”、回复下的“命名对话”共用面板，可以手动输入、使用此产物标题或点击“智能命名”。智能命名先填入输入框，保存才生效。对话中明确要求“把当前对话改名为……”，模型直接调用命名接口。所有主动保存均设置 `titleLocked=true`，之后自动命名和下一轮客户端提交的旧标题都不能覆盖。

## 实现约定

- 使用现有会话 JSON 存储 `titleLocked` 和助手消息的 `artifactTitle`，没有新数据库或后台任务系统。
- 新会话默认允许自动命名；历史会话、导入会话缺少可靠的命名来源，保守保留原名，避免覆盖历史自定义名称。
- 仅交付完整成果时登记标题。大纲、候选标题和过程说明不登记；多个独立成果没有明确主成果时不登记。同一成果更新可同步标题，新文章通过用户主动命名选择。
- `easel/conversation_naming.py` 定义提示约定和受限命名工具。API 直连只开放这一个函数，不增加文件或命令工具。
- Agent 运行时通过 `scripts/name_conversation.py` 调用当前轮次接口。回调地址和短期 token 由服务端注入，只绑定当前会话和正在执行的轮次，收尾即失效。不得让 Agent 修改代码或直接编辑会话数据库来改名。
- `/api/conversations/{identifier}/suggest-title` 只返回建议，不写会话。已有明确成果标题直接返回；否则使用配置的模型和隔离的请求上下文。OpenClaw 使用 `low` thinking；直连已知支持 reasoning effort 的模型使用 `low`，其他运行时保留其支持的默认行为。
- 命名面板沿用会话 revision 校验，拒绝用打开面板时的旧版本覆盖其他窗口的新名称。模型建议返回时也不覆盖用户已经输入的文字。

## 验证

核心覆盖 `tests/test_conversation_naming.py`、`tests/test_direct_api.py`；浏览器交互用 `tests/frontend/conversation_naming_browser.py`，移动端键盘布局用 `tests/frontend/mobile_keyboard_browser.py`。浏览器测试使用模拟 API，不访问真实用户会话、不调用真实模型。
