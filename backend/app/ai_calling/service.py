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
import random
import asyncio

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

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    print("⚠️  WARNING: groq not installed. Install with: pip install groq")
    GROQ_AVAILABLE = False

# Configure logging
import logging
logger = logging.getLogger(__name__)

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
    # Use private key content string if available (for Render), otherwise fallback to file path
    p_key = settings.VONAGE_PRIVATE_KEY if settings.VONAGE_PRIVATE_KEY else settings.VONAGE_PRIVATE_KEY_PATH
    
    vonage_client = Vonage(Auth(
        application_id=settings.VONAGE_APPLICATION_ID,
        private_key=p_key
    ))
    voice = vonage_client.voice
    logger.info("[VONAGE] ✅ Vonage Voice client initialized")
except Exception as e:
    logger.error(f"[VONAGE] ⚠️  Failed to initialize: {e}")
    vonage_client = None
    voice = None

# Initialize Gemini AI client
gemini_client = None
if GEMINI_AVAILABLE and settings.GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info("[GEMINI] ✅ Gemini AI client initialized")
    except Exception as e:
        logger.error(f"[GEMINI] ⚠️  Failed to initialize: {e}")
        gemini_client = None
else:
    logger.warning("[GEMINI] ⚠️  Gemini not configured - AI analysis will be disabled")

# Initialize Groq AI client
groq_client = None
print(f"[DEBUG] GROQ_AVAILABLE: {GROQ_AVAILABLE}")
print(f"[DEBUG] settings.GROQ_API_KEY present: {bool(settings.GROQ_API_KEY)}")

if GROQ_AVAILABLE and settings.GROQ_API_KEY:
    if "your_groq_api_key_here" in settings.GROQ_API_KEY:
        logger.warning("[GROQ] ⚠️  Groq API key is still the placeholder. Please update .env")
    else:
        try:
            from groq import AsyncGroq
            groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            logger.info("[GROQ] ✅ Async Groq AI client initialized")
        except Exception as e:
            logger.error(f"[GROQ] ⚠️  Failed to initialize: {e}")
            groq_client = None
else:
    if not GROQ_AVAILABLE:
        print("[GROQ] ⚠️  Groq library not installed.")
    if not settings.GROQ_API_KEY:
        print("[GROQ] ⚠️  GROQ_API_KEY not found in settings.")
    print("[GROQ] ⚠️  Groq not configured - fallback analysis will be disabled")

# Initialize SYNC Groq client (for real-time responses in Flask sync context)
sync_groq_client = None
if GROQ_AVAILABLE and settings.GROQ_API_KEY and "your_groq_api_key_here" not in settings.GROQ_API_KEY:
    try:
        sync_groq_client = Groq(api_key=settings.GROQ_API_KEY)
        print("[GROQ] ✅ Sync Groq client initialized for real-time call responses")
    except Exception as e:
        print(f"[GROQ] ⚠️  Failed to initialize sync client: {e}")
        sync_groq_client = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

# Common Indian female first names for gender detection
_FEMALE_NAMES = {
    "shalini", "priya", "lakshmi", "deepa", "anita", "sunita", "kavita", "meena",
    "rekha", "neha", "pooja", "swati", "anjali", "divya", "sneha", "ritu",
    "nisha", "rani", "geeta", "seema", "mamta", "sapna", "jyoti", "suman",
    "padma", "vidya", "radha", "uma", "sarita", "asha", "usha", "kalpana",
    "shobha", "lata", "chitra", "kamala", "pushpa", "savita", "sudha", "mala",
    "aruna", "saroj", "indira", "parvati", "malini", "revathi", "bhavani",
    "devi", "gowri", "janaki", "kalyani", "meenakshi", "nirmala", "sarala",
    "vasanthi", "vijaya", "yamuna", "sumathi", "jayanthi", "lalitha", "rohini",
    "preeti", "shweta", "ankita", "pallavi", "shruti", "aishwarya", "bhavna",
    "manisha", "rashmi", "varsha", "alka", "komal", "tanvi", "ritika", "sakshi",
    "aarthi", "karthika", "nandhini", "vaishnavi", "harini", "sangeetha",
    "mythili", "bhuvana", "abinaya", "dhivya", "gayathri", "keerthana",
    "mathangi", "oviya", "priyanka", "ramya", "swetha", "thenmozhi", "vani",
    "amita", "garima", "heena", "ila", "juhi", "kiran", "laxmi", "madhu",
    "namita", "omana", "payal", "rachana", "sonal", "tara", "urmila", "vinita"
}

