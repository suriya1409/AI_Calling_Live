"""
AIaaS Finance Platform - Main Application
==========================================
Entry point for the FastAPI application
Runs both FastAPI (port 8000) and Flask WebSocket server (port 5000)
"""
import asyncio
import threading
import time
import json
from typing import Optional

import os
import sys

# Add the backend directory to sys.path to ensure 'app' module is found
# regardless of where the server is started from.
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.data_ingestion.views import router as data_ingestion_router
from app.ai_calling.views import router as ai_calling_router
from app.auth.views import router as auth_router

from app.ai_calling.service import (
    call_data,
    ConversationHandler,
    AudioBuffer,
    transcribe_sarvam,
    detect_language,
    generate_ai_response,
    synthesize_sarvam,
    is_farewell_response,
    detect_gender_from_name,
)
from config import settings

app = FastAPI(
    title="AIaaS Finance Platform",
    version="1.0.0",
    description="AI as a Service for Finance Agencies"
)

# --- CORS (allow all for development; restrict in production) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(ai_calling_router, prefix="/ai_calling", tags=["AI Calling"])

@app.get("/")
@app.get("/health")
async def root_health():
    import logging
    logging.getLogger(__name__).info("❤️ Health check ping received")
    return {"status": "healthy", "service": "AI Finance Platform"}

