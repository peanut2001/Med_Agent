import asyncio
import sqlite3
from contextlib import contextmanager
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, END

import app as application
import agents.agent_decision as decision
import agents.checkpoint as checkpoints
import agents.security as security
from agents.checkpoint import ConversationMemorySaver
from agents.conversation_store import ConversationStore
from agents.local_auth import LocalAuthStore
from agents.security import CurrentUser, get_current_user
from agents.upload_limits import UploadBodyLimitMiddleware
from agents.validation_store import ValidationStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "conversation_store", ConversationStore(str(tmp_path / "history.db")))
    monkeypatch.setattr(checkpoints, "_checkpointer", ConversationMemorySaver())
    monkeypatch.setattr(application, "validation_store", ValidationStore())
    install_echo_graph(monkeypatch)
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser("review-user", {})
    try:
        with TestClient(application.app) as client:
            yield client
    finally:
        application.app.dependency_overrides.clear()


def install_echo_graph(monkeypatch):
    builder = StateGraph(decision.AgentState)
    builder.add_node("apply_guardrails", lambda state: {
        "messages": [AIMessage(content="answer")], "agent_name": "CONVERSATION_AGENT"
    })
    builder.set_entry_point("apply_guardrails")
    builder.add_edge("apply_guardrails", END)
    graph = builder.compile(checkpointer=checkpoints._checkpointer)
    monkeypatch.setattr(decision, "create_agent_graph", lambda: graph)
    monkeypatch.setattr(decision.config, "max_conversation_history", 4)
    return graph


def test_new_chat_ignores_cookie_and_existing_chat_can_continue(client, monkeypatch):
    graph = install_echo_graph(monkeypatch)
    first = client.post("/chat", json={"query": "first"}).json()
    second = client.post("/chat", json={"query": "new chat"}).json()
    assert first["conversation_id"] != second["conversation_id"]
    resumed = client.post("/chat", json={"query": "continue", "conversation_id": first["conversation_id"]})
    assert resumed.status_code == 200
    state = graph.get_state({"configurable": {"thread_id": f"review-user:{first['conversation_id']}"}})
    assert [m.content for m in state.values["messages"]] == ["first", "answer", "continue", "answer"]
    assert len(client.get("/conversations").json()["conversations"]) == 2


def test_new_trace_ignores_cookie(client):
    first = client.post("/traces", json={}).json()
    second = client.post("/traces", json={}).json()
    assert first["conversation_id"] != second["conversation_id"]


def test_checkpoint_messages_and_snapshots_are_bounded_and_deleted(client, monkeypatch):
    graph = install_echo_graph(monkeypatch)
    for index in range(12):
        response = client.post("/chat", json={"query": f"turn-{index}", "conversation_id": "bounded"})
        assert response.status_code == 200
    state = graph.get_state({"configurable": {"thread_id": "review-user:bounded"}})
    assert [m.content for m in state.values["messages"]] == ["turn-10", "answer", "turn-11", "answer"]
    assert len(list(checkpoints._checkpointer.list({"configurable": {"thread_id": "review-user:bounded"}}))) == 1
    # Reading a checkpoint may create an empty pending-write entry.
    assert not any(checkpoints._checkpointer.writes.values())
    assert client.delete("/conversations/bounded").status_code == 200
    assert graph.get_state({"configurable": {"thread_id": "review-user:bounded"}}).values == {}
    assert client.get("/conversations/bounded/messages").status_code == 404


def test_deletion_waits_for_inflight_history_write(client, monkeypatch):
    entered, release = Event(), Event()

    def slow_reply(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"messages": [AIMessage(content="answer")], "agent_name": "CONVERSATION_AGENT"}

    monkeypatch.setattr(application, "process_query", slow_reply)
    with ThreadPoolExecutor(max_workers=2) as pool:
        chat = pool.submit(client.post, "/chat", json={"query": "hello", "conversation_id": "inflight"})
        assert entered.wait(5)
        deletion = pool.submit(client.delete, "/conversations/inflight")
        try:
            assert not deletion.done()
        finally:
            release.set()
        assert chat.result(timeout=5).status_code == 200
        assert deletion.result(timeout=5).status_code == 200
    assert client.get("/conversations/inflight/messages").status_code == 404


