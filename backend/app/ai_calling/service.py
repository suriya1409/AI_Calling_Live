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
    import logging
    # Suppress internal Gemini SDK logging to match Groq's quiet behavior
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    GEMINI_AVAILABLE = True
except ImportError:
    print("⚠️  WARNING: google-genai not installed. Install with: pip install google-genai")
    GEMINI_AVAILABLE = False

# --- GROQ COMMENTED OUT: Using Gemini Only ---
# try:
#     from groq import Groq
#     GROQ_AVAILABLE = True
# except ImportError:
#     print("⚠️  WARNING: groq not installed. Install with: pip install groq")
#     GROQ_AVAILABLE = False
GROQ_AVAILABLE = False

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
    # Use private key content if available (for Render/ENV), otherwise use path
    private_key = settings.VONAGE_PRIVATE_KEY_CONTENT
    if not private_key and os.path.exists(settings.VONAGE_PRIVATE_KEY_PATH):
        with open(settings.VONAGE_PRIVATE_KEY_PATH, 'rb') as f:
            private_key = f.read()
    
    if private_key:
        vonage_client = Vonage(Auth(
            application_id=settings.VONAGE_APPLICATION_ID,
            private_key=private_key
        ))
        voice = vonage_client.voice
        print("[VONAGE] ✅ Vonage Voice client initialized")
    else:
        print("[VONAGE] ⚠️  No private key found (check .env or private.key)")
        vonage_client = None
        voice = None
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

