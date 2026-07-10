import { CircleAlert, ShieldCheck, Sparkles } from "lucide-react";
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
  onVoiceToggle: () => void;
  onValidate: (validation: "yes" | "no", comments: string) => Promise<void>;
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
  onVoiceToggle,
  onValidate
}: ChatPanelProps) {
  return (
    <main className="chat-panel">
      <header className="chat-header">
        <div className="chat-title-row">
          <div>
            <span className="eyebrow">Clinical Consultation</span>
            <h2>医疗智能体会话</h2>
          </div>
          <div className="online-badge" role="status">
            <span className="status-dot" aria-hidden="true" />
            在线
          </div>
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
          onVoiceToggle={onVoiceToggle}
        />
      </div>
    </main>
  );
}