print("🚀 AI Finance Backend is starting...", flush=True)
app.include_router(data_ingestion_router, prefix="/data_ingestion", tags=["Data Ingestion"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AIaaS Finance Platform API",
        "version": "1.0.0",
        "status": "active",
        "endpoints": {
            "data_ingestion": "/data_ingestion",
            "ai_calling": "/ai_calling",
            "health": "/health",
            "vonage_webhooks": "/webhooks/*",
            "websocket": "/socket/<uuid>"
        }
    }


# ============================================================
# NOISE / ECHO DETECTION
# ============================================================

def _is_echo_or_noise(text):
    """Detect if a transcript is likely echo/noise rather than real user speech."""
    text_lower = text.lower().strip()
    if len(text_lower) < 2: return True
    noise_only_words = {'hmm', 'hm', 'uh', 'um', 'ah', 'oh', 'हम्म', 'ह', 'अ', 'उ'}
    words = text_lower.split()
    if not words or all(w in noise_only_words for w in words): return True
    unique_words = set(words)
    if len(unique_words) == 1 and len(words) >= 4: return True
    if len(unique_words) <= 3 and len(words) >= 9: return True
    return False


# ============================================================
# WEBHOOK ENDPOINTS
# ============================================================

@app.api_route("/webhooks/answer", methods=["GET", "POST"], tags=["Vonage"])
async def answer_webhook(request: Request):
    """Handle incoming call - return NCCO with greeting"""
    if request.method == "GET":
        data = dict(request.query_params)
    else:
        try:
            data = await request.json()
        except:
            data = {}

    if not data:
        return JSONResponse(content=[])

    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    preferred_language = data.get('preferred_language', 'en-IN')
    borrower_id = data.get('borrower_id')
    user_id = data.get('user_id')

    # Create handler
    handler = ConversationHandler(
        call_uuid, 
        user_id=user_id, 
        preferred_language=preferred_language, 
        borrower_id=borrower_id
    )
    call_data[call_uuid] = handler

    # Fetch context
    if borrower_id and user_id:
        try:
            from app.table_models.borrowers_table import get_borrower_by_no
            borrower_data = await get_borrower_by_no(user_id, borrower_id)
            if borrower_data:
                borrower_context = {
                    "name": borrower_data.get("BORROWER", ""),
                    "amount": borrower_data.get("AMOUNT", 0),
                    "due_date": borrower_data.get("DUE_DATE", ""),
                    "loan_no": borrower_id
                }
                handler.context['borrower_info'] = borrower_context
        except Exception as e:
            print(f"[RE-UNIFIED] ⚠️ Context error: {e}")

    # Greeting logic (Simplified for brevity, but matches flask_server)
    lang_config = settings.LANGUAGE_CONFIG.get(preferred_language, settings.LANGUAGE_CONFIG['en-IN'])
    greeting = lang_config["greeting"]
    
    # Check if we can personalize
    if 'borrower_info' in handler.context:
        info = handler.context['borrower_info']
        b_name = info.get('name')
        b_due_date = info.get('due_date', 'soon')
        gender = detect_gender_from_name(b_name)
        
        if preferred_language == "hi-IN":
            honorific = "श्रीमती" if gender == "female" else "श्री"
            greeting = f"नमस्ते {honorific} {b_name} जी, आशा है आप अच्छे हैं। यह आपके लोन पेमेंट के बारे में है। ड्यू डेट {b_due_date} है।"
        elif preferred_language == "ta-IN":
            honorific = "திருமதி" if gender == "female" else "திரு"
            greeting = f"வணக்கம் {honorific} {b_name}, உங்கள் கடன் குறித்த அழைப்பு. செலுத்த வேண்டிய தேதி {b_due_date}."
        else:
            mr_mrs = "Mrs" if gender == "female" else "Mr"
            greeting = f"Hi {mr_mrs} {b_name}, hope you are well. Calling regarding your loan due on {b_due_date}."

    handler.add_entry("AI", greeting)

    # NCCO
    ws_base = settings.BASE_URL.replace("http", "ws")
    ws_uri = f"{ws_base}/socket/{call_uuid}"
    
    ncco = [
        {
            "action": "connect",
            "eventUrl": [f"{settings.BASE_URL}/webhooks/event"],
            "from": settings.VONAGE_FROM_NUMBER,
            "endpoint": [{
                "type": "websocket",
                "uri": ws_uri,
                "content-type": "audio/l16;rate=16000",
                "headers": {"call_uuid": call_uuid, "user_id": user_id or ""}
            }]
        }
    ]
    return JSONResponse(content=ncco)


@app.api_route("/webhooks/event", methods=["GET", "POST"], tags=["Vonage"])
async def event_webhook(request: Request):
    """Handle call events"""
    if request.method == "GET":
        data = dict(request.query_params)
    else:
        try:
            data = await request.json()
        except:
            data = {}

    if not data: return JSONResponse(content={})
    
    event_type = data.get('status')
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    
    print(f"[EVENT] {event_type} for {call_uuid}")

    if event_type == 'completed' and call_uuid in call_data:
        handler = call_data[call_uuid]
        handler.is_active = False
        await handler.save_transcript()
        del call_data[call_uuid]
        print(f"[SUCCESS] Call {call_uuid} saved.")

    return JSONResponse(content={})


# ============================================================
# WEBSOCKET ENDPOINT
# ============================================================

@app.websocket("/socket/{call_uuid}")
async def websocket_handler(websocket: WebSocket, call_uuid: str):
    """FastAPI WebSocket handler for Vonage"""
    await websocket.accept()
    
    if call_uuid not in call_data:
        await websocket.close()
        return

    handler = call_data[call_uuid]
    audio_buffer = AudioBuffer()
    ai_speaking_until = 0

    try:
        while True:
            # Receive message
            message = await websocket.receive_bytes()
            current_time = time.time()
            
            if current_time < ai_speaking_until:
                continue
            
            if ai_speaking_until > 0 and (current_time - ai_speaking_until) < 0.3:
                audio_buffer.get_audio()
                ai_speaking_until = 0
                continue

            if audio_buffer.add_chunk(message):
                audio_data = audio_buffer.get_audio()
                transcript = transcribe_sarvam(audio_data, handler.current_language)
                
                if transcript:
                    clean_text = transcript.strip()
                    if _is_echo_or_noise(clean_text): continue
                    
                    # Process logic
                    handler.add_entry("User", clean_text)
                    ai_response = generate_ai_response(clean_text, handler.current_language, handler.context)
                    handler.add_entry("AI", ai_response)
                    
                    audio_response = synthesize_sarvam(ai_response, handler.current_language)
                    if audio_response:
                        await websocket.send_bytes(audio_response)
                        audio_duration = len(audio_response) / (16000 * 2)
                        ai_speaking_until = time.time() + audio_duration + 1.5
                        audio_buffer.get_audio() # Flush

                    if is_farewell_response(ai_response, handler.current_language):
                        handler.is_active = False
                        await handler.save_transcript()
                        break
    except WebSocketDisconnect:
        print(f"[WS] Disconnected: {call_uuid}")
    except Exception as e:
        print(f"[WS] Error: {e}")
    finally:
        if call_uuid in call_data:
            handler = call_data[call_uuid]
            handler.is_active = False
            await handler.save_transcript()


@app.get("/health", tags=["Health"])
async def health_check():
    """General health check endpoint"""
    return {
        "status": "healthy",
        "service": "AIaaS Finance Platform",
        "port": 8000
    }


if __name__ == "__main__":
    import uvicorn
    print("\n🚀 STARTING UNIFIED AIaaS FINANCE PLATFORM ON PORT 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)