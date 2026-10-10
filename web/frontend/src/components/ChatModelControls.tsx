import { useEffect, useState } from 'react';
import { fetchChatModel } from '../lib/api';
import type { ChatModelStatus, ThinkingLevel } from '../lib/api';
import ThinkingSelect from './ThinkingSelect';

export default function ChatModelControls({ sessionId, streaming, thinking, onThinkingChange }: {
  sessionId: string;
  streaming: boolean;
  thinking?: ThinkingLevel;
  onThinkingChange: (level?: ThinkingLevel) => void;
}) {
  const [status, setStatus] = useState<ChatModelStatus>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    let sequence = 0;
    setStatus(undefined);
    setFailed(false);
    const refresh = () => {
      const requestId = ++sequence;
      fetchChatModel(sessionId).then((result) => {
        if (alive && requestId === sequence) { setStatus(result); setFailed(false); }
      }).catch(() => {
        if (alive && requestId === sequence) { setStatus(undefined); setFailed(true); }
      });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener('easel-model-config', refresh);
    window.addEventListener('focus', refresh);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener('easel-model-config', refresh);
      window.removeEventListener('focus', refresh);
    };
  }, [sessionId, streaming]);
  const uncertain = failed || status?.source === 'unavailable';
  const title = failed ? '模型读取失败，请检查网关连接' : status?.source === 'unavailable'
    ? `网关暂不可用，显示配置中的主模型：${status.modelRef}`
    : status?.modelRef ? `当前模型：${status.modelRef}；可在设置中切换` : '正在读取当前模型';
  return <div className="chat-model-controls" role="group" aria-label="模型与推理">
    <div className={`chat-current-model${uncertain ? ' is-uncertain' : ''}`} title={title}>
      <span className="model-indicator" aria-hidden="true" />
      <span className="chat-model-name">{status?.model || (failed ? '模型不可用' : '读取模型…')}</span>
      {status?.source === 'unavailable' && <span className="model-fallback-label">默认</span>}
    </div>
    <ThinkingSelect value={thinking} onChange={onThinkingChange} disabled={streaming} />
  </div>;
}
