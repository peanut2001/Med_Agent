import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, Loader2, UserRound } from "lucide-react";
import type { ChatMessage } from "../types";
import { AudioReplyButton } from "./AudioReplyButton";
import { ValidationPanel } from "./ValidationPanel";

type MessageListProps = {
  messages: ChatMessage[];
  onValidate: (validation: "yes" | "no", comments: string) => Promise<void>;
};

export function MessageList({ messages, onValidate }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="welcome-state">
        <div className="welcome-kicker">系统就绪</div>
        <h2>从一个问题、一张影像或一段语音开始。</h2>
        <p>
          海豚医疗智能助手会在医疗问答、RAG 检索、网络搜索和影像分析智能体之间协同处理，并在需要时进入人工复核。
        </p>
        <div className="welcome-grid">
          <span>医疗问答</span>
          <span>影像分析</span>
          <span>语音转写</span>
          <span>人工复核</span>
        </div>
      </div>
    );
  }

  return (
    <div className="message-stack">
      {messages.map((message) => (
        <article key={message.id} className={`message message--${message.role}`}>
          <div className="message-meta">
            <span className="message-avatar" aria-hidden="true">
              {message.role === "user" ? <UserRound size={16} /> : <Bot size={16} />}
            </span>
            <span className="agent-label">{message.agent || (message.role === "user" ? "用户输入" : "系统")}</span>
            {message.statusLabel ? <span className="status-label">{message.statusLabel}</span> : null}
          </div>

          <div className="message-surface">
            {message.statusLabel === "分析中" ? (
              <div className="thinking-row">
                <Loader2 className="spin" size={18} />
                <span>{message.content}</span>
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
                    <figcaption>分割结果</figcaption>
                  </figure>
                ) : null}
              </div>
            ) : message.resultImage ? (
              <div className="message-image-wrap">
                <img src={message.resultImage} alt="分析结果图像" />
              </div>
            ) : null}

            {message.role === "assistant" && message.statusLabel !== "分析中" ? (
              <div className="message-actions">
                <AudioReplyButton text={message.content} />
              </div>
            ) : null}

            {message.requiresValidation ? <ValidationPanel onSubmit={onValidate} /> : null}
          </div>
        </article>
      ))}
    </div>
  );
}
