import type { AgentResponse, ConversationSummary, ExecutionTrace, StoredMessage, ValidationResponse } from "../types";

const DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM";

/** 服务连不上时错误的 name，调用方据此区分"没登录"和"没连上"。 */
export const SERVICE_UNAVAILABLE = "ServiceUnavailableError";

// 认证类请求都是短请求，必须有超时：后端或 dev server 挂掉时 fetch 会一直悬着，
// 既不 resolve 也不 reject，页面就永远停在"正在校验会话凭证"。
const AUTH_TIMEOUT_MS = 8000;

function serviceUnavailable(message: string): Error {
  const error = new Error(message);
  error.name = SERVICE_UNAVAILABLE;
  return error;
}

async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(path, {
      ...init,
      credentials: "include",
      signal: AbortSignal.timeout(AUTH_TIMEOUT_MS)
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw serviceUnavailable("连接服务超时，请确认后端服务已启动。");
    }
    throw serviceUnavailable("无法连接服务，请确认后端服务已启动。");
  }
}

async function readJson<T>(response: Response): Promise<T> {
  let data: T;
  try {
    data = (await response.json()) as T;
  } catch {
    // 后端没起时 Vite 代理回的是 HTML/纯文本，直接 json() 会抛出难懂的解析错误。
    throw serviceUnavailable(`服务返回了非预期的响应（HTTP ${response.status}），请确认后端服务状态。`);
  }

  if (!response.ok) {
    const errorData = data as { detail?: string; response?: string; error?: string };
    throw new Error(errorData.detail || errorData.response || errorData.error || "请求失败，请稍后重试。");
  }

  return data;
}

export async function getCurrentUser(): Promise<{ authenticated: boolean; user_id: string }> {
  const response = await authFetch("/auth/me");
  return readJson<{ authenticated: boolean; user_id: string }>(response);
}

export async function loginLocal(username: string, password: string): Promise<{ authenticated: boolean; user_id: string }> {
  const response = await authFetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  return readJson<{ authenticated: boolean; user_id: string }>(response);
}

export async function registerLocal(username: string, password: string): Promise<{ authenticated: boolean; user_id: string }> {
  const response = await authFetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  return readJson<{ authenticated: boolean; user_id: string }>(response);
}

export async function logoutLocal(): Promise<void> {
  await fetch("/auth/logout", { method: "POST", credentials: "include" });
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  const response = await fetch("/conversations", { credentials: "include", signal });
  const data = await readJson<{ conversations: ConversationSummary[] }>(response);
  return data.conversations || [];
}

export async function getConversationMessages(
  conversationId: string,
  signal?: AbortSignal
): Promise<StoredMessage[]> {
  const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    credentials: "include",
    signal
  });
  const data = await readJson<{ messages: StoredMessage[] }>(response);
  return data.messages || [];
}

export async function renameConversation(conversationId: string, title: string): Promise<{ title: string }> {
  const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ title })
  });
  return readJson<{ title: string }>(response);
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    credentials: "include"
  });
  await readJson<{ status: string }>(response);
}

export async function createExecutionTrace(conversationId?: string, signal?: AbortSignal): Promise<ExecutionTrace> {
  const response = await fetch("/traces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ conversation_id: conversationId }),
    signal
  });
  return readJson<ExecutionTrace>(response);
}

export async function getExecutionTrace(traceId: string, signal?: AbortSignal): Promise<ExecutionTrace> {
  const response = await fetch(`/traces/${encodeURIComponent(traceId)}`, {
    credentials: "include",
    signal
  });
  return readJson<ExecutionTrace>(response);
}

export async function cancelExecutionTrace(traceId: string): Promise<ExecutionTrace> {
  // Deliberately un-signalled: this is the request that tells the server to
  // stop, so it must survive the AbortController that stops everything else.
  const response = await fetch(`/traces/${encodeURIComponent(traceId)}/cancel`, {
    method: "POST",
    credentials: "include"
  });
  return readJson<ExecutionTrace>(response);
}

export async function sendChat(
  query: string,
  conversationId?: string,
  traceId?: string,
  signal?: AbortSignal
): Promise<AgentResponse> {
  const response = await fetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      query,
      conversation_history: [],
      conversation_id: conversationId,
      trace_id: traceId
    }),
    credentials: "include",
    signal
  });

  return readJson<AgentResponse>(response);
}

export async function uploadImage(
  text: string,
  image: File,
  conversationId?: string,
  traceId?: string,
  signal?: AbortSignal
): Promise<AgentResponse> {
  const formData = new FormData();
  formData.append("text", text);
  formData.append("image", image);
  if (conversationId) formData.append("conversation_id", conversationId);
  if (traceId) formData.append("trace_id", traceId);

  const response = await fetch("/upload", {
    method: "POST",
    body: formData,
    credentials: "include",
    signal
  });

  return readJson<AgentResponse>(response);
}

export async function validateMedicalOutput(
  validationResult: "yes" | "no",
  comments: string,
  validationId: string,
  conversationId?: string
): Promise<ValidationResponse> {
  const formData = new FormData();
  formData.append("validation_result", validationResult);
  formData.append("comments", comments);
  formData.append("validation_id", validationId);
  if (conversationId) formData.append("conversation_id", conversationId);

  const response = await fetch("/validate", {
    method: "POST",
    body: formData,
    credentials: "include"
  });

  return readJson<ValidationResponse>(response);
}

export async function transcribeAudio(audioBlob: Blob): Promise<string> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.webm");

  const response = await fetch("/transcribe", {
    method: "POST",
    body: formData
  });

  const data = await readJson<{ transcript?: string; error?: string }>(response);
  if (!data.transcript) {
    throw new Error(data.error || "语音转写失败，请重试或直接输入文字。");
  }

  return data.transcript;
}

export async function generateSpeech(text: string, voiceId = DEFAULT_VOICE_ID): Promise<Blob> {
  const response = await fetch("/generate-speech", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      text,
      voice_id: voiceId
    })
  });

  if (!response.ok) {
    let message = "语音生成失败，请稍后重试。";
    try {
      const data = (await response.json()) as { error?: string; detail?: string };
      message = data.error || data.detail || message;
    } catch {
      // Keep the generic message when the server returns non-JSON.
    }
    throw new Error(message);
  }

  return response.blob();
}
