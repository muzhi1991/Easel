import { useRef, useState } from 'react';
import type { ChatSession } from '../lib/store';
import { suggestSessionTitle } from '../lib/sharedSessions';

interface Props {
  session: ChatSession;
  messageIndex?: number;
  artifactTitle?: string;
  onSave: (title: string) => Promise<void>;
  onClose: () => void;
}

export default function RenameDialog({ session, messageIndex, artifactTitle, onSave, onClose }: Props) {
  const [title, setTitle] = useState(session.title);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const editVersion = useRef(0);
  const suggest = async () => {
    const version = editVersion.current;
    setGenerating(true); setError('');
    try {
      const result = await suggestSessionTitle(session, messageIndex);
      if (editVersion.current === version) setTitle(result.title);
    } catch (err) { setError((err as Error).message); }
    finally { setGenerating(false); }
  };
  const save = async () => {
    setSaving(true); setError('');
    try { await onSave(title.trim()); onClose(); }
    catch (err) { setError((err as Error).message); }
    finally { setSaving(false); }
  };
  return <div className="overlay rename-overlay" onClick={() => { if (!saving) onClose(); }}>
    <form className="modal rename-dialog" role="dialog" aria-modal="true" aria-labelledby="rename-dialog-title"
      onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); if (title.trim() && !saving) void save(); }}
      onKeyDown={e => { if (e.key === 'Escape' && !saving) onClose(); }}>
      <h2 id="rename-dialog-title">重命名对话</h2>
      <input className="session-rename-input" aria-label="对话名称" autoFocus maxLength={500} value={title}
        disabled={saving} onChange={e => { editVersion.current++; setTitle(e.target.value); }} />
      <p className="rename-hint">保存后将保留你的命名，不再随产物自动修改。</p>
      <div className="rename-options">
        {artifactTitle && <button type="button" className="btn" disabled={saving} onClick={() => {
          editVersion.current++; setTitle(artifactTitle);
        }}>使用此产物标题</button>}
        {session.source === 'server' && !!session.revision && <button type="button" className="btn"
          disabled={generating || saving} onClick={() => void suggest()}>{generating ? '生成中…' : '智能命名'}</button>}
      </div>
      {error && <p role="alert" className="rename-error">{error}</p>}
      <div className="rename-footer">
        <button type="button" className="btn" disabled={saving} onClick={onClose}>取消</button>
        <button type="submit" className="btn btn-primary" disabled={!title.trim() || saving}>{saving ? '保存中…' : '保存'}</button>
      </div>
    </form>
  </div>;
}