def test_foreign_chat_rejected_before_model_execution(client, monkeypatch):
    application.conversation_store.append(user_id="other-user", conversation_id="foreign", role="user", content="private")
    monkeypatch.setattr(application, "process_query", lambda *a, **kw: pytest.fail("Model must not run"))
    assert client.post("/chat", json={"query": "hello", "conversation_id": "foreign"}).status_code == 403
    assert client.delete("/conversations/foreign").status_code == 403


def test_disabled_account_loses_existing_session(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AUTH_USERS", "")
    monkeypatch.setenv("AUTH_MODE", "local")
    store = LocalAuthStore(str(tmp_path / "auth.db"))
    monkeypatch.setattr(application, "local_auth_store", store)
    monkeypatch.setattr(security, "local_auth_store", store)
    application.app.dependency_overrides.clear()
    assert client.post("/auth/register", json={"username": "review-user", "password": "review-password"}).status_code == 200
    assert client.get("/auth/me").status_code == 200
    with store._connect() as db:
        db.execute("UPDATE local_users SET disabled = 1 WHERE username = ?", ("review-user",))
    assert client.get("/auth/me").status_code == 401
    assert client.post("/chat", json={"query": "hello"}).status_code == 401
    assert client.post("/auth/login", json={"username": "review-user", "password": "review-password"}).status_code == 401


@pytest.mark.parametrize("route,field,filename,setting", [
    ("/upload", "image", "scan.png", "max_image_upload_size"),
    ("/transcribe", "audio", "recording.webm", "max_audio_upload_size"),
])
def test_oversized_files_rejected_without_processing(client, monkeypatch, tmp_path, route, field, filename, setting):
    monkeypatch.setattr(application.config.api, setting, 1)
    monkeypatch.setattr(application, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(application, "SPEECH_DIR", str(tmp_path))
    monkeypatch.setattr(application, "process_query", lambda *a, **kw: pytest.fail("Model must not run"))
    monkeypatch.setattr(application, "_transcribe_audio_sync", lambda *a: pytest.fail("Transcription must not run"))
    before = set(tmp_path.iterdir())
    result = client.post(route, files={field: (filename, b"x" * (1024 * 1024 + 1))})
    assert result.status_code == 413
    assert set(tmp_path.iterdir()) == before


def test_streamed_multipart_body_is_limited_without_content_length():
    api = FastAPI()
    api.add_middleware(UploadBodyLimitMiddleware, limits={"/upload": 200})

    @api.post("/upload")
    async def upload(image: UploadFile = File(...)):
        pytest.fail("Oversized body must not reach the handler")

    async def exercise():
        chunks = iter([
            b'--boundary\r\nContent-Disposition: form-data; name="image"; filename="scan.png"\r\n\r\n',
            b"x" * 150,
            b"\r\n--boundary--\r\n",
        ])
        messages = []

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            messages.append(message)

        await api({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "POST", "scheme": "http", "path": "/upload", "query_string": b"",
                   "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
                   "server": ("test", 80), "client": ("test", 1)}, receive, send)
        assert messages[0]["status"] == 413
        assert len(messages) == 2

    asyncio.run(exercise())


def test_declared_oversized_body_rejected_before_read():
    async def exercise():
        async def downstream(*args):
            pytest.fail("Oversized declared body must not be parsed")

        async def receive():
            pytest.fail("Oversized declared body must not be read")

        messages = []

        async def send(message):
            messages.append(message)

        middleware = UploadBodyLimitMiddleware(downstream, limits={"/upload": 100})
        await middleware({"type": "http", "path": "/upload", "method": "POST",
                          "headers": [(b"content-length", b"101")]}, receive, send)
        assert messages[0]["status"] == 413

    asyncio.run(exercise())


def test_legacy_postgres_deletion_is_scoped_to_one_thread(monkeypatch):
    # Execute the fallback's DELETE statements against small relational tables
    # to verify that another user's checkpoints are preserved.
    with sqlite3.connect(":memory:") as db:
        tables = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
        for table in tables:
            db.execute(f"CREATE TABLE {table} (thread_id TEXT)")
            db.executemany(f"INSERT INTO {table} VALUES (?)", [("owner:chat",), ("other:chat",)])

        class LegacySaver:
            def delete_thread(self, thread_id):
                raise NotImplementedError

            @contextmanager
            def _cursor(self):
                yield self

            def execute(self, sql, params):
                db.execute(sql.replace("%s", "?"), params)

        monkeypatch.setattr(checkpoints, "_checkpointer", LegacySaver())
        checkpoints.delete_conversation_checkpoint("owner:chat")
        for table in tables:
            assert db.execute(f"SELECT thread_id FROM {table}").fetchall() == [("other:chat",)]


def make_review(conversation_id="review-chat", user_id="review-user", image_path=None):
    application.conversation_store.append(
        user_id=user_id, conversation_id=conversation_id, role="user", content="uploaded image"
    )
    record = application.validation_store.create(
        user_id=user_id, conversation_id=conversation_id, thread_id=f"{user_id}:{conversation_id}",
        agent_name="CHEST_XRAY_AGENT", original_output="analysis", result_image_path=image_path,
    )
    return {"validation_id": record.validation_id, "conversation_id": conversation_id,
            "validation_result": "yes"}


def test_validation_retry_preserves_first_decision_and_only_one_message(client):
    payload = make_review()
    payload.update(validation_result="no", comments="first comment")
    first = client.post("/validate", data=payload)
    assert first.status_code == 200
    payload.update(validation_result="yes", comments="different comment")
    retry = client.post("/validate", data=payload)
    assert retry.status_code == 200
    assert first.json() == retry.json()
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    reviews = [message for message in messages if message["agent"] == "HUMAN_VALIDATED"]
    assert len(reviews) == 1
    assert reviews[0]["status_label"] == "需复查"


def test_concurrent_validation_retries_append_once(client):
    payload = make_review()
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(client.post, "/validate", data=payload) for _ in range(2)]
        responses = [call.result(timeout=5) for call in calls]
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert sum(message["agent"] == "HUMAN_VALIDATED" for message in messages) == 1


def test_deleted_conversation_rejects_old_review_and_image(client, monkeypatch, tmp_path):
    import agents.artifacts as artifacts
    monkeypatch.setattr(artifacts, "PRIVATE_ARTIFACT_ROOT", tmp_path.resolve())
    image = tmp_path / "review.png"
    image.write_bytes(b"review-image")
    payload = make_review(image_path=str(image))
    other = make_review("other-chat", user_id="other-user")
    assert client.get(f"/validations/{payload['validation_id']}/image").status_code == 200
    assert client.delete("/conversations/review-chat").status_code == 200
    assert client.post("/validate", data=payload).status_code == 404
    assert client.get("/conversations/review-chat/messages").status_code == 404
    assert client.get(f"/validations/{payload['validation_id']}/image").status_code == 404
    assert application.validation_store.get(payload["validation_id"]) is None
    assert application.validation_store.get(other["validation_id"]) is not None
    # Reusing the deleted conversation ID cannot restore its old review.
    application.conversation_store.append(user_id="review-user", conversation_id="review-chat", role="user", content="new")
    assert client.post("/validate", data=payload).status_code == 404


def test_failed_validation_history_write_can_be_retried(client, monkeypatch):
    payload = make_review()
    with monkeypatch.context() as patch:
        patch.setattr(application.conversation_store, "append_validation", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("storage failure")))
        assert client.post("/validate", data=payload).status_code == 500
    assert client.post("/validate", data=payload).status_code == 200
    assert client.post("/validate", data=payload).status_code == 200
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert sum(message["agent"] == "HUMAN_VALIDATED" for message in messages) == 1


