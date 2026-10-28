# 自建海外热点订阅

热点雷达的渠道栏提供 X、Reddit、海外资讯，均来自同一个自建 RSS。
本机 `.env` 配置 `EASEL_OVERSEAS_RSS_URL` 后，勾选对应渠道即可读取。进程环境变量优先；URL 留空停用，不影响原有六渠道。可选 `EASEL_PROXY` 用于订阅的出网代理。个人订阅 URL 不提交 Git。

## 数据约定

RSS 2.0 `channel/item` 中，`title`、HTTP(S) `link`、`source` 是必需字段。source 为 `x`、`reddit` 或 `news`，分别映射三个按钮；未知来源暂不显示。`guid` 为稳定标识，缺失时使用链接去重。保留订阅顺序，再按来源分组，不重新计算评分、不在分组前截断条目。

可选字段：`publisher`（平台、社区或媒体）、`author`、`description`、`pubDate`。`channel/lastBuildDate` 是订阅更新时间，`pubDate` 是原帖时间。摘要按纯文本展示，不执行其中 HTML。

`heat/heat_score` 为生成端综合分，按原值显示两位小数，不假设百分制。`heat` 中可保留 `impressions`、`likes`、`reposts`、`replies`、`quotes`、`reddit_rank`、`source_weight`；界面辅助展示浏览、赞和转发。排名范围和权重不明确，不在界面宣称为平台官方排名。缺失或非法数值隐藏，真实 0 保留；新增未知字段忽略。

## 独立实现与同步上游

- 后端：[RSS 模块](../easel/overseas_trends.py)，独立 GET `/api/overseas-trends`，应用只注册路由。
- 前端：[海外组件](../web/frontend/src/features/overseas-trends/OverseasTrends.tsx)，请求、类型和样式均在同目录。原页面仅导入 hook、插入按钮/卡片、接入刷新。
- 原有 `TREND_SOURCES`、JSON 解析、`/api/trends`、国内缓存、默认选择和首页逻辑不变。
- 同步上游时重点核查 `web/app.py` 的路由注册和 `TrendsPage.tsx` 的接线；不要把 RSS 逻辑合进国内渠道处理函数。

同一份订阅共享 5 分钟内存缓存及 ETag。请求失败后 1 分钟内不反复重试；有上次成功数据时保留并标记，订阅 URL 改变时清空旧缓存。刷新按钮遵循缓存，不会绕过限频。最多读取 2 MiB XML。缓存随进程重启清空，订阅无内容与获取失败分别展示。

收藏使用现有选题库接口，在备注中保留摘要和原文；做内容通过现有回调传入标题和来源上下文。新模块不修改原渠道收藏或对话行为。

## 验证

新增测试使用合成 XML 与模拟下载，不访问真实平台。专项运行：

```bash
python -m pytest tests/test_overseas_trends.py tests/test_trends.py
```

发布按 [Fork 维护流程](fork-maintenance.md) 执行；前端需要重新构建，服务更新前确认无生成中的会话。无需同步 Agent 技能。

## IT之家订阅

热点雷达另提供「IT之家」渠道，使用本机 `.env` 中的 `EASEL_ITHOME_RSS_URL`。
个人 URL 不提交 Git；留空停用。订阅格式与海外源相同，入口把 `source=news`
映射为 `ithome`，不要求生成端修改。保留混合资讯/热榜的订阅顺序、publisher
标记与综合分，不将列表宣称为官方排名。

`/api/ithome-trends` 复用 RSS 解析和获取类，但使用独立实例，缓存、ETag、失败状态
与海外源隔离。前端复用渠道按钮、卡片和请求 hook。收藏和「做内容」均携带标题、
来源、发布时间、纯文本摘要与原文链接；「做内容」通过原有回调新建会话并发送创作请求。

浏览器回归（先启动本 worktree 的 Vite，端口 5189；以下命令在 `docs/` 执行；
仅模拟 API，不调用真实模型）：

```bash
python ../tests/frontend/overseas_trends_browser.py
python ../tests/frontend/ithome_trends_browser.py
```

热点雷达的所有渠道选择保存在当前浏览器本地，刷新或重新进入页面时恢复，
全部取消也会保留。首次使用仍默认选择微博、抖音、知乎；不同浏览器不互相同步。
