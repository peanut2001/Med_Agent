import { CircleAlert, PanelLeft, PanelRight, ShieldCheck, Sparkles } from "lucide-react";
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
  return (
    <main className="chat-panel">
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
          <div className="chat-title-copy">
            <span className="eyebrow">Clinical Consultation</span>
            <h2>医疗智能体会话</h2>
          </div>
          <div className="online-badge" role="status">
            <span className="status-dot" aria-hidden="true" />
            在线
          </div>
          <button
            type="button"
            className={`panel-toggle${inspectorOpen ? " is-active" : ""}`}
            onClick={onToggleInspector}
            aria-label={inspectorOpen ? "收起执行轨迹" : "展开执行轨迹"}
            aria-expanded={inspectorOpen}
            title={inspectorOpen ? "收起执行轨迹" : "展开执行轨迹"}
          >
            <PanelRight size={18} />
          </button>
        </div>
        <div className="disclaimer-bar">
          <CircleAlert size={16} aria-hidden="true" />
          <p>回答仅用于健康信息参考；如有急症或症状持续加重，请立即联系专业医疗机构。</p>
          <span className="secure-label"><ShieldCheck size={15} /> 安全辅助</span>
        </div>
      </header>

      <section className="chat-scroll" aria-live="polite" aria-busy={busy}>
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