def detect_gender_from_name(name: str) -> str:
    """Detect gender from borrower name using common Indian name patterns.
    Returns 'female' or 'male' (defaults to male if uncertain)."""
    if not name:
        return "male"
    
    # Extract first name
    first_name = name.strip().split()[0].lower()
    
    # Check against known female names
    if first_name in _FEMALE_NAMES:
        return "female"
    
    # Heuristic: many Indian female names end in 'a', 'i', or 'i'
    # But this is unreliable, so we default to male for safety
    return "male"

def calculate_follow_up_schedule(category):
    """
    Calculate follow-up dates based on category (Skipping Weekends):
    - Consistent: 1 call next week (business day)
    - Inconsistent: 3 calls (next 3 business days)
    - Overdue: Daily (next 7 business days)
    """
    from datetime import timedelta
    today = datetime.now()
    dates = []
    
    category = (category or "").lower()
    
    if "inconsistent" in category:
        required_dates = 3
        desc = "3 calls/week"
    elif "overdue" in category:
        required_dates = 7
        desc = "Daily (Business Days)"
    else:
        # Consistent: Just 1 call approximately a week later
        required_dates = 1
        # Start looking from 7 days ahead
        today = today + timedelta(days=6) 
        desc = "1 call/week"
        
    current_date = today
    count = 0
    
    while count < required_dates:
        # Move to next day
        current_date += timedelta(days=1)
        
        # Check if Sat (5) or Sun (6)
        if current_date.weekday() >= 5:
            continue
            
        dates.append(current_date.strftime("%Y-%m-%d"))
        count += 1
        
    return ", ".join(dates), desc

