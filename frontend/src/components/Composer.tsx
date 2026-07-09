import type { ChangeEvent, KeyboardEvent } from "react";
import { ImagePlus, Loader2, Mic, SendHorizontal, Square, X } from "lucide-react";
import type { ImageDraft } from "../types";

type ComposerProps = {
  value: string;
  imageDraft: ImageDraft | null;
  busy: boolean;
  recorderState: "idle" | "recording" | "transcribing" | "error";
  statusMessage: string | null;
  onChange: (value: string) => void;
  onImageChange: (file: File) => void;
  onImageRemove: () => void;
  onSubmit: () => void;
  onVoiceToggle: () => void;
};

export function Composer({
  value,
  imageDraft,
  busy,
  recorderState,
  statusMessage,
  onChange,
  onImageChange,
  onImageRemove,
  onSubmit,
  onVoiceToggle
}: ComposerProps) {
  const voiceBusy = recorderState === "transcribing";
  const canSubmit = !busy && (!!value.trim() || !!imageDraft);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      onImageChange(file);
    }
    event.target.value = "";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) {
        onSubmit();
      }
    }
  }

  return (
    <footer className="composer-shell">
      {imageDraft ? (
        <div className="image-draft">
          <img src={imageDraft.previewUrl} alt="待发送图像预览" />
          <div>
            <strong>{imageDraft.file.name}</strong>
            <span>{Math.max(1, Math.round(imageDraft.file.size / 1024))} KB</span>
          </div>
          <button type="button" onClick={onImageRemove} aria-label="移除图像">
            <X size={18} />
          </button>
        </div>
      ) : null}

      <div className="composer">
        <label className="icon-button file-button" aria-label="上传医学图像">
          <ImagePlus size={20} />
          <input
            type="file"
            accept="image/png,image/jpeg,image/jpg"
            onChange={handleFileChange}
            disabled={busy}
            aria-label="上传医学图像"
          />
        </label>

        <button
          className={`icon-button voice-button voice-button--${recorderState}`}
          type="button"
          onClick={onVoiceToggle}
          disabled={busy || voiceBusy}
          aria-label={recorderState === "recording" ? "停止录音" : "录音输入"}
        >
          {voiceBusy ? <Loader2 className="spin" size={20} /> : recorderState === "recording" ? <Square size={18} /> : <Mic size={20} />}
        </button>

        <label className="sr-only" htmlFor="medical-message">
          输入医疗问题
        </label>
        <textarea
          id="medical-message"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
          rows={1}
          placeholder="输入医疗问题，或结合上传图像描述你想确认的内容..."
        />

        <button
          className="send-button"
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          aria-label="发送消息"
        >
          {busy ? <Loader2 className="spin" size={20} /> : <SendHorizontal size={20} />}
        </button>
      </div>

      {statusMessage ? <div className="inline-status" role="status">{statusMessage}</div> : null}
    </footer>
  );
}
