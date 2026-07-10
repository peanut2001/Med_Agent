import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  BrainCircuit,
  ImagePlus,
  Loader2,
  MessageSquareText,
  Mic,
  ShieldCheck,
  UserRound
} from "lucide-react";
import type { ChatMessage } from "../types";
import { AudioReplyButton } from "./AudioReplyButton";
import { ValidationPanel } from "./ValidationPanel";

type MessageListProps = {
  messages: ChatMessage[];
  onValidate: (validation: "yes" | "no", comments: string) => Promise<void>;
};

const starterCards = [
  {
    icon: MessageSquareText,
    title: "描述健康问题",
    description: "说明症状、持续时间和相关病史，获取结构化参考信息。"
  },
  {
    icon: ImagePlus,
    title: "上传医学影像",
    description: "支持 PNG、JPG、JPEG，可附上希望重点分析的内容。"
  },
  {
    icon: Mic,
    title: "使用语音输入",
    description: "录制问题并自动转写，转写结果仍可编辑后发送。"
  }
];

function statusClassName(status?: string) {
  if (status === "异常" || status === "需复查") return "status-label status-label--danger";
  if (status === "已确认") return "status-label status-label--success";
  if (status === "分析中" || status === "复核中") return "status-label status-label--progress";
  return "status-label";
}

export function MessageList({ messages, onValidate }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="welcome-state">
        <div className="welcome-icon" aria-hidden="true">
          <BrainCircuit size={30} />
        </div>
        <div className="welcome-kicker">智能医疗协作空间</div>
        <h2>今天想了解什么健康问题？</h2>
        <p className="welcome-lead">
          你可以输入文字、上传医学影像或使用语音。系统会自动选择合适的医疗智能体协同处理。
        </p>

        <div className="starter-grid">
          {starterCards.map(({ icon: Icon, title, description }) => (
            <article key={title} className="starter-card">
              <span className="starter-card__icon" aria-hidden="true"><Icon size={20} /></span>
              <div>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </article>
          ))}
        </div>

        <div className="welcome-trust">
          <span><ShieldCheck size={15} /> 输入输出安全护栏</span>
          <span><UserRound size={15} /> 关键结果支持人工复核</span>
        </div>
      </div>
    );
  }

  return (
    <div className="message-stack">
      {messages.map((message) => {
        const isPending = message.statusLabel === "分析中" || message.statusLabel === "复核中";
        const displayAgent = message.agent || (message.role === "user" ? "你的问题" : "医疗智能助手");

        return (
          <article key={message.id} className={`message message--${message.role}`}>
            <div className="message-meta">
              <span className="message-avatar" aria-hidden="true">
                {message.role === "user" ? <UserRound size={17} /> : <Bot size={17} />}
              </span>
              <span className="agent-label">{displayAgent}</span>
              {message.statusLabel ? <span className={statusClassName(message.statusLabel)}>{message.statusLabel}</span> : null}
            </div>

            <div className="message-surface">
              {isPending ? (
                <div className="thinking-row">
                  <Loader2 className="spin" size={18} />
                  <div>
                    <strong>{message.statusLabel === "复核中" ? "正在提交复核" : "正在分析你的问题"}</strong>
                    <span>{message.content}</span>
                  </div>
                </div>
              ) : message.role === "assistant" ? (
                <div className="markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <p>{message.content}</p>
              )}

              {message.imagePreview ? (
                <div className={message.resultImage ? "image-compare" : "message-image-wrap"}>
                  <figure>
                    <img src={message.imagePreview} alt="上传的医学图像" />
                    {message.resultImage ? <figcaption>原始图像</figcaption> : null}
                  </figure>
                  {message.resultImage ? (
                    <figure>
                      <img src={message.resultImage} alt="分析结果图像" />
                      <figcaption>分析结果</figcaption>
                    </figure>
                  ) : null}
                </div>
              ) : message.resultImage ? (
                <div className="message-image-wrap">
                  <img src={message.resultImage} alt="分析结果图像" />
                </div>
              ) : null}

              {message.role === "assistant" && !isPending ? (
                <div className="message-actions">
                  <AudioReplyButton text={message.content} />
                </div>
              ) : null}

              {message.requiresValidation ? <ValidationPanel onSubmit={onValidate} /> : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}
