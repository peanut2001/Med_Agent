import type { AgentResponse, ValidationResponse } from "../types";

const DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM";

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T;

  if (!response.ok) {
    const errorData = data as { detail?: string; response?: string; error?: string };
    throw new Error(errorData.detail || errorData.response || errorData.error || "请求失败，请稍后重试。");
  }

  return data;
}

export async function sendChat(query: string, conversationId?: string): Promise<AgentResponse> {
  const response = await fetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      query,
      conversation_history: [],
      conversation_id: conversationId
    }),
    credentials: "include"
  });

  return readJson<AgentResponse>(response);
}

export async function uploadImage(text: string, image: File, conversationId?: string): Promise<AgentResponse> {
  const formData = new FormData();
  formData.append("text", text);
  formData.append("image", image);
  if (conversationId) formData.append("conversation_id", conversationId);

  const response = await fetch("/upload", {
    method: "POST",
    body: formData,
    credentials: "include"
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
