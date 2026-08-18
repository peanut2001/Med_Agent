export type AgentResponse = {
  status?: string;
  response?: string;
  agent?: string;
  result_image?: string;
  detail?: string;
  error?: string;
  conversation_id?: string;
  validation_id?: string | null;
  requires_validation?: boolean;
};

export type ValidationResponse = {
  status?: string;
  comments?: string;
  message?: string;
  response?: string;
  detail?: string;
  error?: string;
  conversation_id?: string;
  validation_id?: string;
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
  validationId?: string | null;
};

export type ImageDraft = {
  file: File;
  previewUrl: string;
};
