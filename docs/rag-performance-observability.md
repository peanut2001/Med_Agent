# RAG 性能观测与调优

RAG 请求在执行轨迹中拆分为四个节点：

1. `RAG_QUERY_EXPANSION`：确定性判断并按需调用 LLM 扩展问题。
2. `RAG_VECTOR_RETRIEVAL`：生成查询 embedding，执行 Qdrant 混合检索并读取 docstore。
3. `RAG_RERANK`：调用远程 reranker；失败时保留原始排序。
4. `RAG_ANSWER_GENERATION`：基于重排后的上下文生成答案和检索置信度。

轨迹只记录耗时、数量、状态和置信度等统计信息。用户问题、扩展问题和检索文档正文保存在请求级内存上下文中，并在请求完成或失败后清理，不进入 trace 或 LangGraph checkpoint。

## 建议基线

使用固定问题集分别记录冷启动与热请求的 P50、P95、失败率和 Web fallback 率。至少覆盖：

- 简单明确问题，应显示“已跳过 LLM 查询扩展”。
- 上下文相关的追问，应执行问题扩展。
- reranker 正常、超时和服务不可用。
- 高置信度 RAG 回答与低置信度 Web fallback。
- 输出审核正常、超时和模型错误的安全降级。
- `gpt-5.6-sol` Responses Web Search 正常，以及网关不支持 `/responses` 时的低置信度 RAG 安全降级。

先根据四段耗时确定瓶颈，再调整 embedding、候选数量、reranker 或答案模型。不要仅根据 RAG 总耗时更换模型。

## 缓存与失效

编译后的工作流持有一个 `MedicalRAG` 实例。Qdrant vectorstore、BM25 sparse embedding 和 docstore 在第一次检索时初始化并缓存；知识入库完成后缓存会自动失效，下次检索重新加载包装器。

## 医疗安全

输出审核默认使用 `gpt-4o-mini`，可通过 `OUTPUT_GUARDRAIL_MODEL_NAME` 替换为部署环境支持的快速审核模型。审核模型请求超时或异常时采用失败关闭策略，原始医疗回答不会直接返回。

复核策略已支持置信度阈值、异常类型、图片质量原因码和审计事件。当前影像推理接口尚未全部提供诊断置信度及图片质量评分；缺失时会保守地产生 `confidence_unavailable` 或 `image_quality_unassessed` 并要求复核。
