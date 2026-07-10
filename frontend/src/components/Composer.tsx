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

const recorderCopy = {
  idle: "语音输入",
  recording: "停止录音",
  transcribing: "正在转写",
  error: "重试录音"
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
    if (file) onImageChange(file);
    event.target.value = "";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) onSubmit();
    }
  }

  return (
    <footer className="composer-shell">
      {imageDraft ? (
        <div className="image-draft">
          <img src={imageDraft.previewUrl} alt="待发送图像预览" />
          <div className="image-draft__copy">
            <span className="image-draft__label">待分析图像</span>
            <strong>{imageDraft.file.name}</strong>
            <small>{Math.max(1, Math.round(imageDraft.file.size / 1024))} KB</small>
          </div>
          <button type="button" onClick={onImageRemove} aria-label="移除待发送图像">
            <X size={18} />
          </button>
        </div>
      ) : null}

      <div className="composer">
        <label className="icon-button file-button" aria-label="上传医学图像" title="上传医学图像">
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
          aria-label={recorderCopy[recorderState]}
          title={recorderCopy[recorderState]}
        >
          {voiceBusy ? <Loader2 className="spin" size={20} /> : recorderState === "recording" ? <Square size={17} /> : <Mic size={20} />}
        </button>

        <div className="composer-input-wrap">
          <label className="sr-only" htmlFor="medical-message">输入医疗问题</label>
          <textarea
            id="medical-message"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={busy}
            rows={1}
            placeholder="描述你的症状、检查结果，或结合影像提出问题…"
            aria-describedby="composer-shortcut"
          />
          <span id="composer-shortcut" className="keyboard-hint">Enter 发送 · Shift + Enter 换行</span>
        </div>

        <button
          className="send-button"
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          aria-label={busy ? "正在发送" : "发送消息"}
          title="发送消息"
        >
          {busy ? <Loader2 className="spin" size={20} /> : <SendHorizontal size={20} />}
        </button>
      </div>

      {recorderState === "recording" ? (
        <div className="recording-status" role="status">
          <span className="recording-pulse" aria-hidden="true" />
          正在录音，再次点击麦克风结束
        </div>
      ) : null}
      {statusMessage ? <div className="inline-status" role="status">{statusMessage}</div> : null}
    </footer>
  );
}
