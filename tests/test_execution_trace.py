import pytest

import agents.execution_trace as tracing


def test_traced_nodes_preserve_order_status_duration_and_metadata(monkeypatch):
    store = tracing.ExecutionTraceStore()
    monkeypatch.setattr(tracing, "execution_trace_store", store)
    trace = store.create(user_id="user-a", conversation_id="conversation-a")
    trace_id = trace["trace_id"]
    store.activate(trace_id, user_id="user-a", conversation_id="conversation-a")

    first = tracing.traced_node(
        "analyze_input", lambda state: {**state, "has_image": False}
    )
    second = tracing.traced_node(
        "route_to_agent",
        lambda state: {
            **state,
            "selected_agent": "RAG_AGENT",
            "decision_confidence": 0.91,
        },
    )

    state = {"execution_trace_id": trace_id}
    state = first(state)
    second(state)
    store.finish(trace_id, status="completed")
    snapshot = store.get_for_user(trace_id, user_id="user-a")

    assert snapshot["status"] == "completed"
    assert [node["node_id"] for node in snapshot["nodes"]] == [
        "analyze_input",
        "route_to_agent",
    ]
    assert all(node["status"] == "completed" for node in snapshot["nodes"])
    assert all(node["duration_ms"] is not None for node in snapshot["nodes"])
    assert snapshot["nodes"][1]["metadata"]["selected_agent"] == "RAG_AGENT"


def test_failed_node_records_only_exception_type(monkeypatch):
    store = tracing.ExecutionTraceStore()
    monkeypatch.setattr(tracing, "execution_trace_store", store)
    trace = store.create(user_id="user-a", conversation_id="conversation-a")
    trace_id = trace["trace_id"]
    store.activate(trace_id, user_id="user-a", conversation_id="conversation-a")

    def fail(_state):
        raise RuntimeError("sensitive medical text")

    with pytest.raises(RuntimeError):
        tracing.traced_node("RAG_AGENT", fail)({"execution_trace_id": trace_id})
    store.finish(trace_id, status="failed")
    snapshot = store.get_for_user(trace_id, user_id="user-a")

    assert snapshot["status"] == "failed"
    assert snapshot["nodes"][0]["metadata"] == {"error_type": "RuntimeError"}
    assert "sensitive medical text" not in str(snapshot)


def test_trace_lookup_hides_foreign_records():
    store = tracing.ExecutionTraceStore()
    trace = store.create(user_id="user-a", conversation_id="conversation-a")
    with pytest.raises(KeyError):
        store.get_for_user(trace["trace_id"], user_id="user-b")
    with pytest.raises(KeyError):
        store.activate(
            trace["trace_id"], user_id="user-b", conversation_id="conversation-a"
        )


def test_owned_preflight_trace_can_fail_without_touching_foreign_trace():
    store = tracing.ExecutionTraceStore()
    trace = store.create(user_id="user-a", conversation_id="conversation-a")
    trace_id = trace["trace_id"]

    store.fail_for_user(trace_id, user_id="user-b")
    assert store.get_for_user(trace_id, user_id="user-a")["status"] == "queued"

    store.fail_for_user(trace_id, user_id="user-a")
    assert store.get_for_user(trace_id, user_id="user-a")["status"] == "failed"


def test_reusing_trace_raises_specific_error():
    store = tracing.ExecutionTraceStore()
    trace = store.create(user_id="user-a", conversation_id="conversation-a")
    store.activate(trace["trace_id"], user_id="user-a", conversation_id="conversation-a")

    with pytest.raises(tracing.TraceAlreadyUsedError):
        store.activate(trace["trace_id"], user_id="user-a", conversation_id="conversation-a")
