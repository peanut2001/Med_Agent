import os
import uuid
import tempfile
from typing import Dict, Union, Optional, List
import glob
import threading
import time
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Response, Cookie, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import uvicorn
import requests
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from elevenlabs.client import ElevenLabs

from config import Config
from agents.agent_decision import process_query
from agents.security import CurrentUser, get_current_user, resolve_conversation_id
from agents.validation_store import validation_store
from agents.local_auth import local_auth_store

# Load configuration
config = Config()

# Initialize FastAPI app
app = FastAPI(title="Multi-Agent Medical Chatbot", version="2.0")

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

# Set up directories
UPLOAD_FOLDER = "uploads/backend"
FRONTEND_UPLOAD_FOLDER = "uploads/frontend"
SKIN_LESION_OUTPUT = "uploads/skin_lesion_output"
SPEECH_DIR = "uploads/speech"

# Create directories if they don't exist
for directory in [UPLOAD_FOLDER, FRONTEND_UPLOAD_FOLDER, SKIN_LESION_OUTPUT, SPEECH_DIR]:
    os.makedirs(directory, exist_ok=True)

# Mount static files directory
app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

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
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_audio():
    """Deletes all .mp3 files in the uploads/speech folder every 5 minutes."""
    while True:
        try:
            files = glob.glob(f"{SPEECH_DIR}/*.mp3")
            for file in files:
                os.remove(file)
            print("Cleaned up old speech files.")
        except Exception as e:
            print(f"Error during cleanup: {e}")
        time.sleep(300)  # Runs every 5 minutes

# Start background cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_audio, daemon=True)
cleanup_thread.start()

class QueryRequest(BaseModel):
    query: str
    conversation_history: List = []
    conversation_id: Optional[str] = None

class SpeechRequest(BaseModel):
    text: str
    voice_id: str = "EXAMPLE_VOICE_ID"  # Default voice ID


class LocalLoginRequest(BaseModel):
    username: str
    password: str

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


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    local_auth_store.revoke_session(request.cookies.get("med_agent_session"))
    response.delete_cookie("med_agent_session")
    return {"authenticated": False}

