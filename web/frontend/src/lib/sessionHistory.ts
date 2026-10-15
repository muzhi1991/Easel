import type { ChatSession } from './store';

export const historyEnd = (session: ChatSession) => (session.messageStart || 0) + session.messages.length;

/** Metadata refreshes preserve loaded pages; an epoch change invalidates them. */
export function mergeSessionSummary(current: ChatSession | undefined, summary: ChatSession): ChatSession {
  if (current?.source === 'server' && (current.revision || 0) > (summary.revision || 0)) return current;
  if (current?.source === 'server' && current.revision === summary.revision && !current.optimistic) return current;
  if (current?.historyLoaded && current.historyEpoch === summary.historyEpoch) {
    const start = Math.min(current.messageStart || 0, summary.messageCount || 0);
    const length = Math.max(0, (summary.messageCount || 0) - start);
    return { ...summary, messageStart: start, historyLoaded: true,
      messages: current.messages.length > length ? current.messages.slice(0, length) : current.messages };
  }
  return { ...summary, messages: [], messageStart: 0, historyLoaded: summary.messageCount === 0 };
}

export type HistoryPageMode = 'latest' | 'older' | 'newer';

/** Apply only contiguous pages from the same history, tolerating stale replies. */
export function mergeMessagePage(current: ChatSession, page: ChatSession, mode: HistoryPageMode): ChatSession {
  if (current.id !== page.id) return current;
  if (mode !== 'older' && current.optimistic) return current;
  if (mode === 'latest') {
    if ((page.revision || 0) < (current.revision || 0)) return current;
    return { ...page, historyLoaded: true };
  }
  if (!current.historyLoaded || current.historyEpoch !== page.historyEpoch) return current;
  if (mode === 'older' && historyEnd(page) !== (current.messageStart || 0)) return current;
  if (mode === 'newer' && page.messageStart !== historyEnd(current)) return current;
  const { messages: _messages, messageStart: _start, ...summary } = page;
  const metadata = (page.revision || 0) >= (current.revision || 0) && !current.optimistic ? summary : {};
  return { ...current, ...metadata, historyLoaded: true,
    messageStart: mode === 'older' ? page.messageStart : current.messageStart,
    messages: mode === 'older' ? [...page.messages, ...current.messages] : [...current.messages, ...page.messages] };
}