def test_invalid_or_foreign_validation_cannot_modify_history(client):
    payload = make_review()
    assert client.post("/validate", data={**payload, "validation_result": "invalid"}).status_code == 400
    assert application.validation_store.get(payload["validation_id"]).status == "pending"
    foreign = make_review("other-chat", user_id="other-user")
    assert client.post("/validate", data=foreign).status_code == 403
    assert client.delete("/conversations/other-chat").status_code == 403
    assert application.validation_store.get(foreign["validation_id"]).status == "pending"


def test_existing_conversation_database_migrates_without_losing_history(tmp_path):
    database = tmp_path / "legacy.db"
    store = ConversationStore(str(database))
    store.append(user_id="review-user", conversation_id="legacy-chat", role="user", content="keep this")
    with store._connect() as db:
        db.execute("DROP INDEX idx_conversation_validation")
        db.execute("ALTER TABLE conversation_messages DROP COLUMN validation_id")
    migrated = ConversationStore(str(database))
    migrated.append_validation(user_id="review-user", conversation_id="legacy-chat", validation_id="review-id", content="confirmed", status_label="已确认")
    migrated.append_validation(user_id="review-user", conversation_id="legacy-chat", validation_id="review-id", content="confirmed", status_label="已确认")
    assert [message["content"] for message in migrated.get_messages("legacy-chat", user_id="review-user")] == ["keep this", "confirmed"]


