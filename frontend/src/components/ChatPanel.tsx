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
        <div>
          <span className="eyebrow">Agent Console</span>
          <h2>医疗智能体会话</h2>
        </div>
        <p>所有输出仅用于辅助判断，关键诊疗决策仍需专业医生结合临床信息确认。</p>
      </header>
      <section className="chat-scroll" aria-live="polite">
        <MessageList messages={messages} onValidate={onValidate} />
      </section>
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
    </main>
  );
}
