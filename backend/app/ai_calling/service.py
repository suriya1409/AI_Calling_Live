"""
AI Calling Service - User Isolation & Standalone Models Integrated
==================
Core service for handling AI-powered phone calls using Vonage, Sarvam AI, and Gemini
"""

import os
import json
import base64
import uuid
import time
import jwt
import wave
import struct
import threading
from io import BytesIO
from datetime import datetime
from queue import Queue
import re

import requests
from vonage import Vonage, Auth

# Import Gemini SDK
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    print("⚠️  WARNING: google-genai not installed. Install with: pip install google-genai")
    GEMINI_AVAILABLE = False

from config import settings

# Import standalone model functions
from app.table_models.call_sessions import create_call_session
from app.table_models.borrowers_table import update_borrower

# ============================================================
# GLOBAL STORAGE
# ============================================================

call_data = {}
audio_cache = {}

# Initialize Vonage client
try:
    vonage_client = Vonage(Auth(
        application_id=settings.VONAGE_APPLICATION_ID,
        private_key=settings.VONAGE_PRIVATE_KEY_PATH
    ))
    voice = vonage_client.voice
    print("[VONAGE] ✅ Vonage Voice client initialized")
except Exception as e:
    print(f"[VONAGE] ⚠️  Failed to initialize: {e}")
    vonage_client = None
    voice = None

# Initialize Gemini AI client
gemini_client = None
if GEMINI_AVAILABLE and settings.GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        print("[GEMINI] ✅ Gemini AI client initialized")
    except Exception as e:
        print(f"[GEMINI] ⚠️  Failed to initialize: {e}")
        gemini_client = None
else:
    print("[GEMINI] ⚠️  Gemini not configured - AI analysis will be disabled")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def generate_jwt_token():
    """Generate JWT token for Vonage API"""
    try:
        with open(settings.VONAGE_PRIVATE_KEY_PATH, 'rb') as key_file:
            private_key = key_file.read()
        
        payload = {
            'application_id': settings.VONAGE_APPLICATION_ID,
            'iat': int(time.time()),
            'exp': int(time.time()) + 3600,
            'jti': str(uuid.uuid4())
        }
        
        return jwt.encode(payload, private_key, algorithm='RS256')
    except Exception as e:
        print(f"[JWT] Error: {e}")
        return None


# ============================================================
# GEMINI AI ANALYSIS
# ============================================================

def analyze_conversation_with_gemini(conversation):
    """
    Analyze conversation using Gemini AI to extract summary, sentiment, and intent.
    """
    
    if not gemini_client:
        print("[GEMINI] ⚠️  Gemini client not available, skipping analysis")
        return {
            "summary": "AI analysis not available - Gemini API not configured",
            "sentiment": "Neutral",
            "sentiment_reasoning": "Analysis skipped",
            "intent": "No Response",
            "intent_reasoning": "Analysis skipped",
            "payment_date": None
        }
    
    # Prepare conversation text
    conversation_text = "\n".join([
        f"{entry['speaker']}: {entry['text']}" 
        for entry in conversation
    ])
    
    prompt = f"""You are an AI analyst reviewing a phone conversation between a collection agent (AI) and a borrower (User).

Analyze this conversation and provide:

1. **SUMMARY**: A concise 2-3 sentence summary of what was discussed.

2. **SENTIMENT**: Classify as Positive, Neutral, or Negative.

3. **INTENT**: Classify as Paid, Will Pay, Needs Extension, Dispute, or No Response.

CONVERSATION:
{conversation_text}

Respond in JSON format only:
{{
    "summary": "...",
    "sentiment": "...",
    "sentiment_reasoning": "...",
    "intent": "...",
    "intent_reasoning": "...",
    "payment_date": "YYYY-MM-DD or null"
}}"""
    
    # Add retry logic for 429 Resource Exhausted
    max_retries = 5
    base_delay = 3
    
    for attempt in range(max_retries):
        try:
            print(f"\n[GEMINI] 🤖 Starting AI analysis (Attempt {attempt+1}/{max_retries})...")
            
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            response_text = response.text.strip()
            
            # Clean JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            analysis = json.loads(response_text)
            print(f"[GEMINI] ✅ Analysis completed successfully")
            return analysis

        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
                continue
            
            print(f"[GEMINI] ❌ Analysis error: {e}")
            return {
                "summary": "Unable to analyze conversation",
                "sentiment": "Neutral",
                "intent": "No Response"
            }
    
    return {"summary": "Analysis failed", "sentiment": "Neutral", "intent": "No Response"}


