import os
import uuid
from typing import Optional, List
import threading
import time
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Response, Cookie, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

import uvicorn
import requests
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from elevenlabs.client import ElevenLabs

from config import Config
from agents.agent_decision import process_query, sync_validation_to_model
from agents.artifacts import (
    PRIVATE_ARTIFACT_ROOT,
    cleanup_expired_artifacts,
    resolve_private_artifact,
)
from agents.conversation_store import conversation_store
from agents.execution_trace import (
    TraceAlreadyUsedError,
    TraceCancelledError,
    execution_trace_store,
)
from agents.security import CurrentUser, get_current_user, resolve_conversation_id
from agents.validation_store import validation_store
from agents.local_auth import local_auth_store
from agents.upload_limits import UploadBodyLimitMiddleware
from agents.request_admission import RequestAdmissionMiddleware
from agents.concurrency import conversation_lifecycle_locks, conversation_locks
from agents.checkpoint import delete_conversation_checkpoint

# Load configuration
config = Config()

# Initialize FastAPI app from the single release-version source.
APP_VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
app = FastAPI(title="Multi-Agent Medical Chatbot", version=APP_VERSION)

# Queue expensive routes asynchronously before dependencies or handlers borrow
# worker threads. CORS remains outermost so rejection responses are readable.
app.add_middleware(
    RequestAdmissionMiddleware,
    max_active=config.api.max_concurrent_agent_requests,
    max_queued=config.api.max_queued_requests,
    wait_seconds=config.api.request_queue_timeout_seconds,
)

# CORS middleware for cross-origin requests (e.g. Live Server on port 5500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include a small allowance for multipart headers and accompanying fields.
app.add_middleware(
    UploadBodyLimitMiddleware,
    limits={
        "/upload": config.api.max_image_upload_size * 1024 * 1024 + 64 * 1024,
        "/transcribe": config.api.max_audio_upload_size * 1024 * 1024 + 64 * 1024,
    },
)

# Set up directories
UPLOAD_FOLDER = "uploads/backend"
SPEECH_DIR = "uploads/speech"

# Create directories if they don't exist
for directory in [UPLOAD_FOLDER, PRIVATE_ARTIFACT_ROOT, SPEECH_DIR]:
    os.makedirs(directory, exist_ok=True)

# Source documents cited by RAG answers. Only these extensions are served, and
# only from directly inside this root.
RAW_DOCS_ROOT = Path(os.getenv("RAW_DOCS_ROOT", "data/raw")).resolve()
SOURCE_DOCUMENT_EXTENSIONS = {".pdf"}

# Figures extracted from those documents, cited as reference images in RAG
# answers (see reranker._picture_url).
PARSED_DOCS_ROOT = Path(config.rag.parsed_content_dir).resolve()
REFERENCE_IMAGE_EXTENSIONS = {".png"}

FRONTEND_DIST = Path("frontend/dist")
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"
app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS, check_dir=False), name="frontend-assets")

# Initialize ElevenLabs client
client = ElevenLabs(
    api_key=config.speech.eleven_labs_api_key,
)

# Define allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    """Check if file has an allowed extension"""
    return bool(filename and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)