@app.post("/chat")
def chat(
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
        response_data = process_query(
            request.query,
            user_id=current_user.user_id,
            conversation_id=conversation_id,
        )
        response_text = response_data['messages'][-1].content
        
        # Set session cookie
        response.set_cookie(key="session_id", value=session_id)
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")

        # Check if the agent is skin lesion segmentation and find the image path
        result = {
            "status": "success",
            "response": response_text, 
            "agent": response_data["agent_name"],
            "conversation_id": conversation_id,
            "validation_id": response_data.get("validation_id"),
            "requires_validation": bool(response_data.get("validation_id")),
        }
        
        # If it's the skin lesion segmentation agent, check for output image
        if response_data["agent_name"] == "SKIN_LESION_AGENT, HUMAN_VALIDATION":
            segmentation_path = os.path.join(SKIN_LESION_OUTPUT, "segmentation_plot.png")
            if os.path.exists(segmentation_path):
                result["result_image"] = f"/uploads/skin_lesion_output/segmentation_plot.png"
            else:
                print("Skin Lesion Output path does not exist.")
        
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_image(
    response: Response,
    request: Request,
    image: UploadFile = File(...), 
    text: str = Form(""),
    conversation_id: Optional[str] = Form(None),
    current_user: CurrentUser = Depends(get_current_user),
    session_id: Optional[str] = Cookie(None)
):
    """Process medical image uploads with optional text input."""
    # Validate file type
    if not allowed_file(image.filename):
        return JSONResponse(
            status_code=400, 
            content={
                "status": "error",
                "agent": "System",
                "response": "Unsupported file type. Allowed formats: PNG, JPG, JPEG"
            }
        )
    
    # Check file size before saving
    file_content = await image.read()
    if len(file_content) > config.api.max_image_upload_size * 1024 * 1024:  # Convert MB to bytes
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
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    try:
        query = {"text": text, "image": file_path}
        response_data = process_query(
            query,
            user_id=current_user.user_id,
            conversation_id=conversation_id,
        )
        response_text = response_data['messages'][-1].content

        # Set session cookie
        response.set_cookie(key="session_id", value=session_id)
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")

        # Check if the agent is skin lesion segmentation and find the image path
        result = {
            "status": "success",
            "response": response_text, 
            "agent": response_data["agent_name"],
            "conversation_id": conversation_id,
            "validation_id": response_data.get("validation_id"),
            "requires_validation": bool(response_data.get("validation_id")),
        }
        
        # If it's the skin lesion segmentation agent, check for output image
        if response_data["agent_name"] == "SKIN_LESION_AGENT, HUMAN_VALIDATION":
            segmentation_path = os.path.join(SKIN_LESION_OUTPUT, "segmentation_plot.png")
            if os.path.exists(segmentation_path):
                result["result_image"] = f"/uploads/skin_lesion_output/segmentation_plot.png"
            else:
                print("Skin Lesion Output path does not exist.")
        
        # Remove temporary file after sending
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Failed to remove temporary file: {str(e)}")
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        response.set_cookie(key="session_id", value=session_id)
        response.set_cookie(key="conversation_id", value=conversation_id, httponly=True, samesite="lax")
        record = validation_store.resolve(
            validation_id,
            user_id=current_user.user_id,
            conversation_id=conversation_id,
            result=validation_result,
            comments=comments,
        )

        if record.status == 'approved':
            return {
                "status": "validated",
                "message": "**Output confirmed by human validator:**",
                "response": record.original_output,
                "validation_id": validation_id,
                "conversation_id": conversation_id,
            }
        else:
            return {
                "status": "rejected",
                "comments": comments,
                "message": "**Output requires further review:**",
                "response": "The previous medical analysis requires further review.",
                "validation_id": validation_id,
                "conversation_id": conversation_id,
            }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Validation does not belong to this user or conversation") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Validation request not found") from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Endpoint to transcribe speech using ElevenLabs API"""
    if not audio.filename:
        return JSONResponse(
            status_code=400,
            content={"error": "No audio file selected"}
        )
    
    try:
        # Save the audio file temporarily
        os.makedirs(SPEECH_DIR, exist_ok=True)
        temp_audio = f"./{SPEECH_DIR}/speech_{uuid.uuid4()}.webm"
        
        # Read and save the file
        audio_content = await audio.read()
        with open(temp_audio, "wb") as f:
            f.write(audio_content)
        
        # Debug: Print file size to check if it's empty
        file_size = os.path.getsize(temp_audio)
        print(f"Received audio file size: {file_size} bytes")
        
        if file_size == 0:
            return JSONResponse(
                status_code=400,
                content={"error": "Received empty audio file"}
            )
        
        # Convert to MP3
        mp3_path = f"./{SPEECH_DIR}/speech_{uuid.uuid4()}.mp3"
        
        try:
            # Use pydub with format detection
            audio = AudioSegment.from_file(temp_audio)
            audio.export(mp3_path, format="mp3")
            
            # Debug: Print MP3 file size
            mp3_size = os.path.getsize(mp3_path)
            print(f"Converted MP3 file size: {mp3_size} bytes")

            with open(mp3_path, "rb") as mp3_file:
                audio_data = mp3_file.read()
            print(f"Converted audio file into byte array successfully!")

            transcription = client.speech_to_text.convert(
                file=audio_data,
                model_id="scribe_v1",
                tag_audio_events=True,
                language_code="eng",
                diarize=True,
            )
            
            # Clean up temp files
            try:
                os.remove(temp_audio)
                os.remove(mp3_path)
                print(f"Deleted temp files: {temp_audio}, {mp3_path}")
            except Exception as e:
                print(f"Could not delete file: {e}")
            
            if transcription.text:
                return {"transcript": transcription.text}
            else:
                return JSONResponse(
                    status_code=500,
                    content={"error": f"API error: {transcription}", "details": transcription.text}
                )

        except Exception as e:
            print(f"Error processing audio: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error processing audio: {str(e)}"}
            )
                
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/generate-speech")
async def generate_speech(request: SpeechRequest):
    """Endpoint to generate speech using ElevenLabs API"""
    try:
        text = request.text
        selected_voice_id = request.voice_id
        
        if not text:
            return JSONResponse(
                status_code=400,
                content={"error": "Text is required"}
            )
        
        # Define API request to ElevenLabs
        elevenlabs_url = f"https://api.elevenlabs.io/v1/text-to-speech/{selected_voice_id}/stream"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": config.speech.eleven_labs_api_key
        }
        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }

        # Send request to ElevenLabs API
        response = requests.post(elevenlabs_url, headers=headers, json=payload)

        if response.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to generate speech, status: {response.status_code}", "details": response.text}
            )
        
        # Save the audio file temporarily
        os.makedirs(SPEECH_DIR, exist_ok=True)
        temp_audio_path = f"./{SPEECH_DIR}/{uuid.uuid4()}.mp3"
        with open(temp_audio_path, "wb") as f:
            f.write(response.content)

        # Return the generated audio file
        return FileResponse(
            path=temp_audio_path,
            media_type="audio/mpeg",
            filename="generated_speech.mp3"
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# Add exception handler for request entity too large
@app.exception_handler(413)
async def request_entity_too_large(request, exc):
    return JSONResponse(
        status_code=413,
        content={
            "status": "error",
            "agent": "System",
            "response": f"File too large. Maximum size allowed: {config.api.max_image_upload_size}MB"
        }
    )

if __name__ == "__main__":
    uvicorn.run(app, host=config.api.host, port=config.api.port)
