import { useEffect, useRef, useState } from 'react';
import DownloadControl from './DownloadControl';
import { isStandalone } from '../lib/download';
import { artifactFromUrl } from '../lib/artifacts';

/** Standalone WebKit has no back bar on a raw media document. Keep the shell mounted. */
export default function FilePreview() {
  const [url, setUrl] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const open = (event: MouseEvent) => {
      if (!isStandalone() || event.defaultPrevented || event.button !== 0
          || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
      if (!(link instanceof HTMLAnchorElement) || link.closest('.download-control, .file-preview')) return;
      const target = new URL(link.href, window.location.href);
      if (target.origin !== window.location.origin || !target.pathname.includes('/api/media/')) return;
      event.preventDefault();
      target.searchParams.delete('download');
      setUrl(target.href);
    };
    document.addEventListener('click', open, true);
    return () => document.removeEventListener('click', open, true);
  }, []);
  useEffect(() => {
    if (url && !dialog.current?.open) dialog.current?.showModal();
  }, [url]);
  const path = url ? new URL(url).pathname : '';
  const artifact = artifactFromUrl(path.slice(path.indexOf('/api/media/')));
  let name = artifact?.name || path.split('/').pop() || '文件';
  if (!artifact) { try { name = decodeURIComponent(name); } catch { /* Keep malformed names readable. */ } }
  return <dialog ref={dialog} className="file-preview" aria-label="文件预览与保存" onClose={() => setUrl(null)}>
    {url && <>
      <header><button type="button" onClick={() => dialog.current?.close()}>返回 Easel</button><strong>{name}</strong></header>
      <div className="file-preview-content">
        {artifact?.kind === 'image' ? <img src={url} alt={name} />
          : artifact?.kind === 'video' ? <video src={url} controls playsInline preload="metadata" />
          : artifact?.kind === 'audio' ? <audio src={url} controls preload="metadata" />
          : artifact?.kind === 'html' || artifact?.kind === 'pdf' ? <iframe title={name} src={url} sandbox="" />
          : <p>此文件无法直接预览，可以保存后打开。</p>}
      </div>
      <DownloadControl key={url} url={url} name={name} />
    </>}
  </dialog>;
}
