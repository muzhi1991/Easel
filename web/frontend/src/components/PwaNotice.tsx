import { useEffect, useRef, useState } from 'react';

type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let registration: Promise<ServiceWorkerRegistration> | undefined;
export default function PwaNotice({ busy }: { busy: boolean }) {
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [install, setInstall] = useState<InstallPrompt | null>(null);
  const [notice, setNotice] = useState('');
  const [updating, setUpdating] = useState(false);
  useEffect(() => {
    const onInstall = (event: Event) => { event.preventDefault(); setInstall(event as InstallPrompt); };
    const installed = () => setInstall(null);
    window.addEventListener('beforeinstallprompt', onInstall);
    window.addEventListener('appinstalled', installed);
    return () => { window.removeEventListener('beforeinstallprompt', onInstall); window.removeEventListener('appinstalled', installed); };
  }, []);
  useEffect(() => {
    if (!import.meta.env.PROD || !window.isSecureContext || !('serviceWorker' in navigator)) return;
    let disposed = false;
    let cleanup = () => {};
    const controlled = !!navigator.serviceWorker.controller;
    const onChange = () => { if (controlled) window.location.reload(); };
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'CAN_UPDATE') {
        const hasDraft = Array.from(document.querySelectorAll('textarea')).some(el => !!el.value.trim());
        const hasAttachments = !!document.querySelector('.composer-attachments');
        event.ports[0]?.postMessage({ safe: !busyRef.current && !hasDraft && !hasAttachments });
      }
    };
    navigator.serviceWorker.addEventListener('controllerchange', onChange);
    navigator.serviceWorker.addEventListener('message', onMessage);
    registration ??= navigator.serviceWorker.register('./sw.js', { scope: './', updateViaCache: 'none' });
    void registration.then(reg => {
      if (disposed) return;
      const checkWaiting = () => { if (!disposed) setWaiting(reg.waiting); };
      const found = () => {
        const worker = reg.installing;
        worker?.addEventListener('statechange', () => {
          // During the installed event reg.waiting may not be assigned yet.
          if (!disposed && worker.state === 'installed' && reg.active) setWaiting(worker);
          else checkWaiting();
        });
      };
      reg.addEventListener('updatefound', found);
      checkWaiting();
      found();
      const check = () => { if (document.visibilityState === 'visible' && navigator.onLine) void reg.update().catch(() => {}); };
      document.addEventListener('visibilitychange', check);
      const timer = setInterval(check, 60 * 60 * 1000);
      cleanup = () => { clearInterval(timer); reg.removeEventListener('updatefound', found); document.removeEventListener('visibilitychange', check); };
    }).catch(() => { registration = undefined; });
    return () => {
      disposed = true; cleanup();
      navigator.serviceWorker.removeEventListener('controllerchange', onChange);
      navigator.serviceWorker.removeEventListener('message', onMessage);
    };
  }, []);
  const update = () => {
    if (!waiting || busy) return;
    setUpdating(true);
    const channel = new MessageChannel();
    const timeout = setTimeout(() => { setUpdating(false); setNotice('更新暂未完成，请稍后重试。'); channel.port1.close(); }, 5000);
    channel.port1.onmessage = (event) => {
      clearTimeout(timeout); channel.port1.close();
      if (!event.data?.safe) { setUpdating(false); setNotice('请先结束其他窗口的对话，并发送或清空草稿后更新。'); }
    };
    waiting.postMessage({ type: 'UPDATE' }, [channel.port2]);
  };
  if (!waiting && !install && !notice) return null;
  return <div className="history-notice pwa-notice" role="status">
    {waiting && <><span>新版本已准备好。</span><button className="btn btn-sm" disabled={busy || updating} onClick={update}>
      {busy ? '对话结束后可更新' : updating ? '正在更新…' : '更新并刷新'}
    </button></>}
    {install && <button className="btn btn-sm" onClick={async () => {
      try { await install.prompt(); await install.userChoice; } finally { setInstall(null); }
    }}>安装 Easel</button>}
    {notice && <span>{notice}</span>}
  </div>;
}
