import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ThinkingLevel } from '../lib/api';

const levels: ThinkingLevel[] = ['max', 'high', 'medium', 'low', 'off'];

export default function ReasoningMenu({ value, disabled, label, title, onChange }: {
  value?: ThinkingLevel;
  disabled: boolean;
  label: string;
  title: string;
  onChange: (value: ThinkingLevel) => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number }>();
  const open = () => {
    if (disabled || !trigger.current) return;
    const rect = trigger.current.getBoundingClientRect();
    const height = 168;
    setPosition({ left: Math.max(8, Math.min(rect.right - 116, window.innerWidth - 124)),
      top: rect.top >= height + 8 ? rect.top - height - 6 : rect.bottom + 6 });
  };
  const close = (focus = false) => {
    setPosition(undefined);
    if (focus) trigger.current?.focus();
  };
  useEffect(() => {
    if (!position) return;
    if (disabled) { setPosition(undefined); return; }
    menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    const outside = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(undefined);
    };
    const dismiss = () => setPosition(undefined);
    window.addEventListener('pointerdown', outside);
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', dismiss, true);
    return () => {
      window.removeEventListener('pointerdown', outside);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', dismiss, true);
    };
  }, [position, disabled]);
  return <>
    <button ref={trigger} type="button" className="reasoning-trigger" aria-label={`${label} ${value || ''}`}
      aria-haspopup="menu" aria-expanded={!!position} aria-controls={position ? id : undefined}
      title={title} disabled={disabled} onClick={() => position ? close() : open()}
      onKeyDown={(e) => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); open(); } }}>
      <span>{value || '—'}</span>
      <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </button>
    {position && createPortal(<div ref={menu} id={id} role="menu" aria-label={label}
      className="reasoning-menu" style={position} onKeyDown={(e) => {
        const buttons = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') || []);
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
        else if (e.key === 'Tab') { e.preventDefault(); close(true); }
        else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
          e.preventDefault();
          const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1
            : (index + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }
      }}>
      {levels.map((level) => <button type="button" key={level} role="menuitemradio" aria-checked={value === level}
        tabIndex={-1} onClick={() => { onChange(level); close(true); }}>
        <span>{level}</span><span className="reasoning-check" aria-hidden="true">{value === level ? '✓' : ''}</span>
      </button>)}
    </div>, document.body)}
  </>;
}
