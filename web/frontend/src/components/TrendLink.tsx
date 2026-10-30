import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** Keep external articles inside a returnable shell, including standalone iOS. */
export default function TrendLink({ url, title, className, summary }: {
  url?: string; title: string; className: string; summary?: string;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLAnchorElement>(null);
  const address = useRef<HTMLInputElement>(null);
  const safeUrl = url && /^https?:\/\//i.test(url) ? url : undefined;
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  const close = () => {
    setOpen(false);
    setCopied(false);
    trigger.current?.focus();
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(safeUrl!); setCopied(true); }
    catch { address.current?.focus(); address.current?.select(); }
  };
  return <>
    <a ref={trigger} className={className} href={safeUrl} target="_blank" rel="noreferrer" title={title}
      onClick={(event) => {
        if (!safeUrl || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        setOpen(true);
      }}>{title}</a>
    {open && createPortal(<dialog ref={dialog} className="trend-detail" aria-label="热点详情" onClose={close}>
      <header><button type="button" className="btn" onClick={() => dialog.current?.close()}>返回热点</button>
        <strong>{title}</strong></header>
      {summary && <details><summary>查看摘要</summary><p>{summary}</p></details>}
      <iframe title="热点原文" src={safeUrl} sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer" />
      <footer>
        <p>原文若无法显示，可复制链接到浏览器阅读。</p>
        <div><input ref={address} aria-label="原文链接" value={safeUrl} readOnly />
          <button type="button" className="btn" onClick={() => void copy()}>{copied ? '已复制' : '复制链接'}</button></div>
      </footer>
    </dialog>, document.body)}
  </>;
}
