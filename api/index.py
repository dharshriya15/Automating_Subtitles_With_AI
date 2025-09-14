import os
import requests
import time
import uuid
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import datetime
from groq import Groq
import io

### Create FastAPI instance with custom docs and openapi url
app = FastAPI(
    title="Video Subtitle API",
    description="Serverless API for video transcription and subtitle generation",
    version="1.0.0",
    docs_url="/docs", 
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'mp3', 'wav'}
MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB max file size for serverless

# In-memory job storage (use Redis/Database in production)
processing_jobs: Dict[str, Dict[str, Any]] = {}

# Pydantic models
class JobStatus(BaseModel):
    job_id: str
    status: str
    message: str
    filename: Optional[str] = None
    created_at: str
    srt_content: Optional[str] = None
    download_url: Optional[str] = None

class TranscriptionRequest(BaseModel):
    audio_url: str
    language: Optional[str] = "auto"

class TranscriptionResponse(BaseModel):
    job_id: str
    status: str
    message: str

class TranslateSRTRequest(BaseModel):
    srt_content: str
    target_language: str = "English"

class TranslateSRTResponse(BaseModel):
    original_content: str
    translated_content: str
    target_language: str

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None

def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_llama_response(prompt: str) -> Optional[str]:
    """Get response from Groq/Llama with retry logic"""
    max_retries = 2
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{
                    "role": "user",
                    "content": prompt,
                }],
                temperature=0.7,
                max_tokens=4000,
                stream=False,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    return None

