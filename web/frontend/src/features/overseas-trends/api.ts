export type OverseasSource = 'x' | 'reddit' | 'news';
export const overseasSources: { key: OverseasSource; label: string }[] = [
  { key: 'x', label: 'X' }, { key: 'reddit', label: 'Reddit' }, { key: 'news', label: '海外资讯' },
];
export interface OverseasItem {
  id: string; source: OverseasSource; title: string; url: string;
  publisher: string; author: string; summary: string; published_at: number | null;
  heat_score: number | null; metrics: Record<string, number>;
}
export interface OverseasData {
  configured: boolean; error: string; stale: boolean;
  fetched_at: number | null; feed_updated_at: number | null;
  groups: { source: OverseasSource; label: string; items: OverseasItem[] }[];
}
export async function fetchOverseasTrends(signal: AbortSignal): Promise<OverseasData> {
  const base = window.location.pathname.replace(/\/index\.html$/, '').replace(/\/$/, '');
  const response = await fetch(`${base}/api/overseas-trends`, { cache: 'no-store', signal });
  if (!response.ok) throw new Error('海外订阅暂时无法加载，请稍后刷新。');
  return response.json();
}
