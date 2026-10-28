import { useEffect, useState } from 'react';

/** Browser-local preferences; an explicitly empty selection is valid. */
export function useChannelSelection<T extends string>(key: string, allowed: readonly T[], defaults: T[]) {
  const [selected, setSelected] = useState<T[]>(() => {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
      if (Array.isArray(stored) && stored.every((value) => typeof value === 'string')) {
        return [...new Set(stored.filter((value): value is T => allowed.includes(value as T)))];
      }
    } catch { /* Invalid or unavailable storage: use the initial defaults. */ }
    return defaults;
  });
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(selected)); }
    catch { /* Selection still works when browser storage is unavailable. */ }
  }, [key, selected]);
  return [selected, setSelected] as const;
}