# ============================================================
# SARVAM AI - STT/TTS
# ============================================================

def transcribe_sarvam(audio_data, language="en-IN", max_retries=2):
    """Transcribe audio using Sarvam AI STT"""
    if len(audio_data) < 2000: # Very short audio
        return None
    
    for attempt in range(max_retries):
        try:
            # Convert raw PCM audio to WAV format
            wav_buffer = BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(audio_data)
            
            wav_buffer.seek(0)
            
            headers = {'api-subscription-key': settings.SARVAM_API_KEY}
            files = {'file': ('audio.wav', wav_buffer, 'audio/wav')}
            data = {'language_code': language, 'model': 'saarika:v2.5'}
            
            response = requests.post(
                'https://api.sarvam.ai/speech-to-text',
                headers=headers,
                files=files,
                data=data,
                timeout=10
            )
            
            if response.status_code == 200:
                transcript = response.json().get('transcript', '')
                if transcript: return transcript
            
        except Exception as e:
            print(f"[STT] ❌ Error: {e}")
            if attempt < max_retries - 1: time.sleep(0.5)
            
    return None


def synthesize_sarvam(text, language="en-IN", max_retries=2):
    """Convert text to speech using Sarvam AI TTS"""
    if not text: return None
        
    for attempt in range(max_retries):
        try:
            config = settings.LANGUAGE_CONFIG.get(language, {})
            speaker = config.get('speaker', 'manisha')
            
            headers = {
                'api-subscription-key': settings.SARVAM_API_KEY,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'inputs': [text],
                'target_language_code': language,
                'speaker': speaker,
                'pitch': 0,
                'pace': 1.0,
                'loudness': 1.5,
                'speech_sample_rate': 16000,
                'model': 'bulbul:v2'
            }
            
            response = requests.post(
                'https://api.sarvam.ai/text-to-speech',
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                audio_base64 = response.json().get('audios', [None])[0]
                if audio_base64: return base64.b64decode(audio_base64)
                
        except Exception as e:
            print(f"[TTS] ❌ Error: {e}")
            if attempt < max_retries - 1: time.sleep(0.5)
            
    return None


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):
    """Simple language detection based on character sets"""
    text = text.strip()
    if re.search(r'[\u0900-\u097F]', text): return "hi-IN"
    if re.search(r'[\u0B80-\u0BFF]', text): return "ta-IN"
    return "en-IN"


# ============================================================
# AUDIO BUFFERING
# ============================================================

class AudioBuffer:
    """Buffer audio chunks and detect silence"""
    
    def __init__(self, silence_threshold=300, silence_duration=1.2):
        self.buffer = BytesIO()
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.silence_start = None
        self.speech_detected = False
        self.min_speech_duration = 0.6
        
    def add_chunk(self, audio_chunk):
        """Add audio chunk and detect if ready to process"""
        self.buffer.write(audio_chunk)
        current_time = time.time()
        
        try:
            samples = struct.unpack(f'{len(audio_chunk)//2}h', audio_chunk)
            rms = sum(abs(s) for s in samples) / len(samples) if samples else 0
        except: rms = 0
        
        if rms >= self.silence_threshold:
            self.speech_detected = True
            self.silence_start = None
        
        if self.speech_detected and rms < self.silence_threshold:
            if self.silence_start is None:
                self.silence_start = current_time
            elif current_time - self.silence_start >= self.silence_duration:
                if self.buffer.tell() > (16000 * 2 * self.min_speech_duration):
                    return True
        
        if self.buffer.tell() > (16000 * 2 * 10): # 10s max
            if self.speech_detected: return True
        
        return False
    
    def get_audio(self):
        """Get buffered audio and reset"""
        audio_data = self.buffer.getvalue()
        self.buffer = BytesIO()
        self.silence_start = None
        self.speech_detected = False
        return audio_data


# ============================================================
# AI RESPONSE GENERATION
# ============================================================

