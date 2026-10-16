import ChatModelControls from './ChatModelControls';
import { useState, useRef, useEffect, useLayoutEffect } from 'react';
import MessageBubble from './MessageBubble';
import QuestionCards from './QuestionCards';
import BrushEntry from './BrushEntry';
import type { ChatSession, ChatMessage, StreamState } from '../lib/store';
import { historyEnd } from '../lib/sessionHistory';
import { uploadFiles, adoptOversize } from '../lib/api';
import type { UploadedFile, ThinkingLevel } from '../lib/api';
import { IconArrowUp, IconStop, IconPlus, IconFile } from './icons';

interface ChatPageProps {
  apiDirect: boolean;
  session: ChatSession;
  historyLoading?: boolean;
  readOnly?: boolean;
  historyError?: string;
  onLoadHistory?: (older: boolean) => Promise<void>;
  onThinkingChange: (level?: ThinkingLevel) => void;
  stream?: StreamState;          // 进行中的流式态（来自 App，切页也不丢）
  onSend: (displayText: string, attachments?: UploadedFile[]) => Promise<boolean>;
  onStop: () => void;
  onResend: (
    userIndex: number,
    displayText: string,
    attachments?: UploadedFile[],
    legacyAgentText?: string,
  ) => void; // 重试：仅对最后一轮
  onQuestionAnswered?: (questionId: string) => void;   // 某道问答题提交成功（App 记录答过，重放不再出现）
}

// 空态推荐（贴合 Easel 社媒创作场景）
const SUGGESTIONS = [
  { icon: '🔥', title: '蹭个热点', prompt: '看看现在微博和抖音有什么热搜，挑几个适合我做二创的选题' },
  { icon: '✍️', title: '写小红书文案', prompt: '帮我写一条小红书种草文案，主题先问我' },
  { icon: '🎴', title: '做金句卡片', prompt: '把一句走心的话做成一张适合发朋友圈的金句卡片' },
  { icon: '🎬', title: '口播脚本', prompt: '帮我写一条 60 秒的口播短视频脚本，主题先问我' },
];

function greeting(): string {
  const h = new Date().getHours();
  const g = h < 6 ? '夜深了' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  return `${g}，想创作点什么？`;
}

