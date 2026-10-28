export type OverseasSource = 'x' | 'reddit' | 'news' | 'ithome';
export const overseasSources: { key: OverseasSource; label: string }[] = [
  { key: 'x', label: 'X' }, { key: 'reddit', label: 'Reddit' }, { key: 'news', label: '海外资讯' },
];
export interface FeedConfig {
  endpoint: string; label: string; sources: typeof overseasSources;
}
export const overseasConfig: FeedConfig = { endpoint: '/api/overseas-trends', label: '海外', sources: overseasSources };
export const ithomeConfig: FeedConfig = { endpoint: '/api/ithome-trends', label: 'IT之家', sources: [{ key: 'ithome', label: 'IT之家' }] };
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
export async function fetchOverseasTrends(signal: AbortSignal, config: FeedConfig = overseasConfig): Promise<OverseasData> {
  const base = window.location.pathname.replace(/\/index\.html$/, '').replace(/\/$/, '');
  const response = await fetch(`${base}${config.endpoint}`, { cache: 'no-store', signal });
  if (!response.ok) throw new Error(`${config.label}订阅暂时无法加载，请稍后刷新。`);
  return response.json();
}
