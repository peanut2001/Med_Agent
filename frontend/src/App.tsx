import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { createExecutionTrace, getCurrentUser, getExecutionTrace, loginLocal, registerLocal, logoutLocal, sendChat, uploadImage, validateMedicalOutput } from "./api/client";
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

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [imageDraft, setImageDraft] = useState<ImageDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [authChecked, setAuthChecked] = useState(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [traceRuns, setTraceRuns] = useState<TraceRun[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const objectUrlsRef = useRef<Set<string>>(new Set());

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

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError(null);
    try {
      const data = authMode === "register"
        ? await registerLocal(loginUsername.trim(), loginPassword)
        : await loginLocal(loginUsername.trim(), loginPassword);
      setCurrentUser(data.user_id);
      setLoginPassword("");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : authMode === "register" ? "注册失败，请检查输入。" : "登录失败，请检查用户名和密码。");
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleLogout() {
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

  function handleClear() {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current.clear();
    setImageDraft(null);
    setInputValue("");
    setMessages([]);
    setTraceRuns([]);
    setSelectedTraceId(null);
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

    let traceId: string | null = null;
    let polling = false;
    let pollingPromise: Promise<void> | null = null;
    const queryLabel = messageText || "上传影像并开始分析";

    try {
      const initialTrace = await createExecutionTrace(conversationId);
      traceId = initialTrace.trace_id;
      const requestConversationId = initialTrace.conversation_id;
      setConversationId(requestConversationId);
      setSelectedTraceId(traceId);
      upsertTrace(initialTrace, queryLabel);

      polling = true;
      pollingPromise = (async () => {
        while (polling) {
          await new Promise((resolve) => window.setTimeout(resolve, 300));
          if (!polling || !traceId) break;
          try {
            const liveTrace = await getExecutionTrace(traceId);
            upsertTrace(liveTrace, queryLabel);
            if (liveTrace.status === "completed" || liveTrace.status === "failed") break;
          } catch {
            break;
          }
        }
      })();

      const data = draft
        ? await uploadImage(messageText, draft.file, requestConversationId, traceId)
        : await sendChat(messageText, requestConversationId, traceId);
      if (data.conversation_id) setConversationId(data.conversation_id);
      if (data.execution_trace) upsertTrace(data.execution_trace, queryLabel);
      const assistantMessage = createAssistantMessage(data, draft?.previewUrl || null);

      setMessages((current) => current.filter((item) => item.id !== "thinking").concat(assistantMessage));
      setImageDraft(null);
    } catch (error) {
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
    return <div className="auth-screen">正在检查登录状态…</div>;
  }

  if (!currentUser) {
    return (
      <main className="auth-screen">
        <form className="auth-card" onSubmit={(event) => void handleLogin(event)}>
          <div className="welcome-kicker">MED AGENT</div>
          <h1>{authMode === "register" ? "注册医疗助手" : "登录医疗助手"}</h1>
          <p>{authMode === "register" ? "创建一个本地测试账号，注册后将自动登录。" : "请输入本地测试账号继续使用。"}</p>
          <label>
            用户名
            <input value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} autoComplete="username" required />
          </label>
          <label>
            密码
            <input type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete={authMode === "register" ? "new-password" : "current-password"} minLength={8} required />
          </label>
          {loginError && <div className="auth-error">{loginError}</div>}
          <button type="submit" disabled={loginBusy}>{loginBusy ? (authMode === "register" ? "注册中…" : "登录中…") : authMode === "register" ? "注册并登录" : "登录"}</button>
          <button type="button" className="auth-switch" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setLoginError(null); }}>
            {authMode === "register" ? "已有账号？返回登录" : "没有账号？立即注册"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar onClear={handleClear} onLogout={() => void handleLogout()} currentUser={currentUser} />
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