export default function ChatPage({ apiDirect, session, stream, historyLoading = false, readOnly = false, historyError, onLoadHistory, onThinkingChange, onSend, onStop, onResend, onQuestionAnswered }: ChatPageProps) {
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [attachments, setAttachments] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [maxMb, setMaxMb] = useState(50);
  const messagesRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const followMessagesRef = useRef(true);
  const touchingMessagesRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const previousHistoryRef = useRef<{ start: number; offset: number; epoch?: number } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isComposingRef = useRef(false);

  const isStreaming = !!stream;
  const waitingForHistory = session.source === 'server' && !!session.revision
    && (!session.historyLoaded || !session.messages.length && (session.messageCount || 0) > 0);
  const missingLatest = waitingForHistory || (session.source === 'server' && historyEnd(session) < (session.messageCount || 0));
  const isEmpty = !waitingForHistory && session.messages.length === 0 && !isStreaming;

  useEffect(() => {
    fetch('/api/upload/limits').then((r) => r.json())
      .then((d) => { if (d?.max_mb) setMaxMb(d.max_mb); }).catch(() => {});
  }, []);

  const doUpload = async (fs: FileList | File[]) => {
    if (readOnly) return;
    const arr = Array.from(fs);
    if (!arr.length) return;
    const cap = maxMb * 1024 * 1024;
    const big = arr.filter((f) => f.size > cap);
    const small = arr.filter((f) => f.size <= cap);

    if (big.length) {
      // 超限：不走上传通道，复制进收件箱后作为普通附件（界面零新增元素）
      setUploading(true);
      try {
        const saved = await adoptOversize(big, session.id);
        setAttachments((a) => [...a, ...saved]);
      } catch (err) {
        alert((err as Error).message || '超限文件处理失败');
      } finally {
        setUploading(false);
      }
    }
    if (!small.length) return;
    setUploading(true);
    try {
      const saved = await uploadFiles(small, session.id);
      setAttachments((a) => [...a, ...saved]);
    } catch (err) {
      alert((err as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    if (e.dataTransfer.files?.length) doUpload(e.dataTransfer.files);
  };
  const onPaste = (e: React.ClipboardEvent) => {
    if (e.clipboardData.files?.length) { e.preventDefault(); doUpload(e.clipboardData.files); }
  };
  const removeAttachment = (path: string) => setAttachments((a) => a.filter((x) => x.path !== path));

  useLayoutEffect(() => {
    const el = messagesRef.current;
    const thread = threadRef.current;
    const previous = previousHistoryRef.current;
    const start = session.messageStart || 0;
    if (el && thread && previous && previous.epoch === session.historyEpoch && start <= previous.start) {
      const anchor = thread.querySelector<HTMLElement>(`[data-message-index="${previous.start}"]`);
      if (anchor) {
        // Anchor to the old first message, independent of concurrent tail growth
        // or scrolling while the request was in flight. Native anchoring is off.
        el.scrollTop += anchor.getBoundingClientRect().top - thread.getBoundingClientRect().top - previous.offset;
        lastScrollTopRef.current = el.scrollTop;
      }
    }
    if (previous && previous.epoch !== session.historyEpoch) followMessagesRef.current = true;
    const first = thread?.querySelector<HTMLElement>('[data-message-index]');
    previousHistoryRef.current = first && thread
      ? { start, offset: first.getBoundingClientRect().top - thread.getBoundingClientRect().top, epoch: session.historyEpoch } : null;
    // Instant, container-only scrolling avoids queued smooth animations fighting
    // wheel/touch input and avoids moving the outer page on mobile.
    if (el && followMessagesRef.current) {
      el.scrollTop = el.scrollHeight;
      lastScrollTopRef.current = el.scrollTop;
    }
  }, [session.messages, stream?.content, stream?.thinking, stream?.activity, stream?.stillWorking, isEmpty, waitingForHistory, session.messageStart, session.historyEpoch, historyLoading, historyError]);

  useEffect(() => {
    const el = messagesRef.current;
    const thread = threadRef.current;
    if (!el || !thread) return;
    // Images and the mobile keyboard can change geometry without new messages.
    const observer = new ResizeObserver(() => {
      if (followMessagesRef.current) {
        el.scrollTop = el.scrollHeight;
        lastScrollTopRef.current = el.scrollTop;
      }
    });
    observer.observe(el);
    observer.observe(thread);
    return () => observer.disconnect();
  }, [isEmpty, waitingForHistory]);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 180) + 'px';
    }
  }, [input]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || isStreaming || uploading || submitting || missingLatest || readOnly) return;
    // 附件通过结构化字段发送；用户消息气泡只显示用户实际输入的文字。
    setSubmitting(true);
    followMessagesRef.current = true;
    try {
      if (await onSend(trimmed, attachments)) {
        setInput((current) => current.trim() === trimmed ? '' : current);
        const sent = new Set(attachments.map((a) => a.path));
        setAttachments((current) => current.filter((a) => !sent.has(a.path)));
      }
    } finally { setSubmitting(false); }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 输入法确认候选词/英文的回车交给输入法处理，不能触发发送。
    // 部分浏览器先触发 compositionend，此时仍需用 229 识别输入法按键。
    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
    // Touch devices use the keyboard Return key for newlines; send via the arrow.
    if (window.matchMedia('(pointer: coarse)').matches) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const inputBox = (hero: boolean) => (
    <div className={`composer ${hero ? 'composer-hero' : ''} ${dragOver ? 'composer-drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
      onDrop={onDrop}>
      {attachments.length > 0 && (
        <div className="composer-attachments">
          {attachments.map((a) => (
            <span key={a.path} className="attach-chip" title={a.path}>
              <IconFile size={12} /> <span className="attach-name">{a.name}</span>
              <button className="attach-x" onClick={() => removeAttachment(a.path)} title="移除">×</button>
            </span>
          ))}
        </div>
      )}
      <div className="composer-top">
        {apiDirect ? <span className="composer-hint">API 直连 · 文字与附件分析</span>
          : <BrushEntry onPick={(t) => { setInput(t); requestAnimationFrame(() => textareaRef.current?.focus()); }} />}
        <textarea
          ref={textareaRef}
          className="chat-input"
          placeholder={dragOver ? '松手上传素材…' : hero ? '把你的想法告诉我，选题 / 文案 / 卡片 / 视频 / 发布都行…（可拖入图片/文档当素材）' : '发消息…（Enter 发送，Shift+Enter 换行，可拖入/粘贴素材）'}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onCompositionStart={() => { isComposingRef.current = true; }}
          onCompositionEnd={() => { isComposingRef.current = false; }}
          onBlur={() => { isComposingRef.current = false; }}
          onKeyDown={handleKeyDown}
          onPaste={onPaste}
          rows={1}
          autoFocus={hero && !window.matchMedia('(max-width: 767px), (max-width: 1023px) and (pointer: coarse)').matches}
        />
      </div>
      <input ref={fileInputRef} type="file" multiple hidden
        onChange={(e) => { if (e.target.files) doUpload(e.target.files); e.target.value = ''; }} />
      <div className="composer-bar">
        <button className="composer-attach-btn" onClick={() => fileInputRef.current?.click()}
          disabled={readOnly || isStreaming || uploading} title={`添加素材（图片/文档）；超过 ${maxMb}MB 的大文件将自动存为本地素材（不走上传）`}>
          <IconPlus size={15} /><span>{uploading ? '上传中…' : '素材'}</span>
        </button>
        <ChatModelControls apiDirect={apiDirect} sessionId={session.id} streaming={isStreaming} thinking={session.thinking} onThinkingChange={onThinkingChange} />
        {isStreaming ? (
          <button className="send-btn" onClick={onStop} title="停止生成"><IconStop size={15} /></button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={(!input.trim() && !attachments.length) || uploading || submitting || missingLatest || readOnly} title="发送"><IconArrowUp size={17} /></button>
        )}
      </div>
      <div className="composer-hint">{isStreaming ? '生成中…' : 'Enter 发送 · Shift+Enter 换行'}</div>
    </div>
  );

  if (waitingForHistory) {
    return <div className="chat-page"><div className="chat-history-status" role="status">
      {historyError || (readOnly ? '此会话尚未缓存，请联网后加载。' : '正在加载消息…')}
      {historyError && <button className="btn btn-sm" onClick={() => onLoadHistory?.(false)}>重试</button>}
    </div></div>;
  }

  // ---- 空态：居中欢迎页 ----
  if (isEmpty) {
    return (
      <div className="chat-page">
        <div className="chat-hero">
          <div className="chat-hero-brand">
            <img src="./static/easel-icon-transparent.png" alt="" />
            <span>Easel</span>
          </div>
          <h1 className="chat-hero-title">{greeting()}</h1>
          <p className="chat-hero-sub">{apiDirect ? 'API 直连：写文案、策划选题、分析附件。本机工具和自动发布未启用。'
            : '从选题到发布，一站式帮你把想法做成能发的内容。'}</p>
          {inputBox(true)}
          <div className="suggestions">
            {SUGGESTIONS.filter((s) => !apiDirect || ['写小红书文案', '口播脚本'].includes(s.title)).map((s) => (
              <button key={s.title} className="card card-hover suggestion-card"
                onClick={() => { if (!isStreaming) onSend(s.prompt); }}>
                <span className="suggestion-icon">{s.icon}</span>
                <span className="suggestion-body">
                  <span className="suggestion-title">{s.title}</span>
                  <span className="suggestion-text">{s.prompt}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ---- 对话态 ----
  const displayMessages: ChatMessage[] = [...session.messages];
  if (isStreaming) displayMessages.push({ role: 'assistant', content: stream!.content || '' });

  return (
    <div className="chat-page">
      <div className="chat-messages" ref={messagesRef}
        onScroll={(event) => {
          const el = event.currentTarget;
          // Only resume at the bottom (with rounding tolerance), so small
          // upward movements cannot be swallowed by the next streaming token.
          if (!touchingMessagesRef.current) {
            if (el.scrollHeight - el.clientHeight - el.scrollTop <= 2) followMessagesRef.current = true;
            // Content/viewport resizing can emit scroll events too. Only an
            // upward movement should cancel following, not a new bottom gap.
            else if (el.scrollTop < lastScrollTopRef.current) followMessagesRef.current = false;
          }
          lastScrollTopRef.current = el.scrollTop;
          if (el.scrollTop < 80 && session.messageStart && !historyLoading && !historyError) {
            followMessagesRef.current = false;
            void onLoadHistory?.(true);
          }
        }}
        onWheel={(event) => { if (event.deltaY < 0) followMessagesRef.current = false; }}
        onTouchStart={() => {
          // Pause before the browser crosses its native touch-scroll threshold.
          touchingMessagesRef.current = true;
          followMessagesRef.current = false;
        }}
        onTouchEnd={(event) => {
          touchingMessagesRef.current = false;
          const el = event.currentTarget;
          followMessagesRef.current = el.scrollHeight - el.clientHeight - el.scrollTop <= 2;
        }}
        onTouchCancel={() => { touchingMessagesRef.current = false; }}>
        <div className="chat-thread" ref={threadRef}>
          {(!!session.messageStart || historyError || missingLatest) && <div className="chat-history-controls" role="status">
            {historyError && <span>{historyError}</span>}
            <button className="btn btn-sm" disabled={historyLoading || readOnly} onClick={() => {
              followMessagesRef.current = false;
              void onLoadHistory?.(!missingLatest);
            }}>{historyLoading ? '正在加载…' : historyError ? '重试加载消息' : missingLatest ? '加载新消息' : '加载更早消息'}</button>
          </div>}
          {displayMessages.map((msg, i) => {
            const isLast = i === displayMessages.length - 1;
            const live = isStreaming && isLast && msg.role === 'assistant';
            const isFinal = !live && i < session.messages.length;
            let actions;
            if (isFinal) {
              const copy = () => navigator.clipboard?.writeText(msg.content);
              // 只允许对「最后一轮」重试，契合 OpenClaw append-only 模型（不改写历史）；已移除编辑
              const isLastFinal = i === session.messages.length - 1;
              if (msg.role === 'user') {
                actions = {
                  onCopy: copy,
                  onRetry: isLastFinal
                    ? () => onResend(i, msg.content, msg.attachments, msg.agentContent)
                    : undefined,
                  canModify: !readOnly && !isStreaming && !missingLatest,
                };
              } else {
                const pi = i - 1;
                const prevUser = pi >= 0 && session.messages[pi]?.role === 'user' ? session.messages[pi] : null;
                actions = {
                  onCopy: copy,
                  onRetry: (isLastFinal && prevUser)
                    ? () => onResend(pi, prevUser.content, prevUser.attachments, prevUser.agentContent)
                    : undefined,
                  canModify: !readOnly && !isStreaming && !missingLatest,
                };
              }
            }
            return (
              <div key={`${(session.messageStart || 0) + i}-${msg.role}`} data-message-index={(session.messageStart || 0) + i}>
              <MessageBubble
                message={msg}
                isStreaming={live}
                thinking={live ? stream!.thinking : ''}
                activity={live ? stream!.activity : ''}
                stillWorking={live ? stream!.stillWorking : ''}
                actions={actions}
              />
              </div>
            );
          })}
          {isStreaming && (stream!.questions?.length ?? 0) > 0 && (
            <QuestionCards questions={stream!.questions || []} onDone={(qid) => onQuestionAnswered?.(qid)} />
          )}
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input-inner">{inputBox(false)}</div>
      </div>
    </div>
  );
}