def test_failed_turns_restore_completed_state_and_bound_checkpoints(client, monkeypatch):
    graph = install_echo_graph(monkeypatch)
    state = decision.init_agent_state()
    from langchain_core.messages import HumanMessage
    run_config = {"configurable": {"thread_id": "review-user:failures"}}
    state["messages"] = [HumanMessage(content="successful question")]
    decision._invoke_with_bounded_history(graph, state, run_config)
    invoke = graph.invoke

    def fail_after_checkpoint(*args):
        invoke(*args)
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(graph, "invoke", fail_after_checkpoint)
    for index in range(12):
        state["messages"] = [HumanMessage(content=f"failed question {index}")]
        with pytest.raises(RuntimeError, match="upstream failure"):
            decision._invoke_with_bounded_history(graph, state, run_config)
    snapshot = graph.get_state(run_config)
    assert [message.content for message in snapshot.values["messages"]] == ["successful question", "answer"]
    assert not snapshot.next
    assert len(list(graph.checkpointer.list(run_config))) == 1
    monkeypatch.setattr(graph, "invoke", invoke)
    state["messages"] = [HumanMessage(content="recovered question")]
    result = decision._invoke_with_bounded_history(graph, state, run_config)
    assert [message.content for message in result["messages"]] == ["successful question", "answer", "recovered question", "answer"]


@pytest.mark.parametrize("image_text", ["yes please analyze this scan", "no previous scan available"])
def test_image_text_is_not_interpreted_as_a_review_decision(image_text):
    # Exercise the real nested output node without initializing remote models.
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse(Path(decision.__file__).read_text(encoding="utf-8"))
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "apply_output_guardrails")
    calls = []

    def check_output(*args, **kwargs):
        calls.append(args)
        return "checked image analysis", "completed"

    namespace = {"AgentState": dict, "AIMessage": AIMessage,
                 "guardrails": SimpleNamespace(check_output_safely=check_output),
                 "config": SimpleNamespace(guardrails=SimpleNamespace(output_fail_open=False, output_model_name="fake"))}
    exec(compile(ast.Module(body=[node], type_ignores=[]), decision.__file__, "exec"), namespace)
    result = namespace["apply_output_guardrails"]({
        "output": AIMessage(content="image analysis\nHuman Validation Required"),
        "current_input": {"text": image_text}, "messages": [],
    })
    assert len(calls) == 1
    assert result["messages"].content == "checked image analysis"


