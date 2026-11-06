# 自建海外热点订阅

热点雷达的渠道栏提供 X、Reddit、海外资讯，均来自同一个自建 RSS。
本机 `.env` 配置 `EASEL_OVERSEAS_RSS_URL` 后，勾选对应渠道即可读取。进程环境变量优先；URL 留空停用，不影响原有六渠道。可选 `EASEL_PROXY` 用于订阅的出网代理。个人订阅 URL 不提交 Git。

## 数据约定

RSS 2.0 `channel/item` 中，`title`、HTTP(S) `link`、`source` 是必需字段。source 为 `x`、`reddit` 或 `news`，分别映射三个按钮；未知来源暂不显示。`guid` 为稳定标识，缺失时使用链接去重。保留订阅顺序，再按来源分组，不重新计算评分、不在分组前截断条目。

可选字段：`publisher`（平台、社区或媒体）、`author`、`description`、`pubDate`。`channel/lastBuildDate` 是订阅更新时间，`pubDate` 是原帖时间。摘要按纯文本展示，不执行其中 HTML。

`heat/heat_score` 为生成端综合分，按原值显示两位小数，不假设百分制。`heat` 中可保留 `impressions`、`likes`、`reposts`、`replies`、`quotes`、`reddit_rank`、`source_weight`；界面辅助展示浏览、赞和转发。排名范围和权重不明确，不在界面宣称为平台官方排名。缺失或非法数值隐藏，真实 0 保留；新增未知字段忽略。

## 接入官方数据源架构

2026-11-06 起使用官方 `easel.trends` 注册表、RSS/Atom 解析器、隔离采集进程和 `TrendService` 缓存，不再维护独立的下载器或缓存。

- 现有 `.env` 的 `EASEL_OVERSEAS_RSS_URL` / `EASEL_ITHOME_RSS_URL` 自动注册为 `overseas-rss` / `ithome-rss`，无需复制或迁移个人 URL。仍以进程环境优先，留空停用。
- 在官方「数据源」管理中可查看和停用/恢复这两份订阅；由 `.env` 提供的预设不能删除。可信本地 `config/trend-sources.json` 可以按相同 ID 覆盖刷新间隔等选项，`enabled: false` 优先于环境配置；不改写 `.env`。
- 两份订阅也可通过统一 `/api/trends` 查询。兼容接口 `/api/overseas-trends`、`/api/ithome-trends` 只进行分组和字段映射，与统一接口共享同一个服务和缓存。
- 前端保留 X、Reddit、海外资讯和 IT之家独立按钮及丰富卡片；普通自定义 RSS/Atom、HTTP、Python 源使用官方卡片。原有频道选择存储键继续有效，包括全部取消的选择。
- RSS 解析器以 v1 协议的可选 `rss` 元数据保留来源、作者、摘要、综合分及各项指标；普通采集器无需提供这些字段。`feed_updated_at` 保留订阅更新时间。未知字段忽略，摘要仍按纯文本呈现。

采集沿用官方约束：默认 5 分钟缓存，失败最多 30 秒后允许重试，最长保留上次成功数据 24 小时；可通过可信本地配置调整。网络请求在隔离进程中执行，XML 上限 2 MiB、单份订阅上限 500 条，分组视图在该上限内不提前按首页条数截断。ETag 和 304 保留；只有解析成功才更新缓存和校验标记。URL 或环境变化会使用新的缓存键，错误不返回订阅地址或凭证。刷新遵循服务缓存，不绕过限频。

实现入口：[展示适配模块](../easel/overseas_trends.py)、[官方数据源配置](../easel/trends/sources.py)、[RSS 解析](../easel/trends/rss.py)、[采集服务](../easel/trends/service.py)和[前端卡片](../web/frontend/src/features/overseas-trends/OverseasTrends.tsx)。新增数据源优先走官方注册和协议，不再添加并行采集管线。

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

`/api/ithome-trends` 使用官方服务中独立的数据源缓存项，缓存、ETag、失败状态
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
