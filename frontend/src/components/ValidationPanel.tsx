import { CheckCircle2, Loader2, XCircle } from "lucide-react";
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
      <div>
        <p className="validation-title">需要人工验证</p>
        <p className="validation-copy">确认当前影像分析是否可接受，或补充备注后提交复核。</p>
      </div>
      <div className="validation-actions">
        <button
          type="button"
          className="confirm-action"
          onClick={() => void handleSubmit("yes")}
          disabled={pendingChoice !== null}
          aria-label="同意当前分析结果"
        >
          {pendingChoice === "yes" ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          <span>同意结果</span>
        </button>
        <button
          type="button"
          className="reject-action"
          onClick={() => void handleSubmit("no")}
          disabled={pendingChoice !== null}
          aria-label="提交复核请求"
        >
          {pendingChoice === "no" ? <Loader2 className="spin" size={16} /> : <XCircle size={16} />}
          <span>需要复核</span>
        </button>
      </div>
      <label className="field-label" htmlFor="validation-comments">
        备注
      </label>
      <textarea
        id="validation-comments"
        className="validation-comments"
        value={comments}
        onChange={(event) => setComments(event.target.value)}
        rows={3}
        placeholder="补充怀疑误判的区域、病史信息或复查原因。"
      />
    </section>
  );
}
