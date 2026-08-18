import { useEffect, useMemo, useRef, useState } from "react";
import { sendChat, uploadImage, validateMedicalOutput } from "./api/client";
import { ChatPanel } from "./components/ChatPanel";
import { Sidebar } from "./components/Sidebar";
import { useSpeechRecorder } from "./hooks/useSpeechRecorder";
import type { AgentResponse, ChatMessage, ImageDraft } from "./types";

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function needsHumanValidation(data: AgentResponse) {
  return Boolean(data.agent?.includes("HUMAN_VALIDATION"));
}

function createAssistantMessage(data: AgentResponse, imagePreview?: string | null): ChatMessage {
  return {
    id: createId("assistant"),
    role: "assistant",
    agent: data.agent || "系统",
    statusLabel: "已返回",
    content: data.response || "",
    imagePreview: data.result_image && data.agent === "SKIN_LESION_AGENT, HUMAN_VALIDATION" ? imagePreview : null,
    resultImage: data.result_image || null,
    requiresValidation: needsHumanValidation(data),
    validationId: data.validation_id || null
  };
}

function createSystemMessage(content: string): ChatMessage {
  return {
    id: createId("system"),
    role: "system",
    agent: "系统",
    statusLabel: "异常",
    content
  };
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [imageDraft, setImageDraft] = useState<ImageDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const objectUrlsRef = useRef<Set<string>>(new Set());

  const recorder = useSpeechRecorder({
    onTranscript: (transcript) => {
      setInputValue(transcript);
      setStatusMessage("语音已转写，可以继续编辑后发送。");
      window.setTimeout(() => setStatusMessage(null), 2600);
    },
    onError: (message) => {
      setStatusMessage(message);
      window.setTimeout(() => setStatusMessage(null), 3000);
    }
  });

  const thinkingMessage = useMemo<ChatMessage>(
    () => ({
      id: "thinking",
      role: "assistant",
      agent: "系统处理中",
      statusLabel: "分析中",
      content: "正在调度合适的医疗智能体，请稍候..."
    }),
    []
  );

  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current.clear();
    };
  }, []);

  function handleImageChange(file: File) {
    if (imageDraft?.previewUrl) {
      URL.revokeObjectURL(imageDraft.previewUrl);
      objectUrlsRef.current.delete(imageDraft.previewUrl);
    }
    const previewUrl = URL.createObjectURL(file);
    objectUrlsRef.current.add(previewUrl);
    setImageDraft({
      file,
      previewUrl
    });
  }

  function handleImageRemove() {
    if (imageDraft?.previewUrl) {
      URL.revokeObjectURL(imageDraft.previewUrl);
      objectUrlsRef.current.delete(imageDraft.previewUrl);
    }
    setImageDraft(null);
  }

  function handleClear() {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current.clear();
    setImageDraft(null);
    setInputValue("");
    setMessages([]);
    setStatusMessage(null);
  }

  async function handleSubmit() {
    const messageText = inputValue.trim();
    const draft = imageDraft;

    if (busy || (!messageText && !draft)) {
      return;
    }

    const userMessage: ChatMessage = {
      id: createId("user"),
      role: "user",
      agent: "用户输入",
      content: messageText || "已上传 1 张待分析图像，请系统直接开始识别。",
      imagePreview: draft?.previewUrl || null
    };

    setMessages((current) => [...current, userMessage, thinkingMessage]);
    setInputValue("");
    setBusy(true);

    try {
      const data = draft
        ? await uploadImage(messageText, draft.file, conversationId)
        : await sendChat(messageText, conversationId);
      if (data.conversation_id) setConversationId(data.conversation_id);
      const assistantMessage = createAssistantMessage(data, draft?.previewUrl || null);

      setMessages((current) => current.filter((item) => item.id !== "thinking").concat(assistantMessage));
      setImageDraft(null);
    } catch (error) {
      console.error("Request failed:", error);
      const message = error instanceof Error ? error.message : "抱歉，处理您的请求时出错，请重试。";
      setMessages((current) => current.filter((item) => item.id !== "thinking").concat(createSystemMessage(message)));
    } finally {
      setBusy(false);
    }
  }

  async function handleValidation(validation: "yes" | "no", comments: string) {
    const waitingMessage: ChatMessage = {
      id: createId("validation"),
      role: "assistant",
      agent: "系统处理中",
      statusLabel: "复核中",
      content: "正在提交人工验证结果，请稍候..."
    };

    setMessages((current) => [...current, waitingMessage]);

    try {
      const source = [...messages].reverse().find((item) => item.requiresValidation);
      if (!source) throw new Error("找不到待审核的诊断结果，请刷新后重试。");
      const validationId = source.validationId;
      if (!validationId) throw new Error("审核请求已失效，请重新上传图像。");
      const result = await validateMedicalOutput(validation, comments, validationId, conversationId);
      const content = [result.message, result.response].filter(Boolean).join("\n\n");
      const validationMessage: ChatMessage = {
        id: createId("validated"),
        role: "assistant",
        agent: "HUMAN_VALIDATED",
        statusLabel: validation === "yes" ? "已确认" : "需复查",
        content
      };

      setMessages((current) => current
        .filter((item) => item.id !== waitingMessage.id)
        .map((item) => item.validationId === validationId ? { ...item, requiresValidation: false } : item)
        .concat(validationMessage));
    } catch (error) {
      console.error("Validation submission failed:", error);
      const message = error instanceof Error ? error.message : "验证提交失败，请重试。";
      setMessages((current) => current.filter((item) => item.id !== waitingMessage.id).concat(createSystemMessage(message)));
    }
  }

  return (
    <div className="app-shell">
      <Sidebar onClear={handleClear} />
      <ChatPanel
        messages={messages}
        inputValue={inputValue}
        imageDraft={imageDraft}
        busy={busy}
        recorderState={recorder.state}
        statusMessage={statusMessage}
        onInputChange={setInputValue}
        onImageChange={handleImageChange}
        onImageRemove={handleImageRemove}
        onSubmit={() => void handleSubmit()}
        onVoiceToggle={recorder.toggleRecording}
        onValidate={handleValidation}
      />
    </div>
  );
}
