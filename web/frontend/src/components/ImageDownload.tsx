import { useState } from 'react';
import type { Artifact } from '../lib/artifacts';

export default function ImageDownload({ artifact }: { artifact: Artifact }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState('');
  const canShare = typeof navigator.canShare === 'function' && typeof navigator.share === 'function';

  async function prepare() {
    if (file) return file;
    const response = await fetch(artifact.url, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error('download');
    const blob = await response.blob();
    if (!blob.type.startsWith('image/')) throw new Error('image');
    const extensions: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg',
      'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/avif': 'avif' };
    const suffix = extensions[blob.type];
    const name = Array.from(artifact.name).map(c => c === '/' || c === '\\' || c.charCodeAt(0) < 32 ? '_' : c).join('');
    const result = new File([blob], suffix && !/\.(png|jpe?g|webp|gif|svg|avif|bmp|ico)$/i.test(name)
      ? `${name}.${suffix}` : name, { type: blob.type });
    setFile(result);
    return result;
  }

  async function save(share: boolean) {
    setBusy(true);
    setHint('');
    try {
      // Share prepared files on a fresh click, retaining Safari's user activation.
      if (share && file) {
        await navigator.share({ files: [file] });
        return;
      }
      const image = await prepare();
      if (share) {
        setHint(navigator.canShare({ files: [image] })
          ? '图片已准备好，请再次点“分享/保存”，在系统菜单选择保存。'
          : '当前浏览器不支持分享此图片，请点“下载图片”或打开原图保存。');
        return;
      }
      const url = URL.createObjectURL(image);
      const link = document.createElement('a');
      link.href = url;
      link.download = image.name;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      setHint('已请求下载。手机如需存入相册，可使用“分享/保存”或打开原图后长按保存。');
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      setHint('无法直接保存图片。请点“打开 ↗”后长按图片或使用浏览器保存；外部图片可能限制下载。');
    } finally { setBusy(false); }
  }

  return <div className="image-download">
    <div className="image-download-actions">
      <button type="button" disabled={busy} onClick={() => void save(false)}>{busy ? '正在准备…' : '下载图片'}</button>
      {canShare && (!file || navigator.canShare({ files: [file] })) &&
        <button type="button" disabled={busy} onClick={() => void save(true)}>{file ? '分享/保存' : '准备分享/保存'}</button>}
    </div>
    {hint && <p role="status">{hint}</p>}
  </div>;
}