# --- GROQ COMMENTED OUT: Using Gemini Only ---
groq_client = None
sync_groq_client = None
print("[GROQ] ⚠️  Groq disabled — using Gemini API only")
# print(f"[DEBUG] GROQ_AVAILABLE: {GROQ_AVAILABLE}")
# print(f"[DEBUG] settings.GROQ_API_KEY present: {bool(settings.GROQ_API_KEY)}")
#
# if GROQ_AVAILABLE and settings.GROQ_API_KEY:
#     if "your_groq_api_key_here" in settings.GROQ_API_KEY:
#         print("[GROQ] ⚠️  Groq API key is still the placeholder. Please update .env")
#     else:
#         try:
#             from groq import AsyncGroq
#             groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
#             print("[GROQ] ✅ Async Groq AI client initialized")
#         except Exception as e:
#             print(f"[GROQ] ⚠️  Failed to initialize: {e}")
#             groq_client = None
# else:
#     if not GROQ_AVAILABLE:
#         print("[GROQ] ⚠️  Groq library not installed.")
#     if not settings.GROQ_API_KEY:
#         print("[GROQ] ⚠️  GROQ_API_KEY not found in settings.")
#     print("[GROQ] ⚠️  Groq not configured - fallback analysis will be disabled")
#
# # Initialize SYNC Groq client (for real-time responses in Flask sync context)
# sync_groq_client = None
# if GROQ_AVAILABLE and settings.GROQ_API_KEY and "your_groq_api_key_here" not in settings.GROQ_API_KEY:
#     try:
#         sync_groq_client = Groq(api_key=settings.GROQ_API_KEY)
#         print("[GROQ] ✅ Sync Groq client initialized for real-time call responses")
#     except Exception as e:
#         print(f"[GROQ] ⚠️  Failed to initialize sync client: {e}")
#         sync_groq_client = None


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
    Calculate follow-up dates based on acstatus category (Skipping Weekends):
    All statuses get 3 calls/week (next 3 business days) since calls are
    triggered after the due date has already crossed.
    """
    from datetime import timedelta
    today = datetime.now()
    dates = []
    
    required_dates = 3
    desc = "3 calls/week"
        
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

def _get_next_n_business_days(from_date, n=3):
    """Helper: returns a list of the next N business day date strings (skipping weekends) from a given date."""
    from datetime import timedelta
    dates = []
    current = from_date
    while len(dates) < n:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            dates.append(current.strftime("%Y-%m-%d"))
    return dates


def determine_report_outcomes(intent, payment_date, category, borrower_name="Borrower", borrower_id="", is_mid_call=False):
    """
    Centralized logic to determine:
    - payment_confirmation
    - follow_up_date
    - call_frequency
    - require_manual_process
    - email_to_manager_preview
    - next_step_summary  (NOW: detailed AI summary based on intent)
    """
    from datetime import datetime, timedelta
    
    intent = (intent or "No Response").strip()
    category = (category or "SMA0").strip().upper()
    
    next_step_summary = ""
    email_draft = None
    require_manual_process = False
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    
    # 1. Handle Dates & Freq
    escalation_intents = ["Paid", "Dispute", "No Response", "Abusive Language", "Threatening Language", "Stop Calling"]
    
    # Priority for payment_confirmation badge:
    # 1. If it's a known escalation intent, USE that as the badge (Highest Priority)
    # 2. Otherwise, if there is a specific payment_date, use that as the badge
    # 3. Default to the intent string
    if intent in escalation_intents:
        payment_confirmation = intent
    elif payment_date and payment_date.lower() != "null":
        payment_confirmation = payment_date
    else:
        payment_confirmation = intent

    if is_mid_call:
        # Re-trigger Next Day
        next_day = today + timedelta(days=1)
        if next_day.weekday() >= 5:  # Skip to Monday
            next_day += timedelta(days=(7 - next_day.weekday()))
        follow_up_date = next_day.strftime("%Y-%m-%d")
        call_frequency = "1 call (Retry)"
        next_step_summary = (
            f"Borrower {borrower_name} hung up mid-sentence. "
            f"System scheduled a follow-up retry for the next business day ({follow_up_date}). "
            f"Finance team needs to re-trigger the call on {follow_up_date}."
        )
    elif payment_date and payment_date.lower() != "null":
        # Note: payment_confirmation already set to payment_date above
        follow_up_date = payment_date
        call_frequency = "1 call (Verify)"
    else:
        follow_up_date, call_frequency = calculate_follow_up_schedule(category)

    # ──────────────────────────────────────────────
    # 2. DETAILED AI SUMMARY GENERATION PER INTENT
    # ──────────────────────────────────────────────

    # Helper: build follow-up dates string
    follow_up_dates_list = follow_up_date.split(", ") if follow_up_date else []
    follow_up_dates_display = ", ".join(follow_up_dates_list) if follow_up_dates_list else "N/A"

    if intent == "Will Pay":
        # ── WILL PAY with confirmation date ──
        require_manual_process = False
        email_draft = None

        if payment_date and payment_date.lower() != "null":
            # Borrower gave a specific confirmation date
            biz_days_after_confirm = _get_next_n_business_days(
                datetime.strptime(payment_date, "%Y-%m-%d"), 3
            )
            follow_up_date = ", ".join(biz_days_after_confirm)
            call_frequency = "3 calls/week (Post-Confirmation)"

            next_step_summary = (
                f"Borrower {borrower_name} committed to pay on {payment_date}. "
                f"Follow-up dates are set to {', '.join(biz_days_after_confirm)} (next 3 business days after confirmation date). "
                f"Finance team needs to check whether the borrower has paid the loan on {payment_date}. "
                f"If payment is not received by {payment_date}, fall back to the next day to trigger the call."
            )
        else:
            # Borrower said Will Pay but did NOT give a specific date
            biz_days_from_today = _get_next_n_business_days(today, 3)
            follow_up_date = ", ".join(biz_days_from_today)
            call_frequency = "3 calls/week"

            next_step_summary = (
                f"Borrower {borrower_name} committed to pay but did not provide a specific confirmation date. "
                f"Follow-up dates are set to {', '.join(biz_days_from_today)} (next 3 business days from today). "
                f"Finance team needs to check whether the borrower has paid the loan on these dates. "
                f"If payment is not received, fall back to the next day to trigger the call."
            )

    elif intent == "Needs Extension":
        require_manual_process = False
        email_draft = None
        if payment_date and payment_date.lower() != "null":
            biz_days_after = _get_next_n_business_days(
                datetime.strptime(payment_date, "%Y-%m-%d"), 3
            )
            follow_up_date = ", ".join(biz_days_after)
            call_frequency = "3 calls/week (Post-Extension)"
            next_step_summary = (
                f"Borrower {borrower_name} requested an extension until {payment_date}. "
                f"Follow-up dates are set to {', '.join(biz_days_after)} (next 3 business days after extension date). "
                f"Finance team needs to verify if payment is made by {payment_date}, otherwise trigger follow-up calls."
            )
        else:
            biz_days_from_today = _get_next_n_business_days(today, 3)
            follow_up_date = ", ".join(biz_days_from_today)
            call_frequency = "3 calls/week"
            next_step_summary = (
                f"Borrower {borrower_name} requested an extension but did not provide a specific date. "
                f"Follow-up dates are set to {', '.join(biz_days_from_today)} (next 3 business days from today). "
                f"Finance team needs to follow up and verify payment status."
            )

    elif intent == "Paid":
        # ── ALREADY PAID ──
        require_manual_process = True
        claim_date = payment_date if (payment_date and payment_date.lower() != "null") else "a recent date (not specified)"

        next_step_summary = (
            f"Borrower {borrower_name} claims to have already paid on {claim_date}. "
            f"Finance team needs to verify whether this borrower has actually paid the loan. "
            f"If the payment is not confirmed in the system, finance team needs to do manual calling to resolve the discrepancy."
        )
        subject = f"Payment Verification Required: {borrower_name}"
        body = (
            f"Hi Area Manager,\n\n"
            f"Borrower {borrower_name} ({borrower_id}) claims they have already paid on {claim_date}. "
            f"Please verify the transaction in the system.\n\n"
            f"If payment is not found, please initiate manual follow-up.\n\n"
            f"Best regards,\nAI Collection System"
        )
        email_draft = {"to": "Area Manager", "subject": subject, "body": body}

    elif intent in ["Abusive Language", "Threatening Language", "Dispute"]:
        # ── ABUSIVE / THREATENING / DISPUTE ──
        require_manual_process = True

        # Calculate next day from current trigger day
        next_retry = today + timedelta(days=1)
        if next_retry.weekday() >= 5:
            next_retry += timedelta(days=(7 - next_retry.weekday()))
        next_retry_str = next_retry.strftime("%Y-%m-%d")

        # Determine the type label for the summary
        if intent == "Abusive Language":
            behavior_label = "abusive language"
        elif intent == "Threatening Language":
            behavior_label = "threatening language"
        else:
            behavior_label = "dispute"

        next_step_summary = (
            f"Borrower {borrower_name} used {behavior_label} during the call. This requires manual calling. "
            f"On the next day from the current trigger day ({next_retry_str}), retry calling this borrower. "
            f"Escalation has been raised for the finance team to handle this case with priority."
        )

        # Override follow-up to next business day for retry
        follow_up_date = next_retry_str
        call_frequency = "1 call (Retry - Escalated)"

        if intent == "Abusive Language":
            subject = f"Alert: Abusive Language - {borrower_name}"
            body = (
                f"Hi Area Manager,\n\n"
                f"Borrower {borrower_name} ({borrower_id}) used abusive language during the AI call. "
                f"Manual handling is required. A retry call is scheduled for {next_retry_str}.\n\n"
                f"Best regards,\nAI Collection System"
            )
        elif intent == "Threatening Language":
            subject = f"Security Alert: Threatening Language - {borrower_name}"
            body = (
                f"Hi Area Manager,\n\n"
                f"Borrower {borrower_name} ({borrower_id}) made threatening remarks during the call. "
                f"Please handle this case with priority. A retry call is scheduled for {next_retry_str}.\n\n"
                f"Best regards,\nAI Collection System"
            )
        else:  # Dispute
            subject = f"Payment Dispute: {borrower_name}"
            body = (
                f"Hi Area Manager,\n\n"
                f"Borrower {borrower_name} ({borrower_id}) is disputing the loan amount/terms. "
                f"Manual investigation required. A retry call is scheduled for {next_retry_str}.\n\n"
                f"Best regards,\nAI Collection System"
            )
        email_draft = {"to": "Area Manager", "subject": subject, "body": body}

    elif intent == "No Response":
        require_manual_process = True
        next_step_summary = (
            f"No clear response received from borrower {borrower_name}. "
            f"Escalating for manual follow-up. Finance team needs to attempt manual calling."
        )
        subject = f"No Response Escalation: {borrower_name}"
        body = (
            f"Hi Area Manager,\n\n"
            f"We could not get a clear response from {borrower_name} ({borrower_id}). "
            f"Please follow up manually.\n\n"
            f"Best regards,\nAI Collection System"
        )
        email_draft = {"to": "Area Manager", "subject": subject, "body": body}

    elif intent == "Stop Calling":
        require_manual_process = True
        next_step_summary = (
            f"Borrower {borrower_name} requested to stop all calls. "
            f"Escalating to the legal/compliance team. Finance team needs to update DNC (Do Not Call) status."
        )
        subject = f"DNC Request: {borrower_name}"
        body = (
            f"Hi Area Manager,\n\n"
            f"Borrower {borrower_name} ({borrower_id}) requested to stop calling. "
            f"Please update legal/DNC status.\n\n"
            f"Best regards,\nAI Collection System"
        )
        email_draft = {"to": "Area Manager", "subject": subject, "body": body}

    else:
        # Fallback for any other/unknown intent
        if not next_step_summary:
            next_step_summary = f"Call completed with borrower {borrower_name}. Intent: {intent}. Follow-up scheduled."

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
        # Use private key content if available (for Render/ENV), otherwise use path
        private_key = settings.VONAGE_PRIVATE_KEY_CONTENT
        if not private_key and os.path.exists(settings.VONAGE_PRIVATE_KEY_PATH):
            with open(settings.VONAGE_PRIVATE_KEY_PATH, 'rb') as f:
                private_key = f.read()
        
        if not private_key:
            print("[JWT] ⚠️  No private key found for JWT generation")
            return None
        
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
    Primary analysis using Gemini AI (Gemini-only mode).
    """
    if not gemini_client:
        print("[GEMINI] ⚠️  Gemini client not available, returning default analysis")
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
    
    today_date = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt = f"""You are an AI analyst reviewing a phone conversation between a collection agent (AI) and a borrower (User).
    
    Current Date: {today_date}

    Analyze this conversation and provide:
    
    1. **SUMMARY**: A concise 2-3 sentence summary of what was discussed.
    
    2. **SENTIMENT**: Classify as Positive, Neutral, or Negative.
    
    3. **INTENT**: Classify as one of the following:
       - **Paid**, **Will Pay**, **Needs Extension**, **Dispute**, **No Response**, **Abusive Language**, **Threatening Language**, **Stop Calling**.
    
    4. **MID_CALL**: Boolean (true/false). Set to true ONLY if the conversation ends abruptly or the borrower hangs up mid-sentence.

    5. **PAYMENT_DATE**: Extract EXACT date if mentioned (YYYY-MM-DD). Resolve relative dates like "tomorrow", "next Monday", "next week", "end of month" based on {today_date}. The date MUST be today ({today_date}) or in the future. If the borrower mentions a past date, adjust it to the nearest valid future date. If no date, return null.
    
    CONVERSATION:
    {conversation_text}
    
    Respond in JSON format only with these exact keys:
    {{
        "summary": "...",
        "sentiment": "...",
        "sentiment_reasoning": "...",
        "intent": "...",
        "intent_reasoning": "...",
        "payment_date": "YYYY-MM-DD or null",
        "mid_call": true/false
    }}"""
    
    # Add retry logic for 429 Resource Exhausted
    max_retries = 5
    base_delay = 2  # Paid tier recovers faster from rate limits
    
    for attempt in range(max_retries):
        try:
            print(f"\n[GEMINI] 🤖 Starting AI analysis (Attempt {attempt+1}/{max_retries})...")
            
            # Use async version of generate_content with explicit config to reduce noise
            response = await gemini_client.aio.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,  # Lower temperature for more consistent JSON
                    top_p=0.95,
                    max_output_tokens=1024,
                    response_mime_type="application/json" # Force JSON mode at the SDK level
                )
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
            error_str = str(e).lower()
            if "429" in error_str or "resource_exhausted" in error_str:
                if attempt < max_retries - 1:
                    delay = (base_delay * (2 ** attempt)) + random.uniform(0, 5)
                    print(f"[GEMINI] ⏳ Rate limit hit. Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue
            
            print(f"[GEMINI] ❌ Analysis error: {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            
            return {
                "summary": "Unable to analyze conversation",
                "sentiment": "Neutral",
                "intent": "No Response",
                "payment_date": None
            }
    
    return {"summary": "Analysis failed", "sentiment": "Neutral", "intent": "No Response", "payment_date": None}


# --- GROQ ANALYSIS COMMENTED OUT: Using Gemini Only ---
# async def analyze_conversation_with_groq(conversation):
#     """
#     Fallback analysis using Groq AI (Llama 3) when Gemini is unavailable or rate-limited.
#     """
#     if not groq_client:
#         print("[GROQ] ⚠️  Groq client not available, skipping fallback analysis")
#         return None
#     
#     conversation_text = "\n".join([
#         f"{entry['speaker']}: {entry['text']}" 
#         for entry in conversation
#     ])
#     today_date = datetime.now().strftime("%Y-%m-%d (%A)")
#     prompt = f"""..."""  # Full prompt omitted for brevity
#     try:
#         response = await groq_client.chat.completions.create(
#             model="llama-3.3-70b-versatile",
#             messages=[...],
#             response_format={"type": "json_object"}
#         )
#         response_text = response.choices[0].message.content.strip()
#         analysis = json.loads(response_text)
#         return analysis
#     except Exception as e:
#         print(f"[GROQ] ❌ Fallback analysis error: {e}")
#         return None


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
    """Detect language based on Unicode character sets AND Hinglish keyword detection.
    Returns the detected language code.
    
    Key improvement: Detects Hinglish (Hindi spoken in Latin characters) by checking
    for common Hindi words written in English script. This is critical because Sarvam STT
    sometimes transcribes Hindi speech using Latin characters when given an English hint.
    """
    text = text.strip()
    if not text:
        return "en-IN"
    
    # Count characters belonging to each script
    hindi_chars = len(re.findall(r'[\u0900-\u097F]', text))
    tamil_chars = len(re.findall(r'[\u0B80-\u0BFF]', text))
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    total_alpha = hindi_chars + tamil_chars + latin_chars
    
    if total_alpha == 0:
        return "en-IN"
    
    # Use proportional detection - whichever script dominates
    if hindi_chars / total_alpha > 0.3:
        return "hi-IN"
    if tamil_chars / total_alpha > 0.3:
        return "ta-IN"
    
    # ── HINGLISH DETECTION ──
    # If the text is mostly Latin characters, check for common Hindi words
    # written in English script (Hinglish). This catches cases where STT
    # transcribes Hindi speech into Latin characters.
    if latin_chars > 0 and hindi_chars == 0 and tamil_chars == 0:
        text_lower = text.lower()
        words = set(text_lower.split())
        
        # Common Hindi words/phrases that appear in Hinglish transcription
        hinglish_markers = {
            # Affirmatives / negatives
            'haan', 'haa', 'nahi', 'nhi', 'nahin', 'ji', 'accha', 'acha', 'theek',
            'thik', 'bilkul', 'zaroor', 'jaroor',
            # Pronouns / common words
            'mera', 'meri', 'mere', 'mujhe', 'humara', 'hamara', 'aapka', 'aapki',
            'yeh', 'woh', 'kya', 'kaise', 'kab', 'kahan', 'kyun', 'kaun',
            # Financial / loan context
            'paisa', 'paise', 'rupaye', 'rupay', 'bhugtan', 'bhugtaan', 'karz',
            'karj', 'kist', 'kisht', 'rashi', 'raashi', 'bakaya', 'jama',
            # Time words
            'kal', 'aaj', 'parso', 'abhi', 'baad', 'pehle', 'mahina', 'hafte',
            'hafta',
            # Verbs / actions
            'karunga', 'karenge', 'karungi', 'dunga', 'dungi', 'denge', 'batao',
            'bataiye', 'bataye', 'suniye', 'boliye', 'bolo', 'kar', 'karo',
            'de', 'do', 'lo', 'lena', 'dena', 'milega', 'hoga', 'hogi',
            # Greetings / politeness
            'namaste', 'namaskar', 'dhanyavaad', 'dhanyawad', 'shukriya',
            'alvida', 'kripya', 'sahab', 'saab', 'madam', 'bhai',
            # Common fillers
            'are', 'yaar', 'bas', 'toh', 'bhi', 'hai', 'hain', 'tha',
            'wala', 'wali', 'wale', 'se', 'ka', 'ki', 'ke', 'ko', 'ne',
            'par', 'pe', 'mein', 'tak', 'aur',
        }
        
        # Count how many words match Hinglish markers
        hinglish_matches = words.intersection(hinglish_markers)
        match_ratio = len(hinglish_matches) / len(words) if words else 0
        
        # If 30%+ of words are Hinglish markers, classify as Hindi
        if match_ratio >= 0.3 or len(hinglish_matches) >= 3:
            print(f"[LANG] 🔍 Hinglish detected! Matched words: {hinglish_matches} ({match_ratio:.0%})")
            return "hi-IN"
    
    return "en-IN"


def detect_language_from_stt(audio_data, preferred_language, alternate_language=None):
    """Try transcribing audio in multiple languages and pick the best match.
    
    UPDATED LOGIC:
    1. Transcribe in all 3 supported languages (en-IN, hi-IN, ta-IN).
    2. Check if the borrower is speaking in the preferred language.
       If Preferred STT matches its script, we stick to it and continue.
    3. Else, if the language changed, compare scores of other languages
       to the preferred language and switch only if another language's 
       confidence score is clearly higher.
    """
    ALL_SUPPORTED_LANGUAGES = ["en-IN", "hi-IN", "ta-IN"]
    
    # 1. Transcribe in all supported languages to probe for switches
    transcripts = {}
    for lang in ALL_SUPPORTED_LANGUAGES:
        t = transcribe_sarvam(audio_data, lang)
        if t and t.strip():
            transcripts[lang] = t.strip()
            print(f"[STT-PROBE] {lang}: '{t.strip()[:60]}'")
    
    if not transcripts:
        return None, preferred_language

    # 2. Calculate confidence scores for each transcription
    # Heuristic: Score = (3 if script matches hint else 0) + (length / 200)
    scores = {}
    for lang, transcript in transcripts.items():
        detected_script = detect_language(transcript)
        
        # Base score: does the language hint match the character script detected?
        # This is our primary 'confidence' indicator.
        base_score = 3.0 if detected_script == lang else 0.0
        
        # Bonus for longer transcripts (more confident STT capture)
        length_bonus = len(transcript) / 200.0
        
        score = base_score + length_bonus
        scores[lang] = score
        print(f"[STT-SCORE] {lang}: script_detected={detected_script}, score={score:.2f}, len={len(transcript)}")

    # 3. ── NEW LOGIC: PREFERRED LANGUAGE FIRST ──
    # Instruction: "if the borrower is speaking in the preffered language then continue with the flow"
    pref_transcript = transcripts.get(preferred_language)
    if pref_transcript:
        pref_detected_script = detect_language(pref_transcript)
        # If the preferred language transcription matches its script, it's a valid capture.
        # We stick to it unless it's extremely short/meaningless.
        if pref_detected_script == preferred_language and len(pref_transcript) >= 3:
            print(f"[LANG-STICKY] Borrower is speaking Preferred Language ({preferred_language}). Continuing flow...")
            return pref_transcript, preferred_language

    # 4. ── ELSE: DETECT LANGUAGE SWITCH ──
    # Instruction: "compare the confidence score of the current language to the preffered language 
    # and if the current language score is not equal to the preferred language then change"
    
    best_lang = preferred_language
    best_score = scores.get(preferred_language, 0)
    
    # Iterate through other languages to see if user switched
    for lang in ALL_SUPPORTED_LANGUAGES:
        if lang == preferred_language: continue
        
        current_score = scores.get(lang, 0)
        
        # We switch if the current language score is higher than the preferred score.
        # We add a small buffer (0.2) to prevent switching on tiny differences/noise.
        if current_score > (best_score + 0.2):
            best_score = current_score
            best_lang = lang
    
    # If we decided to switch
    if best_lang != preferred_language:
        print(f"[LANG-SWITCH] Switch detected: {preferred_language} (score {scores.get(preferred_language, 0):.2f}) -> {best_lang} (score {best_score:.2f})")
    
    # 5. One more check for Hinglish if the system stayed in English but it looks like Hindi
    if best_lang == preferred_language and preferred_language == "en-IN":
        pref_transcript = transcripts.get("en-IN", "")
        if detect_language(pref_transcript) == "hi-IN":
            # Hinglish detected in English STT - switch to hi-IN result if available
            if "hi-IN" in transcripts:
                print(f"[LANG-HINGLISH] Hinglish detected, using hi-IN transcript instead of en-IN")
                return transcripts["hi-IN"], "hi-IN"
            else:
                return pref_transcript, "hi-IN"

    return transcripts.get(best_lang, pref_transcript), best_lang


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
    
    # ── BUILD STATUS-SPECIFIC TONE MODIFIER ──
    acstatus = "SMA0"
    if context and "borrower_info" in context:
        acstatus = context["borrower_info"].get("acstatus", "SMA0")
    
    tone_instructions = {
        "SMA0": {
            "en": "TONE: Soft and polite. The borrower has missed ONE month's payment. Inform that payment is still pending, warn that delays may impact CIBIL score and could lead to account classification issues. Request payment at the earliest or a convenient time for payment.",
            "hi": "टोन: नरम और विनम्र। उधारकर्ता ने एक महीने का भुगतान नहीं किया है। सूचित करें कि भुगतान लंबित है, चेतावनी दें कि देरी CIBIL स्कोर को प्रभावित कर सकती है और खाता वर्गीकरण समस्याएं हो सकती हैं। जल्द से जल्द भुगतान या सुविधाजनक समय का अनुरोध करें।",
            "ta": "தொனி: மென்மையான மற்றும் கண்ணியமான. கடன் வாங்கியவர் ஒரு மாத தவணை தவறவிட்டுள்ளார். கட்டணம் நிலுவையில் உள்ளது என்று தெரிவிக்கவும், தாமதம் CIBIL மதிப்பெண்ணை பாதிக்கலாம் என எச்சரிக்கவும். விரைவில் பணம் செலுத்த கோரவும்."
        },
        "SMA1": {
            "en": "TONE: More urgent. The borrower has missed TWO months' payments. Records indicate payments are pending, CIBIL score is already being affected, and account may be classified as NPA if not addressed promptly. Strongly request clearing outstanding dues for both months and share a confirmed payment timeline.",
            "hi": "टोन: अधिक गंभीर। उधारकर्ता ने दो महीने का भुगतान नहीं किया है। रिकॉर्ड बताते हैं कि भुगतान लंबित है, CIBIL स्कोर पहले से प्रभावित हो रहा है, और जल्दी निपटान न होने पर खाता NPA वर्गीकृत हो सकता है। दोनों महीनों का बकाया चुकाने और पुष्ट भुगतान समय सीमा का अनुरोध करें।",
            "ta": "தொனி: மிகவும் அவசரமான. கடன் வாங்கியவர் இரண்டு மாத தவணை தவறவிட்டுள்ளார். CIBIL மதிப்பெண் ஏற்கனவே பாதிக்கப்படுகிறது, உடனடியாக நிவர்த்தி செய்யாவிட்டால் NPA ஆக வகைப்படுத்தப்படலாம். இரண்டு மாத நிலுவை செலுத்தவும் உறுதிப்படுத்தப்பட்ட கட்டண காலவரிசை பகிரவும் கோரவும்."
        },
        "SMA2": {
            "en": "TONE: Serious and firm. The borrower has missed THREE months' payments. Account is at HIGH RISK of NPA classification, CIBIL score is already significantly impacted. If dues not cleared immediately, legal proceedings may be initiated. Request clearing all outstanding dues or sharing a repayment plan without delay.",
            "hi": "टोन: गंभीर और दृढ़। उधारकर्ता ने तीन महीने का भुगतान नहीं किया है। खाता NPA वर्गीकरण के उच्च जोखिम में है, CIBIL स्कोर पहले से गंभीर रूप से प्रभावित है। बकाया तुरंत न चुकाने पर कानूनी कार्रवाई शुरू हो सकती है। सभी बकाया चुकाने या पुनर्भुगतान योजना साझा करने का अनुरोध करें।",
            "ta": "தொனி: தீவிரமான மற்றும் உறுதியான. கடன் வாங்கியவர் மூன்று மாத தவணை தவறவிட்டுள்ளார். கணக்கு NPA வகைப்பாட்டின் அதிக ஆபத்தில் உள்ளது, CIBIL மதிப்பெண் கணிசமாக பாதிக்கப்பட்டுள்ளது. நிலுவை உடனடியாக தீர்க்கப்படாவிட்டால் சட்ட நடவடிக்கை எடுக்கப்படலாம்."
        },
        "NPA": {
            "en": "TONE: Direct and authoritative. The borrower's account is classified as NPA due to non-payment for more than three months. CIBIL score is already severely impacted and future credit ability may be affected. URGENTLY request immediate payment to avoid further escalation including legal action and field visits. Ask to confirm payment plan at the earliest.",
            "hi": "टोन: सीधा और अधिकारपूर्ण। तीन महीने से अधिक भुगतान न करने के कारण उधारकर्ता का खाता NPA है। CIBIL स्कोर पर गंभीर प्रभाव पड़ा है और भविष्य में क्रेडिट क्षमता प्रभावित हो सकती है। कानूनी कार्रवाई और फील्ड विजिट से बचने के लिए तुरंत भुगतान की मांग करें। भुगतान योजना की पुष्टि करने को कहें।",
            "ta": "தொனி: நேரடி மற்றும் அதிகாரபூர்வமான. மூன்று மாதங்களுக்கு மேலாக பணம் செலுத்தாததால் கணக்கு NPA ஆக வகைப்படுத்தப்பட்டுள்ளது. CIBIL மதிப்பெண் கடுமையாக பாதிக்கப்பட்டுள்ளது. சட்ட நடவடிக்கை மற்றும் களப்பணி தவிர்க்க உடனடியாக பணம் செலுத்த கோரவும். கட்டணத் திட்டத்தை உறுதிப்படுத்தக் கேளுங்கள்."
        }
    }
    
    tone = tone_instructions.get(acstatus.upper(), tone_instructions["SMA0"])
    
    # System prompts with structured conversation flow (status-aware, due date crossed)
    today_str = datetime.now().strftime("%B %d, %Y")  # e.g. "March 18, 2026"
    today_iso = datetime.now().strftime("%Y-%m-%d")
    
    sys_prompts = {
        "en-IN": (
            "You are Vidya, a loan collection assistant on a PHONE CALL. "
            "CRITICAL RULES:\n"
            "- Respond in English. Keep replies to 1-2 SHORT sentences (max 25 words total).\n"
            "- Never repeat what you already said. Be empathetic but direct.\n"
            f"- Address the borrower as '{honorific_en}' (based on their gender).\n"
            "- NEVER ask for information you already have (amount, name, dates).\n"
            f"- Today's date is: {today_str} ({today_iso}).\n"
            f"- {tone['en']}\n"
            f"- The borrower's account status is: {acstatus}. The payment due date has ALREADY PASSED.\n"
            f"- 🚨 PAST DATE RULE: If the borrower mentions a payment date that is BEFORE today ({today_str}), politely tell them: 'Sorry {honorific_en}, that date has already passed. Please provide an upcoming date to pay the due amount.' Do NOT accept past dates.\n"
            "\nCONVERSATION FLOW TO FOLLOW:\n"
            "1. GREETING (already done): Inform borrower about missed payment(s), warn about credit score impact and NPA risk.\n"
            f"2. If borrower confirms they WILL PAY: Ask for a specific payment date. Only accept dates from today ({today_str}) onwards.\n"
            f"3. If borrower gives a VALID future date: 'Good to know {honorific_en}, we will note your commitment for [date]. We will follow up accordingly.'\n"
            f"4. If borrower asks about loan amounts: 'Sure {honorific_en}, your current outstanding is [amount] and after this month's payment it would be [remaining].'\n"
            f"5. When borrower says thank you or has no more questions: 'Thank you {honorific_en}, have a good day!'\n"
            "6. For any other scenario (dispute, extension, abusive etc.), handle professionally in 1 sentence.\n"
            + borrower_info_str
        ),
        "hi-IN": (
            "आप विद्या हैं, फोन पर लोन वसूली सहायक। "
            "महत्वपूर्ण नियम:\n"
            "- हिंदी में जवाब दें। 1-2 छोटे वाक्यों में (अधिकतम 25 शब्द) जवाब दें।\n"
            "- जो पहले कह चुकी हैं वो दोबारा न कहें।\n"
            f"- उधारकर्ता को '{honorific_hi}' कहें (उनके लिंग के आधार पर)।\n"
            "- जो जानकारी आपके पास पहले से है वो कभी न पूछें।\n"
            f"- आज की तारीख: {today_str} ({today_iso}) है।\n"
            f"- {tone['hi']}\n"
            f"- उधारकर्ता का खाता स्थिति: {acstatus}। भुगतान की due date पहले ही बीत चुकी है।\n"
            f"- 🚨 पिछली तारीख नियम: यदि उधारकर्ता आज ({today_str}) से पहले की कोई तारीख बताए, तो विनम्रता से कहें: 'क्षमा करें {honorific_hi}, वह तारीख पहले ही बीत चुकी है। कृपया बकाया राशि के भुगतान के लिए आने वाली तारीख बताएं।' पिछली तारीख स्वीकार न करें।\n"
            "\nबातचीत का क्रम:\n"
            "1. अभिवादन (पहले ही हो चुका): छूटे हुए भुगतान के बारे में सूचित करें, क्रेडिट स्कोर और NPA जोखिम की चेतावनी दें।\n"
            f"2. अगर उधारकर्ता भुगतान की पुष्टि करे: सटीक तारीख पूछें। आज ({today_str}) या उसके बाद की तारीख ही स्वीकार करें।\n"
            f"3. अगर उधारकर्ता सही भविष्य की तारीख दे: 'यह सुनकर अच्छा लगा {honorific_hi}, [तारीख] के लिए आपकी प्रतिबद्धता नोट कर ली है। हम उसके अनुसार फॉलो अप करेंगे।'\n"
            f"4. अगर लोन राशि पूछें: 'जी {honorific_hi}, आपकी वर्तमान बकाया राशि [राशि] है और भुगतान के बाद [शेष] होगी।'\n"
            f"5. जब धन्यवाद कहें: 'धन्यवाद {honorific_hi}, आपका दिन शुभ हो!'\n"
            "6. अन्य स्थिति को 1 वाक्य में पेशेवर तरीके से संभालें।\n"
            + borrower_info_str
        ),
        "ta-IN": (
            "நீங்கள் வித்யா, தொலைபேசியில் கடன் வசூல் உதவியாளர். "
            "முக்கிய விதிகள்:\n"
            "- தமிழில் பதிலளிக்கவும். 1-2 குறுகிய வாக்கியங்களில் பதிலளிக்கவும்.\n"
            "- ஏற்கனவே கூறியதை மீண்டும் கூறாதீர்கள்.\n"
            f"- கடன் வாங்கியவரை '{honorific_ta}' என்று அழையுங்கள்.\n"
            "- ஏற்கனவே உள்ள தகவல்களை கேட்காதீர்கள்.\n"
            f"- இன்றைய தேதி: {today_str} ({today_iso}).\n"
            f"- {tone['ta']}\n"
            f"- கடன் வாங்கியவரின் கணக்கு நிலை: {acstatus}. செலுத்த வேண்டிய தேதி ஏற்கனவே கடந்துவிட்டது.\n"
            f"- 🚨 கடந்த தேதி விதி: கடன் வாங்கியவர் இன்று ({today_str}) க்கு முன்னதான தேதியை குறிப்பிட்டால், பணிவாக சொல்லுங்கள்: 'மன்னிக்கவும் {honorific_ta}, அந்த தேதி ஏற்கனவே கடந்துவிட்டது. நிலுவைத் தொகை செலுத்த வரவிருக்கும் தேதியைக் கூறுங்கள்.' கடந்த தேதிகளை ஏற்க வேண்டாம்.\n"
            "\nஉரையாடல் வரிசை:\n"
            "1. வாழ்த்து (ஏற்கனவே செய்யப்பட்டது): தவறவிட்ட தவணை பற்றி தெரிவிக்கவும், கடன் மதிப்பெண் மற்றும் NPA அபாயம் பற்றி எச்சரிக்கவும்.\n"
            f"2. செலுத்துவதாக உறுதியளித்தால்: குறிப்பிட்ட தேதி கேளுங்கள். இன்று ({today_str}) அல்லது அதற்குப் பிறகு மட்டுமே ஏற்கவும்.\n"
            f"3. சரியான எதிர்கால தேதி கொடுத்தால்: 'நல்லது {honorific_ta}, [தேதி]-க்கான உங்கள் உறுதிமொழியைக் குறித்துக் கொண்டோம். அதற்கேற்ப பின்தொடர்வோம்.'\n"
            f"4. கடன் தொகை குறித்து கேட்டால்: 'நிச்சயமாக {honorific_ta}, உங்கள் தற்போதைய நிலுவை [தொகை] மற்றும் கட்டணத்திற்குப் பிறகு [மீதமுள்ள] ஆகும்.'\n"
            f"5. நன்றி சொல்லும்போது: 'நன்றி {honorific_ta}, நல்ல நாள் வாழ்த்துகள்!'\n"
            "6. பிற சூழ்நிலைகளை 1 வாக்கியத்தில் தொழில்முறையாக கையாளுங்கள்.\n"
            + borrower_info_str
        )
    }
    
    system_prompt = sys_prompts.get(language, sys_prompts['en-IN'])
    
    # ── DYNAMIC LANGUAGE SWITCHING: Force system prompt to match current language ──
    lang_switch_note = ""
    if context and context.get("language_switched"):
        prev_lang_name = settings.LANGUAGE_CONFIG.get(context.get("previous_language", ""), {}).get('name', 'unknown')
        curr_lang_name = settings.LANGUAGE_CONFIG.get(language, {}).get('name', language)
        
        # CRITICAL: Override the system prompt to the NEW language's prompt
        # This ensures the AI's persona, rules, and conversation flow are all in the new language
        system_prompt = sys_prompts.get(language, sys_prompts['en-IN'])
        
        # Add a forceful language override at the TOP of the system prompt
        language_override = (
            f"🚨 CRITICAL LANGUAGE OVERRIDE 🚨\n"
            f"The user has SWITCHED from {prev_lang_name} to {curr_lang_name}.\n"
            f"You MUST respond ENTIRELY in {curr_lang_name}. Do NOT use {prev_lang_name} at all.\n"
            f"Continue the conversation naturally in {curr_lang_name} without commenting on the language change.\n\n"
        )
        system_prompt = language_override + system_prompt
        
        lang_switch_note = (
            f"\n\n⚠️ LANGUAGE SWITCH DETECTED: The user switched from {prev_lang_name} to {curr_lang_name}. "
            f"You MUST respond ONLY in {curr_lang_name} now."
        )
        print(f"[AI RESPONSE] 🌐 Language switch active: {prev_lang_name} → {curr_lang_name}, using {language} system prompt")
    
    user_message = f"Conversation so far:\n{conv_history}\n\nUser just said: {user_text}{lang_switch_note}\n\nRespond with 1-2 short sentences following the conversation flow above."
    
    # PRIMARY: Use Gemini for real-time responses
    if gemini_client:
        try:
            prompt = f"{system_prompt}\n\n{user_message}\n\nAI (1-2 short sentences only):"
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=100)
            )
            result = response.text.strip()
            print(f"[GEMINI] ✅ Real-time response generated ({len(result)} chars)")
            return result
        except Exception as e:
            print(f"[GEMINI] ❌ Real-time response error: {e}")
    
    # --- GROQ COMMENTED OUT ---
    # if sync_groq_client:
    #     try:
    #         response = sync_groq_client.chat.completions.create(
    #             model="llama-3.3-70b-versatile",
    #             messages=[
    #                 {"role": "system", "content": system_prompt},
    #                 {"role": "user", "content": user_message}
    #             ],
    #             max_tokens=100,
    #             temperature=0.7
    #         )
    #         result = response.choices[0].message.content.strip()
    #         print(f"[GROQ] ✅ Real-time response generated ({len(result)} chars)")
    #         return result
    #     except Exception as e:
    #         print(f"[GROQ] ❌ Sync response error: {e}")
    
    return FALLBACKS.get(language, FALLBACKS["en-IN"])


