import { useState, useEffect } from 'react';
import { fetchOverseasTrends } from './api';
import type { OverseasSource, OverseasData } from './api';

export function useOverseasTrends() {
  const [selected, setSelected] = useState<OverseasSource[]>([]);
  const [data, setData] = useState<OverseasData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const enabled = selected.length > 0;
  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void fetchOverseasTrends(controller.signal).then((next) => {
      if (!controller.signal.aborted) setData(next);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '海外订阅暂时无法加载。');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [enabled, revision]);
  const toggle = (key: OverseasSource) => setSelected((previous) =>
    previous.includes(key) ? previous.filter((value) => value !== key) : [...previous, key]);
  const refresh = () => { if (enabled) setRevision((previous) => previous + 1); };
  return { selected, toggle, data, loading, error, refresh };
}
export type OverseasState = ReturnType<typeof useOverseasTrends>;
