import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { deleteMediaProvider, fetchMediaProviders, probeMediaProvider, saveMediaProvider } from '../lib/api';
import type { MediaConfiguration, MediaProvider, ModelRow } from '../lib/api';

/** Descriptor-driven extension UI: no Qwen fields or endpoint knowledge here. */
export default function MediaProviders({ channel, builtInRows = [], builtInBoard, onConfigured }: { channel: string; builtInRows?: ModelRow[]; builtInBoard?: (rows: ReactNode) => ReactNode; onConfigured?: (configured: boolean) => void }) {
  const [config, setConfig] = useState<MediaConfiguration | null>(null);
  const [draft, setDraft] = useState<MediaProvider | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [probes, setProbes] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    const refresh = () => fetchMediaProviders().then((data) => { if (alive) setConfig(data); })
      .catch((e: Error) => { if (alive) setNote(e.message); });
    refresh();
    window.addEventListener('easel-media-config', refresh);
    return () => { alive = false; window.removeEventListener('easel-media-config', refresh); };
  }, []);

  useEffect(() => { setDraft(null); setNote(''); }, [channel]);
  const adapters = config?.adapters.filter((a) => a.channels.includes(channel)) || [];
  const providers = config?.providers.filter((p) => adapters.some((a) => a.id === p.adapter)) || [];
  useEffect(() => { onConfigured?.(providers.length > 0); }, [config, channel, onConfigured]);
  const selected = adapters.find((a) => a.id === draft?.adapter);

  const newDraft = (adapter: string): MediaProvider => ({
    id: '', name: '', adapter,
    settings: Object.fromEntries((adapters.find((a) => a.id === adapter)?.fields || []).map((f) =>
      [f.key, f.default ?? (f.type === 'boolean' ? false : '')])),
  });

  const act = async (action: () => Promise<MediaConfiguration>) => {
    setBusy(true); setNote('');
    try { setConfig(await action()); setDraft(null); setNote('已保存，下一次任务生效'); window.dispatchEvent(new Event('easel-media-config')); }
    catch (e) { setNote(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); }
  };

  const probe = async (id: string) => {
    setBusy(true);
    setProbes((p) => ({ ...p, [id]: '探活中…' }));
    try {
      const result = await probeMediaProvider(id);
      setProbes((p) => ({ ...p, [id]: `${result.ok ? '连接正常' : '连接失败'}：${result.detail}` }));
    } catch (e) { setProbes((p) => ({ ...p, [id]: e instanceof Error ? e.message : '探活失败' })); }
    finally { setBusy(false); }
  };

  const providerRows = providers.map((provider, index) => {
          const isDefault = config?.defaults[channel] === provider.id;
          const adapter = adapters.find((a) => a.id === provider.adapter);
          const urls = Object.entries(provider.settings).filter(([key]) => key.endsWith('_url'));
          return <div className="prow" key={provider.id}>
            <span className="step">{index + 1}</span>
            <span className="pname">{provider.name}</span>
            <span className="cell-text" title={adapter?.name}>{adapter?.name || provider.adapter}</span>
            <span className="cell-text" title={String(provider.settings.model || '')}>{String(provider.settings.model || '—')}</span>
            <span className="cell-text">{urls.map(([key, value]) => <div key={key} title={String(value)}>{String(value)}</div>)}</span>
            <span className="cell-text" title={String(provider.settings.api_key_env || '无需鉴权')}>
              {provider.settings.api_key_env ? '环境凭证' : '无需'}</span>
            <button className={`tag ${isDefault ? 'main' : 'backup'}`} disabled={busy || isDefault}
              title={isDefault ? '此通道默认供应商' : '设为此通道默认供应商'}
              onClick={() => void act(() => saveMediaProvider(provider, [channel]))}>{isDefault ? '默认' : '可选'}</button>
            <span className="cell-text" title={probes[provider.id] || '尚未探活'}>{probes[provider.id] || '尚未探活'}</span>
            <span className="media-provider-actions">
              <button className="btn btn-sm" disabled={busy} onClick={() => {
                setDraft({ ...provider, settings: { ...provider.settings } }); setEditing(true); setNote('');
              }}>编辑</button>
              <button className="btn btn-sm" disabled={busy} onClick={() => void probe(provider.id)}>探活</button>
              {!isDefault && <button className="btn btn-sm" disabled={busy}
                onClick={() => void act(() => deleteMediaProvider(provider.id))}>删除</button>}
            </span>
          </div>;
        });
  // Other channels can use this same UI when their first execution adapter is installed.
  if (!adapters.length && config && !builtInRows.length && !builtInBoard) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <div className="panel-top">
        <span className="spacer" />
        <button className="btn btn-sm" disabled={busy || !adapters.length} onClick={() => {
          setDraft(newDraft(adapters[0].id)); setEditing(false); setNote('');
        }}>＋ 添加供应商</button>
      </div>
      {builtInBoard ? builtInBoard(providerRows) : <div className="board media-provider-board">
        <div className="prow head">
          <span>顺序</span><span>供应商</span><span>类型</span><span>模型</span>
          <span>Base URL</span><span>API Key</span><span>角色</span><span>连接状态</span><span>操作</span>
        </div>
        {builtInRows.map((row, index) => <div className="prow" key={`builtin-${index}`}>
          <span className="step ghost">{row.order || '—'}</span>
          <span className="pname">{row.name}<small>{row.sub}</small></span>
          <span>{row.type}</span><span className="cell-text">{row.model || '—'}</span>
          <span className="cell-text">{row.baseUrl || '—'}</span><span>{row.keyMasked || '—'}</span>
          <span className="tag main">优先</span><span>{row.result || '—'}</span><span />
        </div>)}
        {providerRows}
      </div>}
      {config && !providers.length && <div className="foot-note">尚未配置此通道的自定义供应商。</div>}
      {draft && <form onSubmit={(e) => { e.preventDefault(); void act(() => saveMediaProvider(draft)); }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(150px, 1fr) minmax(160px, 2fr)', gap: 10, padding: '16px 0' }}>
          <label htmlFor="media-adapter">接口类型</label>
          <select id="media-adapter" value={draft.adapter} disabled={editing || busy}
            onChange={(e) => setDraft(newDraft(e.target.value))}>
            {adapters.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <label htmlFor="media-id">唯一 ID</label>
          <input id="media-id" required pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}" value={draft.id} disabled={editing || busy}
            onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
          <label htmlFor="media-name">名称</label>
          <input id="media-name" required maxLength={100} value={draft.name} disabled={busy}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          {selected?.fields.map((field) => {
            const id = `media-${field.key}`;
            const update = (value: string | number | boolean) => setDraft({ ...draft, settings: { ...draft.settings, [field.key]: value } });
            return <div key={field.key} style={{ display: 'contents' }}>
              <label htmlFor={id}>{field.label}</label>
              {field.type === 'boolean' ? <input id={id} type="checkbox" disabled={busy} checked={Boolean(draft.settings[field.key])}
                onChange={(e) => update(e.target.checked)} /> : field.choices ?
                <select id={id} disabled={busy} value={String(draft.settings[field.key] ?? '')} onChange={(e) => update(e.target.value)}>
                  {field.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
                </select> : <input id={id} disabled={busy} required={field.required} min={field.min} max={field.max}
                  type={field.type === 'url' ? 'url' : field.type === 'number' ? 'number' : 'text'}
                  value={String(draft.settings[field.key] ?? '')}
                  onChange={(e) => update(field.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)} />}
            </div>;
          })}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-sm" type="submit" disabled={busy}>保存供应商</button>
          <button className="btn btn-sm btn-primary" type="button" disabled={busy} onClick={(e) => {
            if (e.currentTarget.form?.reportValidity()) void act(() => saveMediaProvider(draft, [channel]));
          }}>保存并设为默认</button>
          <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setDraft(null)}>取消</button>
        </div>
      </form>}
      {note && <div className="foot-note" role="status">{note}</div>}
    </div>
  );
}
