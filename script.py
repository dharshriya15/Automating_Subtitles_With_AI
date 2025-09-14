import os
import requests
import time
import uuid
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
from moviepy import VideoFileClip, TextClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip
import datetime
from groq import Groq
import subprocess
from pydub import AudioSegment
import threading
import json

app = FastAPI(
    title="Video Subtitle API",
    description="API for adding subtitles to videos using AI transcription",
    version="1.0.0"
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
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm'}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs('temp', exist_ok=True)

# AssemblyAI API key
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

# Store processing status
processing_status: Dict[str, Dict[str, Any]] = {}

# Pydantic models
class JobStatus(BaseModel):
    status: str
    message: str
    filename: str = None
    uploaded_at: str = None

class UploadResponse(BaseModel):
    job_id: str
    message: str
    status_url: str

class ErrorResponse(BaseModel):
    error: str

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_llama_response(prompt: str) -> str:
    """Improved LLM response handling with retry logic"""
    max_retries = 3
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    all_responses = ""     
    for attempt in range(max_retries):
        try:
            full_prompt = f"{prompt}"
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{
                    "role": "user",
                    "content": full_prompt,
                }],
                temperature=1, 
                top_p=1,
                stream=True,
                stop=None,
            )
            for chunk in response:
                content = chunk.choices[0].delta.content or ""
                all_responses += content 
            return all_responses
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

def transcribe_video_to_srt(video_path: str, srt_path: str, job_id: str) -> bool:
    """
    Transcribes the audio from a video file and saves it as an SRT subtitle file using AssemblyAI.
    """
    try:
        processing_status[job_id]['status'] = 'extracting_audio'
        processing_status[job_id]['message'] = 'Extracting audio from video...'
        
        # Extract audio with ffmpeg
        temp_audio_wav = f"temp/temp_audio_{job_id}.wav"
        temp_audio_mp3 = f"temp/output_audio_{job_id}.mp3"
        
        subprocess.call(["ffmpeg", "-i", video_path, temp_audio_wav, "-y"])
        
        # Convert to MP3
        audio = AudioSegment.from_wav(temp_audio_wav)
        audio.export(temp_audio_mp3, format="mp3")
        
        headers = {"authorization": ASSEMBLYAI_API_KEY}
        
        processing_status[job_id]['status'] = 'uploading'
        processing_status[job_id]['message'] = 'Uploading audio to AssemblyAI...'
        
        def upload_file(filename):
            with open(filename, "rb") as f:
                response = requests.post("https://api.assemblyai.com/v2/upload", headers=headers, data=f)
            response.raise_for_status()
            return response.json()["upload_url"]

        upload_url = upload_file(temp_audio_mp3)
        
        processing_status[job_id]['status'] = 'transcribing'
        processing_status[job_id]['message'] = 'Requesting transcription...'
        
        transcript_request = {
            "audio_url": upload_url,
            "speech_model": "universal",
            "language_detection": True, 
        }
        response = requests.post("https://api.assemblyai.com/v2/transcript", json=transcript_request, headers=headers)
        resp_json = response.json()
        
        if "id" not in resp_json:
            processing_status[job_id]['status'] = 'error'
            processing_status[job_id]['message'] = f"Error: No 'id' found in AssemblyAI response. Response: {resp_json}"
            return False
            
        transcript_id = resp_json["id"]
        
        processing_status[job_id]['message'] = 'Waiting for transcription to complete...'
        
        # Poll for completion
        poll_response = requests.get(f"https://api.assemblyai.com/v2/transcript/{transcript_id}/srt", headers=headers)
        
        while poll_response.status_code != 200:
            processing_status[job_id]['message'] = 'Transcription in progress... waiting 10 seconds.'
            time.sleep(10)
            poll_response = requests.get(f"https://api.assemblyai.com/v2/transcript/{transcript_id}/srt", headers=headers)
        
        processing_status[job_id]['status'] = 'translating'
        processing_status[job_id]['message'] = 'Converting to English SRT format...'
        
        response = get_llama_response(f"Convert the following subtitles to English SRT format:\n{poll_response.text} Important: Ensure the SRT format is strictly followed with correct numbering, timestamps, and text formatting. Do not add any extra commentary or explanations, just provide the SRT content.")
        
        if response:
            with open(srt_path, "w", encoding="utf-8") as srt_file:
                srt_file.write(response)
        
        # Cleanup temp files
        if os.path.exists(temp_audio_wav):
            os.remove(temp_audio_wav)
        if os.path.exists(temp_audio_mp3):
            os.remove(temp_audio_mp3)
            
        return True
        
    except Exception as e:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = f'Error during transcription: {str(e)}'
        return False