def test_node_failure_on_first_turn_is_cleared_before_retry(client, monkeypatch):
    from langchain_core.messages import HumanMessage
    failing = True

    def reply(state):
        if failing:
            raise RuntimeError("node failed")
        return {"messages": [AIMessage(content="recovered")], "agent_name": "CONVERSATION_AGENT"}

    builder = StateGraph(decision.AgentState)
    builder.add_node("apply_guardrails", reply)
    builder.set_entry_point("apply_guardrails")
    builder.add_edge("apply_guardrails", END)
    graph = builder.compile(checkpointer=checkpoints._checkpointer)
    monkeypatch.setattr(decision.config, "max_conversation_history", 4)
    run_config = {"configurable": {"thread_id": "review-user:node-failure"}}
    state = decision.init_agent_state()
    for index in range(12):
        state["messages"] = [HumanMessage(content=f"failed-{index}")]
        with pytest.raises(RuntimeError, match="node failed"):
            decision._invoke_with_bounded_history(graph, state, run_config)
    snapshot = graph.get_state(run_config)
    assert snapshot.values["messages"] == []
    assert not snapshot.next
    assert len(list(graph.checkpointer.list(run_config))) == 1
    failing = False
    state["messages"] = [HumanMessage(content="try again")]
    result = decision._invoke_with_bounded_history(graph, state, run_config)
    assert [message.content for message in result["messages"]] == ["try again", "recovered"]


@pytest.mark.parametrize("choice,expected", [("yes", "CONFIRMED"), ("no", "REQUIRES FURTHER REVIEW")])
def test_review_reaches_next_model_turn_once(client, monkeypatch, choice, expected):
    graph = install_echo_graph(monkeypatch)
    payload = make_review()
    payload.update(validation_result=choice, comments="Check the marked region")
    assert client.post("/validate", data=payload).status_code == 200
    assert client.post("/validate", data=payload).status_code == 200
    run_config = {"configurable": {"thread_id": "review-user:review-chat"}}
    snapshot = graph.get_state(run_config)
    reviews = [m for m in snapshot.values["messages"] if m.id == f"validation:{payload['validation_id']}"]
    assert len(reviews) == 1
    assert expected in reviews[0].content
    assert "Check the marked region" in reviews[0].content
    assert "analysis" in reviews[0].content
    assert not snapshot.next
    assert client.post("/chat", json={"query": "Explain the review", "conversation_id": "review-chat"}).status_code == 200
    assert any(expected in m.content for m in graph.get_state(run_config).values["messages"])
    assert graph.get_state({"configurable": {"thread_id": "other-user:review-chat"}}).values == {}


def test_review_checkpoint_failure_can_be_retried(client, monkeypatch):
    graph = install_echo_graph(monkeypatch)
    payload = make_review()
    with monkeypatch.context() as patch:
        patch.setattr(graph, "update_state", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("checkpoint failed")))
        assert client.post("/validate", data=payload).status_code == 500
    assert client.post("/validate", data=payload).status_code == 200
    assert client.post("/validate", data=payload).status_code == 200
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert sum(m["agent"] == "HUMAN_VALIDATED" for m in messages) == 1


def test_restart_restores_owned_history_before_next_model_turn(client, monkeypatch):
    assert client.post("/chat", json={"query": "My detail is 123", "conversation_id": "restart-chat"}).status_code == 200
    monkeypatch.setattr(checkpoints, "_checkpointer", ConversationMemorySaver())
    seen = []
    builder = StateGraph(decision.AgentState)

    def reply(state):
        seen.append([m.content for m in state["messages"]])
        return {"messages": [AIMessage(content="remembered")], "agent_name": "CONVERSATION_AGENT"}

    builder.add_node("apply_guardrails", reply)
    builder.set_entry_point("apply_guardrails")
    builder.add_edge("apply_guardrails", END)
    graph = builder.compile(checkpointer=checkpoints._checkpointer)
    monkeypatch.setattr(decision, "create_agent_graph", lambda: graph)
    assert client.post("/chat", json={"query": "What detail?", "conversation_id": "restart-chat"}).status_code == 200
    assert seen[-1] == ["My detail is 123", "answer", "What detail?"]
    assert client.post("/chat", json={"query": "Continue", "conversation_id": "restart-chat"}).status_code == 200
    assert seen[-1].count("What detail?") == 1
    assert len(graph.get_state({"configurable": {"thread_id": "review-user:restart-chat"}}).values["messages"]) == 4


def test_recovery_is_bounded_and_rejects_foreign_history(client, monkeypatch):
    store = application.conversation_store
    for index in range(20):
        store.append(user_id="review-user", conversation_id="recover", role="user", content=f"old-{index}")
    store.append(user_id="other-user", conversation_id="foreign-recovery", role="user", content="private")
    with pytest.raises(PermissionError):
        store.get_recent_messages("foreign-recovery", user_id="review-user", limit=4)
    assert store.get_recent_messages("missing", user_id="review-user", limit=4) == []
    rows = store.get_recent_messages("recover", user_id="review-user", limit=4)
    assert [row["content"] for row in rows] == ["old-16", "old-17", "old-18", "old-19"]
    graph = install_echo_graph(monkeypatch)
    run_config = {"configurable": {"thread_id": "review-user:recover"}}
    from langchain_core.messages import HumanMessage
    state = decision.init_agent_state()
    state["messages"] = [HumanMessage(content="follow-up")]
    invoke = graph.invoke
    with monkeypatch.context() as patch:
        patch.setattr(graph, "invoke", lambda *args: (_ for _ in ()).throw(RuntimeError("failed follow-up")))
        with pytest.raises(RuntimeError):
            decision._invoke_with_bounded_history(graph, state, run_config,
                lambda limit: store.get_recent_messages("recover", user_id="review-user", limit=limit))
    assert [m.content for m in graph.get_state(run_config).values["messages"]] == ["old-16", "old-17", "old-18", "old-19"]


def test_restart_recovery_includes_persisted_review_decision(client, monkeypatch):
    payload = make_review()
    payload["validation_result"] = "no"
    assert client.post("/validate", data=payload).status_code == 200
    monkeypatch.setattr(checkpoints, "_checkpointer", ConversationMemorySaver())
    graph = install_echo_graph(monkeypatch)
    assert client.post("/chat", json={"query": "Explain", "conversation_id": "review-chat"}).status_code == 200
    snapshot = graph.get_state({"configurable": {"thread_id": "review-user:review-chat"}})
    assert any("requires further review" in m.content for m in snapshot.values["messages"])


def test_history_restores_pending_review_and_hides_it_after_resolution(client):
    payload = make_review()
    application._record_turn(user_id="review-user", conversation_id="review-chat", query="scan",
        payload={"response": "analysis", "agent": "CHEST_XRAY_AGENT, HUMAN_VALIDATION",
                 "validation_id": payload["validation_id"]})
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    answer = next(m for m in messages if m["agent"] == "CHEST_XRAY_AGENT, HUMAN_VALIDATION")
    assert answer["requires_validation"] is True
    assert answer["validation_id"] == payload["validation_id"]
    assert client.post("/validate", data={**payload, "validation_result": "no"}).status_code == 200
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert not any(m["requires_validation"] for m in messages)


def test_history_does_not_restore_missing_foreign_or_other_conversation_reviews(client):
    own = make_review()
    foreign = make_review("foreign-chat", user_id="other-user")
    other_chat = make_review("other-chat")
    for validation_id in ("missing-review", foreign["validation_id"], other_chat["validation_id"]):
        application.conversation_store.append(user_id="review-user", conversation_id="review-chat",
            role="assistant", content="analysis", validation_request_id=validation_id)
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert not any(m["requires_validation"] for m in messages)
    assert all(m["validation_id"] is None for m in messages)


def test_legacy_image_history_restores_valid_review(client):
    payload = make_review()
    application.conversation_store.append(user_id="review-user", conversation_id="review-chat",
        role="assistant", content="segmentation", result_image=f"/validations/{payload['validation_id']}/image")
    messages = client.get("/conversations/review-chat/messages").json()["messages"]
    assert messages[-1]["requires_validation"] is True
    assert messages[-1]["validation_id"] == payload["validation_id"]
