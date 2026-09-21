from fastapi.testclient import TestClient

from agents.security import CurrentUser, get_current_user
import app as application


def _as_user(user_id="user-a"):
    application.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, claims={"sub": user_id}
    )


def test_source_document_is_served_to_signed_in_users(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "RAW_DOCS_ROOT", tmp_path.resolve())
    (tmp_path / "study.pdf").write_bytes(b"%PDF-1.4 fake")

    _as_user()
    try:
        with TestClient(application.app) as client:
            response = client.get("/data/raw/study.pdf")
            assert response.status_code == 200
            assert response.content == b"%PDF-1.4 fake"
            assert response.headers["cache-control"].startswith("private")
    finally:
        application.app.dependency_overrides.clear()


def test_source_document_requires_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "RAW_DOCS_ROOT", tmp_path.resolve())
    (tmp_path / "study.pdf").write_bytes(b"%PDF-1.4 fake")

    application.app.dependency_overrides.clear()
    with TestClient(application.app) as client:
        assert client.get("/data/raw/study.pdf").status_code == 401


def test_reference_image_is_served_and_guarded(tmp_path, monkeypatch):
    root = tmp_path / "parsed"
    root.mkdir()
    (root / "study-picture-0.png").write_bytes(b"\x89PNG fake")
    (root / "notes.txt").write_text("not an image")
    (tmp_path / "secret.png").write_bytes(b"\x89PNG secret")
    monkeypatch.setattr(application, "PARSED_DOCS_ROOT", root.resolve())

    _as_user()
    try:
        with TestClient(application.app) as client:
            ok = client.get("/data/parsed_docs/study-picture-0.png")
            assert ok.status_code == 200
            assert ok.content == b"\x89PNG fake"
            assert ok.headers["cache-control"].startswith("private")

            for attempt in ("../secret.png", "..%2Fsecret.png", "notes.txt"):
                assert client.get(f"/data/parsed_docs/{attempt}").status_code == 404, attempt
    finally:
        application.app.dependency_overrides.clear()


def test_reference_image_requires_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "PARSED_DOCS_ROOT", tmp_path.resolve())
    (tmp_path / "study-picture-0.png").write_bytes(b"\x89PNG fake")

    application.app.dependency_overrides.clear()
    with TestClient(application.app) as client:
        assert client.get("/data/parsed_docs/study-picture-0.png").status_code == 401


def test_source_document_rejects_traversal_and_other_extensions(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    root.mkdir()
    (root / "study.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "notes.txt").write_text("not a pdf")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-1.4 secret")
    monkeypatch.setattr(application, "RAW_DOCS_ROOT", root.resolve())

    _as_user()
    try:
        with TestClient(application.app) as client:
            # Escaping the root must not reach a sibling file.
            for attempt in (
                "../secret.pdf",
                "..%2Fsecret.pdf",
                "%2e%2e%2fsecret.pdf",
                "sub/study.pdf",
            ):
                assert client.get(f"/data/raw/{attempt}").status_code == 404, attempt
            # Non-whitelisted extensions stay private.
            assert client.get("/data/raw/notes.txt").status_code == 404
            # The legitimate file still works.
            assert client.get("/data/raw/study.pdf").status_code == 200
    finally:
        application.app.dependency_overrides.clear()
