import { useState } from "react";
import {
  Check,
  HeartPulse,
  ImagePlus,
  LogOut,
  MessageSquareText,
  Mic,
  PenSquare,
  Pencil,
  Trash2
} from "lucide-react";
import type { ConversationSummary } from "../types";

type SidebarProps = {
  onNewConversation: () => void;
  onLogout: () => void;
  currentUser: string;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  historyLoading: boolean;
  onSelectConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, title: string) => void;
  onDeleteConversation: (conversationId: string) => void;
};

const capabilities = [
  {
    icon: MessageSquareText,
    title: "智能问答",
    description: "症状、用药与健康信息咨询"
  },
  {
    icon: ImagePlus,
    title: "影像分析",
    description: "脑部、胸片与皮肤图像辅助识别"
  },
  {
    icon: Mic,
    title: "语音交互",
    description: "语音转写与回复朗读"
  }
];

type HistoryGroup = {
  label: string;
  items: ConversationSummary[];
};

/** 按最近使用时间分成三段，空分组不渲染。 */
function groupConversations(conversations: ConversationSummary[]): HistoryGroup[] {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const todayStart = midnight.getTime() / 1000;
  const weekStart = todayStart - 6 * 86400;

  const groups: HistoryGroup[] = [
    { label: "今天", items: [] },
    { label: "近 7 天", items: [] },
    { label: "更早", items: [] }
  ];

  conversations.forEach((item) => {
    if (item.updated_at >= todayStart) groups[0].items.push(item);
    else if (item.updated_at >= weekStart) groups[1].items.push(item);
    else groups[2].items.push(item);
  });

  return groups.filter((group) => group.items.length > 0);
}

export function Sidebar({
  onNewConversation,
  onLogout,
  currentUser,
  conversations,
  activeConversationId,
  historyLoading,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation
}: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const groups = groupConversations(conversations);

  function startRename(item: ConversationSummary) {
    setEditingId(item.conversation_id);
    setDraftTitle(item.title);
  }

  function commitRename(item: ConversationSummary) {
    const title = draftTitle.trim();
    // 卸载输入框后 onBlur 不再触发，所以这里不会重复提交。
    setEditingId(null);
    if (title && title !== item.title) {
      onRenameConversation(item.conversation_id, title);
    }
  }

  function confirmDelete(item: ConversationSummary) {
    if (window.confirm(`删除对话「${item.title}」？该操作不可撤销。`)) {
      onDeleteConversation(item.conversation_id);
    }
  }

  return (
    <aside className="sidebar" aria-label="应用导航">
      <div className="brand-row">
        <span className="brand-mark" aria-hidden="true">
          <HeartPulse size={18} strokeWidth={2.1} />
        </span>
        <h1>多智能体医疗助手</h1>
      </div>

      <button
        type="button"
        className="new-chat-button"
        onClick={onNewConversation}
        aria-label="开启新对话"
        title="开启新对话"
      >
        <PenSquare size={16} aria-hidden="true" />
        <span>新对话</span>
      </button>

      <nav className="capability-nav" aria-label="核心能力">
        <div className="section-label">核心能力</div>
        <ul>
          {capabilities.map(({ icon: Icon, title, description }) => (
            <li key={title}>
              <Icon size={16} aria-hidden="true" />
              <span>
                <strong>{title}</strong>
                <small>{description}</small>
              </span>
            </li>
          ))}
        </ul>
      </nav>

      <nav className="history-nav" aria-label="历史对话">
        <div className="section-label">历史对话</div>

        {historyLoading && conversations.length === 0 ? (
          <p className="history-hint">正在载入历史记录…</p>
        ) : conversations.length === 0 ? (
          <p className="history-hint">还没有历史对话，发出第一条消息后会自动保存。</p>
        ) : (
          groups.map((group) => (
            <div className="history-group" key={group.label}>
              <div className="history-group__label">{group.label}</div>
              <ul>
                {group.items.map((item) => {
                  const isActive = item.conversation_id === activeConversationId;
                  const isEditing = item.conversation_id === editingId;

                  return (
                    <li
                      key={item.conversation_id}
                      className={`history-item${isActive ? " is-active" : ""}`}
                    >
                      {isEditing ? (
                        <>
                          <input
                            className="history-item__input"
                            value={draftTitle}
                            autoFocus
                            maxLength={40}
                            aria-label="对话标题"
                            onChange={(event) => setDraftTitle(event.target.value)}
                            onBlur={() => commitRename(item)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") commitRename(item);
                              if (event.key === "Escape") setEditingId(null);
                            }}
                          />
                          <span className="history-item__actions is-visible">
                            <button
                              type="button"
                              // onMouseDown 抢在输入框 blur 之前，保证点击确实提交。
                              onMouseDown={(event) => {
                                event.preventDefault();
                                commitRename(item);
                              }}
                              aria-label="保存标题"
                              title="保存标题"
                            >
                              <Check size={13} aria-hidden="true" />
                            </button>
                          </span>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="history-item__open"
                            onClick={() => onSelectConversation(item.conversation_id)}
                            title={item.title}
                          >
                            <MessageSquareText size={14} aria-hidden="true" />
                            <span>{item.title}</span>
                          </button>
                          <span className="history-item__actions">
                            <button
                              type="button"
                              onClick={() => startRename(item)}
                              aria-label={`重命名对话：${item.title}`}
                              title="重命名"
                            >
                              <Pencil size={13} aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              className="history-item__delete"
                              onClick={() => confirmDelete(item)}
                              aria-label={`删除对话：${item.title}`}
                              title="删除"
                            >
                              <Trash2 size={13} aria-hidden="true" />
                            </button>
                          </span>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-user">已登录：{currentUser}</div>
        <button type="button" className="logout-button" onClick={onLogout} aria-label="退出登录" title="退出登录">
          <LogOut size={16} aria-hidden="true" />
          <span>退出登录</span>
        </button>
      </div>
    </aside>
  );
}
