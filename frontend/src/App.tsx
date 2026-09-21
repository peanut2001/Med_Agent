import { useEffect, useMemo, useRef, useState } from "react";
import { createExecutionTrace, getCurrentUser, getExecutionTrace, loginLocal, registerLocal, logoutLocal, sendChat, uploadImage, validateMedicalOutput } from "./api/client";
import { AuthScreen, AuthSplash } from "./components/AuthScreen";
import { ChatPanel } from "./components/ChatPanel";
import { ExecutionInspector } from "./components/ExecutionInspector";
import { Sidebar } from "./components/Sidebar";
import { useSpeechRecorder } from "./hooks/useSpeechRecorder";
import type { AgentResponse, ChatMessage, ExecutionTrace, ImageDraft, TraceRun } from "./types";

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

function createStoppedMessage(): ChatMessage {
  return {
    id: createId("stopped"),
    role: "system",
    agent: "系统",
    statusLabel: "已暂停",
    content: "已停止等待本次回答，你可以修改内容后重新发送。"
  };
}

// 中断原因：新建会话时静默丢弃请求，不再向已清空的消息流追加提示。
const RESET_REASON = "conversation-reset";

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [imageDraft, setImageDraft] = useState<ImageDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [authChecked, setAuthChecked] = useState(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [traceRuns, setTraceRuns] = useState<TraceRun[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  // 窄屏下两侧改为抽屉，默认收起，避免一进来就盖住会话区。
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 1040);
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth > 1180);
  const objectUrlsRef = useRef<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);

  function upsertTrace(trace: ExecutionTrace, queryLabel?: string) {
    setTraceRuns((current) => {
      const existing = current.find((item) => item.trace_id === trace.trace_id);
      const next: TraceRun = {
        ...trace,
        queryLabel: queryLabel || existing?.queryLabel || "本次智能体调用"
      };
      return existing
        ? current.map((item) => item.trace_id === trace.trace_id ? next : item)
        : [...current, next];
    });
  }

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
    void getCurrentUser()
      .then((data) => setCurrentUser(data.user_id))
      .catch(() => setCurrentUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current.clear();
    };
  }, []);

  async function handleAuth(mode: "login" | "register", username: string, password: string) {
    const data = mode === "register"
      ? await registerLocal(username, password)
      : await loginLocal(username, password);
    setCurrentUser(data.user_id);
  }

  async function handleLogout() {
    abortRef.current?.abort(RESET_REASON);
    await logoutLocal();
    setCurrentUser(null);
    setConversationId(undefined);
    setMessages([]);
    setTraceRuns([]);
    setSelectedTraceId(null);
  }

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

  function handleNewConversation() {
    abortRef.current?.abort(RESET_REASON);
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current.clear();
    setImageDraft(null);
    setInputValue("");
    setMessages([]);
    setTraceRuns([]);
    setSelectedTraceId(null);
    setConversationId(undefined);
    setStatusMessage(null);
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  async function handleSubmit() {
    const messageText = inputValue.trim();
    const draft = imageDraft;

    if (busy || (!messageText && !draft)) {
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

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

    let traceId: string | null = null;
    let polling = false;
    let pollingPromise: Promise<void> | null = null;
    const queryLabel = messageText || "上传影像并开始分析";

    try {
      const initialTrace = await createExecutionTrace(conversationId, controller.signal);
      traceId = initialTrace.trace_id;
      const requestConversationId = initialTrace.conversation_id;
      setConversationId(requestConversationId);
      setSelectedTraceId(traceId);
      upsertTrace(initialTrace, queryLabel);

      polling = true;
      pollingPromise = (async () => {
        while (polling) {
          await new Promise((resolve) => window.setTimeout(resolve, 300));
          if (!polling || !traceId || controller.signal.aborted) break;
          try {
            const liveTrace = await getExecutionTrace(traceId, controller.signal);
            upsertTrace(liveTrace, queryLabel);
            if (liveTrace.status === "completed" || liveTrace.status === "failed") break;
          } catch {
            break;
          }
        }
      })();

      const data = draft
        ? await uploadImage(messageText, draft.file, requestConversationId, traceId, controller.signal)
        : await sendChat(messageText, requestConversationId, traceId, controller.signal);
      if (data.conversation_id) setConversationId(data.conversation_id);
      if (data.execution_trace) upsertTrace(data.execution_trace, queryLabel);
      const assistantMessage = createAssistantMessage(data, draft?.previewUrl || null);

      setMessages((current) => current.filter((item) => item.id !== "thinking").concat(assistantMessage));
      setImageDraft(null);
    } catch (error) {
      if (controller.signal.aborted) {
        const silent = controller.signal.reason === RESET_REASON;
        setMessages((current) => {
          const remaining = current.filter((item) => item.id !== "thinking");
          return silent ? remaining : remaining.concat(createStoppedMessage());
        });
        if (!silent) {
          // 输入框为空时把原问题放回去，避免用户重打；已写新内容则保留新内容。
          setInputValue((current) => current || messageText);
          setStatusMessage("已暂停等待，可修改后重新发送。");
          window.setTimeout(() => setStatusMessage(null), 3000);
        }
        return;
      }
      console.error("Request failed:", error);
      if (traceId) {
        try {
          upsertTrace(await getExecutionTrace(traceId), queryLabel);
        } catch {
          // Keep the last successfully polled snapshot.
        }
      }
      const message = error instanceof Error ? error.message : "抱歉，处理您的请求时出错，请重试。";
      setMessages((current) => current.filter((item) => item.id !== "thinking").concat(createSystemMessage(message)));
    } finally {
      polling = false;
      if (pollingPromise) await pollingPromise;
      if (abortRef.current === controller) abortRef.current = null;
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

  if (!authChecked) {
    return <AuthSplash />;
  }

  if (!currentUser) {
    return <AuthScreen onSubmit={handleAuth} />;
  }

  const shellClassName = [
    "app-shell",
    sidebarOpen ? "" : "app-shell--sidebar-collapsed",
    inspectorOpen ? "" : "app-shell--inspector-collapsed"
  ].filter(Boolean).join(" ");

  return (
    <div className={shellClassName}>
      <Sidebar onNewConversation={handleNewConversation} onLogout={() => void handleLogout()} currentUser={currentUser} />
      <button
        type="button"
        className="drawer-scrim"
        aria-label="关闭侧栏"
        onClick={() => {
          setSidebarOpen(false);
          setInspectorOpen(false);
        }}
      />
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
        onStop={handleStop}
        onVoiceToggle={recorder.toggleRecording}
        onValidate={handleValidation}
        sidebarOpen={sidebarOpen}
        inspectorOpen={inspectorOpen}
        onToggleSidebar={() => setSidebarOpen((current) => !current)}
        onToggleInspector={() => setInspectorOpen((current) => !current)}
      />
      <ExecutionInspector
        traces={traceRuns}
        selectedTraceId={selectedTraceId}
        busy={busy}
        conversationId={conversationId}
        onSelect={setSelectedTraceId}
      />
    </div>
  );
}
