import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { IconNewChat } from './icons';

const MOBILE_QUERY = '(max-width: 767px), (max-width: 1023px) and (pointer: coarse)';

/** One navigation tree: persistent on desktop, modal drawer on narrow screens. */
export default function ResponsiveShell({ title, persona, navigation, onNewChat, children }: {
  title: string;
  persona: string;
  navigation: (close: () => void) => ReactNode;
  onNewChat: () => void;
  children: ReactNode;
}) {
  const [mobile, setMobile] = useState(() => matchMedia(MOBILE_QUERY).matches);
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const close = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    const query = matchMedia(MOBILE_QUERY);
    const resize = () => {
      setMobile(query.matches);
      if (!query.matches) setOpen(false);
    };
    query.addEventListener('change', resize);
    return () => query.removeEventListener('change', resize);
  }, []);

  useEffect(() => {
    // dvh follows browser chrome; VisualViewport also follows the software keyboard.
    const viewport = window.visualViewport;
    const resize = () => {
      if (mobile && viewport && viewport.scale === 1) {
        document.documentElement.style.setProperty('--app-height', `${viewport.height}px`);
      } else {
        document.documentElement.style.removeProperty('--app-height');
      }
    };
    resize();
    viewport?.addEventListener('resize', resize);
    return () => {
      viewport?.removeEventListener('resize', resize);
      document.documentElement.style.removeProperty('--app-height');
    };
  }, [mobile]);

  useEffect(() => {
    if (mobile && open) drawer.current?.querySelector<HTMLButtonElement>('.mobile-nav-close')?.focus();
    else if (mobile && wasOpen.current) menuButton.current?.focus();
    wasOpen.current = open;
  }, [mobile, open]);

  return <div className="app-layout">
    <header className="mobile-header" inert={mobile && open}>
      <button ref={menuButton} className="mobile-icon-button" aria-label="打开导航"
        aria-expanded={open} aria-controls="app-navigation" onClick={() => setOpen(true)}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <div className="mobile-header-context"><strong>{title}</strong><span title={persona}>{persona}</span></div>
      <button className="mobile-icon-button" aria-label="新建对话" onClick={onNewChat}><IconNewChat size={21} /></button>
    </header>
    {mobile && open && <button className="mobile-nav-backdrop" tabIndex={-1} aria-label="关闭导航" onClick={close} />}
    <div id="app-navigation" ref={drawer} className={`navigation-shell${mobile && open ? ' is-open' : ''}`}
      role={mobile && open ? 'dialog' : undefined} aria-modal={mobile && open ? true : undefined}
      aria-label={mobile && open ? '导航与历史对话' : undefined} inert={mobile && !open}
      onKeyDown={(event) => {
        if (!mobile || !open || event.defaultPrevented) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        if (event.key !== 'Tab') return;
        const controls = Array.from(drawer.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), select:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]',
        ) || []).filter((el) => el.getClientRects().length > 0);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}>
      <button className="mobile-nav-close mobile-icon-button" aria-label="关闭导航" onClick={close}>×</button>
      {navigation(close)}
    </div>
    <main className="main-content" inert={mobile && open}>{children}</main>
  </div>;
}