def determine_report_outcomes(intent, payment_date, category, borrower_name="Borrower", borrower_id="", is_mid_call=False):
    """
    Centralized logic to determine:
    - payment_confirmation
    - follow_up_date
    - call_frequency
    - require_manual_process
    - email_to_manager_preview
    - next_step_summary
    """
    from datetime import datetime, timedelta
    
    intent = (intent or "No Response").strip()
    category = (category or "Consistent").strip()
    
    next_step_summary = ""
    email_draft = None
    require_manual_process = False
    payment_confirmation = intent
    
    # 1. Handle Dates & Freq
    if is_mid_call:
        # Re-trigger Next Day
        today = datetime.now()
        next_day = today + timedelta(days=1)
        if next_day.weekday() >= 5: # Skip to Monday
            next_day += timedelta(days=(7 - next_day.weekday()))
        follow_up_date = next_day.strftime("%Y-%m-%d")
        call_frequency = "1 call (Retry)"
        next_step_summary = "The borrower hung up mid-sentence. System scheduled a follow-up retry for the next business day."
    elif payment_date and payment_date.lower() != "null":
        payment_confirmation = payment_date
        follow_up_date = payment_date
        call_frequency = "1 call (Verify)"
    else:
        follow_up_date, call_frequency = calculate_follow_up_schedule(category)

    # 2. Logic for Manual Process & Email Previews
    escalation_intents = ["Paid", "Dispute", "No Response", "Abusive Language", "Threatening Language", "Stop Calling"]
    
    if intent in escalation_intents:
        require_manual_process = True
        
        if intent == "Paid":
            next_step_summary = f"Borrower {borrower_name} claims payment made. Please verify."
            subject = f"Payment Verification Required: {borrower_name}"
            body = f"Hi Area Manager,\n\nBorrower {borrower_name} ({borrower_id}) claims they have already paid. Please verify the transaction.\n\nBest regards,\nAI System"
        elif intent == "Dispute":
            next_step_summary = "Borrower is disputing the loan payment. Escalating for manual investigation."
            subject = f"Payment Dispute: {borrower_name}"
            body = f"Hi Area Manager,\n\nBorrower {borrower_name} ({borrower_id}) is disputing the loan amount/terms. Manual investigation required.\n\nBest regards,\nAI System"
        elif intent == "No Response":
            next_step_summary = "No clear response from borrower. Escalating for manual follow-up."
            subject = f"No Response Escalation: {borrower_name}"
            body = f"Hi Area Manager,\n\nWe could not get a clear response from {borrower_name} ({borrower_id}). Please follow up manually.\n\nBest regards,\nAI System"
        elif intent == "Abusive Language":
            next_step_summary = "Borrower used abusive language. Escalating for manual process."
            subject = f"Alert: Abusive Language - {borrower_name}"
            body = f"Hi Area Manager,\n\nBorrower {borrower_name} ({borrower_id}) was abusive during the call. Initiating manual handling.\n\nBest regards,\nAI System"
        elif intent == "Threatening Language":
            next_step_summary = "Borrower used threatening language. Escalating for manual process."
            subject = f"Security Alert: {borrower_name}"
            body = f"Hi Area Manager,\n\nBorrower {borrower_name} ({borrower_id}) was threatening. Please handle this case with priority.\n\nBest regards,\nAI System"
        elif intent == "Stop Calling":
            next_step_summary = "Borrower requested to stop calls. Escalating for manual process."
            subject = f"DNC Request: {borrower_name}"
            body = f"Hi Area Manager,\n\nBorrower {borrower_name} ({borrower_id}) requested to stop calling. Please update legal status.\n\nBest regards,\nAI System"
        
        email_draft = {"to": "Area Manager", "subject": subject, "body": body}

    elif intent == "Will Pay" or intent == "Needs Extension":
        require_manual_process = False
        email_draft = None
        if payment_date:
            next_step_summary = f"Borrower committed to pay/extend until {payment_date}."
        else:
            next_step_summary = f"Borrower committed to {intent}. Follow-up scheduled."

    return {
        "payment_confirmation": payment_confirmation,
        "follow_up_date": follow_up_date,
        "call_frequency": call_frequency,
        "require_manual_process": require_manual_process,
        "email_to_manager_preview": email_draft,
        "next_step_summary": next_step_summary
    }

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

