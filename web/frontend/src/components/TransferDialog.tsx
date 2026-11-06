import { useState } from 'react';
import type { ChatSession } from '../lib/store';
import type { PersonaItem } from '../lib/api';

export default function TransferDialog({ session, personas, onSave, onClose }: {
  session: ChatSession; personas: PersonaItem[];
  onSave: (persona: string, copy: boolean) => Promise<void>; onClose: () => void;
}) {
  const [persona, setPersona] = useState(session.persona || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (copy: boolean) => {
    setBusy(true); setError('');
    try { await onSave(persona, copy); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); }
  };
  return <div className="overlay rename-overlay" onClick={() => { if (!busy) onClose(); }}>
    <div className="modal rename-dialog" role="dialog" aria-modal="true" aria-labelledby="transfer-title"
      onClick={e => e.stopPropagation()}>
      <h3 id="transfer-title">复制或移动对话</h3>
      <p>{session.title}</p>
      <select className="session-rename-input" aria-label="目标画像" autoFocus disabled={busy}
        value={persona} onChange={event => setPersona(event.target.value)}>
        <option value="">通用模式</option>
        {personas.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
      </select>
      <p>保留历史内容，后续创作和发布使用目标画像及其账号。复制会保留原对话。</p>
      {error && <p role="alert">{error}</p>}
      <div className="rename-footer">
        <button className="btn" disabled={busy} onClick={onClose}>取消</button>
        <button className="btn" disabled={busy} onClick={() => void save(true)}>复制</button>
        <button className="btn btn-primary" disabled={busy || persona === (session.persona || '')}
          onClick={() => void save(false)}>移动</button>
      </div>
    </div>
  </div>;
}