def generate_ai_response(user_text, language="en-IN", context=None):
    """Generate AI response using Gemini with User context"""
    FALLBACKS = {
        "en-IN": "I'm sorry, I'm having a bit of trouble hearing you. Could you repeat that?",
        "hi-IN": "क्षमा करें, मुझे आपकी बात सुनने में कठिनाई हो रही है। क्या आप दोहरा सकते हैं?",
        "ta-IN": "மன்னிக்கவும், உங்கள் பேச்சைக் கேட்பதில் சிரமம் உள்ளது. மீண்டும் கூற முடியுமா?"
    }
    
    if not gemini_client:
        return FALLBACKS.get(language, FALLBACKS["en-IN"])
    
    conv_history = ""
    if context and "conversation" in context:
        conv_history = "\n".join([f"{e['speaker']}: {e['text']}" for e in context["conversation"][-5:]])
    
    sys_prompts = {
        "en-IN": "You are a professional collection assistant named Vidya. Respond in English brief (1-2 sentences).",
        "hi-IN": "आप एक वित्त एजेंसी की वसूली सहायक 'विद्या' हैं। हिंदी में संक्षिप्त जवाब दें।",
        "ta-IN": "நீங்கள் நிதி நிறுவனத்தின் வசூல் உதவியாளர் 'வித்யா'. தமிழில் சுருக்கமாக பதிலளிக்கவும்."
    }
    
    prompt = f"{sys_prompts.get(language, sys_prompts['en-IN'])}\n\nHistory:\n{conv_history}\n\nUser: {user_text}\n\nAI:"
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=200)
        )
        return response.text.strip()
    except:
        return FALLBACKS.get(language, FALLBACKS["en-IN"])

# ============================================================
# CONVERSATION HANDLER
# ============================================================

class ConversationHandler:
    """Manages conversation state and transcript with USER ISOLATION"""
    
    def __init__(self, call_uuid, user_id=None, preferred_language="en-IN", borrower_id=None):
        self.call_uuid = call_uuid
        self.user_id = user_id
        self.borrower_id = borrower_id
        self.conversation = []
        self.context = {}
        self.is_active = True
        self.start_time = datetime.now()
        self.preferred_language = preferred_language
        self.current_language = preferred_language
        self.language_history = []
        
    def add_entry(self, speaker, text):
        entry = {
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "language": self.current_language
        }
        self.conversation.append(entry)
        self.context["conversation"] = self.conversation
        print(f"[CONV] [{self.user_id}] [{speaker}] {text}")
    
    def update_language(self, detected_language):
        if detected_language != self.current_language:
            self.language_history.append({
                "from": self.current_language,
                "to": detected_language,
                "timestamp": datetime.now().isoformat()
            })
            self.current_language = detected_language
    
    async def save_transcript(self):
        """Save transcript using standalone model functions with User Isolation"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        ai_analysis = analyze_conversation_with_gemini(self.conversation) if len(self.conversation) > 1 else {
            "summary": "No meaningful conversation detected",
            "sentiment": "No Response",
            "intent": "No Response"
        }
        
        transcript_data = {
            "call_uuid": self.call_uuid,
            "user_id": self.user_id,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_seconds": round(duration, 2),
            "preferred_language": self.preferred_language,
            "final_language": self.current_language,
            "conversation": self.conversation,
            "ai_analysis": ai_analysis
        }
        
        # Save to MongoDB using isolated model functions
        try:
            # Note: create_call_session is async, and we are in an async function
            await create_call_session(self.user_id, transcript_data)
            
            # Update Borrower if ID exists
            if self.borrower_id and self.user_id:
                await update_borrower(self.user_id, self.borrower_id, {
                    "call_completed": True,
                    "call_in_progress": False,
                    "transcript": self.conversation,
                    "ai_summary": ai_analysis.get('summary', 'Done')
                })
        except Exception as e:
            print(f"[DB] ❌ Isolated Save Error: {e}")
        
        return f"transcript_{self.call_uuid}.json"


# ============================================================
# CALL MANAGEMENT
# ============================================================

def make_outbound_call(user_id, to_number, language="en-IN", borrower_id=None):
    """Trigger an isolated outbound call passing user_id to webhooks"""
    if not voice:
        return {"success": False, "error": "Vonage client not initialized"}
    
    if to_number.startswith('+'): to_number = to_number[1:]
    
    try:
        # Include user_id in answer URL for isolation in the webhook handler
        answer_url = f'{settings.BASE_URL}/webhooks/answer?preferred_language={language}&user_id={user_id}'
        if borrower_id:
            answer_url += f'&borrower_id={borrower_id}'
        
        response = voice.create_call({
            'to': [{'type': 'phone', 'number': to_number}],
            'from_': {'type': 'phone', 'number': settings.VONAGE_FROM_NUMBER},
            'answer_url': [answer_url],
            'event_url': [f'{settings.BASE_URL}/webhooks/event']
        })
        
        return {
            "success": True,
            "call_uuid": response.uuid,
            "status": "initiated",
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"[ERROR] Outbound Error: {e}")
        return {"success": False, "error": str(e)}

def get_call_data_store():
    return call_data