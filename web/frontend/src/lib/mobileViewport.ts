/** Keep the app in the visible part of an iOS WebView, including keyboard pans.
 * This changes geometry only: never blur/refocus, reload, or replace the draft.
 */
export function observeMobileViewport() {
  const root = document.documentElement;
  const viewport = window.visualViewport;
  let frame = 0;
  let timers: ReturnType<typeof setTimeout>[] = [];

  const revealInput = () => {
    const input = document.activeElement;
    if (!(input instanceof HTMLElement) || !input.matches('input, textarea, [contenteditable="true"]')) return;
    // Scroll the app's own containers, not the document: scrollIntoView can
    // trigger another WebKit viewport pan and move the entire shell offscreen.
    for (let parent = input.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (!/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) continue;
      const field = input.getBoundingClientRect();
      const box = parent.getBoundingClientRect();
      if (field.bottom > box.bottom - 8) parent.scrollTop += field.bottom - box.bottom + 8;
      else if (field.top < box.top + 8) parent.scrollTop += field.top - box.top - 8;
    }
  };
  const update = () => {
    frame = 0;
    if (document.visibilityState === 'hidden') return;
    // Preserve pinch zoom and ignore transient zero sizes during app switching.
    if (viewport && Math.abs(viewport.scale - 1) > 0.01) return;
    const height = viewport?.height ?? window.innerHeight;
    const top = viewport?.offsetTop ?? 0;
    if (!Number.isFinite(height) || height <= 0 || !Number.isFinite(top)) return;
    root.style.setProperty('--app-height', `${height}px`);
    root.style.setProperty('--app-top', `${Math.max(0, top)}px`);
    revealInput();
  };
  const schedule = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(update);
  };
  const settle = () => {
    timers.forEach(clearTimeout);
    timers = [];
    if (document.visibilityState === 'hidden') return;
    schedule();
    // Focus and foreground callbacks can precede WebKit's final viewport values,
    // and the final change does not always produce a resize event in a PWA.
    timers = [100, 350, 750].map(delay => setTimeout(schedule, delay));
  };
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  window.addEventListener('resize', settle);
  window.addEventListener('pageshow', settle);
  window.addEventListener('focus', settle);
  document.addEventListener('visibilitychange', settle);
  document.addEventListener('focusin', settle);
  document.addEventListener('focusout', settle);
  settle();
  return () => {
    cancelAnimationFrame(frame);
    timers.forEach(clearTimeout);
    viewport?.removeEventListener('resize', schedule);
    viewport?.removeEventListener('scroll', schedule);
    window.removeEventListener('resize', settle);
    window.removeEventListener('pageshow', settle);
    window.removeEventListener('focus', settle);
    document.removeEventListener('visibilitychange', settle);
    document.removeEventListener('focusin', settle);
    document.removeEventListener('focusout', settle);
    root.style.removeProperty('--app-height');
    root.style.removeProperty('--app-top');
  };
}
