import { useEffect, useState } from 'react';
import { fetchThinking, saveThinking } from '../lib/api';
import type { ThinkingLevel } from '../lib/api';

const levels: [ThinkingLevel, string][] = [
  ['off', '关闭'], ['minimal', '最低'], ['low', '低'], ['medium', '中'],
  ['high', '高'], ['xhigh', '更高'], ['adaptive', '自动'], ['max', '最大'], ['ultra', '极高'],
];

export default function ThinkingSelect({ defaults = false, value, onChange, disabled = false }: {
  defaults?: boolean; value?: ThinkingLevel; onChange?: (level?: ThinkingLevel) => void; disabled?: boolean;
}) {
  const [current, setCurrent] = useState<ThinkingLevel>();
  const [draft, setDraft] = useState<ThinkingLevel>();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  useEffect(() => {
    let alive = true;
    fetchThinking().then((d) => { if (alive) { setCurrent(d.thinking); setDraft(d.thinking); } })
      .catch(() => { if (alive) setNote('默认强度读取失败'); });
    return () => { alive = false; };
  }, []);
  const save = async () => {
    if (!draft) return;
    setBusy(true); setNote('');
    try { const d = await saveThinking(draft); setCurrent(d.thinking); setDraft(d.thinking); setNote('已保存，下次发送生效'); }
    catch (e) { setNote(e instanceof Error ? e.message : '保存失败'); }
    finally { setBusy(false); }
  };
  const label = levels.find(([id]) => id === current)?.[1];
  return <div className="thinking-control">
    <label>{defaults ? '默认推理强度' : '推理强度'}
      <select aria-label={defaults ? '默认推理强度' : '当前对话推理强度'}
        disabled={disabled || busy || (defaults && !current)} value={defaults ? draft || '' : value || ''}
        onChange={(e) => defaults ? setDraft(e.target.value as ThinkingLevel) : onChange?.((e.target.value || undefined) as ThinkingLevel | undefined)}>
        {!defaults && <option value="">跟随默认{label ? `（${label}）` : ''}</option>}
        {defaults && !current && <option value="">读取中…</option>}
        {levels.map(([id, text]) => <option value={id} key={id}>{text} · {id}</option>)}
      </select>
    </label>
    {defaults && <><button className="btn btn-sm" disabled={busy || !draft || draft === current} onClick={() => void save()}>{busy ? '保存中…' : '保存强度'}</button>
      <span className="desc">用于跟随默认的对话；可用档位取决于模型。</span></>}
    {note && <span role="status">{note}</span>}
  </div>;
}