async def analyze_conversation_with_gemini(conversation):
    """
    COMMENTED OUT GEMINI: FORCING GROQ FOR NOW
    """
    print("[AI ANALYSIS] 🔄 Forcing Groq fallback as requested...")
    return await analyze_conversation_with_groq(conversation)

    # if not gemini_client:
    #     print("[GEMINI] ⚠️  Gemini client not available, skipping analysis")
    #     return {
    #         "summary": "AI analysis not available - Gemini API not configured",
    #         "sentiment": "Neutral",
    #         "sentiment_reasoning": "Analysis skipped",
    #         "intent": "No Response",
    #         "intent_reasoning": "Analysis skipped",
    #         "payment_date": None
    #     }
    
    # # Prepare conversation text
    # conversation_text = "\n".join([
    #     f"{entry['speaker']}: {entry['text']}" 
    #     for entry in conversation
    # ])
    # 
    # prompt = f"""You are an AI analyst reviewing a phone conversation between a collection agent (AI) and a borrower (User).
    # 
    # Analyze this conversation and provide:
    # 
    # 1. **SUMMARY**: A concise 2-3 sentence summary of what was discussed.
    # 
    # 2. **SENTIMENT**: Classify as Positive, Neutral, or Negative.
    # 
    # 3. **INTENT**: Classify as one of the following:
    #    - **Paid**, **Will Pay**, **Needs Extension**, **Dispute**, **No Response**, **Abusive Language**, **Threatening Language**, **Stop Calling**.
    # 
    # 4. **MID_CALL**: Boolean (true/false). Set to true ONLY if the conversation ends abruptly or the borrower hangs up mid-sentence.
    # 
    # CONVERSATION:
    # {conversation_text}
    # 
    # Respond in JSON format only with these exact keys:
    # {{
    #     "summary": "...",
    #     "sentiment": "...",
    #     "sentiment_reasoning": "...",
    #     "intent": "...",
    #     "intent_reasoning": "...",
    #     "payment_date": "YYYY-MM-DD or null",
    #     "extension_date": "YYYY-MM-DD or null",
    #     "mid_call": true/false
    # }}"""
    # 
    # 
    # # Add retry logic for 429 Resource Exhausted
    # max_retries = 5
    # base_delay = 3
    # 
    # for attempt in range(max_retries):
    #     try:
    #         print(f"\n[GEMINI] 🤖 Starting AI analysis (Attempt {attempt+1}/{max_retries})...")
    #         
    #         # Use async version of generate_content
    #         response = await gemini_client.aio.models.generate_content(
    #             model='gemini-2.0-flash',
    #             contents=prompt
    #         )
    #         
    #         response_text = response.text.strip()
    #         
    #         # Clean JSON
    #         if "```json" in response_text:
    #             response_text = response_text.split("```json")[1].split("```")[0].strip()
    #         elif "```" in response_text:
    #             response_text = response_text.split("```")[1].split("```")[0].strip()
    #         
    #         analysis = json.loads(response_text)
    #         print(f"[GEMINI] ✅ Analysis completed successfully")
    #         return analysis
    # 
    #     except Exception as e:
    #         error_str = str(e).lower()
    #         if "429" in error_str or "resource_exhausted" in error_str:
    #             if attempt < max_retries - 1:
    #                 # Exponential backoff with random jitter to avoid thundering herd
    #                 delay = (base_delay * (2 ** attempt)) + random.uniform(0, 5)
    #                 print(f"[GEMINI] ⏳ Rate limit hit. Retrying in {delay:.1f}s...")
    #                 await asyncio.sleep(delay)
    #                 continue
    #             else:
    #                 print(f"[GEMINI] 🚨 Rate limit exhausted. Falling back to Groq...")
    #                 fallback = await analyze_conversation_with_groq(conversation)
    #                 if fallback: return fallback
    #         
    #         print(f"[GEMINI] ❌ Analysis error: {e}")
    #         
    #         if attempt < max_retries - 1:
    #             await asyncio.sleep(2)
    #             continue
    #         
    #         # Check if it's a 429 error and try fallback
    #         if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
    #             print(f"[GEMINI] 🚨 Rate limit hit. Attempting fallback to Groq...")
    #             fallback_analysis = await analyze_conversation_with_groq(conversation)
    #             if fallback_analysis:
    #                 return fallback_analysis
    #         
    #         return {
    #             "summary": "Unable to analyze conversation",
    #             "sentiment": "Neutral",
    #             "intent": "No Response"
    #         }
    # 
    # return {"summary": "Analysis failed", "sentiment": "Neutral", "intent": "No Response"}


async def analyze_conversation_with_groq(conversation):
    """
    Fallback analysis using Groq AI (Llama 3) when Gemini is unavailable or rate-limited.
    """
    
    if not groq_client:
        print("[GROQ] ⚠️  Groq client not available, skipping fallback analysis")
        return None
    
    # Prepare conversation text
    conversation_text = "\n".join([
        f"{entry['speaker']}: {entry['text']}" 
        for entry in conversation
    ])
    
    today_date = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt = f"""You are an AI analyst reviewing a phone conversation between a collection agent (AI) and a borrower (User).
    
    Current Date: {today_date}

Analyze this conversation and provide:
1. SUMMARY: A concise 2-3 sentence summary.
2. SENTIMENT: Positive, Neutral, or Negative.
3. INTENT: Paid, Will Pay, Needs Extension, Dispute, No Response, Abusive Language, Threatening Language, or Stop Calling.
4. PAYMENT_DATE: Extract EXACT date if mentioned (YYYY-MM-DD). handling "tomorrow", "next week", etc. relative to {today_date}. If no date, return null.
5. MID_CALL: Boolean (true/false). Set to true ONLY if the conversation ends abruptly or the borrower hangs up mid-sentence without a professional closing.

CONVERSATION:
{conversation_text}

Respond in JSON format only with these exact keys:
{{
    "summary": "...",
    "sentiment": "...",
    "intent": "...",
    "payment_date": "YYYY-MM-DD or null",
    "mid_call": true/false
}}"""

    
    try:
        print(f"\n[GROQ] 🤖 Starting fallback AI analysis...")
        
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that responds in JSON format."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        response_text = response.choices[0].message.content.strip()
        analysis = json.loads(response_text)
        print(f"[GROQ] ✅ Analysis completed successfully via fallback")
        return analysis

    except Exception as e:
        print(f"[GROQ] ❌ Fallback analysis error: {e}")
        return None


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
    
    def __init__(self, silence_threshold=500, silence_duration=1.8):
        self.buffer = BytesIO()
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.silence_start = None
        self.speech_detected = False
        self.min_speech_duration = 1.0
        
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

