import RenameDialog from './components/RenameDialog';
import type { ThinkingLevel } from './lib/api';
import { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ResponsiveShell from './components/ResponsiveShell';
import type { Page } from './components/Sidebar';
import ChatPage from './components/ChatPage';
import SkillPage from './components/SkillPage';
import OutputsPage from './components/OutputsPage';
import AccountsPage from './components/AccountsPage';
import ProfilePage from './components/ProfilePage';
import DashboardPage from './components/DashboardPage';
import TrendsPage from './components/TrendsPage';
import CalendarPage from './components/CalendarPage';
import IdeasPage from './components/IdeasPage';
import PublishPage from './components/PublishingPage';
import BreakdownPage from './components/BreakdownPage';
import SubNav from './components/SubNav';
import OnboardingWizard from './components/OnboardingWizard';
import SettingsPanel from './components/SettingsPanel';
import { fetchStatus, fetchPersonas, streamChat, fetchLastTurn, stopChat } from './lib/api';
import type { PersonaItem, UploadedFile, ChatQuestion } from './lib/api';
import { questionStatus } from './lib/api';
import { deleteSession as deleteRemoteSession } from './lib/api';
import {
  loadSessions,
  saveSessions,
  createSession,
  updateSessionTitle,
  loadActiveId,
  saveActiveId,
} from './lib/store';
import type { ChatSession, ChatMessage, StreamState } from './lib/store';
import type { SharedTurn } from './lib/api';
import { loadSharedSessions, getSharedSession, ensureSharedSession, patchSharedSession, deleteSharedSession, importLocalSessions } from './lib/sharedSessions';

import { readCachedSummaries, readCachedHistory } from './lib/historyCache';
import PwaNotice from './components/PwaNotice';

import { historyEnd, mergeSessionSummary, mergeMessagePage } from './lib/sessionHistory';

const ONBOARDING_SEEN_KEY = 'easel_onboarding_seen';

function onboardingSeen(): boolean {
  const current = localStorage.getItem(ONBOARDING_SEEN_KEY);
  if (current) return true;
  const previousKey = `${['post', 'craft'].join('')}_onboarding_seen`;
  const previous = localStorage.getItem(previousKey);
  if (previous) {
    localStorage.setItem(ONBOARDING_SEEN_KEY, previous);
    localStorage.removeItem(previousKey);
    return true;
  }
  return false;
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [selectedPersona, setSelectedPersona] = useState('');
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [gatewayStatus, setGatewayStatus] = useState('connecting');
  const [apiDirect, setApiDirect] = useState(false);
  const [agentRuntime, setAgentRuntime] = useState('openclaw');
  const [showRecommend, setShowRecommend] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [historyReady, setHistoryReady] = useState(false);
  const [historyVerified, setHistoryVerified] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const hydrated = useRef(new Set<string>());
  useEffect(() => {
    const update = () => { setOnline(navigator.onLine); if (!navigator.onLine) setHistoryVerified(false); };
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  const [showImportLocal, setShowImportLocal] = useState(false);
  const [importingLocal, setImportingLocal] = useState(false);
  const historyBusy = useRef(new Set<string>());
  const reportHistoryError = useCallback((error: unknown) => {
    setHistoryVerified(false);
    setHistoryError(error instanceof Error ? error.message : '共享会话暂时不可用，请重试');
  }, []);
  // 装完还没配模型时，首开要把用户直接带到模型设置页（安装脚本不再在终端问 Key）
  const [needModelSetup, setNeedModelSetup] = useState(false);

  // 对话里的「产物路径 → 内容库」跳转：linkifyOutputs 把目录路径生成为
  // `#/outputs/<路径>` 锚点，这里监听 hashchange 切页并带上下文，随后清掉 hash
  // （不污染地址栏与前进/后退历史）。
  const [outputsJump, setOutputsJump] = useState('');
  useEffect(() => {
    const onHash = () => {
      const m = window.location.hash.match(/^#\/outputs\/(.+)$/);
      if (!m) return;
      let path = m[1];
      try { path = decodeURIComponent(path); } catch { /* 保留原样 */ }
      setOutputsJump(path);
      setCurrentPage('outputs');
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    };
    window.addEventListener('hashchange', onHash);
    onHash();
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const clearOutputsJump = useCallback(() => setOutputsJump(''), []);

  // Active selection remains tab-local; history itself is loaded from the service.
  const TAB_SESSION_KEY = 'easel_tab_session';
  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      const cached = await readCachedSummaries();
      if (cancelled) return;
      if (cached.length) {
        setSessions(prev => prev.some(s => s.source === 'server' && s.revision) ? prev : [...cached, ...loadSessions()]);
        setHistoryReady(true);
      }
      try {
        const shared = await loadSharedSessions();
        if (cancelled) return;
        setSessions(prev => {
          const byId = new Map(prev.map(s => [s.id, s]));
          return [...shared.map(s => mergeSessionSummary(byId.get(s.id), s)), ...loadSessions()];
        });
        setHistoryVerified(true);
        setHistoryReady(true);
        setHistoryError('');
      } catch (error) { if (!cancelled) reportHistoryError(error); }
    };
    void initialize();
    const retry = () => { if (!cancelled) void initialize(); };
    window.addEventListener('easel-retry-history', retry);
    return () => { cancelled = true; window.removeEventListener('easel-retry-history', retry); };
  }, [reportHistoryError]);

  useEffect(() => {
    if (!historyReady || activeSessionId) return;
    const last = sessionStorage.getItem(TAB_SESSION_KEY) || loadActiveId();
    const target = sessions.find(s => s.id === last || s.id === `shared_${last}`);
    const selected = target || createSession();
    if (!target) setSessions(prev => [selected, ...prev]);
    setActiveSessionId(selected.id);
    setSelectedPersona(selected.persona || '');
  }, [historyReady, activeSessionId, sessions]);

  // 持久化当前活跃会话 id，重开网页据此续接上次对话（修复"今天再问就忘了"）。
  // 仅在非空时写：避免挂载首刷 activeSessionId 尚为 null 时误清掉已存的 id。
  // 同时更新本标签的 sessionStorage 标记：手动切会话/新建后刷新本标签仍续在正确会话上。
  useEffect(() => {
    if (activeSessionId) {
      saveActiveId(activeSessionId);
      try { sessionStorage.setItem(TAB_SESSION_KEY, activeSessionId); } catch { /* ignore */ }
    }
  }, [activeSessionId]);

  // Fetch status on mount — 真实反映 gateway 状态 + 首次引导检测
  useEffect(() => {
    // 先问 bootstrap：模型没配好时，画像推荐弹窗要让位 —— 一次只问用户一件事，
    // 而且画像配得再好，没有模型也对话不了。
    const bootstrap = fetch('./api/settings/bootstrap')
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);

    Promise.all([fetchStatus(), bootstrap])
      .then(([data, boot]) => {
        setPersonas(data.personas || []);
        setGatewayStatus(data.gateway ? 'connected' : 'disconnected');
        setApiDirect(data.transport === 'api');
        setAgentRuntime(data.runtime || 'openclaw');
        const unconfigured = !!boot && boot.modelConfigured === false;
        if (unconfigured) {
          // 直接打开设置面板（它默认就停在「模型配置 · 对话」页）
          setNeedModelSetup(true);
          setSettingsOpen(true);
          return;
        }
        // 首次使用：没有任何个性化画像 且 未看过引导 → 推荐配置
        if ((data.personas || []).length === 0 && !onboardingSeen()) {
          setShowRecommend(true);
        }
      })
      .catch(() => {
        setGatewayStatus('disconnected');
      });
  }, []);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;

  // Other pages may choose a different persona for their next task. Returning to
  // a conversation restores its binding, including general mode (no persona).
  useEffect(() => {
    if (currentPage === 'chat' && activeSession) {
      setSelectedPersona(activeSession.persona || '');
    }
  }, [currentPage, activeSession?.id, activeSession?.persona]);

  // 最新 sessions 的 ref，供回调里读取而不必进依赖数组（避免闭包过期/频繁重建）
  const sessionsRef = useRef(sessions);
  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  // 当前活跃会话 id 的 ref：供跨标签「谁在用会话 X」查询时即时应答（见挂载 effect）

  // ---- 流式对话：状态与生命周期都放在 App（永不卸载），切页/切 ChatPage 都不中断/丢失 ----
  const [streams, setStreams] = useState<Record<string, StreamState>>({});
  const streamCtl = useRef<Record<string, AbortController>>({});
  const finishingStreams = useRef(new Set<string>());
  const streamAcc = useRef<Record<string, { content: string; thinking: string; steps: string[]; questions: ChatQuestion[] }>>({});
  const finalizers = useRef(new Map<string, { owner: object; finish: () => void; timer?: ReturnType<typeof setTimeout> }>());
  const answeredRef = useRef<Set<string>>(new Set());   // 已提交答案的 question id：重放/恢复不再重现
  // ---- 打字机：分批到达的 token 按节奏吐给界面 ----
  const typingBuf = useRef<Record<string, string>>({});
  const typingTimer = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  const TYPING_INTERVAL = 12;          // 每 tick 间隔 ms（短回复约 83 字/秒：快且有逐字感）

  const refreshShared = useCallback(async (forceId?: string) => {
    const knownIds = new Set(sessionsRef.current.map((s) => s.id));
    const incoming = await loadSharedSessions();
    setHistoryVerified(true);
    setHistoryError('');
    setSessions((prev) => {
      const previous = new Map(prev.map((item) => [item.id, item]));
      const shared = incoming.map((item) => mergeSessionSummary(previous.get(item.id), item));
      const byId = new Map(shared.map((item) => [item.id, item]));
      const retained = prev.filter((item) => item.source === 'server' && (
        (!byId.has(item.id) && (!item.revision || !knownIds.has(item.id))) ||
        (byId.has(item.id) && (item.revision || 0) > (byId.get(item.id)?.revision || 0)) ||
        (item.id !== forceId && historyBusy.current.has(item.id)) ||
        (item.id !== forceId && !!streamCtl.current[item.id])
      ));
      const keep = new Set(retained.map((item) => item.id));
      return [...retained, ...shared.filter((item) => !keep.has(item.id)), ...loadSessions()];
    });
  }, []);

  useEffect(() => {
    if (!historyReady) return;
    const refresh = () => { void refreshShared().catch(reportHistoryError); };
    const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    const timer = setInterval(onVisible, 5000);
    window.addEventListener('focus', refresh);
    window.addEventListener('online', refresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => { clearInterval(timer); window.removeEventListener('focus', refresh); window.removeEventListener('online', refresh); document.removeEventListener('visibilitychange', onVisible); };
  }, [historyReady, refreshShared, reportHistoryError]);

  const messageRequests = useRef(new Set<string>());
  const [messageLoading, setMessageLoading] = useState<Record<string, boolean>>({});
  const [messageErrors, setMessageErrors] = useState<Record<string, string>>({});
  const loadMessages = useCallback(async (id: string, older = false) => {
    let current = sessionsRef.current.find((s) => s.id === id);
    if (!current || current.source !== 'server' || !current.revision || messageRequests.current.has(id)) return;
    if (!hydrated.current.has(id) && !current.historyLoaded) {
      messageRequests.current.add(id);
      setMessageLoading(p => ({ ...p, [id]: true }));
      const cached = await readCachedHistory(id);
      hydrated.current.add(id);
      messageRequests.current.delete(id);
      current = sessionsRef.current.find(s => s.id === id);
      if (current && cached && current.historyEpoch === cached.historyEpoch && !current.optimistic) {
        const restored = mergeSessionSummary(cached, current);
        setSessions(prev => prev.map(s => s.id === id && !s.historyLoaded && s.historyEpoch === cached.historyEpoch ? mergeSessionSummary(cached, s) : s));
        current = restored;
      }
      setMessageLoading(p => ({ ...p, [id]: false }));
    }
    if (!current || !navigator.onLine || !historyVerified) {
      if (current && !current.historyLoaded) setMessageErrors(p => ({ ...p, [id]: '此会话尚未缓存，请联网后加载。' }));
      return;
    }
    if (older && (!current.historyLoaded || !current.messageStart)) return;
    if (!older && (current.optimistic || streamCtl.current[id] || historyBusy.current.has(id))) return;
    if (!older && current.historyLoaded && historyEnd(current) >= (current.messageCount || 0)) return;
    const mode = older ? 'older' : current.historyLoaded && current.messages.length ? 'newer' : 'latest';
    messageRequests.current.add(id);
    setMessageLoading((p) => ({ ...p, [id]: true }));
    setMessageErrors((p) => ({ ...p, [id]: '' }));
    try {
      const page = await getSharedSession(id, mode === 'latest' ? {} : {
        ...(older ? { before: current.messageStart } : { after: historyEnd(current) - 1 }),
        epoch: current.historyEpoch,
      });
      setSessions((prev) => prev.map((s) => s.id === id ? mergeMessagePage(s, page, mode) : s));
    } catch (error) {
      if ((error as { status?: number }).status === 409) {
        // A retry in another window replaced the indexed history. Restart at
        // the latest page rather than mixing snapshots or duplicating messages.
        setSessions((prev) => prev.map((s) => s.id === id && !s.optimistic
          ? { ...s, messages: [], messageStart: 0, historyLoaded: false } : s));
      } else {
        setMessageErrors((p) => ({ ...p, [id]: (error as Error).message }));
      }
    } finally {
      messageRequests.current.delete(id);
      setMessageLoading((p) => ({ ...p, [id]: false }));
    }
  }, [historyVerified]);

  useEffect(() => {
    if (online && historyVerified) setMessageErrors({});
  }, [online, historyVerified]);

  // Home loads summaries only. Selected conversations fetch their latest page,
  // and later fetch just appended messages when the summary count advances.
  useEffect(() => {
    if (currentPage === 'chat' && activeSessionId && !messageErrors[activeSessionId]
      && !messageLoading[activeSessionId]) void loadMessages(activeSessionId);
  }, [currentPage, activeSessionId, activeSession?.revision, activeSession?.historyLoaded,
    activeSession?.messages.length, activeSession?.messageStart, activeSession?.messageCount,
    messageErrors, messageLoading, loadMessages]);

  const updateShared = useCallback(async (id: string, changes: Partial<ChatSession>) => {
    const current = sessionsRef.current.find((item) => item.id === id);
    if (!current || historyBusy.current.has(id)) return;
    historyBusy.current.add(id);
    try {
      const saved = await patchSharedSession(current, changes);
      setSessions((prev) => prev.map((item) => item.id === id ? mergeSessionSummary(item, saved) : item));
      setHistoryError('');
    } catch (error) {
      reportHistoryError(error);
    } finally {
      historyBusy.current.delete(id);
      void refreshShared().catch(reportHistoryError);
    }
  }, [refreshShared, reportHistoryError]);

  const handleImportLocal = async () => {
    if (Object.keys(streamCtl.current).length || historyBusy.current.size || sessionsRef.current.some((s) => s.pendingTurnId)) {
      setHistoryError('请先等待当前对话完成，再迁移本浏览器的旧记录。');
      return;
    }
    setImportingLocal(true);
    historyBusy.current.add('import');
    try {
      await importLocalSessions();
      setShowImportLocal(false);
      if (activeSessionId && sessionsRef.current.find((s) => s.id === activeSessionId && s.source !== 'server' && s.messages.length)) {
        setActiveSessionId(`shared_${activeSessionId}`);
      }
      await refreshShared();
      setHistoryError('');
    } catch (error) { reportHistoryError(error); }
    finally { historyBusy.current.delete('import'); setImportingLocal(false); }
  };

  const pumpTyping = (sessionId: string) => {
    const buf = typingBuf.current[sessionId] || '';
    if (!buf) { clearTyping(sessionId); return; }
    // 动态步长：<80 字逐字吐（83字/秒），每满 80 字每 tick 多吐 1 字，长文更快
    const step = Math.max(1, Math.floor(buf.length / 80));
    const take = buf.slice(0, step);
    typingBuf.current[sessionId] = buf.slice(step);
    const a = streamAcc.current[sessionId]; if (!a) { clearTyping(sessionId); return; }
    a.content += take;
    setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], content: a.content } } : p));
  };
  const startTypingPump = (sessionId: string) => {
    if (typingTimer.current[sessionId]) return;
    typingTimer.current[sessionId] = setInterval(() => pumpTyping(sessionId), TYPING_INTERVAL);
  };
  const ensureTypingPump = (sessionId: string) => {
    if (!typingTimer.current[sessionId]) startTypingPump(sessionId);
  };
  const clearTyping = (sessionId: string) => {
    const t = typingTimer.current[sessionId];
    if (t) { clearInterval(t); delete typingTimer.current[sessionId]; }
  };
  /** 收尾冲刷：把剩余队列立刻吐完（避免结束瞬间内容被截断）。 */
  const flushTyping = (sessionId: string) => {
    clearTyping(sessionId);
    const buf = typingBuf.current[sessionId] || '';
    if (!buf) return;
    typingBuf.current[sessionId] = '';
    const a = streamAcc.current[sessionId]; if (!a) return;
    a.content += buf;
    setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], content: a.content } } : p));
  };

  const appendAssistant = useCallback((sessionId: string, msg: ChatMessage, sessionKey?: string) => {
    if (sessionsRef.current.find((s) => s.id === sessionId)?.source === 'server') {
      // The supervisor persists even when no browser is connected. Never append a duplicate locally.
      if (msg.content.includes('Error:')) setHistoryError(msg.content);
      void refreshShared(sessionId).catch(reportHistoryError);
      return;
    }
    setSessions((prev) => {
      const next = prev.map((s) =>
        s.id === sessionId
          ? { ...s, messages: [...s.messages, msg], sessionKey: sessionKey || s.sessionKey, pendingTurnId: undefined }
          : s);
      saveSessions(next);
      return next;
    });
  }, [refreshShared, reportHistoryError]);

  const clearStream = useCallback((sessionId: string) => {
    const pending = finalizers.current.get(sessionId);
    if (pending?.timer) clearTimeout(pending.timer);
    finalizers.current.delete(sessionId);
    // 打字机收尾：剩余队列立刻吐出，避免结束瞬间内容被截断
    flushTyping(sessionId);
    delete streamCtl.current[sessionId];
    delete streamAcc.current[sessionId];
    if (sessionsRef.current.find((s) => s.id === sessionId)?.source === 'server') {
      // Keep the final bubble until its persisted page arrives. Removing it
      // between two network requests would shrink the thread and steal scroll.
      finishingStreams.current.add(sessionId);
      setStreams((prev) => ({ ...prev }));
      return;
    }
    setStreams((prev) => {
      const next = { ...prev };
      delete next[sessionId];
      return next;
    });
  }, []);

  useEffect(() => {
    const settled = [...finishingStreams.current].filter((id) => {
      const s = sessions.find((item) => item.id === id);
      return !s || s.historyLoaded && !s.optimistic && !s.pendingTurnId && historyEnd(s) >= (s.messageCount || 0);
    });
    if (!settled.length) return;
    setStreams((prev) => {
      const next = { ...prev };
      for (const id of settled) { delete next[id]; finishingStreams.current.delete(id); }
      return next;
    });
  }, [sessions]);
  const finalizeStream = useCallback((sessionId: string, owner: typeof streamAcc.current[string],
    sessionKey?: string, error?: Error) => {
    if (streamAcc.current[sessionId] !== owner || finalizers.current.has(sessionId)) return;
    const pending: { owner: object; finish: () => void; timer?: ReturnType<typeof setTimeout> } = {
      owner,
      finish: () => {
        if (finalizers.current.get(sessionId) !== pending || streamAcc.current[sessionId] !== owner) return;
        finalizers.current.delete(sessionId);
        if (pending.timer) clearTimeout(pending.timer);
        flushTyping(sessionId);
        appendAssistant(sessionId, {
          role: 'assistant', content: owner.content + (error ? `\n\nError: ${error.message}` : ''),
          thinking: owner.thinking || undefined, activity: owner.steps.join('\n') || undefined,
          questions: owner.questions.length ? [...owner.questions] : undefined,
        }, sessionKey);
        clearStream(sessionId);
        try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch {}
      },
    };
    finalizers.current.set(sessionId, pending);
    const poll = () => {
      if (finalizers.current.get(sessionId) !== pending || streamAcc.current[sessionId] !== owner) return;
      if (typingBuf.current[sessionId] && document.visibilityState !== 'hidden') {
        pending.timer = setTimeout(poll, 60);
      } else pending.finish();
    };
    poll();
  }, [appendAssistant, clearStream]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState !== 'hidden') return;
      for (const sessionId of Object.keys(streamAcc.current)) flushTyping(sessionId);
      for (const pending of [...finalizers.current.values()]) pending.finish();
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, []);

  const closeQuestion = useCallback((sessionId: string, closed: { id: string; status: string }) => {
    const owner = streamAcc.current[sessionId];
    if (owner) {
      owner.questions = owner.questions.map(question => question.id === closed.id
        ? { ...question, status: closed.status } : question);
      setStreams(previous => previous[sessionId] ? { ...previous,
        [sessionId]: { ...previous[sessionId], questions: [...owner.questions] } } : previous);
    }
    setSessions(previous => {
      const updated = previous.map(session => session.id === sessionId ? { ...session,
        messages: session.messages.map(message => ({ ...message, questions: message.questions?.map(question =>
          question.id === closed.id ? { ...question, status: closed.status } : question) })) } : session);
      saveSessions(updated);
      return updated;
    });
  }, []);

  const receiveQuestion = useCallback((sessionId: string, owner: typeof streamAcc.current[string], q: ChatQuestion) => {
    if (streamAcc.current[sessionId] !== owner || answeredRef.current.has(q.id) || owner.questions.some(question => question.id === q.id)) return;
    owner.questions.push({ ...q, status: q.status || 'pending' });
    setStreams(previous => previous[sessionId] ? { ...previous,
      [sessionId]: { ...previous[sessionId], questions: [...owner.questions] } } : previous);
    void questionStatus([q.id]).then(states => {
      const status = states[q.id]?.status;
      if (status && status !== 'pending' && status !== 'unknown') closeQuestion(sessionId, { id: q.id, status });
    });
  }, [closeQuestion]);

  // 启动一次流式（fetch + 累积 + 回调）——只管流，不动消息列表
  const startStream = useCallback((
    sessionId: string,
    text: string,
    persona: string | undefined,
    attachments: UploadedFile[] = [],
    thinking?: ThinkingLevel,
    sharedTurn?: SharedTurn,
  ) => new Promise<boolean>((resolve) => {
    const turnId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try { sessionStorage.setItem(`easel_pending_turn:${sessionId}`, turnId); } catch { /* ignore */ }
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === sessionId ? { ...s, pendingTurnId: turnId } : s));
      saveSessions(next); return next;
    });
    const owner = { content: '', thinking: '', steps: [] as string[], questions: [] as ChatQuestion[] };
    streamAcc.current[sessionId] = owner;
    setStreams((prev) => ({ ...prev, [sessionId]: { content: '', thinking: '', activity: '', questions: [] } }));
    // 打字机队列：流式事件按批到达（OpenClaw 攒批），前端按字符节奏显示，体验逐字浮现。
    typingBuf.current[sessionId] = '';
    startTypingPump(sessionId);
    streamCtl.current[sessionId] = streamChat(
      text, persona, sessionId,
      (chunk) => {
        const a = streamAcc.current[sessionId]; if (a !== owner) return;
        // 不直接追加 content——进打字机队列，pump 按节奏吐出（切会话不中断，队列归属 sessionId）
        typingBuf.current[sessionId] = (typingBuf.current[sessionId] || '') + chunk;
        ensureTypingPump(sessionId);
      },
      (sessionKey) => {
        resolve(true);
        // done 不能立即 flush——token 和 done 几乎同时到达（OpenClaw 攒批），
        // 立即 flush 会把整包瞬间冲出，打字机白做。等队列吐完再落盘。
        finalizeStream(sessionId, owner, sessionKey);
      },
      (err) => {
        resolve(false);
        finalizeStream(sessionId, owner, undefined, err);
      },
      (thinkChunk) => {
        const a = streamAcc.current[sessionId]; if (a !== owner) return;
        a.thinking = (a.thinking + thinkChunk).slice(-4000);
        // 有真实思考流 → 清掉防呆提示（不再显示「未卡住」）
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], thinking: a.thinking, stillWorking: undefined } } : p));
      },
      (status) => {
        const a = streamAcc.current[sessionId]; if (a !== owner) return;
        if (a.steps[a.steps.length - 1] !== status) a.steps.push(status);
        // 有真实活动状态 → 清掉防呆提示，让真实状态占据活动行
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], activity: status, stillWorking: undefined } } : p));
      },
      // onInterrupted：SSE 被中断（长任务时代理掐断），但后端仍在跑并会落盘完整结果。
      // streamChat 会按 eventId 自动重连并补发遗漏事件；这里只更新用户可见状态。
      () => {
        if (streamAcc.current[sessionId] !== owner) return;
        setStreams((p) => (p[sessionId]
          ? { ...p, [sessionId]: { ...p[sessionId], activity: '⏳ 连接中断，正在自动续接…' } } : p));
      },
      turnId,
      false,
      undefined,
      attachments,
      (q) => {
        // ask_user 问答题：追加进流式状态（去重），ChatPage 渲染为选项卡片
        // 重放可能带已解决/已过期的旧问题，先查状态只留 pending（失败则保留）
        receiveQuestion(sessionId, owner, q);
      },
      // onHeartbeat：防呆心跳（30s 静默）。只设独立的「未卡住」提示，绝不写 activity/thinking → 不顶掉真实状态。
      (note) => { if (streamAcc.current[sessionId] === owner) setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], stillWorking: note } } : p)); },
      thinking,
      sharedTurn,
      () => resolve(true),
      (closed) => closeQuestion(sessionId, closed),
    );
  }), [finalizeStream, closeQuestion, receiveQuestion]);

  // 刷新/重开页面后按 eventId=0 重放当前 job，再继续实时 tail；旧任务无事件日志时退回最终快照。
  const resumePendingTurn = useCallback((sessionId: string) => {
    if (streamCtl.current[sessionId] || streamAcc.current[sessionId] || finishingStreams.current.has(sessionId)) return;
    const s = sessionsRef.current.find((x) => x.id === sessionId);
    const last = s?.messages[s.messages.length - 1];
    if (s?.source === 'server' && !s.pendingTurnId) return;
    if (!last || last.role !== 'user') return;   // 没有悬空的用户消息 = 无需恢复
    let turnId = s.pendingTurnId;
    try { if (s.source !== 'server') turnId = sessionStorage.getItem(`easel_pending_turn:${sessionId}`) || turnId; } catch { /* use persisted id */ }
    const owner = { content: '', thinking: '', steps: [] as string[], questions: [] as ChatQuestion[] };
    streamAcc.current[sessionId] = owner;
    setStreams((p) => ({ ...p, [sessionId]: { content: '', thinking: '', activity: '⏳ 正在接回上一轮结果…', questions: [] } }));
    typingBuf.current[sessionId] = '';
    startTypingPump(sessionId);
    if (!turnId) {
      void fetchLastTurn(sessionId).then((r) => {
        if (streamAcc.current[sessionId] !== owner) return;
        if (r.status === 'done') appendAssistant(sessionId, { role: 'assistant', content: r.text || '（无输出）' });
        clearStream(sessionId);
      }).catch(() => { if (streamAcc.current[sessionId] === owner) clearStream(sessionId); });
      return;
    }
    streamCtl.current[sessionId] = streamChat(
      '', undefined, sessionId,
      (chunk) => {
        const a = streamAcc.current[sessionId]; if (a !== owner) return;
        typingBuf.current[sessionId] = (typingBuf.current[sessionId] || '') + chunk;
        ensureTypingPump(sessionId);
      },
      (sessionKey) => {
        finalizeStream(sessionId, owner, sessionKey);
      },
      (err) => {
        finalizeStream(sessionId, owner, undefined, err);
      },
      (chunk) => { const a = streamAcc.current[sessionId]; if (a === owner) a.thinking = (a.thinking + chunk).slice(-4000); },
      (status) => {
        const a = streamAcc.current[sessionId]; if (a !== owner) return;
        if (a.steps[a.steps.length - 1] !== status) a.steps.push(status);
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], activity: status } } : p));
      },
      () => { if (streamAcc.current[sessionId] === owner) setStreams((p) => (p[sessionId]
        ? { ...p, [sessionId]: { ...p[sessionId], activity: '⏳ 正在自动续接…' } } : p)); },
      turnId,
      true,
      () => {
        // The event log may disappear after a backend restart. Prefer the
        // completed per-session snapshot; otherwise terminate stale recovery.
        void fetchLastTurn(sessionId, turnId).then((r) => {
          if (streamAcc.current[sessionId] !== owner) return;
          if (r.status === 'done') {
            appendAssistant(sessionId, { role: 'assistant', content: r.text || '（无输出）' });
          } else {
            appendAssistant(sessionId, {
              role: 'assistant',
              content: '上一轮任务记录已失效，无法继续恢复。请重新发送上一条消息。',
            });
          }
          clearStream(sessionId);
          try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
        }).catch(() => {
          if (streamAcc.current[sessionId] !== owner) return;
          appendAssistant(sessionId, {
            role: 'assistant', content: '上一轮任务记录已失效，请重新发送上一条消息。',
          });
          clearStream(sessionId);
        });
      },
      undefined,   // attachments: 恢复轮次无新附件
      (q) => {
        receiveQuestion(sessionId, owner, q);
      },
      // onHeartbeat：同上，独立的「未卡住」提示，不覆盖 activity/thinking。
      (note) => { if (streamAcc.current[sessionId] === owner) setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], stillWorking: note } } : p)); },
      undefined, undefined, undefined,
      (closed) => closeQuestion(sessionId, closed),
    );
  }, [appendAssistant, clearStream, finalizeStream, closeQuestion, receiveQuestion]);

  // 活跃会话确定后（含挂载首刷）尝试恢复它悬空的一轮
  useEffect(() => {
    if (online && historyVerified && currentPage === 'chat' && activeSessionId && (activeSession?.source !== 'server'
      || activeSession.historyLoaded && historyEnd(activeSession) === activeSession.messageCount)) resumePendingTurn(activeSessionId);
  }, [currentPage, activeSessionId, activeSession, resumePendingTurn, online, historyVerified]);

  // 落用户消息（可选先把 messages 截断到 truncateAt）→ 启动流。retry/edit 都走这里。
  const sendUserAndStream = useCallback(async (
    sessionId: string,
    displayText: string,
    attachments: UploadedFile[] = [],
    legacyAgentText?: string,
    truncateAt?: number,
  ) => {
    const visible = displayText.trim();
    const agentMessage = (legacyAgentText || displayText).trim();
    if ((!agentMessage && attachments.length === 0) || streamCtl.current[sessionId] || streamAcc.current[sessionId] || historyBusy.current.has(sessionId)) return false;
    let cur = sessionsRef.current.find((s) => s.id === sessionId);
    if (!cur || !historyReady || !navigator.onLine || !historyVerified) return false;
    if (cur.source === 'server' && (!cur.historyLoaded || historyEnd(cur) !== cur.messageCount)) return false;
    if (cur.pendingTurnId) { setHistoryError('此会话正在回复中，请等待完成或先停止。'); return false; }
    historyBusy.current.add(sessionId);
    try {
      if (cur.source === 'server') cur = await ensureSharedSession(cur);
      const start = cur.messageStart || 0;
      const absoluteTruncateAt = truncateAt == null ? undefined : start + truncateAt;
      const base = truncateAt != null ? cur.messages.slice(0, truncateAt) : cur.messages;
      const updated: ChatSession = { ...cur,
        ...(cur.source === 'server' ? { optimistic: true, messageCount: start + base.length + 1,
          historyEpoch: (cur.historyEpoch || 0) + (truncateAt == null ? 0 : 1) } : {}),
        messages: [...base, {
        role: 'user', content: visible,
        ...(attachments.length ? { attachments } : {}),
        ...(legacyAgentText && legacyAgentText !== visible ? { agentContent: legacyAgentText } : {}),
      }] };
      updateSessionTitle(updated);
      // Update the ref before starting the stream so an immediate response sees the same identity.
      const next = sessionsRef.current.map((s) => s.id === sessionId ? updated : s);
      sessionsRef.current = next;
      setSessions(next);
      saveSessions(next);
      setHistoryError('');
      return await startStream(sessionId, agentMessage, cur.persona, attachments, cur.thinking,
        cur.source === 'server' ? {
          conversationId: cur.id, revision: cur.revision!, displayMessage: visible,
          conversationTitle: updated.title, truncateAt: absoluteTruncateAt,
        } : undefined);
    } catch (error) {
      reportHistoryError(error);
      void refreshShared().catch(reportHistoryError);
      return false;
    } finally { historyBusy.current.delete(sessionId); }
  }, [historyReady, historyVerified, startStream, reportHistoryError, refreshShared]);

  const handleSendMessage = useCallback((sessionId: string, displayText: string, attachments?: UploadedFile[]) => {
    return sendUserAndStream(sessionId, displayText, attachments);
  }, [sendUserAndStream]);

  // 重试/编辑重发：从该用户消息处截断（丢弃它及其之后），用 text 重新发起。
  const handleResend = useCallback((
    sessionId: string,
    userIndex: number,
    displayText: string,
    attachments?: UploadedFile[],
    legacyAgentText?: string,
  ) => {
    sendUserAndStream(sessionId, displayText, attachments, legacyAgentText, userIndex);
  }, [sendUserAndStream]);

  // 热点「一键做成内容」：新开会话，把选题作为指令发出去，跳到对话页。
  const handleUseTopic = useCallback((title: string) => {
    const prompt = `围绕当前热点「${title}」：先判断它适不适合我的账号赛道；若合适，给 2-3 个差异化的二创角度，并把你最推荐的那条写成可直接发布的文案初稿。`;
    const ns = createSession(selectedPersona || undefined);
    setSessions((prev) => { const u = [ns, ...prev]; saveSessions(u); return u; });
    sessionsRef.current = [ns, ...sessionsRef.current];
    setActiveSessionId(ns.id);
    setCurrentPage('chat');
    void sendUserAndStream(ns.id, prompt);
  }, [selectedPersona, sendUserAndStream]);

  const handleStopStream = useCallback((sessionId: string) => {
    const pending = finalizers.current.get(sessionId);
    if (pending) { pending.finish(); return; }
    if (sessionsRef.current.find((s) => s.id === sessionId)?.source === 'server') {
      streamCtl.current[sessionId]?.abort();
      clearStream(sessionId);
      void stopChat(sessionId).then(() => refreshShared(sessionId)).catch(reportHistoryError);
      try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
      return;
    }
    streamCtl.current[sessionId]?.abort();
    // 告诉后端**真正终止**这一轮 agent 并释放会话锁——否则后端进程还在跑、占着锁，下一句会被拦
    void stopChat(sessionId).catch(() => { /* 后端可能已结束，忽略 */ });
    flushTyping(sessionId);   // 停止时立刻把队列余字吐完，保证已到内容不丢
    const a = streamAcc.current[sessionId];
    if (a && (a.content || a.thinking || a.steps.length)) {
      appendAssistant(sessionId, {
        role: 'assistant',
        content: (a.content || '') + '\n\n_（已停止）_',
        thinking: a.thinking || undefined,
        activity: a.steps.join('\n') || undefined,
        questions: a.questions.length ? [...a.questions] : undefined,
      });
    }
    clearStream(sessionId);
    // 关键：清掉「本轮进行中」标记，否则下一句被判为「上一条还没跑完」拦下
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === sessionId ? { ...s, pendingTurnId: undefined } : s));
      saveSessions(next);
      return next;
    });
    try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
  }, [appendAssistant, clearStream, refreshShared, reportHistoryError]);

  const [renameTarget, setRenameTarget] = useState<{
    session: ChatSession; messageIndex?: number; artifactTitle?: string;
  } | null>(null);
  const handleSessionRename = (id: string, messageIndex?: number, artifactTitle?: string) => {
    const session = sessionsRef.current.find(s => s.id === id);
    if (session) setRenameTarget({ session, messageIndex, artifactTitle });
  };
  const saveSessionName = async (title: string) => {
    if (!renameTarget) return;
    const current = renameTarget.session;
    if (current.source === 'server') {
      // Save against the version seen when the dialog opened; don't overwrite
      // a newer name from another tab while a suggestion was being generated.
      const saved = await patchSharedSession(current, { title });
      setSessions(prev => prev.map(s => s.id === current.id ? mergeSessionSummary(s, saved) : s));
    } else {
      setSessions(prev => {
        const next = prev.map(s => s.id === current.id ? { ...s, title, titleLocked: true } : s);
        saveSessions(next); return next;
      });
    }
  };

  const handleSessionArchive = useCallback((id: string, archived: boolean) => {
    if (sessionsRef.current.find((s) => s.id === id)?.source === 'server') { void updateShared(id, { archived }); return; }
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, archived } : s));
      saveSessions(next);
      return next;
    });
    // 归档当前激活会话 → 切到另一个未归档会话或新建
    if (archived && id === activeSessionId) {
      const rest = sessionsRef.current.filter((s) => s.id !== id && !s.archived);
      if (rest.length) {
        setActiveSessionId(rest[0].id);
      } else {
        const ns = createSession(selectedPersona || undefined);
        setSessions((prev) => { const u = [ns, ...prev]; saveSessions(u); return u; });
        setActiveSessionId(ns.id);
      }
      setCurrentPage('chat');
    }
  }, [activeSessionId, selectedPersona, updateShared]);

  const handleNewChat = useCallback(() => {
    const newSession = createSession(selectedPersona || undefined);
    setSessions((prev) => {
      const updated = [newSession, ...prev];
      saveSessions(updated);
      return updated;
    });
    setActiveSessionId(newSession.id);
    setCurrentPage('chat');
  }, [selectedPersona]);

  const handleSessionSelect = useCallback((id: string) => {
    setActiveSessionId(id);
    const target = sessions.find(s => s.id === id);
    if (target) {
      setSelectedPersona(target.persona || '');
    }
    setCurrentPage('chat');
  }, [sessions]);

  const handleSessionDelete = useCallback(async (id: string) => {
    if (!window.confirm('确定删除这条对话？')) return;

    const target = sessionsRef.current.find((s) => s.id === id);
    if (target?.source === 'server') {
      if (historyBusy.current.has(id)) return;
      historyBusy.current.add(id);
      try {
        // Running shared tasks must be stopped explicitly; a stale browser cannot delete a new turn.
        await deleteSharedSession(target);
        setSessions((prev) => prev.filter((s) => s.id !== id));
        if (activeSessionId === id) { setActiveSessionId(null); setCurrentPage('dashboard'); }
        setHistoryError('');
      } catch (error) { reportHistoryError(error); }
      finally { historyBusy.current.delete(id); void refreshShared().catch(reportHistoryError); }
      return;
    }
    const wasRunning = Boolean(streamCtl.current[id]);
    const stopped = wasRunning
      ? stopChat(id).catch(() => ({ stopped: false }))
      : Promise.resolve({ stopped: false });
    streamCtl.current[id]?.abort();   // 删除正在流式的会话时中止其流
    clearStream(id);
    try { sessionStorage.removeItem(`easel_pending_turn:${id}`); } catch { /* ignore */ }

    const sharedCopy = sessionsRef.current.some((s) => s.source === 'server' && s.agentSessionId === id);
    if (target?.sessionKey && !sharedCopy) {
      // Do not delete OpenClaw's session record while its agent is still
      // writing to it; the stop endpoint waits for backend cleanup first.
      void stopped.then(() => deleteRemoteSession(target.sessionKey as string)).catch(() => {});
    }

    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id);
      saveSessions(updated);

      if (id === activeSessionId) {
        if (updated.length > 0) {
          setActiveSessionId(updated[0].id);
        } else {
          const newSession = createSession();
          updated.unshift(newSession);
          saveSessions(updated);
          setActiveSessionId(newSession.id);
        }
      }
      return updated;
    });
  }, [activeSessionId, clearStream, refreshShared, reportHistoryError]);

  // 首次引导：跳过（用通用模式）
  const dismissRecommend = useCallback(() => {
    localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
    setShowRecommend(false);
  }, []);

  // 打开引导向导
  const openWizard = useCallback(() => {
    setShowRecommend(false);
    setShowWizard(true);
  }, []);

  // 画像创建完成
  const handleProfileCreated = useCallback((name: string) => {
    localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
    setShowWizard(false);
    fetchPersonas().then((list) => {
      setPersonas(list);
      setSelectedPersona(name);
      // 用新画像开一个新会话
      const newSession = createSession(name);
      setSessions((prev) => {
        const updated = [newSession, ...prev];
        saveSessions(updated);
        return updated;
      });
      setActiveSessionId(newSession.id);
      setCurrentPage('profile');
    }).catch(() => {});
  }, []);

  // 画像删除完成：刷新列表 + 若删的是当前选中的则清空选择
  const handleProfileDeleted = useCallback((name: string) => {
    fetchPersonas().then((list) => {
      setPersonas(list);
      setSelectedPersona((cur) => (cur === name ? '' : cur));
    }).catch(() => {});
  }, []);

  // 流式生命周期在 App，页面切换随意——ChatPage 可自由卸载/重挂，回来从 props 读流式态即可。
  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return (
          <DashboardPage
            persona={selectedPersona}
            gatewayStatus={gatewayStatus}
            apiDirect={apiDirect}
            agentRuntime={agentRuntime}
            onNavigate={(page) => page === 'chat' ? handleNewChat() : setCurrentPage(page)}
            onUseTopic={handleUseTopic}
          />
        );
      case 'chat':
        return activeSession ? (
          <ChatPage
            apiDirect={apiDirect}
            key={activeSession.id}
            session={activeSession}
            readOnly={!online || !historyVerified}
            historyLoading={!!messageLoading[activeSession.id]}
            historyError={messageErrors[activeSession.id]}
            onLoadHistory={(older) => loadMessages(activeSession.id, older)}
            onThinkingChange={(thinking) => {
              if (activeSession.source === 'server') { void updateShared(activeSession.id, { thinking }); return; }
              setSessions((prev) => {
              const next = prev.map((s) => s.id === activeSession.id ? { ...s, thinking } : s);
              saveSessions(next); return next;
              });
            }}
            stream={finishingStreams.current.has(activeSession.id) && activeSession.historyLoaded
              && !activeSession.optimistic && !activeSession.pendingTurnId
              && historyEnd(activeSession) >= (activeSession.messageCount || 0) ? undefined : streams[activeSession.id]}
            onSend={(displayText, attachments) => handleSendMessage(activeSession.id, displayText, attachments)}
            onRename={(index, title) => handleSessionRename(activeSession.id, index, title)}
            onStop={() => handleStopStream(activeSession.id)}
            onResend={(userIndex, displayText, attachments, legacyAgentText) => handleResend(
              activeSession.id, userIndex, displayText, attachments, legacyAgentText,
            )}
            onQuestionAnswered={(qid) => {
              answeredRef.current.add(qid);
              closeQuestion(activeSession.id, { id: qid, status: 'answered' });
              // 已答题从流式状态中移除——切走/切回会话都不再重现（组件内部 state 会在重挂时清零，只藏不移除没用）
              const a = streamAcc.current[activeSession.id];
              if (a) {
                const before = a.questions.length;
                const kept = a.questions.filter((q) => q.id !== qid);
                if (kept.length !== before) {
                  a.questions = kept;
                  setStreams((p) => {
                    const cur = p[activeSession.id];
                    if (!cur) return p;
                    return { ...p, [activeSession.id]: { ...cur, questions: [...kept] } };
                  });
                }
              }
            }}
            onQuestionClosed={(id, status) => closeQuestion(activeSession.id, { id, status })}
          />
        ) : null;
      case 'trends':
        return <TrendsPage onUseTopic={handleUseTopic} />;
      case 'ideas':
        return <IdeasPage onUseTopic={handleUseTopic} />;
      case 'calendar':
        return <CalendarPage />;
      case 'publish':
        return <PublishPage persona={selectedPersona} />;
      case 'breakdown':
        return <BreakdownPage persona={selectedPersona} />;
      case 'skills':
        return <SkillPage persona={selectedPersona} />;
      case 'outputs':
        return <OutputsPage jumpPath={outputsJump} onJumpHandled={clearOutputsJump} />;
      case 'accounts':
        return <AccountsPage />;
      case 'profile':
        return <ProfilePage persona={selectedPersona} onUsePersona={handlePersonaChange} onNewProfile={() => setShowWizard(true)} onDeleted={handleProfileDeleted} />;
      default:
        return null;
    }
  };

  const handlePersonaChange = useCallback((persona: string) => {
    setSelectedPersona(persona);
    if (currentPage !== 'chat') return;
    const cur = sessionsRef.current.find((s) => s.id === activeSessionId);
    if (cur && (cur.persona || '') === persona) return;
    if (cur && (cur.messageCount ?? cur.messages.length) === 0) {
      if (cur.source === 'server' && cur.revision) { void updateShared(cur.id, { persona: persona || undefined }); return; }
      setSessions((prev) => {
        const updated = prev.map((s) =>
          s.id === activeSessionId ? { ...s, persona: persona || undefined } : s);
        saveSessions(updated);
        return updated;
      });
      return;
    }
    const newSession = createSession(persona || undefined);
    setSessions((prev) => {
      const updated = [newSession, ...prev];
      saveSessions(updated);
      return updated;
    });
    setActiveSessionId(newSession.id);
  }, [activeSessionId, currentPage, updateShared]);

  return (
    <>
      <ResponsiveShell
        title={{dashboard: '工作台', chat: '对话', skills: '技能库', outputs: '内容库', accounts: '账号', profile: '画像', trends: '热点雷达', ideas: '选题库', calendar: '内容日历', publish: '发布中心', breakdown: '爆款拆解'}[currentPage]}
        persona={selectedPersona || '通用模式'} onNewChat={handleNewChat}
        navigation={(close) => <Sidebar
        currentPage={currentPage}
        onPageChange={(page) => { setCurrentPage(page); close(); }}
        personas={personas}
        selectedPersona={selectedPersona}
        onPersonaChange={(persona) => { handlePersonaChange(persona); close(); }}
        onNewProfile={() => { setShowWizard(true); close(); }}
        sessions={sessions}
        onImportLocal={() => setShowImportLocal(true)}
        activeSessionId={activeSessionId}
        onSessionSelect={(id) => { handleSessionSelect(id); close(); }}
        onSessionDelete={handleSessionDelete}
        onSessionRename={handleSessionRename}
        onSessionArchive={handleSessionArchive}
        onNewChat={() => { handleNewChat(); close(); }}
        gatewayStatus={gatewayStatus}
        apiDirect={apiDirect}
        agentRuntime={agentRuntime}
        onOpenSettings={() => { setSettingsOpen(true); close(); }}
      />}>
        {(['trends', 'ideas', 'calendar', 'publish', 'breakdown'] as Page[]).includes(currentPage) && (
          <SubNav current={currentPage} onNavigate={setCurrentPage} />
        )}
        <PwaNotice busy={Object.keys(streams).length > 0 || sessions.some(s => !!s.pendingTurnId)} />
        {(!online || !historyVerified) && historyReady && <div className="history-notice" role="status">
          {!online ? '当前离线，可阅读已缓存的对话。联网后自动同步。' : '正在核对服务端记录，当前显示本地缓存。'}
        </div>}
        {historyError && online && <div className="history-notice" role="alert">
          <span>{historyError}</span>
          <button className="btn btn-sm" onClick={() => {
            if (historyReady) void refreshShared().then(() => setHistoryError('')).catch(reportHistoryError);
            else window.dispatchEvent(new Event('easel-retry-history'));
          }}>刷新会话</button>
          <button className="btn btn-sm" onClick={() => setHistoryError('')} aria-label="关闭提示">×</button>
        </div>}
        <div className="page-host">
          {renderPage()}
        </div>
      </ResponsiveShell>

      {renameTarget && <RenameDialog key={`${renameTarget.session.id}-${renameTarget.messageIndex ?? 'all'}`}
        {...renameTarget} onSave={saveSessionName} onClose={() => setRenameTarget(null)} />}
      {showImportLocal && <div className="overlay">
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="import-history-title" style={{ width: 420, maxWidth: '100%' }}>
          <h2 id="import-history-title">迁移本浏览器旧对话</h2>
          <p>将此浏览器的旧对话复制到服务端，供手机和其他电脑查看。本地保留备份，其他浏览器不会自动迁移。</p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <button className="btn" disabled={importingLocal} onClick={() => setShowImportLocal(false)}>取消</button>
            <button className="btn btn-primary" disabled={importingLocal} onClick={() => void handleImportLocal()}>{importingLocal ? '迁移中…' : '复制到服务端'}</button>
          </div>
        </div>
      </div>}
      {/* 首次使用：推荐配置画像 */}
      {showRecommend && (
        <div className="overlay">
          <div className="modal" style={{ width: 420, maxWidth: '100%', textAlign: 'center' }}>
            <div style={{ fontSize: 40 }}>👋</div>
            <h2 style={{ margin: '12px 0 8px', fontSize: 20 }}>欢迎使用 Easel</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.6 }}>
              配置你的账号画像，生成的内容会更贴合你的风格、受众和平台调性。<br />
              大约 2 分钟，也可以随时在侧栏「+ 新建画像」补配。
            </p>
            <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'center' }}>
              <button className="btn" onClick={dismissRecommend}>先用通用模式</button>
              <button className="btn btn-primary" onClick={openWizard}>开始配置</button>
            </div>
          </div>
        </div>
      )}

      {/* 画像配置向导 */}
      {showWizard && (
        <OnboardingWizard onClose={() => setShowWizard(false)} onCreated={handleProfileCreated} />
      )}

      {/* 设置（统一入口：模型配置 · 环境安装 · 更多设置） */}
      {settingsOpen && (
        <SettingsPanel
          banner={needModelSetup
            ? '还没有配置模型 —— 填一个 API Key 才能开始对话。保存后会自动同步配置并重启网关。'
            : ''}
          onClose={() => {
            setSettingsOpen(false);
            setNeedModelSetup(false);
            void fetchStatus().then((data) => {
              setApiDirect(data.transport === 'api');
              setAgentRuntime(data.runtime || 'openclaw');
              setGatewayStatus(data.gateway ? 'connected' : 'disconnected');
            }).catch(() => setGatewayStatus('disconnected'));
          }}
        />
      )}
    </>
  );
}
