from fastapi import APIRouter, WebSocket, Request, Response, WebSocketDisconnect
from fastapi.responses import JSONResponse
import json
import uuid
import time
import asyncio
import logging
from typing import Dict

from app.ai_calling.service import (
    call_data,
    ConversationHandler,
    AudioBuffer,
    transcribe_sarvam,
    detect_language,
    detect_language_from_stt,
    generate_ai_response,
    synthesize_sarvam,
    is_farewell_response,
    detect_gender_from_name,
)
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================
# NOISE / ECHO DETECTION
# ============================================================

def _is_echo_or_noise(text):
    """Detect if a transcript is likely echo/noise rather than real user speech."""
    text_lower = text.lower().strip()
    if len(text_lower) < 2: return True
    noise_only_words = {'hmm', 'hm', 'uh', 'um', 'ah', 'oh', 'हम्म', 'ह', 'अ', 'उ'}
    words = text_lower.split()
    if not words: return True
    if all(w in noise_only_words for w in words): return True
    unique_words = set(words)
    if len(unique_words) == 1 and len(words) >= 4: return True
    if len(unique_words) <= 3 and len(words) >= 9: return True
    return False

# ============================================================
# MANUAL CALL BRIDGING (Agent <-> Borrower)
# ============================================================

class ManualBridge:
    def __init__(self, call_uuid):
        self.call_uuid = call_uuid
        self.vonage_ws: WebSocket = None
        self.agent_ws: WebSocket = None
        self.active = True
        self.ready_event = asyncio.Event()
        self.start_time = time.time()
        self.v2a_queue = asyncio.Queue()
        self.a2v_queue = asyncio.Queue()

    async def set_vonage(self, ws: WebSocket):
        self.vonage_ws = ws
        if self.agent_ws:
            self.ready_event.set()

    async def set_agent(self, ws: WebSocket):
        self.agent_ws = ws
        if self.vonage_ws:
            self.ready_event.set()

    async def bridge_v2a(self):
        """Vonage -> Agent"""
        try:
            while self.active:
                if not self.vonage_ws: break
                data = await self.vonage_ws.receive_bytes()
                if self.agent_ws:
                    await self.agent_ws.send_bytes(data)
        except Exception as e:
            logger.error(f"[BRIDGE] V->A Error {self.call_uuid}: {e}")
        finally:
            self.active = False

    async def bridge_a2v(self):
        """Agent -> Vonage"""
        try:
            while self.active:
                if not self.agent_ws: break
                data = await self.agent_ws.receive_bytes()
                if self.vonage_ws:
                    await self.vonage_ws.send_bytes(data)
        except Exception as e:
            logger.error(f"[BRIDGE] A->V Error {self.call_uuid}: {e}")
        finally:
            self.active = False

manual_bridges: Dict[str, ManualBridge] = {}

# ============================================================
# WEBHOOK ENDPOINTS
# ============================================================

@router.api_route("/webhooks/answer", methods=["GET", "POST"])
async def answer_webhook(request: Request):
    """Handle incoming call - return NCCO."""
    if request.method == "GET":
        data = dict(request.query_params)
    else:
        data = await request.json()
    
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    is_manual = data.get('is_manual') == 'true'
    preferred_language = data.get('preferred_language', 'en-IN')
    borrower_id = data.get('borrower_id')
    user_id = data.get('user_id')
    
    # WebSocket URI setup
    base_url = settings.BASE_URL
    prefix = 'wss://' if base_url.startswith('https://') else 'ws://'
    clean_url = base_url.split('://')[-1]
    
    if is_manual:
        ws_uri = f"{prefix}{clean_url}/ai_calling/manual-socket/{call_uuid}"
        if call_uuid not in manual_bridges:
            manual_bridges[call_uuid] = ManualBridge(call_uuid)
        
        ncco = [
            {
                "action": "connect",
                "from": settings.VONAGE_FROM_NUMBER,
                "endpoint": [
                    {
                        "type": "websocket",
                        "uri": ws_uri,
                        "content-type": "audio/l16;rate=16000",
                        "headers": {"call_uuid": call_uuid}
                    }
                ]
            }
        ]
        return JSONResponse(ncco)

    # AI Call Logic
    handler = ConversationHandler(
        call_uuid, 
        user_id=user_id, 
        preferred_language=preferred_language, 
        borrower_id=borrower_id
    )
    call_data[call_uuid] = handler
    
    # Load Borrower Context
    borrower_context = None
    if borrower_id and user_id:
        try:
            from app.table_models.borrowers_table import get_borrower_by_no
            borrower_data = await get_borrower_by_no(user_id, borrower_id)
            if borrower_data:
                borrower_context = {
                    "name": borrower_data.get("BORROWER", ""),
                    "amount": borrower_data.get("AMOUNT", 0),
                    "due_date": borrower_data.get("DUE_DATE", ""),
                }
                handler.context['borrower_info'] = borrower_context
        except Exception as e:
            logger.error(f"[WEBHOOK] Could not fetch borrower context: {e}")
    
    # Greeting
    if borrower_context and borrower_context.get("name"):
        b_name = borrower_context["name"]
        b_due_date = borrower_context.get("due_date", "soon")
        gender = detect_gender_from_name(b_name)
        
        if preferred_language == "hi-IN":
            honorific = "श्रीमती" if gender == "female" else "श्री"
            greeting = f"नमस्ते {honorific} {b_name} जी, आशा है आप अच्छे हैं। आपकी ड्यू डेट जल्द आ रही है {b_due_date}। क्या आप ड्यू डेट से पहले भुगतान कर देंगे?"
        elif preferred_language == "ta-IN":
            honorific = "திருமதி" if gender == "female" else "திரு"
            greeting = f"வணக்கம் {honorific} {b_name}, நலமாக இருப்பீர்கள் என நம்புகிறேன். உங்கள் செலுத்த வேண்டிய தேதி விரைவில் வரவிருக்கிறது {b_due_date}. நிலுவைத் தொகையை ட்யூ டேட்-க்கு முன் செலுத்துவீர்களா?"
        else:
            mr_mrs = "Mrs" if gender == "female" else "Mr"
            greeting = f"Hi {mr_mrs} {b_name}, hope you are doing well today. Your due date is coming up soon on {b_due_date}. Can you please let us know if you will be paying the balance amount before the due date?"
    else:
        lang_config = settings.LANGUAGE_CONFIG.get(preferred_language, settings.LANGUAGE_CONFIG['en-IN'])
        greeting = lang_config["greeting"]
    
    handler.add_entry("AI", greeting)
    ws_uri = f"{prefix}{clean_url}/ai_calling/socket/{call_uuid}"
    
    ncco = [
        {
            "action": "connect",
            "eventUrl": [f"{settings.BASE_URL}/ai_calling/webhooks/event"],
            "from": settings.VONAGE_FROM_NUMBER,
            "endpoint": [
                {
                    "type": "websocket",
                    "uri": ws_uri,
                    "content-type": "audio/l16;rate=16000",
                    "headers": {"call_uuid": call_uuid, "user_id": user_id}
                }
            ]
        }
    ]
    
    # Cache greeting audio in handler for the socket
    greeting_audio = synthesize_sarvam(greeting, preferred_language)
    if greeting_audio:
        handler.context['greeting_audio'] = greeting_audio
        
    return JSONResponse(ncco)