def is_farewell_response(text, language="en-IN"):
    """Detect if the AI response is a FINAL farewell/closing statement.
    
    IMPORTANT: This must be VERY strict to avoid cutting calls mid-conversation.
    Only match when the response is clearly a goodbye (end of conversation),
    NOT when it merely contains words like 'thank you' or 'update records' 
    as part of an ongoing exchange.
    
    Strategy: Check that farewell phrases appear at the END of the text (last part),
    and that the text does NOT contain follow-up questions (like 'Do you have any questions?').
    """
    text_lower = text.lower().strip()
    
    # If the response contains a question, it's NOT a farewell — the AI is still engaging
    question_indicators = ["?", "any questions", "anything else", "कोई सवाल", "कुछ और", "கேள்வி", "வேறு ஏதாவது"]
    if any(q in text_lower for q in question_indicators):
        return False
    
    # Only check the TAIL of the response for farewell patterns
    # This avoids matching "thank you for telling us" at the start of a longer response
    tail = text_lower[-80:] if len(text_lower) > 80 else text_lower
    
    # ── ENGLISH ──
    farewell_patterns_en = [
        "have a good day",
        "have a nice day", 
        "goodbye",
        "good bye",
        "take care",
    ]
    
    # ── HINDI ──
    # "दिन शुभ हो" = have a good day (very specific)
    # "अलविदा" = goodbye  
    # "ख्याल रखिए" = take care
    farewell_patterns_hi = [
        "दिन शुभ हो",
        "शुभ दिन",
        "अलविदा",
        "ख्याल रखिए",
        "ख्याल रखें",
    ]
    
    # ── TAMIL ──
    # "நல்ல நாள் வாழ்த்துகள்" = good day wishes (very specific)
    # "போய் வருகிறேன்" = goodbye (I'll go and come)
    # "நலமாக இருங்கள்" = be well / take care
    farewell_patterns_ta = [
        "நல்ல நாள் வாழ்த்துகள்",
        "நல்ல நாள்",
        "போய் வருகிறேன்",
        "நலமாக இருங்கள்",
    ]
    
    if language == "hi-IN":
        return any(p in tail for p in farewell_patterns_hi)
    elif language == "ta-IN":
        return any(p in tail for p in farewell_patterns_ta)
    else:
        return any(p in tail for p in farewell_patterns_en)


