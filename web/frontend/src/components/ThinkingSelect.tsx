import ReasoningMenu from './ReasoningMenu';
import { useEffect, useState } from 'react';
import { fetchThinking, saveThinking } from '../lib/api';
import type { ThinkingLevel } from '../lib/api';

const levels: ThinkingLevel[] = ['max', 'high', 'medium', 'low', 'off'];
// Migrate older saved choices to the compact set, including the value sent with a turn.
function compactLevel(level: ThinkingLevel): ThinkingLevel {
  if (levels.includes(level)) return level;
  if (level === 'minimal') return 'low';
  if (level === 'xhigh' || level === 'ultra') return 'max';
  return 'high';
}

export default function ThinkingSelect({ defaults = false, value, onChange, disabled = false }: {
  defaults?: boolean; value?: ThinkingLevel; onChange?: (level?: ThinkingLevel) => void; disabled?: boolean;
}) {
  const [current, setCurrent] = useState<ThinkingLevel>();
  const [draft, setDraft] = useState<ThinkingLevel>();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  useEffect(() => {
    let alive = true;
    const refresh = () => {
      fetchThinking().then((d) => {
        if (alive) { setCurrent(d.thinking); setDraft(compactLevel(d.thinking)); setNote(''); }
      }).catch(() => { if (alive) setNote('推理设置读取失败'); });
    };
    refresh();
    window.addEventListener('easel-thinking-config', refresh);
    window.addEventListener('focus', refresh);
    return () => {
      alive = false;
      window.removeEventListener('easel-thinking-config', refresh);
      window.removeEventListener('focus', refresh);
    };
  }, []);
  const effective = value ?? current;
  useEffect(() => {
    if (!defaults && !disabled && effective && compactLevel(effective) !== effective) {
      onChange?.(compactLevel(effective));
    }
  }, [defaults, disabled, effective, onChange]);
  const save = async () => {
    if (!draft) return;
    setBusy(true); setNote('');
    try {
      const d = await saveThinking(draft);
      setCurrent(d.thinking); setDraft(compactLevel(d.thinking));
      window.dispatchEvent(new Event('easel-thinking-config'));
      setNote('已保存');
    } catch (e) { setNote(e instanceof Error ? e.message : '保存失败'); }
    finally { setBusy(false); }
  };
  return <div className={`thinking-control${defaults ? ' thinking-defaults' : ''}`}>
    <div className="thinking-field"><span>{defaults ? '默认推理' : '推理'}</span>
      <ReasoningMenu label={defaults ? '默认推理' : '推理'}
        title={note || (defaults ? '新对话的默认推理级别' : '下一条消息的推理级别')}
        disabled={disabled || busy || (!defaults && !effective) || (defaults && !current)}
        value={defaults ? draft : effective ? compactLevel(effective) : undefined}
        onChange={(level) => defaults ? setDraft(level) : onChange?.(level)} />
    </div>
    {defaults && <><button className="btn btn-sm" disabled={busy || !draft || draft === current} onClick={() => void save()}>{busy ? '保存中…' : '保存'}</button>
      <span className="desc">用于未单独设置推理的对话。</span></>}
    {note && <span className="thinking-note" role="status">{note}</span>}
  </div>;
}
