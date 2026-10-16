import { useEffect, useRef, useState } from 'react';
import type { UploadedFile } from '../lib/api';
import { mediaUrl } from '../lib/api';
import { IconFile } from './icons';
import DownloadControl from './DownloadControl';

function Attachment({ file }: { file: UploadedFile }) {
  const card = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Render only a filename; internal storage paths belong in the URL, not the UI.
  const name = file.name?.split(/[\\/]/).at(-1) || '附件';
  const valid = typeof file.path === 'string' && file.path.length > 0
    && !file.path.includes('\\') && !file.path.split('/').some(part => !part || part === '.' || part === '..');
  const url = valid ? mediaUrl(file.path) : '';
  const extension = name.split('.').at(-1)?.toLowerCase() || '';
  const kind = /^(png|jpe?g|gif|webp|svg|avif|bmp|ico)$/.test(extension) ? 'image'
    : /^(mp4|webm|mov|m4v|mkv)$/.test(extension) ? 'video'
    : /^(mp3|wav|ogg|m4a|flac|aac)$/.test(extension) ? 'audio' : 'file';

  useEffect(() => {
    if (!card.current) return;
    if (!('IntersectionObserver' in window)) { setVisible(true); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: '200px' });
    observer.observe(card.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || !url) return;
    const controller = new AbortController();
    setFailed(false);
    setMissing(false);
    void fetch(url, { method: 'HEAD', cache: 'no-store', signal: controller.signal }).then(response => {
      if (controller.signal.aborted) return;
      setMissing(response.status === 404 || response.status === 410);
      setFailed(!response.ok && response.status !== 404 && response.status !== 410);
    }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [url, visible, attempt]);

  return <div className="message-attachment" ref={card}>
    <div className="message-attachment-name"><IconFile size={16} /><span title={name}>{name}</span></div>
    {!valid || missing ? <p className="message-attachment-hint" role="status">附件不可用</p> : <>
      {visible && !previewFailed && <div className="message-attachment-preview">
        {kind === 'image' && <a href={url} target="_blank" rel="noreferrer" aria-label={`查看原图：${name}`}>
          <img src={url} alt={name} loading="lazy" onError={() => setPreviewFailed(true)} /></a>}
        {kind === 'video' && <video src={url} controls playsInline preload="none" aria-label={name} onError={() => setPreviewFailed(true)} />}
        {kind === 'audio' && <audio src={url} controls preload="none" aria-label={name} onError={() => setPreviewFailed(true)} />}
      </div>}
      {(failed || previewFailed) && <p className="message-attachment-hint" role="status">
        {failed ? '暂时无法检查附件，请检查网络后重试。' : '无法预览，可尝试打开或下载。'}
        <button type="button" onClick={() => { setPreviewFailed(false); setAttempt(value => value + 1); }}>重试</button>
      </p>}
      <div className="message-attachment-actions">
        <a href={url} target="_blank" rel="noreferrer">{kind === 'image' ? '查看原图' : '打开'}</a>
        <DownloadControl key={url} url={url} name={name} />
      </div>
    </>}
  </div>;
}

export default function MessageAttachments({ files }: { files: UploadedFile[] }) {
  return <div className="message-attachments" aria-label="消息附件">
    {files.filter(Boolean).map((file, index) => <Attachment key={`${file.id}:${file.path}:${index}`} file={file} />)}
  </div>;
}