# ============================================================
# CONVERSATION HANDLER
# ============================================================

class ConversationHandler:
    """Manages conversation state and transcript with USER ISOLATION.
    
    Dynamic Multilingual Switching:
    - Tracks the user's preferred_language (set at call start)
    - Detects the first non-preferred language the user speaks → becomes alternate_language
    - Only switches between these 2 languages dynamically during the call
    - AI responds in whichever language the user is currently speaking
    """
    
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
        # Dynamic multilingual switching: track alternate language
        self.alternate_language = None  # First non-preferred language detected
        self.language_history = []
        self.language_switch_count = 0
        
    def add_entry(self, speaker, text):
        entry = {
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "language": self.current_language
        }
        self.conversation.append(entry)
        self.context["conversation"] = self.conversation
        print(f"[CONV] [{self.user_id}] [{speaker}] ({self.current_language}) {text}")
    
    def handle_language_switch(self, detected_language):
        """Handle dynamic language switching between any of the supported languages.
        
        Updated Logic (Multilingual Support):
        - Any detected switch between en-IN, hi-IN, and ta-IN is allowed.
        - The AI will adapt its system prompt and output to the new detected language.
        """
        if detected_language == self.current_language:
            return False  # No change
        
        # Allow any of the 3 supported languages
        ALL_SUPPORTED = ["en-IN", "hi-IN", "ta-IN"]
        if detected_language not in ALL_SUPPORTED:
            return False

        old_lang = self.current_language
        self.current_language = detected_language
        self.language_switch_count += 1
        
        # Track alternate language (first switch from preferred)
        if not self.alternate_language and detected_language != self.preferred_language:
            self.alternate_language = detected_language

        self.language_history.append({
            "from": old_lang,
            "to": detected_language,
            "timestamp": datetime.now().isoformat(),
            "switch_number": self.language_switch_count
        })
        
        lang_name = settings.LANGUAGE_CONFIG.get(detected_language, {}).get('name', detected_language)
        print(f"[LANG SWITCH] 🔄 #{self.language_switch_count} Switch detected: {old_lang} → {detected_language} ({lang_name})")
        return True
    
    def update_language(self, detected_language):
        """Legacy method - delegates to handle_language_switch for backward compatibility"""
        return self.handle_language_switch(detected_language)
    
    async def save_transcript(self):
        """Save transcript using standalone model functions with User Isolation"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        # Use Gemini for analysis
        ai_analysis = await analyze_conversation_with_gemini(self.conversation) if len(self.conversation) > 1 else {
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
            "alternate_language": self.alternate_language,
            "final_language": self.current_language,
            "language_switches": self.language_history,
            "language_switch_count": self.language_switch_count,
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
                category = borrower.get("acstatus", "SMA0") if borrower else "SMA0"
                
                # 2. Determine Logic
                payment_date = ai_analysis.get("payment_date")
                intent = ai_analysis.get("intent", "No Response")
                is_mid_call = ai_analysis.get("mid_call", False)
                borrower_name = borrower.get("h_name", borrower.get("BORROWER", "Borrower"))
                
                # Validate: payment_date must be today or in the future
                # EXCEPTION: For "Paid" intent, past dates are valid (borrower already paid)
                if payment_date and payment_date.lower() != "null" and intent != "Paid":
                    try:
                        pd = datetime.strptime(payment_date, "%Y-%m-%d")
                        if pd.date() < datetime.now().date():
                            corrected = datetime.now() + timedelta(days=7)
                            payment_date = corrected.strftime("%Y-%m-%d")
                            print(f"[REAL CALL] ⚠️ Payment date was in the past, corrected to {payment_date}")
                            ai_analysis["payment_date"] = payment_date
                    except ValueError:
                        pass
                
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

def make_outbound_call(user_id, to_number, language="en-IN", borrower_id=None, is_manual=False):
    """Trigger an isolated outbound call passing user_id to webhooks"""
    if not voice:
        return {"success": False, "error": "Vonage client not initialized"}
    
    # Clean the number: remove +, spaces, dashes
    to_number = to_number.strip().replace(' ', '').replace('-', '')
    if to_number.startswith('+'): to_number = to_number[1:]
    
    # Auto-prepend 91 (India) country code for 10-digit Indian mobile numbers
    if len(to_number) == 10 and to_number[0] in '6789':
        to_number = '91' + to_number
        print(f"[VONAGE] 📱 Auto-prepended country code: 91 → {to_number}")
    
    try:
        # Include user_id and is_manual in answer URL
        answer_url = f'{settings.BASE_URL}/webhooks/answer?preferred_language={language}&user_id={user_id}'
        if borrower_id:
            answer_url += f'&borrower_id={borrower_id}'
        if is_manual:
            answer_url += f'&is_manual=true'
        
        print(f"\n[VONAGE] 📞 Making {'MANUAL' if is_manual else 'AI'} outbound call:")
        print(f"  To: {to_number}")
        print(f"  From: {settings.VONAGE_FROM_NUMBER}")
        print(f"  Language: {language}")
        print(f"  Borrower: {borrower_id}")
        print(f"  Manual: {is_manual}")
        print(f"  Answer URL: {answer_url}")
        
        response = voice.create_call({
            'to': [{'type': 'phone', 'number': to_number}],
            'from_': {'type': 'phone', 'number': settings.VONAGE_FROM_NUMBER},
            'answer_url': [answer_url],
            'event_url': [f'{settings.BASE_URL}/webhooks/event']
        })
        
        print(f"[VONAGE] ✅ Call initiated! UUID: {response.uuid}")
        
        return {
            "success": True,
            "call_uuid": response.uuid,
            "status": "initiated",
            "user_id": user_id,
            "is_manual": is_manual
        }
        
    except Exception as e:
        print(f"[VONAGE] ❌ Outbound Error: {e}")
        return {"success": False, "error": str(e)}

def get_call_data_store():
    return call_data