def generate_ai_response(user_text, language="en-IN", context=None):
    """Generate AI response for real-time calls. Uses sync Groq (primary) or Gemini (fallback).
    Follows a structured conversation flow with gender-aware greetings.
    Responses are kept SHORT (1-2 sentences max) for natural phone conversation flow."""
    FALLBACKS = {
        "en-IN": "I understand. Could you tell me more about your payment status?",
        "hi-IN": "मैं समझ रही हूं। कृपया अपने भुगतान की स्थिति बताएं?",
        "ta-IN": "புரிகிறது. உங்கள் கட்டண நிலை பற்றி கூறுங்கள்?"
    }
    
    conv_history = ""
    if context and "conversation" in context:
        conv_history = "\n".join([f"{e['speaker']}: {e['text']}" for e in context["conversation"][-6:]])
    
    # ── BUILD BORROWER CONTEXT STRING ──
    borrower_info_str = ""
    gender = "male"
    honorific_en = "sir"
    honorific_hi = "श्रीमान"
    honorific_ta = "ஐயா"
    
    if context and "borrower_info" in context:
        bi = context["borrower_info"]
        b_name = bi.get('name', 'Unknown')
        gender = detect_gender_from_name(b_name)
        
        if gender == "female":
            honorific_en = "ma'am"
            honorific_hi = "मैडम"
            honorific_ta = "மேடம்"
        
        outstanding = bi.get('amount', 0)
        emi = bi.get('emi', 0)
        remaining_after_emi = outstanding - emi if outstanding and emi else 0
        
        gender_label = "sir" if gender == "male" else "ma'am"
        borrower_info_str = (
            f"\n\nBORROWER DATA (you already know this - use this naturally, NEVER ask for this info):\n"
            f"- Name: {b_name}\n"
            f"- Gender: {gender} (use {gender_label} accordingly)\n"
            f"- Outstanding Loan Amount: ₹{outstanding:,.2f}\n"
            f"- Monthly EMI: ₹{emi:,.2f}\n"
            f"- Remaining After This Month's Payment: ₹{remaining_after_emi:,.2f}\n"
            f"- Due Date: {bi.get('due_date', 'N/A')}\n"
            f"- Last Paid: {bi.get('last_paid', 'N/A')}\n"
            f"- Payment Category: {bi.get('payment_category', 'N/A')}\n"
            f"- Loan No: {bi.get('loan_no', 'N/A')}\n"
        )
    
    # System prompts with structured conversation flow
    sys_prompts = {
        "en-IN": (
            "You are Vidya, a polite loan collection assistant on a PHONE CALL. "
            "CRITICAL RULES:\n"
            "- Respond in English. Keep replies to 1-2 SHORT sentences (max 25 words total).\n"
            "- Never repeat what you already said. Be empathetic but direct.\n"
            f"- Address the borrower as '{honorific_en}' (based on their gender).\n"
            "- NEVER ask for information you already have (amount, name, dates).\n"
            "\nCONVERSATION FLOW TO FOLLOW:\n"
            "1. GREETING (already done): 'Hi Mr/Mrs [Name], hope you are doing well today. We are calling from the Loan sector, this is a general check-up call regarding the Loan amount that you have borrowed. Your due date is coming up soon [date]. Can you please let us know if you will be paying the balance amount before due date?'\n"
            "2. If borrower confirms they WILL PAY: 'Good to know {honorific}, we will update our records accordingly. Do you have any questions for us?'\n"
            "3. If borrower asks about loan amounts: 'Sure {honorific}, your current outstanding loan amount is [amount] and after payment of the due this month your loan amount would be [remaining].'\n"
            "4. When borrower says thank you or has no more questions: 'Thank you {honorific}, have a good day!'\n"
            "5. For any other scenario (dispute, extension, abusive etc.), handle professionally in 1 sentence.\n"
            + borrower_info_str
        ),
        "hi-IN": (
            "आप विद्या हैं, फोन पर लोन वसूली सहायक। "
            "महत्वपूर्ण नियम:\n"
            "- हिंदी में जवाब दें। 1-2 छोटे वाक्यों में (अधिकतम 25 शब्द) जवाब दें।\n"
            "- जो पहले कह चुकी हैं वो दोबारा न कहें।\n"
            f"- उधारकर्ता को '{honorific_hi}' कहें (उनके लिंग के आधार पर)।\n"
            "- जो जानकारी आपके पास पहले से है (राशि, नाम, तारीख) वो कभी न पूछें।\n"
            "\nबातचीत का क्रम:\n"
            "1. अभिवादन (पहले ही हो चुका): 'नमस्ते श्री/श्रीमती [नाम] जी, आशा है आप अच्छे हैं। हम लोन सेक्टर से कॉल कर रहे हैं, यह आपके उधार लिए गए लोन के बारे में एक सामान्य फॉलो-अप कॉल है। आपकी due date जल्द आ रही है [तारीख]। क्या आप due date से पहले बकाया राशि का भुगतान कर देंगे?'\n"
            f"2. अगर उधारकर्ता भुगतान की पुष्टि करे: 'यह सुनकर अच्छा लगा {honorific_hi}, हम अपने रिकॉर्ड अपडेट कर देंगे। क्या आपका कोई सवाल है?'\n"
            f"3. अगर लोन राशि पूछें: 'जी {honorific_hi}, आपकी वर्तमान कुल बकाया लोन राशि [राशि] है और इस महीने के भुगतान के बाद आपकी बकाया राशि [शेष] होगी।'\n"
            f"4. जब उधारकर्ता धन्यवाद कहें या कोई सवाल न हो: 'धन्यवाद {honorific_hi}, आपका दिन शुभ हो!'\n"
            "5. किसी भी अन्य स्थिति (विवाद, एक्सटेंशन, अभद्र) को 1 वाक्य में पेशेवर तरीके से संभालें।\n"
            + borrower_info_str
        ),
        "ta-IN": (
            "நீங்கள் வித்யா, தொலைபேசியில் கடன் வசூல் உதவியாளர். "
            "முக்கிய விதிகள்:\n"
            "- தமிழில் பதிலளிக்கவும். 1-2 குறுகிய வாக்கியங்களில் (அதிகபட்சம் 25 வார்த்தைகள்) பதிலளிக்கவும்.\n"
            "- ஏற்கனவே கூறியதை மீண்டும் கூறாதீர்கள்.\n"
            f"- கடன் வாங்கியவரை '{honorific_ta}' என்று அழையுங்கள் (பாலினத்தின் அடிப்படையில்).\n"
            "- உங்களிடம் ஏற்கனவே உள்ள தகவல்களை (தொகை, பெயர், தேதிகள்) ஒருபோதும் கேட்காதீர்கள்.\n"
            "\nஉரையாடல் வரிசை:\n"
            "1. வாழ்த்து (ஏற்கனவே செய்யப்பட்டது): 'வணக்கம் திரு/திருமதி [பெயர்], நலமாக இருப்பீர்கள் என நம்புகிறேன். கடன் பிரிவிலிருந்து அழைக்கிறோம், நீங்கள் பெற்ற கடன் தொகை குறித்த வழக்கமான பின்தொடர் அழைப்பு. உங்கள் செலுத்த வேண்டிய தேதி வரவிருக்கிறது [தேதி]. நிலுவைத் தொகையை due date-க்கு முன் செலுத்துவீர்களா?'\n"
            f"2. கடன் வாங்கியவர் செலுத்துவதாக உறுதியளித்தால்: 'நல்லது {honorific_ta}, நாங்கள் எங்கள் பதிவுகளை அதற்கேற்ப புதுப்பிப்போம். உங்களுக்கு ஏதாவது கேள்விகள் உள்ளதா?'\n"
            f"3. கடன் தொகை குறித்து கேட்டால்: 'நிச்சயமாக {honorific_ta}, உங்கள் தற்போதைய கடன் நிலுவை [தொகை] மற்றும் இந்த மாத கட்டணத்திற்குப் பிறகு உங்கள் கடன் நிலுவை [மீதமுள்ள] ஆகும்.'\n"
            f"4. நன்றி சொல்லும்போது அல்லது கேள்விகள் இல்லை என்றால்: 'நன்றி {honorific_ta}, நல்ல நாள் வாழ்த்துகள்!'\n"
            "5. பிற சூழ்நிலைகளுக்கு (சர்ச்சை, நீட்டிப்பு, அவமரியாதை) 1 வாக்கியத்தில் தொழில்முறையாக கையாளுங்கள்.\n"
            + borrower_info_str
        )
    }
    
    system_prompt = sys_prompts.get(language, sys_prompts['en-IN'])
    user_message = f"Conversation so far:\n{conv_history}\n\nUser just said: {user_text}\n\nRespond with 1-2 short sentences following the conversation flow above."
    
    # PRIMARY: Use sync Groq client (fast, no async issues in Flask)
    if sync_groq_client:
        try:
            response = sync_groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=100,
                temperature=0.7
            )
            result = response.choices[0].message.content.strip()
            print(f"[GROQ] ✅ Real-time response generated ({len(result)} chars)")
            return result
        except Exception as e:
            print(f"[GROQ] ❌ Sync response error: {e}")
    
    # FALLBACK: Use Gemini
    if gemini_client:
        try:
            prompt = f"{system_prompt}\n\n{user_message}\n\nAI (1-2 short sentences only):"
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=100)
            )
            return response.text.strip()
        except Exception as e:
            print(f"[GEMINI] ❌ Fallback response error: {e}")
    
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
        
        # Use Groq for analysis
        ai_analysis = await analyze_conversation_with_groq(self.conversation) if len(self.conversation) > 1 else {
            "summary": "No meaningful conversation detected",
            "sentiment": "No Response",
            "intent": "No Response",
            "payment_date": None
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
                # 1. Get current borrower to check category
                from app.table_models.borrowers_table import get_borrower_by_no
                borrower = await get_borrower_by_no(self.user_id, self.borrower_id)
                category = borrower.get("Payment_Category", "Consistent") if borrower else "Consistent"
                
                # 2. Determine Logic
                payment_date = ai_analysis.get("payment_date")
                intent = ai_analysis.get("intent", "No Response")
                is_mid_call = ai_analysis.get("mid_call", False)
                borrower_name = borrower.get("BORROWER", "Borrower")
                
                outcomes = determine_report_outcomes(
                    intent, 
                    payment_date, 
                    category, 
                    borrower_name=borrower_name, 
                    borrower_id=self.borrower_id,
                    is_mid_call=is_mid_call
                )
                
                update_payload = {
                    "call_completed": True,
                    "call_in_progress": False,
                    "transcript": self.conversation,
                    "ai_summary": outcomes["next_step_summary"] or ai_analysis.get('summary', 'Done'),
                    "payment_confirmation": outcomes["payment_confirmation"],
                    "follow_up_date": outcomes["follow_up_date"],
                    "call_frequency": outcomes["call_frequency"],
                    "require_manual_process": outcomes["require_manual_process"],
                    "email_to_manager_preview": outcomes["email_to_manager_preview"]
                }
                
                print(f"[DB] 💾 Saving Borrower Update: {update_payload}")
                await update_borrower(self.user_id, self.borrower_id, update_payload)
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
    
    # Clean the number: remove +, spaces, dashes
    to_number = to_number.strip().replace(' ', '').replace('-', '')
    if to_number.startswith('+'): to_number = to_number[1:]
    
    # Auto-prepend 91 (India) country code for 10-digit Indian mobile numbers
    # Indian mobile numbers start with 6, 7, 8, or 9
    if len(to_number) == 10 and to_number[0] in '6789':
        to_number = '91' + to_number
        print(f"[VONAGE] 📱 Auto-prepended country code: 91 → {to_number}")
    
    try:
        # Include user_id in answer URL for isolation in the webhook handler
        answer_url = f'{settings.BASE_URL}/webhooks/answer?preferred_language={language}&user_id={user_id}'
        if borrower_id:
            answer_url += f'&borrower_id={borrower_id}'
        
        print(f"\n[VONAGE] 📞 Attempting outbound call to {to_number}...", flush=True)
        print(f"  From: {settings.VONAGE_FROM_NUMBER}", flush=True)
        print(f"  Answer URL: {answer_url}", flush=True)
        
        if not settings.VONAGE_FROM_NUMBER:
            print("[VONAGE] 🚨 ERROR: VONAGE_FROM_NUMBER is not set in environment variables!", flush=True)
            return {"success": False, "error": "VONAGE_FROM_NUMBER is not configured"}

        response = voice.create_call({
            'to': [{'type': 'phone', 'number': to_number}],
            'from_': {'type': 'phone', 'number': settings.VONAGE_FROM_NUMBER},
            'answer_url': [answer_url],
            'event_url': [f'{settings.BASE_URL}/webhooks/event']
        })
        
        print(f"[VONAGE] ✅ Call successfully initiated! UUID: {response.uuid}", flush=True)
        
        return {
            "success": True,
            "call_uuid": response.uuid,
            "status": "initiated",
            "user_id": user_id
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"[VONAGE] ❌ Outbound Error Detail: {error_msg}", flush=True)
        # Check for common Vonage errors
        if "401" in error_msg:
            print("[VONAGE] 🚨 Authentication Failed: Check your API Key, Secret, and Application ID.", flush=True)
        elif "429" in error_msg:
            print("[VONAGE] 🚨 Rate Limit: Too many requests.", flush=True)
        return {"success": False, "error": error_msg}

def get_call_data_store():
    return call_data