@router.api_route("/webhooks/event", methods=["GET", "POST"])
async def event_webhook(request: Request):
    if request.method == "GET":
        data = dict(request.query_params)
    else:
        data = await request.json()
    
    event_type = data.get('status')
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    
    if event_type == 'completed' and call_uuid in call_data:
        handler = call_data[call_uuid]
        handler.is_active = False
        await handler.save_transcript()
        del call_data[call_uuid]
        
    return Response(status_code=200)

# ============================================================
# WEBSOCKET ENDPOINTS
# ============================================================

@router.websocket("/socket/{call_uuid}")
async def websocket_handler(websocket: WebSocket, call_uuid: str):
    await websocket.accept()
    if call_uuid not in call_data:
        await websocket.close()
        return
    
    handler = call_data[call_uuid]
    audio_buffer = AudioBuffer()
    ai_speaking_until = 0
    
    # Send Greeting Audio
    greeting_audio = handler.context.get('greeting_audio')
    if greeting_audio:
        await websocket.send_bytes(greeting_audio)
        audio_duration_secs = len(greeting_audio) / (16000 * 2)
        ai_speaking_until = time.time() + audio_duration_secs + 1.5

    try:
        while True:
            try:
                message = await websocket.receive_bytes()
            except WebSocketDisconnect:
                break
                
            current_time = time.time()
            if current_time < ai_speaking_until: continue
            
            if ai_speaking_until > 0 and (current_time - ai_speaking_until) < 0.3:
                audio_buffer.get_audio() # Flush
                ai_speaking_until = 0
                continue
            
            if audio_buffer.add_chunk(message):
                audio_data = audio_buffer.get_audio()
                transcript, detected_lang = detect_language_from_stt(
                    audio_data, handler.preferred_language, handler.alternate_language
                )
                
                if transcript:
                    clean_text = transcript.strip()
                    if _is_echo_or_noise(clean_text): continue
                    
                    handler.handle_language_switch(detected_lang)
                    handler.add_entry("User", clean_text)
                    
                    ai_response = generate_ai_response(clean_text, handler.current_language, handler.context)
                    handler.add_entry("AI", ai_response)
                    
                    audio_response = synthesize_sarvam(ai_response, handler.current_language)
                    if audio_response:
                        await websocket.send_bytes(audio_response)
                        duration = len(audio_response) / (16000 * 2)
                        ai_speaking_until = time.time() + duration + 1.5
                        audio_buffer.get_audio() # Flush
                    
                    if is_farewell_response(ai_response, handler.current_language):
                        if audio_response:
                            await asyncio.sleep(duration + 0.5)
                        handler.is_active = False
                        await handler.save_transcript()
                        break
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        if call_uuid in call_data:
            del call_data[call_uuid]

@router.websocket("/manual-socket/{call_uuid}")
async def manual_socket_handler(websocket: WebSocket, call_uuid: str):
    await websocket.accept()
    if call_uuid not in manual_bridges:
        manual_bridges[call_uuid] = ManualBridge(call_uuid)
    bridge = manual_bridges[call_uuid]
    await bridge.set_vonage(websocket)
    
    try:
        await asyncio.wait_for(bridge.ready_event.wait(), timeout=30)
        await asyncio.gather(bridge.bridge_v2a(), bridge.bridge_a2v())
    except Exception as e:
        logger.error(f"[WS-MANUAL] error: {e}")
    finally:
        if call_uuid in manual_bridges: del manual_bridges[call_uuid]

@router.websocket("/agent-socket/{call_uuid}")
async def agent_socket_handler(websocket: WebSocket, call_uuid: str):
    await websocket.accept()
    if call_uuid not in manual_bridges:
        manual_bridges[call_uuid] = ManualBridge(call_uuid)
    bridge = manual_bridges[call_uuid]
    await bridge.set_agent(websocket)
    
    try:
        await asyncio.wait_for(bridge.ready_event.wait(), timeout=30)
        await bridge.bridge_a2v()
    except Exception as e:
        logger.error(f"[WS-AGENT] error: {e}")