async def upload_to_assemblyai(file_content: bytes) -> str:
    """Upload file to AssemblyAI and return upload URL"""
    headers = {"authorization": os.getenv("ASSEMBLYAI_API_KEY")}
    
    try:
        response = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers=headers,
            data=file_content,
            timeout=60
        )
        response.raise_for_status()
        return response.json()["upload_url"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

async def request_transcription(upload_url: str) -> str:
    """Request transcription from AssemblyAI"""
    headers = {"authorization": os.getenv("ASSEMBLYAI_API_KEY")}
    
    transcript_request = {
        "audio_url": upload_url,
        "speech_model": "universal",
        "language_detection": True,
        "punctuate": True,
        "format_text": True
    }
    
    try:
        response = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            json=transcript_request,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        resp_json = response.json()
        
        if "id" not in resp_json:
            raise HTTPException(status_code=500, detail="Invalid AssemblyAI response")
            
        return resp_json["id"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription request failed: {str(e)}")

async def get_transcription_result(transcript_id: str, max_wait: int = 300) -> str:
    """Poll for transcription completion and return SRT content"""
    headers = {"authorization": os.getenv("ASSEMBLYAI_API_KEY")}
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            # Check status first
            status_response = requests.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers=headers,
                timeout=30
            )
            status_response.raise_for_status()
            status_data = status_response.json()
            
            if status_data["status"] == "completed":
                # Get SRT format
                srt_response = requests.get(
                    f"https://api.assemblyai.com/v2/transcript/{transcript_id}/srt",
                    headers=headers,
                    timeout=30
                )
                if srt_response.status_code == 200:
                    return srt_response.text
                else:
                    # Fallback: convert from segments
                    return convert_to_srt(status_data.get("words", []))
                    
            elif status_data["status"] == "error":
                raise HTTPException(status_code=500, detail="Transcription failed")
                
            # Wait before next poll
            await asyncio.sleep(5)
            
        except Exception as e:
            if time.time() - start_time > max_wait - 30:  # Don't retry in last 30 seconds
                raise HTTPException(status_code=500, detail=f"Transcription polling failed: {str(e)}")
            await asyncio.sleep(5)
    
    raise HTTPException(status_code=408, detail="Transcription timeout")

def convert_to_srt(words: list) -> str:
    """Convert word-level timestamps to SRT format"""
    if not words:
        return ""
    
    srt_content = ""
    subtitle_index = 1
    current_text = ""
    start_time = None
    
    for i, word in enumerate(words):
        if start_time is None:
            start_time = word.get("start", 0)
        
        current_text += word.get("text", "") + " "
        
        # Create subtitle every ~5 seconds or 10 words
        if (i + 1) % 10 == 0 or i == len(words) - 1:
            end_time = word.get("end", word.get("start", 0) + 1)
            
            start_srt = format_time_srt(start_time)
            end_srt = format_time_srt(end_time)
            
            srt_content += f"{subtitle_index}\n"
            srt_content += f"{start_srt} --> {end_srt}\n"
            srt_content += f"{current_text.strip()}\n\n"
            
            subtitle_index += 1
            current_text = ""
            start_time = None
    
    return srt_content

def format_time_srt(seconds: float) -> str:
    """Convert seconds to SRT time format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

@app.get("/")
async def root():
    """API information and available endpoints"""
    return {
        "message": "Serverless Video Subtitle API",
        "version": "1.0.0",
        "endpoints": {
            "POST /transcribe": "Upload audio/video for transcription",
            "GET /status/{job_id}": "Check transcription status",
            "GET /download/{job_id}": "Download SRT file",
            "POST /translate-srt": "Translate existing SRT content",
            "GET /jobs": "List recent jobs",
            "GET /docs": "API documentation (Swagger UI)"
        },
        "limits": {
            "max_file_size": "25MB",
            "supported_formats": list(ALLOWED_EXTENSIONS),
            "max_duration": "10 minutes (recommended)"
        }
    }

@app.get("/hello")
def hello_fast_api():
    """Test endpoint to verify API is working"""
    return {"message": "Hello from Video Subtitle API", "status": "healthy"}

@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_file(
    file: UploadFile = File(..., description="Audio or video file to transcribe")
):
    """Upload and transcribe an audio/video file"""
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    if not allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Check API keys
    if not os.getenv("ASSEMBLYAI_API_KEY"):
        raise HTTPException(status_code=500, detail="AssemblyAI API key not configured")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    try:
        # Read file content
        file_content = await file.read()
        
        if len(file_content) > MAX_CONTENT_LENGTH:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 25MB")
        
        # Initialize job
        processing_jobs[job_id] = {
            "job_id": job_id,
            "status": "uploading",
            "message": "Uploading file to transcription service...",
            "filename": file.filename,
            "created_at": datetime.datetime.now().isoformat(),
            "srt_content": None
        }
        
        # Upload to AssemblyAI
        upload_url = await upload_to_assemblyai(file_content)
        
        processing_jobs[job_id].update({
            "status": "transcribing",
            "message": "Transcription in progress..."
        })
        
        # Request transcription
        transcript_id = await request_transcription(upload_url)
        
        # Wait for completion (with timeout)
        srt_content = await get_transcription_result(transcript_id)
        
        # Update job with results
        processing_jobs[job_id].update({
            "status": "completed",
            "message": "Transcription completed successfully",
            "srt_content": srt_content,
            "download_url": f"/download/{job_id}"
        })
        
        return TranscriptionResponse(
            job_id=job_id,
            status="completed",
            message="Transcription completed successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # Update job with error
        if job_id in processing_jobs:
            processing_jobs[job_id].update({
                "status": "error",
                "message": f"Transcription failed: {str(e)}"
            })
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get the status of a transcription job"""
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatus(**processing_jobs[job_id])

@app.get("/download/{job_id}")
async def download_srt(job_id: str):
    """Download the SRT file for a completed job"""
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = processing_jobs[job_id]
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Transcription not completed")
    
    if not job.get("srt_content"):
        raise HTTPException(status_code=404, detail="SRT content not available")
    
    return StreamingResponse(
        io.BytesIO(job["srt_content"].encode('utf-8')),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={job_id}.srt"}
    )

@app.post("/translate-srt", response_model=TranslateSRTResponse)
async def translate_srt_content(request: TranslateSRTRequest):
    """Translate SRT content to specified language using Groq"""
    if not request.srt_content.strip():
        raise HTTPException(status_code=400, detail="No SRT content provided")
    
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="Groq API key not configured")
    
    try:
        prompt = f"""
        Translate the following SRT subtitle content to {request.target_language}. 
        Maintain the exact SRT format with timestamps and numbering.
        Only translate the text content, keep all timing information unchanged.
        
        SRT Content:
        {request.srt_content}
        """
        
        translated_content = get_llama_response(prompt)
        
        if not translated_content:
            raise HTTPException(status_code=500, detail="Translation failed")
        
        return TranslateSRTResponse(
            original_content=request.srt_content,
            translated_content=translated_content,
            target_language=request.target_language
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation error: {str(e)}")

@app.get("/jobs")
async def list_jobs():
    """List recent transcription jobs"""
    return {
        "total_jobs": len(processing_jobs),
        "jobs": list(processing_jobs.values())
    }

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job from memory"""
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    del processing_jobs[job_id]
    return {"message": f"Job {job_id} deleted successfully"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "version": "1.0.0",
        "environment": {
            "assemblyai_configured": bool(os.getenv("ASSEMBLYAI_API_KEY")),
            "groq_configured": bool(os.getenv("GROQ_API_KEY"))
        }
    }

# Exception handlers
@app.exception_handler(413)
async def request_entity_too_large_handler(request, exc):
    return JSONResponse(
        status_code=413,
        content={"error": "File too large", "max_size": "25MB"}
    )

@app.exception_handler(500)
async def internal_server_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )