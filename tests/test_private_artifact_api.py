from fastapi.testclient import TestClient

import agents.artifacts as artifacts
from agents.security import CurrentUser, get_current_user
import app as application


def test_private_image_requires_owner_and_static_roots_are_not_public(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "PRIVATE_ARTIFACT_ROOT", tmp_path.resolve())
    image_path = artifacts.create_private_artifact_path()
    image_path.write_bytes(b"private-image")
    record = application.validation_store.create(
        user_id="user-a",
        conversation_id="conversation-a",
        thread_id="user-a:conversation-a",
        agent_name="SKIN_LESION_AGENT",
        original_output="result",
        result_image_path=str(image_path),
    )

    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app) as client:
            owned = client.get(f"/validations/{record.validation_id}/image")
            assert owned.status_code == 200
            assert owned.content == b"private-image"
            assert owned.headers["cache-control"].startswith("private")
            assert client.get("/data/secret").status_code == 404
            assert client.get("/uploads/secret").status_code == 404

            application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                user_id="user-b", claims={"sub": "user-b"}
            )
            assert client.get(f"/validations/{record.validation_id}/image").status_code == 404
    finally:
        application.app.dependency_overrides.clear()


def test_private_image_rejects_unauthenticated_requests():
    application.app.dependency_overrides.clear()
    with TestClient(application.app) as client:
        response = client.get("/validations/unknown/image")
    assert response.status_code == 401


def test_failed_upload_removes_temporary_source(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        application,
        "process_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("inference failed")),
    )
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/upload",
                files={"image": ("scan.png", b"fake-image", "image/png")},
                data={"conversation_id": "conversation-a"},
            )
        assert response.status_code == 500
        assert list(tmp_path.iterdir()) == []
    finally:
        application.app.dependency_overrides.clear()


def test_failed_transcription_removes_all_temporary_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "SPEECH_DIR", str(tmp_path))
    monkeypatch.setattr(
        application,
        "_transcribe_audio_sync",
        lambda *args: (_ for _ in ()).throw(RuntimeError("speech failed")),
    )
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app) as client:
            response = client.post(
                "/transcribe",
                files={"audio": ("recording.webm", b"fake-audio", "audio/webm")},
            )
        assert response.status_code == 500
        assert list(tmp_path.iterdir()) == []
    finally:
        application.app.dependency_overrides.clear()


def test_generated_speech_is_deleted_after_response(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "SPEECH_DIR", str(tmp_path))

    def fake_generate(text, voice_id, output_path):
        output_path.write_bytes(b"generated-audio")

    monkeypatch.setattr(application, "_generate_speech_sync", fake_generate)
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app) as client:
            response = client.post(
                "/generate-speech",
                json={"text": "hello", "voice_id": "test-voice"},
            )
        assert response.status_code == 200
        assert response.content == b"generated-audio"
        assert list(tmp_path.iterdir()) == []
    finally:
        application.app.dependency_overrides.clear()


def test_execution_trace_api_is_scoped_to_authenticated_user():
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app) as client:
            created = client.post(
                "/traces", json={"conversation_id": "conversation-a"}
            )
            assert created.status_code == 200
            trace = created.json()
            assert trace["status"] == "queued"
            assert trace["nodes"] == []

            owned = client.get(f"/traces/{trace['trace_id']}")
            assert owned.status_code == 200

            application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                user_id="user-b", claims={"sub": "user-b"}
            )
            assert client.get(f"/traces/{trace['trace_id']}").status_code == 404
    finally:
        application.app.dependency_overrides.clear()


def test_rejected_upload_marks_preflight_trace_failed():
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-a", claims={"sub": "user-a"}
    )
    try:
        with TestClient(application.app) as client:
            trace = client.post(
                "/traces", json={"conversation_id": "conversation-a"}
            ).json()
            rejected = client.post(
                "/upload",
                files={"image": ("notes.txt", b"not-an-image", "text/plain")},
                data={
                    "conversation_id": "conversation-a",
                    "trace_id": trace["trace_id"],
                },
            )
            assert rejected.status_code == 400
            snapshot = client.get(f"/traces/{trace['trace_id']}").json()
            assert snapshot["status"] == "failed"
    finally:
        application.app.dependency_overrides.clear()
