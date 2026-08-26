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

export type TraceNodeStatus = "running" | "completed" | "failed";

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
  status: "queued" | "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  total_duration_ms: number | null;
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
  requiresValidation?: boolean;
  validationId?: string | null;
};

export type ImageDraft = {
  file: File;
  previewUrl: string;
};