def _safe_unlink(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        print(f"Could not delete temporary file {path}: {exc}")


def _cleanup_expired_files(directory: str | Path, ttl_seconds: int) -> int:
    root = Path(directory)
    if ttl_seconds <= 0 or not root.exists():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for path in root.iterdir():
        try:
            if (
                path.is_file()
                and not path.name.startswith(".")
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def cleanup_expired_private_files():
    """Periodically delete only private files older than their retention TTL."""
    while True:
        time.sleep(300)
        try:
            ttl = config.api.private_artifact_ttl_seconds
            removed = cleanup_expired_artifacts(ttl)
            removed += _cleanup_expired_files(SPEECH_DIR, ttl)
            if removed:
                print(f"Cleaned up {removed} expired private files.")
        except Exception as e:
            print(f"Error during cleanup: {e}")

# Start background cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_private_files, daemon=True)
cleanup_thread.start()

class QueryRequest(BaseModel):
    query: str
    conversation_history: List = []
    conversation_id: Optional[str] = None
    trace_id: Optional[str] = None


class TraceStartRequest(BaseModel):
    conversation_id: Optional[str] = None

class SpeechRequest(BaseModel):
    # Falls back to the configured voice instead of a placeholder id, which the
    # speech API would reject for any client that omits the field.
    text: str
    voice_id: str = config.speech.eleven_labs_voice_id


class LocalLoginRequest(BaseModel):
    username: str
    password: str


class LocalRegisterRequest(BaseModel):
    username: str
    password: str


class ConversationRenameRequest(BaseModel):
    title: str

@app.get("/")
async def index():
    """Serve the React frontend built by Vite."""
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=503, detail="React frontend is not built. Run `cd frontend && npm run build`.")
    return FileResponse(FRONTEND_INDEX)

@app.get("/health")
def health_check():
    """Health check endpoint for Docker health checks"""
    return {"status": "healthy"}


@app.get("/auth/me")
def auth_me(current_user: CurrentUser = Depends(get_current_user)):
    """Validate the upstream OAuth/OIDC access token and expose its subject."""
    return {"authenticated": True, "user_id": current_user.user_id}


@app.post("/auth/login")
def auth_login(request: LocalLoginRequest, response: Response):
    """Local-only login for small trusted test deployments."""
    if os.getenv("AUTH_MODE", "local").lower() != "local":
        raise HTTPException(status_code=404, detail="Local authentication is disabled")
    user_id = local_auth_store.authenticate(request.username, request.password)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    session_id = local_auth_store.create_session(user_id)
    secure = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
    response.set_cookie(
        key="med_agent_session",
        value=session_id,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(os.getenv("LOCAL_AUTH_SESSION_TTL", str(12 * 3600))),
    )
    return {"authenticated": True, "user_id": user_id}


@app.post("/auth/register")
def auth_register(request: LocalRegisterRequest, response: Response):
    """Register and sign in a local account for small trusted test deployments."""
    if os.getenv("AUTH_MODE", "local").lower() != "local":
        raise HTTPException(status_code=404, detail="Local authentication is disabled")
    try:
        user_id = local_auth_store.register(request.username, request.password)
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "already registered" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    session_id = local_auth_store.create_session(user_id)
    secure = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
    response.set_cookie(
        key="med_agent_session",
        value=session_id,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(os.getenv("LOCAL_AUTH_SESSION_TTL", str(12 * 3600))),
    )
    return {"authenticated": True, "user_id": user_id}


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    local_auth_store.revoke_session(request.cookies.get("med_agent_session"))
    response.delete_cookie("med_agent_session")
    response.delete_cookie("conversation_id")
    return {"authenticated": False}


def _agent_response_payload(response_data: dict, conversation_id: str) -> dict:
    validation_id = response_data.get("validation_id")
    result = {
        "status": "success",
        "response": response_data["messages"][-1].content,
        "agent": response_data["agent_name"],
        "conversation_id": conversation_id,
        "validation_id": validation_id,
        "requires_validation": bool(validation_id),
        "execution_trace": response_data.get("execution_trace"),
    }
    if validation_id and response_data.get("result_image_path"):
        result["result_image"] = f"/validations/{validation_id}/image"
    return result


# Mirrors the placeholder the frontend shows for an image sent without text.
IMAGE_ONLY_QUERY = "已上传 1 张待分析图像，请系统直接开始识别。"


def _record_turn(
    *,
    user_id: str,
    conversation_id: str,
    query: str,
    payload: dict,
    has_image: bool = False,
) -> None:
    """Persist one request/answer pair so the sidebar can replay the thread.

    History is a convenience layer: a storage failure must never discard an
    answer the user is already waiting for, so it is logged server-side and
    the response still goes out.
    """
    try:
        conversation_store.append(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=query or (IMAGE_ONLY_QUERY if has_image else ""),
            has_image=has_image,
        )
        conversation_store.append(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=payload.get("response") or "",
            agent=payload.get("agent"),
            status_label="已返回",
            result_image=payload.get("result_image"),
            validation_request_id=payload.get("validation_id"),
        )
    except Exception:
        import traceback
        traceback.print_exc()


def _process_turn(query, *, user_id, conversation_id, trace_id, has_image=False):
    """Serialize model execution and history writes against conversation deletion."""
    with conversation_lifecycle_locks.hold(f"{user_id}:{conversation_id}"):
        conversation_store.check_access(conversation_id, user_id=user_id)
        result = process_query(
            query, user_id=user_id, conversation_id=conversation_id, trace_id=trace_id,
            history_loader=lambda limit: conversation_store.get_recent_messages(
                conversation_id, user_id=user_id, limit=limit
            ),
        )
        payload = _agent_response_payload(result, conversation_id)
        _record_turn(
            user_id=user_id,
            conversation_id=conversation_id,
            query=query.get("text", "") if isinstance(query, dict) else query,
            payload=payload,
            has_image=has_image,
        )
        return payload


@app.get("/conversations")
def list_conversations(current_user: CurrentUser = Depends(get_current_user)):
    """List the signed-in user's saved threads, most recently used first."""
    return {"conversations": conversation_store.list_for_user(current_user.user_id)}


@app.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        messages = conversation_store.get_messages(
            conversation_id, user_id=current_user.user_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Conversation belongs to another user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    for message in messages:
        validation_id = message.pop("validation_request_id", None)
        # Older image answers already contain the review ID in their private
        # image URL; retain support for these pre-migration history rows.
        image_url = message.get("result_image") or ""
        if not validation_id and image_url.startswith("/validations/") and image_url.endswith("/image"):
            validation_id = image_url[len("/validations/"):-len("/image")]
        message["requires_validation"] = False
        message["validation_id"] = None
        if message["role"] != "assistant" or not validation_id:
            continue
        try:
            record = validation_store.get_for_user(validation_id, user_id=current_user.user_id)
        except KeyError:
            continue
        if record.conversation_id != conversation_id:
            continue
        message["validation_id"] = validation_id
        message["requires_validation"] = record.status == "pending"
    return {"conversation_id": conversation_id, "messages": messages}


@app.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    request: ConversationRenameRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return conversation_store.rename(
            conversation_id, user_id=current_user.user_id, title=request.title
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Conversation belongs to another user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Title must not be empty") from exc


@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        thread_id = f"{current_user.user_id}:{conversation_id}"
        with conversation_lifecycle_locks.hold(thread_id), conversation_locks.hold(thread_id):
            conversation_store.check_access(conversation_id, user_id=current_user.user_id, require_exists=True)
            validation_store.delete_for_conversation(
                user_id=current_user.user_id, conversation_id=conversation_id
            )
            delete_conversation_checkpoint(thread_id)
            conversation_store.delete(conversation_id, user_id=current_user.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Conversation belongs to another user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    return {"status": "deleted", "conversation_id": conversation_id}


@app.post("/traces")
def create_execution_trace(
    request: TraceStartRequest,
    response: Response,
    http_request: Request,
    current_user: CurrentUser = Depends(get_current_user),
):
    conversation_id = resolve_conversation_id(http_request, request.conversation_id)
    trace = execution_trace_store.create(
        user_id=current_user.user_id, conversation_id=conversation_id
    )
    response.set_cookie(
        key="conversation_id",
        value=conversation_id,
        httponly=True,
        samesite="lax",
    )
    return trace


@app.get("/traces/{trace_id}")
def get_execution_trace(
    trace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return execution_trace_store.get_for_user(
            trace_id, user_id=current_user.user_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Execution trace not found")


@app.post("/traces/{trace_id}/cancel")
def cancel_execution_trace(
    trace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Ask a running graph to unwind at its next node boundary."""
    try:
        return execution_trace_store.cancel_for_user(
            trace_id, user_id=current_user.user_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Execution trace not found")


@app.post("/chat")
async def chat(
    request: QueryRequest, 
    response: Response, 
    http_request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_id: Optional[str] = Cookie(None)
):
    """Process user text query through the multi-agent system."""
    # Generate session ID for cookie if it doesn't exist
    if not session_id:
        session_id = str(uuid.uuid4())
    
    conversation_id = resolve_conversation_id(http_request, request.conversation_id)
    try:
        payload = await run_in_threadpool(
            _process_turn,
            request.query,
            user_id=current_user.user_id,
            conversation_id=conversation_id,
            trace_id=request.trace_id,
        )
        
        # Set session cookie
        response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax")
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")

        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Conversation belongs to another user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Execution trace not found") from exc
    except TraceAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail="Execution trace has already been used") from exc
    except TraceCancelledError as exc:
        # The user hit stop; this is an expected unwind, not a server fault.
        raise HTTPException(status_code=409, detail="Execution trace was cancelled") from exc
    except Exception:
        # Log the cause server-side; the client gets a generic message so
        # gateway URLs, model names and file paths are not leaked.
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Unable to process the query")

@app.post("/upload")
async def upload_image(
    response: Response,
    request: Request,
    image: UploadFile = File(...), 
    text: str = Form(""),
    conversation_id: Optional[str] = Form(None),
    trace_id: Optional[str] = Form(None),
    current_user: CurrentUser = Depends(get_current_user),
    session_id: Optional[str] = Cookie(None)
):
    """Process medical image uploads with optional text input."""
    # Validate file type
    if not allowed_file(image.filename):
        execution_trace_store.fail_for_user(
            trace_id, user_id=current_user.user_id
        )
        return JSONResponse(
            status_code=400, 
            content={
                "status": "error",
                "agent": "System",
                "response": "Unsupported file type. Allowed formats: PNG, JPG, JPEG"
            }
        )
    
    # Check file size before saving
    file_content = await image.read(config.api.max_image_upload_size * 1024 * 1024 + 1)
    if len(file_content) > config.api.max_image_upload_size * 1024 * 1024:  # Convert MB to bytes
        execution_trace_store.fail_for_user(
            trace_id, user_id=current_user.user_id
        )
        return JSONResponse(
            status_code=413, 
            content={
                "status": "error",
                "agent": "System",
                "response": f"File too large. Maximum size allowed: {config.api.max_image_upload_size}MB"
            }
        )
    
    # Generate session ID for cookie if it doesn't exist
    if not session_id:
        session_id = str(uuid.uuid4())
    conversation_id = resolve_conversation_id(request, conversation_id)
    
    # Save file securely
    filename = secure_filename(f"{uuid.uuid4()}_{image.filename}")
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    try:
        await run_in_threadpool(Path(file_path).write_bytes, file_content)
        query = {"text": text, "image": file_path}
        payload = await run_in_threadpool(
            _process_turn,
            query,
            user_id=current_user.user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            has_image=True,
        )

        # Set session cookie
        response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax")
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")

        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Conversation belongs to another user") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Execution trace not found") from exc
    except TraceAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail="Execution trace has already been used") from exc
    except TraceCancelledError as exc:
        # The user hit stop; this is an expected unwind, not a server fault.
        raise HTTPException(status_code=409, detail="Execution trace was cancelled") from exc
    except Exception:
        import traceback
        traceback.print_exc()
        execution_trace_store.fail_for_user(
            trace_id, user_id=current_user.user_id
        )
        raise HTTPException(status_code=500, detail="Unable to process the image")
    finally:
        await run_in_threadpool(_safe_unlink, file_path)

@app.post("/validate")
def validate_medical_output(
    response: Response,
    request: Request,
    validation_result: str = Form(...), 
    comments: Optional[str] = Form(None),
    validation_id: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    current_user: CurrentUser = Depends(get_current_user),
    session_id: Optional[str] = Cookie(None)
):
    """Handle human validation for medical AI outputs."""
    # Generate session ID for cookie if it doesn't exist
    if not session_id:
        session_id = str(uuid.uuid4())
    conversation_id = resolve_conversation_id(request, conversation_id)

    try:
        # Set session cookie
        response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax")
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")
        with conversation_lifecycle_locks.hold(f"{current_user.user_id}:{conversation_id}"):
            conversation_store.check_access(
                conversation_id, user_id=current_user.user_id, require_exists=True
            )
            record = validation_store.resolve(
                validation_id,
                user_id=current_user.user_id,
                conversation_id=conversation_id,
                result=validation_result,
                comments=comments,
                reviewer_id=current_user.user_id,
            )
            approved = record.status == "approved"
            result = {
                "status": "validated" if approved else "rejected",
                "message": "**Output confirmed by human validator:**" if approved else "**Output requires further review:**",
                "response": record.original_output if approved else "The previous medical analysis requires further review.",
                "validation_id": validation_id,
                "conversation_id": conversation_id,
            }
            if not approved:
                result["comments"] = record.comments
            sync_validation_to_model(record)
            conversation_store.append_validation(
                user_id=current_user.user_id,
                conversation_id=conversation_id,
                validation_id=validation_id,
                content="\n\n".join(part for part in (result["message"], result["response"]) if part),
                status_label="已确认" if approved else "需复查",
            )
            return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Validation does not belong to this user or conversation") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Validation request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Unable to record the validation")


@app.get("/data/raw/{filename}")
def get_source_document(
    filename: str,
    _current_user: CurrentUser = Depends(get_current_user),
):
    """Serve a cited source document to signed-in users.

    RAG answers cite their sources as links under ``/data/raw/...`` (see
    vectorstore_qdrant._source_url), but nothing served that path, so every
    citation was a dead link. Only regular files directly inside the raw
    document root are returned, and only for allowed extensions.
    """
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Source document not found")
    if Path(filename).suffix.lower() not in SOURCE_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Source document not found")

    candidate = (RAW_DOCS_ROOT / filename).resolve()
    try:
        candidate.relative_to(RAW_DOCS_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="Source document not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Source document not found")

    return FileResponse(
        path=candidate,
        media_type="application/pdf",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/data/parsed_docs/{filename}")
def get_reference_image(
    filename: str,
    _current_user: CurrentUser = Depends(get_current_user),
):
    """Serve a figure cited by a RAG answer, to signed-in users only."""
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Reference image not found")
    if Path(filename).suffix.lower() not in REFERENCE_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Reference image not found")

    candidate = (PARSED_DOCS_ROOT / filename).resolve()
    try:
        candidate.relative_to(PARSED_DOCS_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="Reference image not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Reference image not found")

    return FileResponse(
        path=candidate,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/validations/{validation_id}/image")
def get_validation_image(
    validation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Return a private result image only to the validation owner."""
    try:
        record = validation_store.get_for_user(
            validation_id, user_id=current_user.user_id
        )
        if not record.result_image_path:
            raise FileNotFoundError("artifact_not_found")
        artifact_path = resolve_private_artifact(record.result_image_path)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Result image not found")
    return FileResponse(
        path=artifact_path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )

def _transcribe_audio_sync(source_path: Path, mp3_path: Path) -> str:
    converted = AudioSegment.from_file(source_path)
    converted.export(mp3_path, format="mp3")
    audio_data = mp3_path.read_bytes()
    transcription = client.speech_to_text.convert(
        file=audio_data,
        model_id="scribe_v1",
        tag_audio_events=True,
        language_code="eng",
        diarize=True,
    )
    if not transcription.text:
        raise RuntimeError("Speech service returned an empty transcript")
    return transcription.text


@app.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    _current_user: CurrentUser = Depends(get_current_user),
):
    """Transcribe a private temporary audio upload."""
    if not audio.filename:
        return JSONResponse(status_code=400, content={"error": "No audio file selected"})
    max_audio_bytes = config.api.max_audio_upload_size * 1024 * 1024
    audio_content = await audio.read(max_audio_bytes + 1)
    if len(audio_content) > max_audio_bytes:
        return JSONResponse(status_code=413, content={"error": "Audio file too large"})
    if not audio_content:
        return JSONResponse(status_code=400, content={"error": "Received empty audio file"})

    source_path = Path(SPEECH_DIR) / f"speech_{uuid.uuid4().hex}.webm"
    mp3_path = Path(SPEECH_DIR) / f"speech_{uuid.uuid4().hex}.mp3"
    try:
        await run_in_threadpool(source_path.write_bytes, audio_content)
        transcript = await run_in_threadpool(
            _transcribe_audio_sync, source_path, mp3_path
        )
        return {"transcript": transcript}
    except Exception as exc:
        print(f"Transcription error: {exc}")
        return JSONResponse(status_code=500, content={"error": "Unable to transcribe audio"})
    finally:
        await run_in_threadpool(_safe_unlink, source_path)
        await run_in_threadpool(_safe_unlink, mp3_path)


def _generate_speech_sync(text: str, selected_voice_id: str, output_path: Path) -> None:
    elevenlabs_url = f"https://api.elevenlabs.io/v1/text-to-speech/{selected_voice_id}/stream"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": config.speech.eleven_labs_api_key,
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.5},
    }
    service_response = requests.post(
        elevenlabs_url, headers=headers, json=payload, timeout=60
    )
    service_response.raise_for_status()
    output_path.write_bytes(service_response.content)


@app.post("/generate-speech")
async def generate_speech(
    request: SpeechRequest,
    _current_user: CurrentUser = Depends(get_current_user),
):
    """Endpoint to generate speech using ElevenLabs API"""
    try:
        if not request.text:
            return JSONResponse(
                status_code=400,
                content={"error": "Text is required"}
            )
        temp_audio_path = Path(SPEECH_DIR) / f"{uuid.uuid4().hex}.mp3"
        await run_in_threadpool(
            _generate_speech_sync,
            request.text,
            request.voice_id,
            temp_audio_path,
        )

        return FileResponse(
            path=temp_audio_path,
            media_type="audio/mpeg",
            filename="generated_speech.mp3",
            background=BackgroundTask(_safe_unlink, temp_audio_path),
        )

    except Exception as exc:
        if "temp_audio_path" in locals():
            await run_in_threadpool(_safe_unlink, temp_audio_path)
        print(f"Speech generation error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to generate speech"}
        )

# Oversized uploads are already rejected inside /upload, which returns this
# same payload directly; a 413 exception handler never fired and was removed.

if __name__ == "__main__":
    uvicorn.run(app, host=config.api.host, port=config.api.port)
