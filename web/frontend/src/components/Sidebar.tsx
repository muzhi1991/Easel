import { useState } from 'react';
import type { ChatSession } from '../lib/store';
import type { PersonaItem } from '../lib/api';
import type { ComponentType } from 'react';
import {
  IconChat, IconSkills, IconOutputs, IconAccounts, IconProfile,
  IconNewChat, IconEdit, IconArchive, IconUnarchive, IconTrash, IconChevron,
  IconDashboard,
} from './icons';
import { IconGear } from './settingsIcons';
import ThemeToggle from './ThemeToggle';

export type Page = 'dashboard' | 'chat' | 'trends' | 'ideas' | 'calendar' | 'publish' | 'breakdown' | 'skills' | 'outputs' | 'accounts' | 'profile';

interface SidebarProps {
  currentPage: Page;
  onPageChange: (page: Page) => void;
  personas: PersonaItem[];
  selectedPersona: string;
  onPersonaChange: (persona: string) => void;
  onNewProfile: () => void;
  sessions: ChatSession[];
  onImportLocal: () => void;
  activeSessionId: string | null;
  onSessionSelect: (id: string) => void;
  onSessionDelete: (id: string) => void;
  onSessionRename: (id: string) => void;
  onSessionArchive: (id: string, archived: boolean) => void;
  onNewChat: () => void;
  gatewayStatus: string;
  apiDirect: boolean;
  agentRuntime: string;
  onOpenSettings: () => void;
}

// 主导航（精简）；热点雷达/选题库/内容日历/发布中心 收进「工作台」，不占侧栏
const NAV: { page: Page; Icon: ComponentType<{ size?: number }>; label: string }[] = [
  { page: 'dashboard', Icon: IconDashboard, label: '工作台' },
  { page: 'chat', Icon: IconChat, label: '对话' },
  { page: 'skills', Icon: IconSkills, label: '技能库' },
  { page: 'outputs', Icon: IconOutputs, label: '内容库' },
  { page: 'accounts', Icon: IconAccounts, label: '账号' },
  { page: 'profile', Icon: IconProfile, label: '画像' },
];

export default function Sidebar({
  currentPage,
  onPageChange,
  personas,
  selectedPersona,
  onPersonaChange,
  onNewProfile,
  sessions,
  onImportLocal,
  activeSessionId,
  onSessionSelect,
  onSessionDelete,
  onSessionRename,
  onSessionArchive,
  onNewChat,
  gatewayStatus,
  apiDirect,
  agentRuntime,
  onOpenSettings,
}: SidebarProps) {
  const [showArchived, setShowArchived] = useState(false);

  const active = sessions.filter((s) => !s.archived && ((s.messageCount ?? s.messages.length) > 0 || s.id === activeSessionId));
  const archived = sessions.filter((s) => s.archived);

  const renderItem = (s: ChatSession, isArchived: boolean) => {
    return (
      <div
        key={s.id}
        className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
        onClick={() => onSessionSelect(s.id)}
      >
        <span className="session-item-title" title={s.title}>{s.title}{s.source !== 'server' && <small className="local-history-badge">本地旧记录</small>}</span>
        <div className="session-actions">
          <button className="session-act" title="重命名"
            onClick={(e) => { e.stopPropagation(); onSessionRename(s.id); }}><IconEdit size={14} /></button>
          <button className="session-act" title={isArchived ? '取消归档' : '归档'}
            onClick={(e) => { e.stopPropagation(); onSessionArchive(s.id, !isArchived); }}>
            {isArchived ? <IconUnarchive size={14} /> : <IconArchive size={14} />}
          </button>
          <button className="session-act danger" title="删除"
            onClick={(e) => { e.stopPropagation(); onSessionDelete(s.id); }}><IconTrash size={14} /></button>
        </div>
      </div>
    );
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <img className="sidebar-logo-icon" src="./static/easel-icon-transparent.png" alt="" />
          <h1>Easel</h1>
          <ThemeToggle />
        </div>
        <select
          className="persona-select"
          value={selectedPersona}
          onChange={(e) => {
            if (e.target.value === '__new__') { onNewProfile(); return; }
            onPersonaChange(e.target.value);
          }}
          aria-label="用户画像"
          title={currentPage === 'chat' ? '选择画像；已有消息时切换会新建对话' : '选择当前任务使用的画像，不影响历史对话'}
        >
          <option value="">通用模式</option>
          {personas.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
          <option value="__new__">+ 新建画像…</option>
        </select>
      </div>

      <nav className="sidebar-nav">
        {NAV.map(({ page, Icon, label }) => (
          <button
            key={page}
            className={`nav-item ${currentPage === page ? 'active' : ''}`}
            onClick={() => onPageChange(page)}
          >
            <span className="nav-icon"><Icon size={18} /></span>
            {label}
          </button>
        ))}
      </nav>

      <div className="sidebar-section">
        <div className="sidebar-section-header">
          <span className="sidebar-section-title">对话</span>
          <button className="new-chat-btn" onClick={onNewChat} title="新建对话">
            <IconNewChat size={13} /> 新对话
          </button>
        </div>
        {active.map((s) => renderItem(s, false))}
        {sessions.some((s) => s.source !== 'server' && s.messages.length > 0) && <button
          className="local-history-import" onClick={onImportLocal}>迁移本浏览器旧对话</button>}

        {archived.length > 0 && (
          <>
            <div className="archived-header" onClick={() => setShowArchived((v) => !v)}>
              <span className={`archived-chevron ${showArchived ? 'open' : ''}`}><IconChevron size={12} /></span>
              已归档 · {archived.length}
            </div>
            {showArchived && archived.map((s) => renderItem(s, true))}
          </>
        )}
      </div>

      <div className="sidebar-status">
        <span className={`status-dot ${gatewayStatus === 'connected' ? '' : 'offline'}`} />
        <span className="sidebar-status-text">{gatewayStatus === 'connected'
          ? (apiDirect ? '仅聊天模式已配置' : agentRuntime !== 'openclaw' ? `${agentRuntime} CLI 已安装` : '网关已连接')
          : gatewayStatus === 'disconnected'
            ? (apiDirect ? 'API 配置不完整' : agentRuntime !== 'openclaw' ? `${agentRuntime} CLI 未配置` : '网关离线')
            : '连接中…'}</span>
        <button className="settings-gear" onClick={onOpenSettings} title="设置（模型 · 环境 · 更多）">
          <IconGear size={13} /> 设置
        </button>
      </div>
    </div>
  );
}
