import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelExecutionTrace,
  createExecutionTrace,
  deleteConversation,
  getConversationMessages,
  getCurrentUser,
  getExecutionTrace,
  listConversations,
  loginLocal,
  registerLocal,
  logoutLocal,
  renameConversation,
  sendChat,
  SERVICE_UNAVAILABLE,
  uploadImage,
  validateMedicalOutput
} from "./api/client";
import { AuthScreen, AuthSplash } from "./components/AuthScreen";
import { ChatPanel } from "./components/ChatPanel";
import { ExecutionInspector } from "./components/ExecutionInspector";
import { Sidebar } from "./components/Sidebar";
import { useSpeechRecorder } from "./hooks/useSpeechRecorder";
import type {
  AgentResponse,
  ChatMessage,
  ConversationSummary,
  ExecutionTrace,
  ImageDraft,
  StoredMessage,
  TraceRun
} from "./types";

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

// 历史记录只保存文本与结果图路径：上传的原图是临时文件，不回放。
// 复核按钮也不还原，审核状态存在服务端内存里，重放会得到失效的请求。
function toChatMessage(stored: StoredMessage): ChatMessage {
  return {
    id: `stored-${stored.message_id}`,
    role: stored.role,
    agent: stored.agent || undefined,
    statusLabel: stored.status_label || undefined,
    content: stored.content,
    resultImage: stored.result_image,
    imageOmitted: stored.has_image,
    requiresValidation: false
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
  const [bootstrapNotice, setBootstrapNotice] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [traceRuns, setTraceRuns] = useState<TraceRun[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  // 窄屏下两侧改为抽屉，默认收起，避免一进来就盖住会话区。
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 1040);
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth > 1180);
  const objectUrlsRef = useRef<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const activeTraceRef = useRef<string | null>(null);

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

  // 只 abort 本地 fetch 的话服务端会把整张图跑完，所以暂停必须先落到服务端。
  function abortRun(reason?: string) {
    const traceId = activeTraceRef.current;
    if (traceId) {
      activeTraceRef.current = null;
      cancelExecutionTrace(traceId).catch(() => undefined);
    }
    abortRef.current?.abort(reason);
  }

  // 服务端要跑完当前节点才落终态，补拉到终态为止再定格面板。
  async function settleTrace(traceId: string, queryLabel: string) {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      try {
        const trace = await getExecutionTrace(traceId);
        upsertTrace(trace, queryLabel);
        if (trace.status !== "running" && trace.status !== "queued") return;
      } catch {
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
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
      .then((data) => {
        setCurrentUser(data.user_id);
        setBootstrapNotice(null);
      })
      .catch((error: unknown) => {
        setCurrentUser(null);
        // 未登录是正常路径，只有真的连不上服务才需要在登录页解释一句。
        if (error instanceof Error && error.name === SERVICE_UNAVAILABLE) {
          setBootstrapNotice(error.message);
        }
      })
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!currentUser) {
      setConversations([]);
      return;
    }
    setHistoryLoading(true);
    void listConversations()
      .then(setConversations)
      .catch((error) => console.error("Failed to load conversations:", error))
      .finally(() => setHistoryLoading(false));
  }, [currentUser]);

  // 回答落库后标题与排序才是新的，所以每轮结束都重新拉一次列表。
  function refreshConversations() {
    void listConversations()
      .then(setConversations)
      .catch((error) => console.error("Failed to refresh conversations:", error));
  }

  function flashStatus(message: string) {
    setStatusMessage(message);
    window.setTimeout(() => setStatusMessage(null), 3000);
  }

  async function handleSelectConversation(conversationIdToOpen: string) {
    if (conversationIdToOpen === conversationId) return;

    abortRun(RESET_REASON);
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current.clear();
    setImageDraft(null);
    setInputValue("");
    // 执行轨迹只存在服务端内存中，历史会话没有可回放的调用链。
    setTraceRuns([]);
    setSelectedTraceId(null);
    setMessages([]);
    setConversationId(conversationIdToOpen);
    if (window.innerWidth <= 1040) setSidebarOpen(false);

    try {
      const stored = await getConversationMessages(conversationIdToOpen);
      setMessages(stored.map(toChatMessage));
    } catch (error) {
      console.error("Failed to open conversation:", error);
      setMessages([createSystemMessage("载入历史对话失败，请稍后重试。")]);
    }
  }

  async function handleRenameConversation(targetId: string, title: string) {
    const snapshot = conversations;
    setConversations((current) => current.map(
      (item) => item.conversation_id === targetId ? { ...item, title } : item
    ));
    try {
      await renameConversation(targetId, title);
    } catch (error) {
      console.error("Failed to rename conversation:", error);
      setConversations(snapshot);
      flashStatus("重命名失败，请稍后重试。");
    }
  }

  async function handleDeleteConversation(targetId: string) {
    try {
      await deleteConversation(targetId);
    } catch (error) {
      console.error("Failed to delete conversation:", error);
      flashStatus("删除失败，请稍后重试。");
      return;
    }
    setConversations((current) => current.filter((item) => item.conversation_id !== targetId));
    if (targetId === conversationId) handleNewConversation();
  }

  async function handleAuth(mode: "login" | "register", username: string, password: string) {
    const data = mode === "register"
      ? await registerLocal(username, password)
      : await loginLocal(username, password);
    setCurrentUser(data.user_id);
  }

  async function handleLogout() {
    abortRun(RESET_REASON);
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
    abortRun(RESET_REASON);
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
    abortRun();
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
      activeTraceRef.current = traceId;
      const requestConversationId = initialTrace.conversation_id;
      setConversationId(requestConversationId);
      setSelectedTraceId(traceId);
      upsertTrace(initialTrace, queryLabel);

      polling = true;
      pollingPromise = (async () => {
        let consecutiveErrors = 0;
        while (polling) {
          await new Promise((resolve) => window.setTimeout(resolve, 300));
          if (!polling || !traceId || controller.signal.aborted) break;
          try {
            const liveTrace = await getExecutionTrace(traceId, controller.signal);
            upsertTrace(liveTrace, queryLabel);
            consecutiveErrors = 0;
            if (liveTrace.status !== "queued" && liveTrace.status !== "running") break;
          } catch {
            // 一次网络抖动不该让面板永远停在「执行中」，连续失败才放弃轮询。
            consecutiveErrors += 1;
            if (consecutiveErrors >= 3) break;
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
      refreshConversations();
    } catch (error) {
      if (controller.signal.aborted) {
        const silent = controller.signal.reason === RESET_REASON;
        setMessages((current) => {
          const remaining = current.filter((item) => item.id !== "thinking");
          return silent ? remaining : remaining.concat(createStoppedMessage());
        });
        // 取消已经发给服务端，这里把它收尾后的真实停点补回面板。
        if (!silent && traceId) void settleTrace(traceId, queryLabel);
        if (!silent) {
          // 输入框为空时把原问题放回去，避免用户重打；已写新内容则保留新内容。
          // 停止本身已经由会话里的那条提示说明，这里不再弹状态条。
          setInputValue((current) => current || messageText);
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
      if (activeTraceRef.current === traceId) activeTraceRef.current = null;
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
      refreshConversations();
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
    return <AuthScreen onSubmit={handleAuth} notice={bootstrapNotice} />;
  }

  const shellClassName = [
    "app-shell",
    sidebarOpen ? "" : "app-shell--sidebar-collapsed",
    inspectorOpen ? "" : "app-shell--inspector-collapsed"
  ].filter(Boolean).join(" ");

  return (
    <div className={shellClassName}>
      <div className="side-slot sidebar-slot">
        <Sidebar
          onNewConversation={handleNewConversation}
          onLogout={() => void handleLogout()}
          currentUser={currentUser}
          conversations={conversations}
          activeConversationId={conversationId}
          historyLoading={historyLoading}
          onSelectConversation={(id) => void handleSelectConversation(id)}
          onRenameConversation={(id, title) => void handleRenameConversation(id, title)}
          onDeleteConversation={(id) => void handleDeleteConversation(id)}
        />
      </div>
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
      <div className="side-slot inspector-slot">
        <ExecutionInspector
          traces={traceRuns}
          selectedTraceId={selectedTraceId}
          busy={busy}
          conversationId={conversationId}
          onSelect={setSelectedTraceId}
        />
      </div>
    </div>
  );
}
