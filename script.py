import os
import requests
import time
import uuid
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from moviepy import VideoFileClip, TextClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip
import datetime
from groq import Groq
# from python_dotenv import load_dotenv
import subprocess
from pydub import AudioSegment
import threading
import json

# load_dotenv()

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm'}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROCESSED_FOLDER'] = PROCESSED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs('temp', exist_ok=True)

# AssemblyAI API key
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

# Store processing status
processing_status = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_llama_response(prompt):
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

def transcribe_video_to_srt(video_path, srt_path, job_id):
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

def embed_subtitles_into_video(video_path, srt_path, output_path, job_id):
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

def process_video_async(video_path, job_id):
    """Process video in background thread"""
    try:
        srt_path = os.path.join(app.config['PROCESSED_FOLDER'], f"{job_id}.srt")
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], f"{job_id}_with_subtitles.mp4")
        
        # Transcribe video to SRT
        if transcribe_video_to_srt(video_path, srt_path, job_id):
            # Embed subtitles into video
            embed_subtitles_into_video(video_path, srt_path, output_path, job_id)
        
    except Exception as e:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = f'Unexpected error: {str(e)}'

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'message': 'Video Subtitle API',
        'endpoints': {
            'POST /upload': 'Upload a video file for subtitle processing',
            'GET /status/<job_id>': 'Check processing status',
            'GET /download/<job_id>': 'Download processed video',
            'GET /download/<job_id>/srt': 'Download SRT file'
        }
    })

@app.route('/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        file_extension = filename.rsplit('.', 1)[1].lower()
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}.{file_extension}")
        file.save(video_path)
        
        # Initialize processing status
        processing_status[job_id] = {
            'status': 'queued',
            'message': 'Video uploaded successfully, processing queued...',
            'filename': filename,
            'uploaded_at': datetime.datetime.now().isoformat()
        }
        
        # Start background processing
        thread = threading.Thread(target=process_video_async, args=(video_path, job_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'job_id': job_id,
            'message': 'Video uploaded successfully, processing started',
            'status_url': f'/status/{job_id}'
        }), 202
    
    return jsonify({'error': 'Invalid file type. Allowed: mp4, avi, mov, mkv, wmv, flv, webm'}), 400

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if job_id not in processing_status:
        return jsonify({'error': 'Job ID not found'}), 404
    
    return jsonify(processing_status[job_id])

@app.route('/download/<job_id>', methods=['GET'])
def download_video(job_id):
    if job_id not in processing_status:
        return jsonify({'error': 'Job ID not found'}), 404
    
    if processing_status[job_id]['status'] != 'completed':
        return jsonify({'error': 'Processing not completed yet'}), 400
    
    output_path = os.path.join(app.config['PROCESSED_FOLDER'], f"{job_id}_with_subtitles.mp4")
    
    if not os.path.exists(output_path):
        return jsonify({'error': 'Processed video file not found'}), 404
    
    return send_file(output_path, as_attachment=True, download_name=f"{job_id}_with_subtitles.mp4")

@app.route('/download/<job_id>/srt', methods=['GET'])
def download_srt(job_id):
    if job_id not in processing_status:
        return jsonify({'error': 'Job ID not found'}), 404
    
    if processing_status[job_id]['status'] not in ['completed', 'embedding', 'rendering']:
        return jsonify({'error': 'SRT file not ready yet'}), 400
    
    srt_path = os.path.join(app.config['PROCESSED_FOLDER'], f"{job_id}.srt")
    
    if not os.path.exists(srt_path):
        return jsonify({'error': 'SRT file not found'}), 404
    
    return send_file(srt_path, as_attachment=True, download_name=f"{job_id}.srt")

@app.route('/jobs', methods=['GET'])
def list_jobs():
    """List all processing jobs and their statuses"""
    return jsonify(processing_status)

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 500MB'}), 413

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)