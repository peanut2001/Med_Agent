import {
  Activity,
  CheckCircle2,
  CircleDashed,
  Clock3,
  GitBranch,
  Route,
  ShieldCheck,
  XCircle
} from "lucide-react";
import type { TraceNode, TraceRun } from "../types";

type ExecutionInspectorProps = {
  traces: TraceRun[];
  selectedTraceId: string | null;
  busy: boolean;
  conversationId?: string;
  onSelect: (traceId: string) => void;
};

const statusCopy = {
  queued: "排队中",
  running: "执行中",
  completed: "已完成",
  failed: "失败"
} as const;

function formatDuration(value: number | null) {
  if (value === null) return "运行中";
  if (value < 1) return "<1 ms";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function nodeDetail(node: TraceNode) {
  const metadata = node.metadata;
  if (typeof metadata.candidate_count === "number") return `候选文档：${metadata.candidate_count}`;
  if (typeof metadata.output_count === "number") {
    return metadata.rerank_fallback ? `重排降级：保留 ${metadata.output_count} 条` : `重排结果：${metadata.output_count} 条`;
  }
  if (typeof metadata.expansion_skipped === "boolean") {
    return metadata.expansion_skipped ? "已跳过 LLM 查询扩展" : "已执行 LLM 查询扩展";
  }
  if (typeof metadata.guardrail_status === "string") {
    return metadata.guardrail_fallback ? `安全降级：${metadata.guardrail_status}` : "医疗安全检查通过";
  }
  if (typeof metadata.web_search_provider === "string") {
    if (metadata.web_search_fallback) return `联网降级：${metadata.web_search_error_type || "服务不可用"}`;
    return `联网来源：${metadata.web_source_count || 0} 条`;
  }
  if (typeof metadata.retrieval_confidence === "number") {
    return `检索置信度：${Math.round(metadata.retrieval_confidence * 100)}%`;
  }
  const agent = metadata.selected_agent || metadata.next_route;
  if (typeof agent === "string") return `路由：${agent}`;
  if (typeof metadata.image_type === "string") return `影像类型：${metadata.image_type}`;
  if (typeof metadata.decision_confidence === "number") {
    return `决策置信度：${Math.round(metadata.decision_confidence * 100)}%`;
  }
  if (typeof metadata.error_type === "string") return `异常：${metadata.error_type}`;
  return node.node_id;
}

function NodeStatusIcon({ node }: { node: TraceNode }) {
  if (node.status === "completed") return <CheckCircle2 size={17} aria-hidden="true" />;
  if (node.status === "failed") return <XCircle size={17} aria-hidden="true" />;
  return <CircleDashed className="spin" size={17} aria-hidden="true" />;
}

function latestSelectedAgent(trace: TraceRun | null) {
  if (!trace) return null;
  for (let index = trace.nodes.length - 1; index >= 0; index -= 1) {
    const value = trace.nodes[index].metadata.selected_agent;
    if (typeof value === "string") return value;
  }
  return null;
}

export function ExecutionInspector({
  traces,
  selectedTraceId,
  busy,
  conversationId,
  onSelect
}: ExecutionInspectorProps) {
  const selected: TraceRun | null = traces.find((trace) => trace.trace_id === selectedTraceId)
    || traces[traces.length - 1]
    || null;
  const selectedAgent = latestSelectedAgent(selected);

  return (
    <aside className="execution-inspector" aria-label="智能体执行轨迹">
      <header className="inspector-header">
        <div className="inspector-title-row">
          <span className="inspector-icon" aria-hidden="true"><Activity size={19} /></span>
          <div>
            <span className="eyebrow">Agent Observability</span>
            <h2>节点执行轨迹</h2>
          </div>
        </div>
        <div className={`trace-health trace-health--${selected?.status || (busy ? "running" : "idle")}`} role="status">
          <span className="status-dot" aria-hidden="true" />
          {selected ? statusCopy[selected.status] : busy ? "准备中" : "等待调用"}
        </div>
      </header>

      <section className="trace-context" aria-label="当前轨迹摘要">
        <div><GitBranch size={15} aria-hidden="true" /><span>会话</span><strong>{conversationId ? conversationId.slice(0, 8) : "未建立"}</strong></div>
        <div><Route size={15} aria-hidden="true" /><span>路由</span><strong>{typeof selectedAgent === "string" ? selectedAgent : "待判定"}</strong></div>
        <div><Clock3 size={15} aria-hidden="true" /><span>总耗时</span><strong>{selected ? formatDuration(selected.total_duration_ms) : "—"}</strong></div>
      </section>

      {traces.length > 0 && (
        <nav className="trace-history" aria-label="调用记录">
          {traces.map((trace, index) => (
            <button
              key={trace.trace_id}
              type="button"
              className={trace.trace_id === selected?.trace_id ? "trace-history__item is-active" : "trace-history__item"}
              onClick={() => onSelect(trace.trace_id)}
              aria-pressed={trace.trace_id === selected?.trace_id}
              title={trace.queryLabel}
            >
              <span>#{index + 1}</span>
              <small>{trace.status === "running" ? "执行中" : `${trace.nodes.length} 节点`}</small>
            </button>
          ))}
        </nav>
      )}

      <section className="trace-body" aria-live="polite" aria-busy={selected?.status === "running" || selected?.status === "queued"}>
        {!selected ? (
          <div className="trace-empty">
            <span className="trace-empty__icon" aria-hidden="true"><GitBranch size={24} /></span>
            <h3>等待首次调用</h3>
            <p>发送问题或上传影像后，这里会按真实执行顺序显示触发的 LangGraph 节点。</p>
          </div>
        ) : (
          <>
            <div className="trace-request-copy">
              <span>本次输入</span>
              <strong>{selected.queryLabel}</strong>
              <code>{selected.trace_id.slice(0, 8)}</code>
            </div>
            {selected.nodes.length === 0 ? (
              <div className="trace-awaiting">
                <CircleDashed className="spin" size={19} aria-hidden="true" />
                <div><strong>等待首个节点回传</strong><span>请求已进入执行队列</span></div>
              </div>
            ) : (
              <ol className="trace-timeline">
                {selected.nodes.map((node, index) => (
                  <li key={node.event_id} className={`trace-node trace-node--${node.status}`}>
                    <span className="trace-node__rail" aria-hidden="true">
                      <span className="trace-node__index">{index + 1}</span>
                    </span>
                    <div className="trace-node__card">
                      <div className="trace-node__heading">
                        <span className="trace-node__status"><NodeStatusIcon node={node} /></span>
                        <strong>{node.label}</strong>
                        <time>{formatDuration(node.duration_ms)}</time>
                      </div>
                      <p>{nodeDetail(node)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </section>

      <footer className="inspector-footer">
        <ShieldCheck size={15} aria-hidden="true" />
        服务端轨迹仅记录节点、状态和耗时，不保存问题正文
      </footer>
    </aside>
  );
}
