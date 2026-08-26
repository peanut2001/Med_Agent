from types import SimpleNamespace
from threading import RLock

from agents.execution_trace import ExecutionTraceStore, traced_node
from agents.rag_agent.query_expander import QueryExpander
from agents.rag_agent.runtime import RAGRequestContext, RAGRequestContextStore
from agents.guardrails.local_guardrails import LocalGuardrails, SAFE_OUTPUT_FALLBACK
from agents.rag_agent import vectorstore_qdrant


class FakeModel:
    def __init__(self):
        self.calls = 0

    def invoke(self, _prompt):
        self.calls += 1
        return SimpleNamespace(content="expanded medical query")


def expander_config(model, **overrides):
    values = {
        "llm": model,
        "query_expansion_enabled": True,
        "skip_simple_query_expansion": True,
        "simple_query_max_chars": 80,
    }
    values.update(overrides)
    return SimpleNamespace(rag=SimpleNamespace(**values))


def test_simple_query_skips_llm_expansion():
    model = FakeModel()
    expander = QueryExpander(expander_config(model))

    result = expander.expand_query("什么是脑肿瘤？")

    assert result["expanded_query"] == "什么是脑肿瘤？"
    assert result["expansion_skipped"] is True
    assert result["expansion_reason"] == "simple_clear_query"
    assert model.calls == 0


def test_context_dependent_query_uses_llm_expansion():
    model = FakeModel()
    expander = QueryExpander(expander_config(model))

    result = expander.expand_query("这个一般怎么办？")

    assert result["expanded_query"] == "expanded medical query"
    assert result["expansion_skipped"] is False
    assert result["expansion_reason"] == "context_dependent"
    assert model.calls == 1


def test_rag_request_context_is_ephemeral_and_isolated():
    store = RAGRequestContextStore()
    first = RAGRequestContext(original_query="private one", query="one")
    second = RAGRequestContext(original_query="private two", query="two")
    store.create("trace-1", first)
    store.create("trace-2", second)

    assert store.get("trace-1") is first
    assert store.get("trace-2") is second
    store.discard("trace-1")

    try:
        store.get("trace-1")
    except RuntimeError as exc:
        assert "private one" not in str(exc)
    else:
        raise AssertionError("discarded RAG context remained accessible")


def test_node_metadata_does_not_leak_into_following_node(monkeypatch):
    import agents.execution_trace as tracing

    store = ExecutionTraceStore()
    monkeypatch.setattr(tracing, "execution_trace_store", store)
    trace = store.create(user_id="u", conversation_id="c")
    trace_id = trace["trace_id"]
    store.activate(trace_id, user_id="u", conversation_id="c")

    first = traced_node(
        "RAG_VECTOR_RETRIEVAL",
        lambda state: {**state, "trace_metadata": {"candidate_count": 5}},
    )
    second = traced_node("RAG_RERANK", lambda state: {**state})
    state = first({"execution_trace_id": trace_id, "trace_metadata": {}})
    second(state)
    snapshot = store.get_for_user(trace_id, user_id="u")

    assert snapshot["nodes"][0]["metadata"]["candidate_count"] == 5
    assert "candidate_count" not in snapshot["nodes"][1]["metadata"]


def test_output_guardrail_timeout_fails_closed():
    guardrails = LocalGuardrails.__new__(LocalGuardrails)
    guardrails.check_output = lambda *_args: (_ for _ in ()).throw(TimeoutError())

    output, status = guardrails.check_output_safely("unchecked medical answer", "query")

    assert output == SAFE_OUTPUT_FALLBACK
    assert "unchecked medical answer" not in output
    assert status == "timeout"


def test_output_guardrail_model_error_fails_closed():
    guardrails = LocalGuardrails.__new__(LocalGuardrails)
    guardrails.check_output = lambda *_args: (_ for _ in ()).throw(RuntimeError())

    output, status = guardrails.check_output_safely("unchecked medical answer", "query")

    assert output == SAFE_OUTPUT_FALLBACK
    assert status == "model_error"


def test_vectorstore_and_docstore_are_loaded_once(monkeypatch):
    calls = {"collection": 0, "sparse": 0, "vectorstore": 0, "docstore": 0}
    store = vectorstore_qdrant.VectorStore.__new__(vectorstore_qdrant.VectorStore)
    store._cache_lock = RLock()
    store._cached_vectorstore = None
    store._cached_docstore = None
    store.collection_name = "medical"
    store.client = object()
    store.embedding_model = object()
    store.docstore_local_path = "docs"
    store.logger = SimpleNamespace(error=lambda *_args: None, info=lambda *_args: None)

    def collection_exists():
        calls["collection"] += 1
        return True

    def sparse(**_kwargs):
        calls["sparse"] += 1
        return object()

    def vectorstore(**_kwargs):
        calls["vectorstore"] += 1
        return object()

    def docstore(_path):
        calls["docstore"] += 1
        return object()

    store._does_collection_exist = collection_exists
    monkeypatch.setattr(vectorstore_qdrant, "FastEmbedSparse", sparse)
    monkeypatch.setattr(vectorstore_qdrant, "QdrantVectorStore", vectorstore)
    monkeypatch.setattr(vectorstore_qdrant, "LocalFileStore", docstore)

    first = store.load_vectorstore()
    second = store.load_vectorstore()

    assert first == second
    assert calls == {"collection": 1, "sparse": 1, "vectorstore": 1, "docstore": 1}
