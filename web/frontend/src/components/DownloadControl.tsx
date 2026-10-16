import { useEffect, useRef, useState } from 'react';
import { browserDownloadUrl, DownloadTask, formatBytes } from '../lib/download';
import type { DownloadState } from '../lib/download';

export default function DownloadControl({ url, name }: { url: string; name: string }) {
  const task = useRef<DownloadTask | null>(null);
  const [state, setState] = useState<DownloadState | null>(null);
  const [now, setNow] = useState(Date.now());
  const busy = state?.phase === 'connecting' || state?.phase === 'receiving';
  const ready = state?.phase === 'ready';
  const sharing = state?.phase === 'sharing';
  useEffect(() => {
    const leave = () => { task.current?.dispose(); task.current = null; setState(null); };
    window.addEventListener('pagehide', leave);
    return () => { window.removeEventListener('pagehide', leave); task.current?.dispose(); task.current = null; };
  }, [url]);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [busy]);
  function start(share: boolean) {
    task.current?.dispose();
    const next = new DownloadTask(setState);
    task.current = next;
    void next.start(url, name, share);
  }
  const stalled = busy && state && now - state.lastData > 15000;
  const percent = state?.total ? Math.min(99, Math.floor(state.received / state.total * 100)) : undefined;
  const eta = state?.total && state.speed > 0 && now - state.started > 3000 && !stalled
    ? Math.ceil(Math.max(0, state.total - state.received) / state.speed) : undefined;
  const supportsShare = typeof navigator.share === 'function' && typeof navigator.canShare === 'function';
  return <div className="download-control">
    <div className="download-actions">
      {!busy && !ready && !sharing && state?.phase !== 'browser' && <button type="button" onClick={() => start(false)}>{state?.phase === 'error' || state?.phase === 'cancelled' ? '重新下载' : '下载'}</button>}
      {supportsShare && !busy && !sharing && state?.phase !== 'browser' && <button type="button" onClick={() => ready ? void task.current?.share() : start(true)}>{ready ? '分享/保存' : '准备分享/保存'}</button>}
      {(busy || ready) && <button type="button" onClick={() => task.current?.cancel()}>{ready ? '清理临时文件' : '取消下载'}</button>}
      {!sharing && <a href={browserDownloadUrl(url, window.location.origin)} download={name} target="_blank" rel="noreferrer"
        onClick={() => { task.current?.dispose(); task.current = null; setState({ phase: 'browser', received: 0, speed: 0, started: 0, lastData: 0,
          message: '已请求浏览器下载，请在浏览器下载列表查看进度；外部文件可能会在新页面打开。' }); }}>使用浏览器下载</a>}
    </div>
    {busy && state && <div className="download-progress">
      <progress aria-label={`${name} 下载进度`} max={100} value={percent} />
      <span>{state.phase === 'connecting' ? '正在连接…' : `${percent === undefined ? '' : percent + '% · '}${formatBytes(state.received)}${state.total ? ' / ' + formatBytes(state.total) : ' 已下载'}`}</span>
      {state.phase === 'receiving' && !stalled && <span>{formatBytes(state.speed)}/s{eta === undefined ? '' : ` · 预计剩余 ${eta < 60 ? eta + ' 秒' : Math.ceil(eta / 60) + ' 分钟'}`}</span>}
    </div>}
    {state && <p role="status">{stalled ? '连接较慢，正在等待数据；可以取消下载。' : state.message}</p>}
  </div>;
}
