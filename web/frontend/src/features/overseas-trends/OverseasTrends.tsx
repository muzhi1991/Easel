import { useState } from 'react';
import TrendLink from '../../components/TrendLink';
import DOMPurify from 'dompurify';
import { createIdea } from '../../lib/api';
import { IconBookmark, IconCheck } from '../../components/icons';
import type { OverseasItem } from './api';
import type { OverseasState } from './useOverseasTrends';
import './overseas-trends.css';

export function OverseasChannels({ feed }: { feed: OverseasState }) {
  return <>{feed.config.sources.map(({ key, label }) =>
    <button key={key} className={`chip ${feed.selected.includes(key) ? 'active' : ''}`}
      aria-pressed={feed.selected.includes(key)} onClick={() => feed.toggle(key)}>{label}</button>)}</>;
}

function dateLabel(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}
function summaryText(summary: string) {
  const clean = DOMPurify.sanitize(summary, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
  return new DOMParser().parseFromString(clean, 'text/html').body.textContent ?? '';
}
function context(item: OverseasItem) {
  return [item.title, `来源：${[item.publisher, item.author].filter(Boolean).join(' · ')}`,
    item.published_at ? `发布时间：${dateLabel(item.published_at)}` : '',
    `原文：${item.url}`, summaryText(item.summary)].filter(Boolean).join('\n');
}

function OverseasRow({ item, saved, onSaved, onUseTopic }: {
  item: OverseasItem; saved: boolean; onSaved: (id: string) => void; onUseTopic: (text: string) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    if (saved || saving) return;
    setSaving(true);
    setError('');
    try {
      await createIdea({ title: item.title, note: context(item), source: item.publisher || item.source, status: 'pending' });
      onSaved(item.id);
    } catch { setError('收藏失败，请重试。'); }
    finally { setSaving(false); }
  };
  const metrics = (['impressions', 'likes', 'reposts'] as const).flatMap((key) => {
    const value = item.metrics[key];
    if (value === undefined) return [];
    const labels = { impressions: '浏览', likes: '赞', reposts: '转发' };
    return [`${new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)}${labels[key]}`];
  });
  const summary = summaryText(item.summary);
  return <li className="overseas-item">
    <TrendLink className="overseas-title" url={item.url} title={item.title} summary={summary} />
    <div className="overseas-meta">{[item.publisher, item.author].filter(Boolean).join(' · ')}
      {item.published_at !== null && <time dateTime={new Date(item.published_at * 1000).toISOString()}> · {dateLabel(item.published_at)}</time>}
    </div>
    <div className="overseas-heat">
      {item.heat_score !== null && <span>综合分 {item.heat_score.toFixed(2)}</span>}
      {metrics.length > 0 && <span>{metrics.join(' · ')}</span>}
    </div>
    {summary && <details className="overseas-summary"><summary>查看摘要</summary><p>{summary}</p></details>}
    <div className="overseas-actions">
      <button className="btn btn-sm" onClick={() => void save()} disabled={saving || saved} aria-label={saved ? '已收藏' : '收藏到选题库'}>
        {saved ? <IconCheck size={14} /> : <IconBookmark size={14} />}{saved ? '已收藏' : saving ? '收藏中…' : '收藏'}
      </button>
      <button className="btn btn-sm" onClick={() => onUseTopic(context(item))}>做内容</button>
    </div>
    {error && <p className="overseas-error" role="alert">{error}</p>}
  </li>;
}

export function OverseasCards({ feed, onUseTopic }: { feed: OverseasState; onUseTopic: (text: string) => void }) {
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const markSaved = (id: string) => setSaved((previous) => new Set(previous).add(id));
  return <>{feed.config.sources.filter(({ key }) => feed.selected.includes(key)).map(({ key, label }) => {
    const items = feed.data?.groups.find((group) => group.source === key)?.items ?? [];
    const unavailable = feed.error || feed.data?.error;
    return <section className="card trend-col overseas-card" key={key} aria-label={`${label}热点`} aria-busy={feed.loading}>
      <div className="trend-col-head">{label}<span className="trend-count">{items.length}</span>
        {feed.loading && <span className="overseas-meta">更新中…</span>}
      </div>
      {feed.data?.feed_updated_at && <p className="overseas-status">订阅更新 {dateLabel(feed.data.feed_updated_at)}</p>}
      {feed.data?.fetched_at && <p className="overseas-status">最近获取 {dateLabel(feed.data.fetched_at)}</p>}
      {feed.data && !feed.data.configured && <p className="overseas-status">尚未配置{feed.config.label}订阅，请在本机配置后刷新。</p>}
      {unavailable && <p className="overseas-status overseas-error" role="alert">{unavailable}{items.length > 0 ? ' 当前显示上次获取的内容。' : ''}</p>}
      {!feed.loading && !unavailable && feed.data?.configured && items.length === 0 && <p className="overseas-status">本期订阅暂无该来源内容。</p>}
      <ol className="overseas-list">{items.map((item) => <OverseasRow key={item.id} item={item}
        saved={saved.has(item.id)} onSaved={markSaved} onUseTopic={onUseTopic} />)}</ol>
    </section>;
  })}</>;
}
