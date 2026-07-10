import { CheckCircle2, ClipboardCheck, Loader2, XCircle } from "lucide-react";
import { useState } from "react";

type ValidationPanelProps = {
  onSubmit: (validation: "yes" | "no", comments: string) => Promise<void>;
};

export function ValidationPanel({ onSubmit }: ValidationPanelProps) {
  const [comments, setComments] = useState("");
  const [pendingChoice, setPendingChoice] = useState<"yes" | "no" | null>(null);

  async function handleSubmit(validation: "yes" | "no") {
    setPendingChoice(validation);
    try {
      await onSubmit(validation, comments.trim());
      setComments("");
    } finally {
      setPendingChoice(null);
    }
  }

  return (
    <section className="validation-panel" aria-label="人工验证">
      <div className="validation-heading">
        <span className="validation-icon" aria-hidden="true"><ClipboardCheck size={19} /></span>
        <div>
          <p className="validation-title">此结果需要人工确认</p>
          <p className="validation-copy">请确认当前影像分析是否可接受，或填写备注后提交复核。</p>
        </div>
      </div>

      <label className="field-label" htmlFor="validation-comments">复核备注 <span>选填</span></label>
      <textarea
        id="validation-comments"
        className="validation-comments"
        value={comments}
        onChange={(event) => setComments(event.target.value)}
        rows={3}
        placeholder="例如：怀疑误判的区域、相关病史或建议复查的原因…"
      />

      <div className="validation-actions">
        <button
          type="button"
          className="confirm-action"
          onClick={() => void handleSubmit("yes")}
          disabled={pendingChoice !== null}
          aria-label="确认当前分析结果"
        >
          {pendingChoice === "yes" ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          <span>确认结果</span>
        </button>
        <button
          type="button"
          className="reject-action"
          onClick={() => void handleSubmit("no")}
          disabled={pendingChoice !== null}
          aria-label="提交人工复核请求"
        >
          {pendingChoice === "no" ? <Loader2 className="spin" size={16} /> : <XCircle size={16} />}
          <span>需要复核</span>
        </button>
      </div>
    </section>
  );
}
