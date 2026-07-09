export type AgentResponse = {
  status?: string;
  response?: string;
  agent?: string;
  result_image?: string;
  detail?: string;
  error?: string;
};

export type ValidationResponse = {
  status?: string;
  comments?: string;
  message?: string;
  response?: string;
  detail?: string;
  error?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  agent?: string;
  statusLabel?: string;
  content: string;
  imagePreview?: string | null;
  resultImage?: string | null;
  requiresValidation?: boolean;
};

export type ImageDraft = {
  file: File;
  previewUrl: string;
};
