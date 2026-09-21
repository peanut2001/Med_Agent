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
  execution_trace?: ExecutionTrace;
};

export type TraceNodeStatus = "running" | "completed" | "failed" | "cancelled";

export type TraceNode = {
  event_id: string;
  node_id: string;
  label: string;
  status: TraceNodeStatus;
  started_at: string;
  duration_ms: number | null;
  metadata: Record<string, string | number | boolean>;
};

export type ExecutionTrace = {
  trace_id: string;
  conversation_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  total_duration_ms: number | null;
  cancel_requested: boolean;
  nodes: TraceNode[];
};

export type TraceRun = ExecutionTrace & {
  queryLabel: string;
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
  /** 历史回放时为真：这条消息原本带图，但上传的原图不做持久化。 */
  imageOmitted?: boolean;
  requiresValidation?: boolean;
  validationId?: string | null;
};

export type ImageDraft = {
  file: File;
  previewUrl: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
};

/** 后端持久化的历史消息，字段与 conversation_store 表保持一致。 */
export type StoredMessage = {
  message_id: number;
  role: "user" | "assistant" | "system";
  agent: string | null;
  status_label: string | null;
  content: string;
  result_image: string | null;
  has_image: boolean;
  created_at: number;
};
