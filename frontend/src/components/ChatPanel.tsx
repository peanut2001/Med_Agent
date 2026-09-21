import { useEffect, useRef } from "react";
import { Activity, CircleAlert, PanelLeft, ShieldCheck, Sparkles } from "lucide-react";
import type { ChatMessage, ImageDraft } from "../types";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";

type ChatPanelProps = {
  messages: ChatMessage[];
  inputValue: string;
  imageDraft: ImageDraft | null;
  busy: boolean;
  recorderState: "idle" | "recording" | "transcribing" | "error";
  statusMessage: string | null;
  onInputChange: (value: string) => void;
  onImageChange: (file: File) => void;
  onImageRemove: () => void;
  onSubmit: () => void;
  onStop: () => void;
  onVoiceToggle: () => void;
  onValidate: (validation: "yes" | "no", comments: string) => Promise<void>;
  sidebarOpen: boolean;
  inspectorOpen: boolean;
  onToggleSidebar: () => void;
  onToggleInspector: () => void;
};

export function ChatPanel({
  messages,
  inputValue,
  imageDraft,
  busy,
  recorderState,
  statusMessage,
  onInputChange,
  onImageChange,
  onImageRemove,
  onSubmit,
  onStop,
  onVoiceToggle,
  onValidate,
  sidebarOpen,
  inspectorOpen,
  onToggleSidebar,
  onToggleInspector
}: ChatPanelProps) {
  const isWelcome = messages.length === 0;
  const scrollRef = useRef<HTMLElement | null>(null);
  // 用户往上翻阅时不抢滚动条，回到底部附近再恢复跟随。
  const pinnedToBottom = useRef(true);

  function handleScroll() {
    const node = scrollRef.current;
    if (!node) return;
    pinnedToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
  }

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinnedToBottom.current) return;
    // 流式输出会高频触发，用 auto 覆盖掉 CSS 的 smooth，否则滚动条一直在追动画。
    node.scrollTo({ top: node.scrollHeight, behavior: "auto" });
  }, [messages]);

  return (
    <main className={`chat-panel${isWelcome ? "" : " chat-panel--chatting"}`}>
      <header className="chat-header">
        <div className="chat-title-row">
          <button
            type="button"
            className={`panel-toggle${sidebarOpen ? " is-active" : ""}`}
            onClick={onToggleSidebar}
            aria-label={sidebarOpen ? "收起左侧导航" : "展开左侧导航"}
            aria-expanded={sidebarOpen}
            title={sidebarOpen ? "收起左侧导航" : "展开左侧导航"}
          >
            <PanelLeft size={18} />
          </button>
          {/* 对话态只留两侧开关图标，中间完全交给正文。 */}
          {isWelcome ? (
            <div className="online-badge" role="status">
              <span className="status-dot" aria-hidden="true" />
              在线
            </div>
          ) : null}
          <button
            type="button"
            className={`panel-toggle${inspectorOpen ? " is-active" : ""}`}
            onClick={onToggleInspector}
            aria-label={inspectorOpen ? "收起执行轨迹" : "展开执行轨迹"}
            aria-expanded={inspectorOpen}
            title={inspectorOpen ? "收起执行轨迹" : "展开执行轨迹"}
          >
            <Activity size={18} />
          </button>
        </div>
        {/* 免责声明只在欢迎页展示；进入对话后顶栏留空，
            合规提示交给输入框上方常驻的那行。 */}
        {isWelcome ? (
          <div className="disclaimer-bar">
            <CircleAlert size={16} aria-hidden="true" />
            <p>回答仅用于健康信息参考；如有急症或症状持续加重，请立即联系专业医疗机构。</p>
            <span className="secure-label"><ShieldCheck size={15} /> 安全辅助</span>
          </div>
        ) : null}
      </header>

      <section
        className="chat-scroll"
        ref={scrollRef}
        onScroll={handleScroll}
        aria-live="polite"
        aria-busy={busy}
      >
        <MessageList messages={messages} onValidate={onValidate} />
      </section>

      <div className="composer-region">
        <div className="composer-context" aria-hidden="true">
          <Sparkles size={14} />
          <span>AI 可能会出错，请核对重要医疗信息</span>
        </div>
        <Composer
          value={inputValue}
          imageDraft={imageDraft}
          busy={busy}
          recorderState={recorderState}
          statusMessage={statusMessage}
          onChange={onInputChange}
          onImageChange={onImageChange}
          onImageRemove={onImageRemove}
          onSubmit={onSubmit}
          onStop={onStop}
          onVoiceToggle={onVoiceToggle}
        />
      </div>
    </main>
  );
}
