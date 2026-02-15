"""
AI Calling Service - COMPLETE WORKING VERSION
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
    Analyze conversation using Gemini AI to extract:
    1. Summary of conversation
    2. Sentiment (Positive/Neutral/Negative)
    3. Borrower Intent (Paid/Will Pay/Needs Extension/Dispute/No Response)
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

1. **SUMMARY**: A concise 2-3 sentence summary of what was discussed in the conversation.

2. **SENTIMENT**: Classify the borrower's overall sentiment as one of:
   - Positive (cooperative, friendly, willing to resolve)
   - Neutral (matter-of-fact, neither positive nor negative)
   - Negative (angry, frustrated, hostile, uncooperative)

3. **INTENT**: Classify the borrower's intent as ONE of:
   - Paid (already made payment or claims to have paid)
   - Will Pay (committed to making payment, provide the date if mentioned)
   - Needs Extension (requesting more time or a payment plan)
   - Dispute (disputing the debt or claiming error)
   - No Response (minimal engagement, evasive, or hung up quickly)

CONVERSATION:
{conversation_text}

Respond in JSON format only:
{{
    "summary": "Brief summary of the conversation",
    "sentiment": "Positive|Neutral|Negative",
    "sentiment_reasoning": "Brief explanation of why you chose this sentiment",
    "intent": "Paid|Will Pay|Needs Extension|Dispute|No Response",
    "intent_reasoning": "Brief explanation of why you chose this intent",
    "payment_date": "YYYY-MM-DD or null if not mentioned or not applicable"
}}"""
    
    # Add retry logic for 429 Resource Exhausted
    max_retries = 5
    base_delay = 3
    
    for attempt in range(max_retries):
        try:
            print(f"\n[GEMINI] 🤖 Starting AI analysis (Attempt {attempt+1}/{max_retries})...")
            
            # Use the new Gemini SDK
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            # Extract JSON from response
            response_text = response.text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            response_text = response_text.strip()
            
            # Parse JSON
            analysis = json.loads(response_text)
            
            print(f"[GEMINI] ✅ Analysis completed successfully")
            print(f"[GEMINI] 📊 Sentiment: {analysis.get('sentiment')}")
            print(f"[GEMINI] 🎯 Intent: {analysis.get('intent')}")
            
            return analysis

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"[GEMINI] ⚠️  Rate limited (429). Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
            
            print(f"[GEMINI] ❌ Analysis error: {e}")
            if attempt == max_retries - 1:
                try:
                    # If we have response_text, try to return it even if parsing fails
                    if 'response_text' in locals():
                         return {
                            "summary": f"Raw analysis result: {response_text[:100]}...",
                            "sentiment": "Neutral",
                            "intent": "No Response",
                            "error": "JSON parsing error"
                        }
                except: pass

                return {
                    "summary": "Unable to analyze conversation - API or parsing error",
                    "sentiment": "Neutral",
                    "sentiment_reasoning": "Error in analysis",
                    "intent": "No Response",
                    "intent_reasoning": "Error in analysis",
                    "payment_date": None,
                    "error": error_str
                }
    
    return {
        "summary": "Analysis failed after internal retries",
        "sentiment": "Neutral",
        "intent": "No Response"
    }


# ============================================================
# SARVAM AI - STT/TTS
# ============================================================

def transcribe_sarvam(audio_data, language="en-IN", max_retries=2):
    """Transcribe audio using Sarvam AI STT (saarika:v2.5) with retry logic"""
    
    # Skip if audio is too short (less than 0.3 seconds)
    min_audio_size = settings.SAMPLE_RATE * settings.SAMPLE_WIDTH * 0.3
    if len(audio_data) < min_audio_size:
        print(f"[STT] ⚠️  Audio too short ({len(audio_data)} bytes), skipping")
        return None
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"[STT] 🔄 Retry attempt {attempt + 1}/{max_retries}")
            
            print(f"[STT] 🎤 Transcribing audio ({len(audio_data)} bytes, {language})...")
            
            # Convert raw PCM audio to WAV format
            wav_buffer = BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(settings.CHANNELS)  # Mono
                wav_file.setsampwidth(settings.SAMPLE_WIDTH)  # 16-bit
                wav_file.setframerate(settings.SAMPLE_RATE)  # 16kHz
                wav_file.writeframes(audio_data)
            
            wav_buffer.seek(0)
            
            # Prepare multipart form data
            headers = {
                'api-subscription-key': settings.SARVAM_API_KEY,
            }
            
            files = {
                'file': ('audio.wav', wav_buffer, 'audio/wav')
            }
            
            data = {
                'language_code': language,
                'model': 'saarika:v2.5'
            }
            
            # Reduced timeout to 10 seconds for faster failure
            response = requests.post(
                'https://api.sarvam.ai/speech-to-text',
                headers=headers,
                files=files,
                data=data,
                timeout=10  # Reduced from 30 to 10 seconds
            )
            
            if response.status_code == 200:
                result = response.json()
                transcript = result.get('transcript', '')
                
                if transcript:
                    print(f"[STT] ✅ Transcribed: '{transcript}'")
                    return transcript
                else:
                    print("[STT] ⚠️  Empty transcript")
                    return None
            else:
                print(f"[STT] ❌ API Error {response.status_code}: {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(0.5)  # Brief pause before retry
                    continue
                return None
                
        except requests.exceptions.Timeout:
            print(f"[STT] ⏱️  Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            print("[STT] ❌ All retry attempts failed due to timeout")
            return None
            
        except Exception as e:
            print(f"[STT] ❌ Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            import traceback
            traceback.print_exc()
            return None
    
    return None


def synthesize_sarvam(text, language="en-IN", max_retries=2):
    """Convert text to speech using Sarvam AI TTS (bulbul:v2) with retry logic"""
    if not text:
        print("[TTS] ⚠️ No text provided for synthesis")
        return None
        
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"[TTS] 🔄 Retry attempt {attempt + 1}/{max_retries}")
            
            # Get speaker and preprocessing from config
            config = settings.LANGUAGE_CONFIG.get(language, {})
            speaker = config.get('speaker', 'manisha')
            enable_preprocessing = config.get('enable_preprocessing', False)
            
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
                'enable_preprocessing': enable_preprocessing,
                'model': 'bulbul:v2'
            }
            
            print(f"[TTS] 🔊 Synthesizing: '{str(text)[:50]}...' ({language}, {speaker})")
            
            # Reduced timeout to 10 seconds
            response = requests.post(
                'https://api.sarvam.ai/text-to-speech',
                headers=headers,
                json=payload,
                timeout=10  # Reduced from 30 to 10 seconds
            )
            
            if response.status_code == 200:
                result = response.json()
                audios = result.get('audios', [])
                
                if audios and audios[0]:
                    audio_base64 = audios[0]
                    audio_bytes = base64.b64decode(audio_base64)
                    print(f"[TTS] ✅ Generated {len(audio_bytes)} bytes of audio")
                    return audio_bytes
                else:
                    print("[TTS] ⚠️  No audio in response")
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    return None
            else:
                print(f"[TTS] ❌ API Error {response.status_code}: {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                return None
                
        except requests.exceptions.Timeout:
            print(f"[TTS] ⏱️  Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            print("[TTS] ❌ All retry attempts failed due to timeout")
            return None
            
        except Exception as e:
            print(f"[TTS] ❌ Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            import traceback
            traceback.print_exc()
            return None
    
    return None


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):
    """Simple language detection based on character sets"""
    text = text.strip()
    
    # Check for Devanagari script (Hindi)
    if re.search(r'[\u0900-\u097F]', text):
        return "hi-IN"
    
    # Check for Tamil script
    if re.search(r'[\u0B80-\u0BFF]', text):
        return "ta-IN"
    
    # Default to English
    return "en-IN"


# ============================================================
# AUDIO BUFFERING
# ============================================================

class AudioBuffer:
    """Buffer audio chunks and detect silence"""
    
    def __init__(self, silence_threshold=300, silence_duration=1.2):  # Optimized for natural turn-taking
        self.buffer = BytesIO()
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.silence_start = None
        self.sample_rate = settings.SAMPLE_RATE
        self.last_chunk_time = time.time()
        self.speech_detected = False  # Track if we've detected speech
        self.min_speech_duration = 0.6  # Support short "Yes/No/Okay" responses
        
    def add_chunk(self, audio_chunk):
        """Add audio chunk and detect if ready to process"""
        self.buffer.write(audio_chunk)
        current_time = time.time()
        
        # Calculate RMS volume
        try:
            samples = struct.unpack(f'{len(audio_chunk)//2}h', audio_chunk)
            rms = sum(abs(s) for s in samples) / len(samples) if samples else 0
        except:
            rms = 0
        
        # Detect if speech has started
        if rms >= self.silence_threshold:
            self.speech_detected = True
            self.silence_start = None  # Reset silence counter when speech is detected
        
        # Only check for silence AFTER speech has been detected
        if self.speech_detected and rms < self.silence_threshold:
            if self.silence_start is None:
                self.silence_start = current_time
            elif current_time - self.silence_start >= self.silence_duration:
                # Silence detected for required duration after speech
                # Ensure we have a reasonable amount of audio before processing
                min_buffer_size = int(self.sample_rate * 2 * self.min_speech_duration)
                if self.buffer.tell() > min_buffer_size:
                    return True
        
        # Process if buffer gets too large (8 seconds max to allow longer utterances)
        max_buffer_size = settings.SAMPLE_RATE * 2 * 8  # 8 seconds max
        if self.buffer.tell() > max_buffer_size:
            # Only process if we've detected speech
            if self.speech_detected:
                return True
        
        self.last_chunk_time = current_time
        return False
    
    def get_audio(self):
        """Get buffered audio and reset"""
        audio_data = self.buffer.getvalue()
        self.buffer = BytesIO()
        self.silence_start = None
        self.speech_detected = False  # Reset speech detection for next utterance
        return audio_data


# ============================================================
# AI RESPONSE GENERATION
# ============================================================

def generate_ai_response(user_text, language="en-IN", context=None):
    """
    Generate AI response based on user input and language using Gemini AI
    Focused on finance collection calls with specific intent capture.
    Includes retry logic for 429 RESOURCE_EXHAUSTED errors.
    """
    # Define human-like fallbacks for when the API is completely exhausted
    FALLBACKS = {
        "en-IN": "I'm sorry, I'm having a bit of trouble hearing you clearly. Could you please repeat that?",
        "hi-IN": "क्षमा करें, मुझे आपकी बात सुनने में थोड़ी कठिनाई हो रही है। क्या आप कृपया उसे फिर से दोहरा सकते हैं?",
        "ta-IN": "மன்னிக்கவும், உங்கள் பேச்சைக் கேட்பதில் எனக்கு சற்று சிரமம் உள்ளது. தயவுசெய்து அதை மீண்டும் கூற முடியுமா?"
    }
    
    if not gemini_client:
        print("[AI RESPONSE] ⚠️  Gemini client not available, using fallback")
        user_lower = user_text.lower()
        # Route to language-specific fallback responses
        if language == "hi-IN":
            return generate_hindi_response(user_lower)
        elif language == "ta-IN":
            return generate_tamil_response(user_lower)
        else:
            return generate_english_response(user_lower)
    
    # Get language configuration
    lang_config = settings.LANGUAGE_CONFIG.get(language, settings.LANGUAGE_CONFIG["en-IN"])
    lang_name = lang_config["name"]
    
    # Build conversation history from context
    conversation_history = ""
    if context and "conversation" in context and context["conversation"]:
        conversation_history = "\n".join([
            f"{entry['speaker']}: {entry['text']}" 
            for entry in context["conversation"][-5:]  # Last 5 exchanges for context
        ])
    
    # Create dynamic prompt for Gemini based on language
    if language == "en-IN":
        system_prompt = """You are a highly professional and empathetic human-like collection assistant named Vidya, calling from a finance agency.
        
Your goal is to have a natural, real-time conversation with a borrower about their loan repayment.

CONVERSATION STYLE:
1. **SOUND HUMAN**: Use natural phrasing like 'I understand', 'Got it', or 'Thank you for sharing that'.
2. **BE PROFESSIONAL**: Maintain a polite, helpful, but firm female persona.
3. **FINANCE FOCUS**: Stay on topic regarding payments, EMIs, or outstanding amounts.
4. **NO TRUNCATION**: Never stop speaking in the middle of a thought. Every sentence must be grammatically complete and concluded.
5. **REAL-TIME FLOW**: If the user makes a commitment (e.g., 'paying tomorrow'), acknowledge it warmly and confirm.

Keep it brief (1-2 sentences) but sound like a real person. Respond in English only."""
    
    elif language == "hi-IN":
        system_prompt = """आप एक वित्त एजेंसी की ओर से लोन वसूली के लिए कॉल करने वाली एक बहुत ही पेशेवर और सहानुभूतिपूर्ण (empathetic) मानव-जैसी सहायक 'विद्या' हैं।

आपका लक्ष्य उधारकर्ता के साथ उनके लोन भुगतान के बारे में स्वाभाविक, वास्तविक समय (real-time) में बातचीत करना है।

वार्तालाप शैली:
1. **इंसानी व्यवहार**: 'मैं समझ सकती हूँ', 'ठीक है', या 'यह जानकारी देने के लिए धन्यवाद' जैसे स्वाभाविक वाक्यांशों का उपयोग करें।
2. **पेशेवर व्यक्तित्व**: एक विनम्र, सहायक लेकिन दृढ़ महिला व्यक्तित्व बनाए रखें (स्त्रीलिंग 'रही हूँ' का प्रयोग करें)।
3. **अधूरा न छोड़ें**: कभी भी किसी विचार के बीच में बोलना बंद न करें। हर वाक्य व्याकरण की दृष्टि से पूर्ण और समाप्त होना चाहिए।

जवाब संक्षिप्त रखें (1-2 वाक्य) लेकिन एक रोबोट की तरह नहीं, बल्कि एक असली इंसान की तरह बोलें। केवल हिंदी में जवाब दें।"""
    
    else:  # Tamil (ta-IN)
        system_prompt = """நீங்கள் ஒரு நிதி நிறுவனத்தின் சார்பாக கடன் வசூலுக்காக அழைக்கும் மிகவும் தொழில்முறை மற்றும் கனிவான மனித-உதவியாளர் 'வித்யா'. உங்களின் நோக்கம் வாடிக்கையாளருடன் இயல்பாகப் பேசி அவர்களின் நிலுவைத் தொகையை வசூலிப்பதாகும்.

உரையாடல் நடை:
1. **இயல்பான குரல்**: 'எனக்கு புரிகிறது', 'சரி' அல்லது 'தகவலுக்கு நன்றி' போன்ற இயல்பான சொற்களைப் பயன்படுத்தவும்.
2. **முழுமையான வாக்கியங்கள்**: எக்காரணம் கொண்டும் வாக்கியத்தைப் பாதியிலேயே நிறுத்த வேண்டாம். ஒவ்வொரு சொல்லும் இலக்கணப்படி முழுமையாக இருக்க வேண்டும்.

பதில்கள் சுருக்கமாக (1-2 வாக்கியங்கள்) இருக்க வேண்டும், ஆனால் ஒரு மனிதனைப் போலவே ஒலிக்க வேண்டும். தமிழில் மட்டும் பதிலளிக்கவும்."""
    
    # Create the full prompt with conversation context
    prompt = f"""{system_prompt}
 
CONVERSATION HISTORY:
{conversation_history if conversation_history else "This is the start of the conversation (Greeting phase)."}
 
USER'S LATEST MESSAGE: {user_text}
 
Generate a natural, human-to-human response in {lang_name}. 
CRITICAL RULE: YOU MUST COMPLETE EVERY SENTENCE YOU START. NEVER TRUNCATE MID-SENTENCE. 
Ensure the response is grammatically perfect and ends with proper punctuation."""
    
    # Retry logic for 429 Resource exhausted
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            print(f"[AI RESPONSE] 🤖 Generating (Attempt {attempt+1}/{max_retries}) using Gemini AI ({lang_name})...")
            
            # Call Gemini API
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=400,
                )
            )
            
            ai_response = response.text.strip()
            
            # Safety Check: Strip trailing conjunctions that indicate truncation
            unwanted_endings = (' and', ' or', ' with', ' to', ' but', ' because', ' for', ' then')
            for ending in unwanted_endings:
                if ai_response.lower().endswith(ending):
                    ai_response = ai_response[:-len(ending)].strip()
                    print(f"[AI RESPONSE] ⚠️  Stripped trailing '{ending}' from response")

            # Ensure the response ends with proper punctuation
            # This helps avoid cut-off sentences and ensures clean endings
            valid_punctuations = ('.', '?', '!', '।', '॥')
            if ai_response and not ai_response.endswith(valid_punctuations):
                # If response doesn't end with punctuation, add the appropriate one
                if language == "hi-IN":
                    ai_response += " ।"  # Hindi full stop
                else:
                    ai_response += "."   # English/Tamil period
            
            print(f"[AI RESPONSE] ✅ Generated: {ai_response}")
            return ai_response
            
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"[AI RESPONSE] ⚠️  Rate limited (429). Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
            
            print(f"[AI RESPONSE] ❌ Gemini API error: {e}")
            if attempt == max_retries - 1:
                # If all retries fail, return a polite fallback message
                return FALLBACKS.get(language, FALLBACKS["en-IN"])
    
    return FALLBACKS.get(language, FALLBACKS["en-IN"])

# ============================================================
# CONVERSATION HANDLER
# ============================================================

class ConversationHandler:
    """Manages conversation state and transcript"""
    
    def __init__(self, call_uuid, preferred_language="en-IN", borrower_id=None):
        self.call_uuid = call_uuid
        self.borrower_id = borrower_id
        self.conversation = []
        self.context = {}
        self.is_active = True
        self.start_time = datetime.now()
        self.preferred_language = preferred_language
        self.current_language = preferred_language
        self.language_history = []
        
    def add_entry(self, speaker, text):
        """Add conversation entry"""
        entry = {
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "language": self.current_language
        }
        self.conversation.append(entry)
        # Update context with conversation for AI response generation
        self.context["conversation"] = self.conversation
        print(f"[CONV] [{speaker}] [{self.current_language}] {text}")
    
    def update_language(self, detected_language):
        """Update conversation language"""
        if detected_language != self.current_language:
            old_lang = settings.LANGUAGE_CONFIG.get(self.current_language, {}).get("name", self.current_language)
            new_lang = settings.LANGUAGE_CONFIG.get(detected_language, {}).get("name", detected_language)
            print(f"[LANG] 🔄 Switching from {old_lang} to {new_lang}")
            
            self.language_history.append({
                "from": self.current_language,
                "to": detected_language,
                "timestamp": datetime.now().isoformat()
            })
            
            self.current_language = detected_language
    
    def save_transcript(self):
        """Save conversation transcript with AI analysis"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        ai_analysis = None
        if len(self.conversation) > 1:
            print(f"\n[AI ANALYSIS] Starting Gemini AI analysis for call {self.call_uuid}")
            ai_analysis = analyze_conversation_with_gemini(self.conversation)
        else:
            print(f"[AI ANALYSIS] Skipping analysis - insufficient conversation data")
            ai_analysis = {
                "summary": "No meaningful conversation detected",
                "sentiment": "No Response",
                "sentiment_reasoning": "Insufficient data",
                "intent": "No Response",
                "intent_reasoning": "Call ended without engagement",
                "payment_date": None
            }
        
        import os
        os.makedirs(".transcripts", exist_ok=True)
        filename = f".transcripts/transcript_{self.call_uuid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        transcript_data = {
            "call_uuid": self.call_uuid,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_seconds": round(duration, 2),
            "preferred_language": self.preferred_language,
            "final_language": self.current_language,
            "language_switches": len(self.language_history),
            "language_history": self.language_history,
            "conversation": self.conversation,
            "ai_analysis": ai_analysis
        }
        
        # Save to MongoDB (Call Session Schema)
        try:
            from app.db import db
            session_data = transcript_data.copy()
            if self.borrower_id:
                session_data["loan_no"] = self.borrower_id
            db.insert_call_session(session_data)
        except Exception as e:
            print(f"[DB] ❌ Failed to save Call Session: {e}")
        
        if ai_analysis:
            print(f"\n{'='*60}")
            print(f"AI ANALYSIS SUMMARY - {self.call_uuid}")
            print(f"{'='*60}")
            print(f"📝 Summary: {ai_analysis.get('summary', 'N/A')}")
            print(f"😊 Sentiment: {ai_analysis.get('sentiment', 'N/A')} - {ai_analysis.get('sentiment_reasoning', 'N/A')}")
            print(f"🎯 Intent: {ai_analysis.get('intent', 'N/A')} - {ai_analysis.get('intent_reasoning', 'N/A')}")
            if ai_analysis.get('payment_date'):
                print(f"📅 Payment Date: {ai_analysis.get('payment_date')}")
            print(f"{'='*60}\n")
        
        return filename


# ============================================================
# CALL MANAGEMENT
# ============================================================

def make_outbound_call(to_number, language="en-IN", borrower_id=None):
    """Trigger an outbound call with preferred language and borrower ID"""
    if not voice:
        return {"success": False, "error": "Vonage client not initialized"}
    
    # Strip '+' for Vonage SDK
    if to_number.startswith('+'):
        to_number = to_number[1:]
    
    try:
        # Create call with language and borrower_id parameters in answer URL
        answer_url = f'{settings.BASE_URL}/webhooks/answer?preferred_language={language}'
        if borrower_id:
            answer_url += f'&borrower_id={borrower_id}'
        
        response = voice.create_call({
            'to': [{'type': 'phone', 'number': to_number}],
            'from_': {'type': 'phone', 'number': settings.VONAGE_FROM_NUMBER},
            'answer_url': [answer_url],
            'event_url': [f'{settings.BASE_URL}/webhooks/event']
        })
        
        call_uuid = response.uuid
        
        print(f"\n{'*'*60}")
        print(f"📞 OUTBOUND CALL INITIATED")
        print(f"{'*'*60}")
        print(f"To: {to_number}")
        print(f"UUID: {call_uuid}")
        print(f"Preferred Language: {language}")
        print(f"Answer URL: {answer_url}")
        print(f"Event URL: {settings.BASE_URL}/webhooks/event")
        print(f"{'*'*60}\n")
        
        return {
            "success": True,
            "call_uuid": call_uuid,
            "status": getattr(response, 'status', 'initiated'),
            "to_number": to_number,
            "language": language
        }
        
    except Exception as e:
        print(f"[ERROR] ❌ {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def get_call_data_store():
    """Get the global call data storage"""
    return call_data