def embed_subtitles_into_video(video_path: str, srt_path: str, output_path: str, job_id: str) -> bool:
    """
    Embeds an SRT subtitle file into a video file using moviepy.
    """
    try:
        if not os.path.exists(srt_path):
            processing_status[job_id]['status'] = 'error'
            processing_status[job_id]['message'] = f"Error: Subtitle file '{srt_path}' not found."
            return False

        processing_status[job_id]['status'] = 'embedding'
        processing_status[job_id]['message'] = 'Embedding subtitles into video...'
        
        # Load the video clip
        video = VideoFileClip(video_path)
        
        # Create a subtitle generator function for MoviePy
        def generator(txt):
            return TextClip(
                font=r"C:\Windows\Fonts\arial.ttf", 
                text=txt,
                font_size=24,
                color='white',
                stroke_color='black',
                stroke_width=1,
                bg_color='black'
            )
        
        # Create the subtitle clip from the SRT file using the generator
        subtitles = SubtitlesClip(srt_path, make_textclip=generator, encoding="utf-8")
        
        # Overlay the subtitles on the video
        final_video = CompositeVideoClip([video, subtitles.with_position(('center', video.size[1]*0.8))])
        
        processing_status[job_id]['status'] = 'rendering'
        processing_status[job_id]['message'] = 'Rendering final video file. This may take a while...'
        
        # Write the final video file
        final_video.write_videofile(
            output_path, 
            codec="libx264", 
            audio_codec="aac",
            logger=None
        )
        
        # Close video objects to free memory
        video.close()
        final_video.close()
        
        processing_status[job_id]['status'] = 'completed'
        processing_status[job_id]['message'] = 'Process completed successfully!'
        
        return True
        
    except Exception as e:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = f'Error during video processing: {str(e)}'
        return False

def process_video_async(video_path: str, job_id: str):
    """Process video in background thread"""
    try:
        srt_path = os.path.join(PROCESSED_FOLDER, f"{job_id}.srt")
        output_path = os.path.join(PROCESSED_FOLDER, f"{job_id}_with_subtitles.mp4")
        
        # Transcribe video to SRT
        if transcribe_video_to_srt(video_path, srt_path, job_id):
            # Embed subtitles into video
            embed_subtitles_into_video(video_path, srt_path, output_path, job_id)
        
    except Exception as e:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = f'Unexpected error: {str(e)}'

@app.get("/", response_model=dict)
async def root():
    """API information and available endpoints"""
    return {
        'message': 'Video Subtitle API',
        'endpoints': {
            'POST /upload': 'Upload a video file for subtitle processing',
            'GET /status/{job_id}': 'Check processing status',
            'GET /download/{job_id}': 'Download processed video',
            'GET /download/{job_id}/srt': 'Download SRT file',
            'GET /jobs': 'List all processing jobs',
            'GET /docs': 'API documentation (Swagger UI)',
            'GET /redoc': 'API documentation (ReDoc)'
        }
    }

@app.post("/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(..., description="Video file to process")
):
    """Upload a video file for subtitle processing"""
    
    # Check if file is provided
    if not video.filename:
        raise HTTPException(status_code=400, detail="No file selected")
    
    # Check file type
    if not allowed_file(video.filename):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Allowed: mp4, avi, mov, mkv, wmv, flv, webm"
        )
    
    # Check file size
    if hasattr(video, 'size') and video.size > MAX_CONTENT_LENGTH:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 500MB")
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded file
    file_extension = video.filename.rsplit('.', 1)[1].lower()
    video_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.{file_extension}")
    
    try:
        with open(video_path, "wb") as buffer:
            content = await video.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Initialize processing status
    processing_status[job_id] = {
        'status': 'queued',
        'message': 'Video uploaded successfully, processing queued...',
        'filename': video.filename,
        'uploaded_at': datetime.datetime.now().isoformat()
    }
    
    # Start background processing
    background_tasks.add_task(process_video_async, video_path, job_id)
    
    return UploadResponse(
        job_id=job_id,
        message="Video uploaded successfully, processing started",
        status_url=f"/status/{job_id}"
    )

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    """Check the processing status of a job"""
    if job_id not in processing_status:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    return JobStatus(**processing_status[job_id])

@app.get("/download/{job_id}")
async def download_video(job_id: str):
    """Download the processed video with subtitles"""
    if job_id not in processing_status:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    if processing_status[job_id]['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Processing not completed yet")
    
    output_path = os.path.join(PROCESSED_FOLDER, f"{job_id}_with_subtitles.mp4")
    
    if not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Processed video file not found")
    
    return FileResponse(
        path=output_path,
        media_type='video/mp4',
        filename=f"{job_id}_with_subtitles.mp4"
    )

@app.get("/download/{job_id}/srt")
async def download_srt(job_id: str):
    """Download the SRT subtitle file"""
    if job_id not in processing_status:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    if processing_status[job_id]['status'] not in ['completed', 'embedding', 'rendering']:
        raise HTTPException(status_code=400, detail="SRT file not ready yet")
    
    srt_path = os.path.join(PROCESSED_FOLDER, f"{job_id}.srt")
    
    if not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="SRT file not found")
    
    return FileResponse(
        path=srt_path,
        media_type='text/plain',
        filename=f"{job_id}.srt"
    )

@app.get("/jobs", response_model=dict)
async def list_jobs():
    """List all processing jobs and their statuses"""
    return processing_status

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated files"""
    if job_id not in processing_status:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    # Remove files
    files_to_remove = [
        os.path.join(UPLOAD_FOLDER, f"{job_id}.*"),
        os.path.join(PROCESSED_FOLDER, f"{job_id}.srt"),
        os.path.join(PROCESSED_FOLDER, f"{job_id}_with_subtitles.mp4")
    ]
    
    for file_pattern in files_to_remove:
        import glob
        for file_path in glob.glob(file_pattern):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error removing file {file_path}: {e}")
    
    # Remove from processing status
    del processing_status[job_id]
    
    return {"message": f"Job {job_id} and associated files deleted successfully"}

# Exception handlers
@app.exception_handler(413)
async def request_entity_too_large_handler(request, exc):
    return JSONResponse(
        status_code=413,
        content={"error": "File too large. Maximum size is 500MB"}
    )

@app.exception_handler(500)
async def internal_server_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        "script:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info"
    )