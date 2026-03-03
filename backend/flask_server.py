"""
Flask WebSocket Server for Vonage Integration - User Isolation Fix
==============================================
Handles Vonage webhooks and WebSocket connections for real-time audio
Supports User Isolation by tracking user_id from outbound calls
"""

import os
import json
import uuid
import time
import threading
import asyncio
from flask import Flask, request, jsonify
from flask_sock import Sock
from flask_cors import CORS

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

# ============================================================
# FLASK APP SETUP
# ============================================================

flask_app = Flask(__name__)
CORS(flask_app)  # Enable CORS for all routes including WebSockets
sock = Sock(flask_app)

# Reference to the main FastAPI/uvicorn event loop (set from main.py on startup)
main_event_loop = None

def set_main_loop(loop):
    """Called from main.py to store the uvicorn event loop for cross-thread async calls"""
    global main_event_loop
    main_event_loop = loop
    print(f"[FLASK] ✅ Main event loop reference stored for async DB operations")

print("[FLASK] WebSocket server initialized with User Isolation support")


# ============================================================
# NOISE / ECHO DETECTION
# ============================================================

def _is_echo_or_noise(text):
    """Detect if a transcript is likely echo/noise rather than real user speech.
    Returns True if the text should be SKIPPED."""
    text_lower = text.lower().strip()
    
    # Too short to be meaningful
    if len(text_lower) < 2:
        return True
    
    # Common noise/filler words that appear when mic picks up ambient sound
    noise_only_words = {'hmm', 'hm', 'uh', 'um', 'ah', 'oh', 'हम्म', 'ह', 'अ', 'उ'}
    
    words = text_lower.split()
    if not words:
        return True
    
    # If ALL words are noise fillers, skip
    if all(w in noise_only_words for w in words):
        return True
    
    # If the same short word/phrase is repeated 4+ times (echo artifact)
    unique_words = set(words)
    if len(unique_words) == 1 and len(words) >= 4:
        return True
    
    # If a short phrase is repeated 3+ times
    if len(unique_words) <= 3 and len(words) >= 9:
        return True
    
    return False


# ============================================================
# WEBHOOK ENDPOINTS
# ============================================================

# ============================================================
# MANUAL CALL BRIDGING (Agent <-> Borrower)
# ============================================================

manual_bridges = {}
manual_bridges_lock = threading.Lock()

class ManualBridge:
    def __init__(self, call_uuid):
        self.call_uuid = call_uuid
        self.vonage_ws = None
        self.agent_ws = None
        self.active = True
        self.ready_event = threading.Event()
        self.start_time = time.time()

    def set_vonage(self, ws):
        with manual_bridges_lock:
            self.vonage_ws = ws
            if self.agent_ws:
                self.ready_event.set()

    def set_agent(self, ws):
        with manual_bridges_lock:
            self.agent_ws = ws
            if self.vonage_ws:
                self.ready_event.set()

    def bridge_v2a(self):
        """Vonage -> Agent"""
        print(f"[BRIDGE] Start V->A for {self.call_uuid}")
        try:
            while self.active:
                if not self.vonage_ws: break
                data = self.vonage_ws.receive(timeout=10)
                if data is None: break
                if self.agent_ws:
                    try:
                        self.agent_ws.send(data)
                    except: pass
        except Exception as e:
            print(f"[BRIDGE] V->A Error {self.call_uuid}: {e}")
        finally:
            self.active = False
            print(f"[BRIDGE] Stop V->A for {self.call_uuid}")

    def bridge_a2v(self):
        """Agent -> Vonage"""
        print(f"[BRIDGE] Start A->V for {self.call_uuid}")
        try:
            while self.active:
                if not self.agent_ws: break
                data = self.agent_ws.receive(timeout=10)
                if data is None: break
                if self.vonage_ws:
                    try:
                        self.vonage_ws.send(data)
                    except: pass
        except Exception as e:
            print(f"[BRIDGE] A->V Error {self.call_uuid}: {e}")
        finally:
            self.active = False
            print(f"[BRIDGE] Stop A->V for {self.call_uuid}")

@flask_app.route('/webhooks/answer', methods=['GET', 'POST'])
def answer_webhook():
    """
    Handle incoming call - return NCCO.
    If is_manual=true, connect to manual-socket.
    Otherwise, connect to AI socket via ConversationHandler.
    """
    if request.method == 'GET':
        data = request.args.to_dict()
    else:
        data = request.get_json() or {}
    
    if not data:
        return jsonify([]), 200
    
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    is_manual = data.get('is_manual') == 'true'
    preferred_language = data.get('preferred_language', 'en-IN')
    borrower_id = data.get('borrower_id')
    user_id = data.get('user_id')
    
    # WebSocket URI
    base_url = settings.BASE_URL
    prefix = 'wss://' if base_url.startswith('https://') else 'ws://'
    clean_url = base_url.split('://')[-1]
    
    if is_manual:
        print(f"\n[WEBHOOK] 📞 Manual Call Answer URL hit:")
        print(f"  Call UUID: {call_uuid}")
        print(f"  Borrower: {borrower_id}")
        ws_uri = f"{prefix}{clean_url}/manual-socket/{call_uuid}"
        print(f"  Linking to: {ws_uri}")
        
        with manual_bridges_lock:
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
        return jsonify(ncco)

    # ── AI CALL LOGIC (Existing) ──
    
    if not user_id:
        print(f"[WEBHOOK] ⚠️  Warning: answer webhook missing user_id for call {call_uuid}")

    # Create conversation handler with preferred language, borrower_id, and user_id
    handler = ConversationHandler(
        call_uuid, 
        user_id=user_id, 
        preferred_language=preferred_language, 
        borrower_id=borrower_id
    )
    call_data[call_uuid] = handler
    
    # ── FETCH BORROWER DETAILS FROM DB ──
    # So the AI knows the borrower's name, due amount, EMI, etc. during the conversation
    borrower_context = None
    if borrower_id and user_id and main_event_loop and main_event_loop.is_running():
        try:
            from app.table_models.borrowers_table import get_borrower_by_no
            future = asyncio.run_coroutine_threadsafe(
                get_borrower_by_no(user_id, borrower_id),
                main_event_loop
            )
            borrower_data = future.result(timeout=5)
            if borrower_data:
                borrower_context = {
                    "name": borrower_data.get("BORROWER", ""),
                    "amount": borrower_data.get("AMOUNT", 0),
                    "emi": borrower_data.get("EMI", 0),
                    "due_date": borrower_data.get("DUE_DATE", ""),
                    "last_paid": borrower_data.get("LAST DUE REVD DATE", borrower_data.get("LAST_PAID_DATE", "")),
                    "payment_category": borrower_data.get("Payment_Category", ""),
                    "loan_no": borrower_id
                }
                handler.context['borrower_info'] = borrower_context
                print(f"[WEBHOOK] 📋 Borrower context loaded: {borrower_context.get('name')}, ₹{borrower_context.get('amount')}")
        except Exception as e:
            print(f"[WEBHOOK] ⚠️  Could not fetch borrower context: {e}")
    
    # ── PERSONALIZED GREETING WITH GENDER-AWARE Mr/Mrs ──
    lang_config = settings.LANGUAGE_CONFIG.get(preferred_language, settings.LANGUAGE_CONFIG['en-IN'])
    
    if borrower_context and borrower_context.get("name"):
        b_name = borrower_context["name"]
        b_amount = f"₹{borrower_context['amount']:,.2f}" if borrower_context.get("amount") else ""
        b_due_date = borrower_context.get("due_date", "soon")
        
        # Detect gender from name for Mr/Mrs
        gender = detect_gender_from_name(b_name)
        
        if preferred_language == "hi-IN":
            honorific = "श्रीमती" if gender == "female" else "श्री"
            sir_madam = "मैडम" if gender == "female" else "श्रीमान"
            greeting = (f"नमस्ते {honorific} {b_name} जी, आशा है आप अच्छे हैं। "
                       f"हम लोन सेक्टर से कॉल कर रहे हैं, यह आपके उधार लिए गए लोन के बारे में एक सामान्य फॉलो-अप कॉल है। "
                       f"आपकी ड्यू डेट जल्द आ रही है {b_due_date}। "
                       f"क्या आप ड्यू डेट से पहले बकाया राशि का भुगतान कर देंगे?")
        elif preferred_language == "ta-IN":
            honorific = "திருமதி" if gender == "female" else "திரு"
            sir_madam = "மேடம்" if gender == "female" else "ஐயா"
            greeting = (f"வணக்கம் {honorific} {b_name}, நலமாக இருப்பீர்கள் என நம்புகிறேன். "
                       f"கடன் பிரிவிலிருந்து அழைக்கிறோம், நீங்கள் பெற்ற கடன் தொகை குறித்த வழக்கமான பின்தொடர் அழைப்பு. "
                       f"உங்கள் செலுத்த வேண்டிய தேதி விரைவில் வரவிருக்கிறது {b_due_date}. "
                       f"நிலுவைத் தொகையை ட்யூ டேட்-க்கு முன் செலுத்துவீர்களா?")
        else:
            mr_mrs = "Mrs" if gender == "female" else "Mr"
            sir_madam = "ma'am" if gender == "female" else "sir"
            greeting = (f"Hi {mr_mrs} {b_name}, hope you are doing well today. "
                       f"We are calling from the Loan sector, this is a general check-up call regarding the Loan amount that you have borrowed. "
                       f"Your due date is coming up soon on {b_due_date}. "
                       f"Can you please let us know if you will be paying the balance amount before the due date?")
        
        # Store gender info in handler context for later use
        handler.context['gender'] = gender
    else:
        greeting = lang_config["greeting"]
    
    handler.add_entry("AI", greeting)
    
    # WebSocket URI
    ws_uri = f"{prefix}{clean_url}/socket/{call_uuid}"
    
    # Generate greeting audio
    greeting_audio = synthesize_sarvam(greeting, preferred_language)
    
    # NCCO
    ncco = [
        {
            "action": "connect",
            "eventUrl": [f"{settings.BASE_URL}/webhooks/event"],
            "from": settings.VONAGE_FROM_NUMBER,
            "endpoint": [
                {
                    "type": "websocket",
                    "uri": ws_uri,
                    "content-type": "audio/l16;rate=16000",
                    "headers": {
                        "call_uuid": call_uuid,
                        "user_id": user_id
                    }
                }
            ]
        }
    ]
    
    if greeting_audio:
        if not hasattr(flask_app, 'greeting_cache'):
            flask_app.greeting_cache = {}
        flask_app.greeting_cache[call_uuid] = greeting_audio
    
    return jsonify(ncco)
    

@sock.route('/manual-socket/<call_uuid>')
def manual_socket_handler(ws, call_uuid):
    """Bridge for Vonage Side"""
    with manual_bridges_lock:
        bridge = manual_bridges.get(call_uuid)
        if not bridge:
            bridge = ManualBridge(call_uuid)
            manual_bridges[call_uuid] = bridge
    
    bridge.set_vonage(ws)
    print(f"[WS] 📞 Vonage connected to manual bridge {call_uuid}")
    
    # Wait for agent
    if not bridge.ready_event.wait(timeout=30):
        print(f"[WS] ⚠️ Manual call {call_uuid} timed out waiting for agent")
        return

    # Start bridging in two directions
    t = threading.Thread(target=bridge.bridge_v2a)
    t.start()
    bridge.bridge_a2v()
    
    # Cleanup
    with manual_bridges_lock:
        if call_uuid in manual_bridges: del manual_bridges[call_uuid]

@sock.route('/agent-socket/<call_uuid>')
def agent_socket_handler(ws, call_uuid):
    """Bridge for Browser/Agent Side"""
    with manual_bridges_lock:
        bridge = manual_bridges.get(call_uuid)
        if not bridge:
            bridge = ManualBridge(call_uuid)
            manual_bridges[call_uuid] = bridge
    
    bridge.set_agent(ws)
    print(f"[WS] 🎧 Agent connected to manual bridge {call_uuid}")
    
    # Wait for Vonage
    if not bridge.ready_event.wait(timeout=30):
        print(f"[WS] ⚠️ Manual call {call_uuid} timed out waiting for Vonage")
        return

    bridge.bridge_a2v()


@flask_app.route('/webhooks/event', methods=['GET', 'POST'])
def event_webhook():
    """Handle call events - Saves transcript via the main uvicorn event loop"""
    if request.method == 'GET':
        data = request.args.to_dict()
    else:
        data = request.get_json() or {}
    
    if not data: return ('', 200)
    
    event_type = data.get('status')
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    
    # ── DETAILED EVENT LOGGING ──
    # Log ALL events so we can diagnose real call failures
    reason = data.get('reason', '')
    from_num = data.get('from', '')
    to_num = data.get('to', '')
    direction = data.get('direction', '')
    print(f"\n[EVENT] 📞 Call Event Received:")
    print(f"  Status: {event_type}")
    print(f"  UUID: {call_uuid}")
    print(f"  From: {from_num} → To: {to_num}")
    print(f"  Direction: {direction}")
    if reason:
        print(f"  ⚠️  Reason: {reason}")
    if event_type in ('failed', 'rejected', 'unanswered', 'busy', 'cancelled'):
        print(f"  🚨 CALL FAILED! Full event data: {data}")
    
    # Save transcript on completion
    if event_type == 'completed' and call_uuid in call_data:
        handler = call_data[call_uuid]
        handler.is_active = False
        
        # Use the MAIN event loop (from uvicorn) so motor/MongoDB works correctly
        try:
            if main_event_loop and main_event_loop.is_running():
                # Schedule coroutine on the main loop (thread-safe)
                future = asyncio.run_coroutine_threadsafe(
                    handler.save_transcript(), 
                    main_event_loop
                )
                future.result(timeout=30)  # Wait up to 30s for DB save
            else:
                # Fallback: create a new event loop (may have motor issues)
                print("[EVENT] ⚠️  Main loop not available, using fallback loop")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(handler.save_transcript())
                loop.close()
        except Exception as e:
            print(f"[EVENT] ❌ Error saving transcript: {e}")
        
        # Cleanup
        del call_data[call_uuid]
        if hasattr(flask_app, 'greeting_cache') and call_uuid in flask_app.greeting_cache:
            del flask_app.greeting_cache[call_uuid]
        
        print(f"[SUCCESS] ✅ Isolated call {call_uuid} completed and saved.")
    
    return ('', 200)


# ============================================================
# WEBSOCKET ENDPOINT
# ============================================================

@sock.route('/socket/<call_uuid>')
def websocket_handler(ws, call_uuid):
    """Handle WebSocket connection for real-time audio with natural conversation flow.
    
    Key features:
    - Echo suppression: Cooldown period after AI speaks prevents mic from picking up AI's own audio
    - Noise filtering: Rejects gibberish/filler transcripts
    - Natural pacing: Waits for user to finish speaking before processing
    - Auto-hangup: Detects farewell responses and disconnects automatically
    - Parallel report update: Updates borrower report when call ends
    """
    if call_uuid not in call_data: return
    
    handler = call_data[call_uuid]
    audio_buffer = AudioBuffer()
    
    # Timestamp when AI will finish speaking (for echo suppression cooldown)
    ai_speaking_until = 0
    
    # Send Greeting Audio
    if hasattr(flask_app, 'greeting_cache') and call_uuid in flask_app.greeting_cache:
        greeting_audio = flask_app.greeting_cache[call_uuid]
        ws.send(greeting_audio)
        # Calculate how long the greeting audio plays + buffer time
        audio_duration_secs = len(greeting_audio) / (16000 * 2)  # 16kHz, 16-bit mono
        ai_speaking_until = time.time() + audio_duration_secs + 1.5
        print(f"[WS] 🔊 Greeting sent ({audio_duration_secs:.1f}s), cooldown until {ai_speaking_until:.1f}")
    
    try:
        while True:
            message = ws.receive()
            if message is None: break
            
            if isinstance(message, bytes):
                current_time = time.time()
                
                # ──── ECHO SUPPRESSION ────
                # While the AI is "speaking", ignore all incoming audio to prevent
                # the microphone from picking up the AI's own voice through the phone speaker
                if current_time < ai_speaking_until:
                    continue
                
                # Right after cooldown ends, flush the audio buffer to clear any 
                # residual echo that was buffered during the tail of the cooldown
                if ai_speaking_until > 0 and (current_time - ai_speaking_until) < 0.3:
                    audio_buffer.get_audio()  # Flush
                    ai_speaking_until = 0
                    continue
                
                # ──── SPEECH DETECTION & PROCESSING ────
                if audio_buffer.add_chunk(message):
                    audio_data = audio_buffer.get_audio()
                    
                    # ──── MULTI-LANGUAGE STT ────
                    # CRITICAL: Always pass handler.preferred_language (the original
                    # call language), NOT handler.current_language. This ensures:
                    # 1. When no alternate is established: tries ALL languages to detect first switch
                    # 2. When alternate is established: tries preferred ↔ alternate pair consistently
                    # Using current_language would shift the reference point after each switch.
                    transcript, detected_lang = detect_language_from_stt(
                        audio_data, 
                        handler.preferred_language, 
                        handler.alternate_language
                    )
                    
                    if transcript:
                        clean_text = transcript.strip()
                        
                        # Filter out noise/echo artifacts
                        if _is_echo_or_noise(clean_text):
                            print(f"[WS] 🔇 Filtered noise: '{clean_text[:50]}'")
                            continue
                        
                        # ──── DYNAMIC LANGUAGE SWITCHING ────
                        # handle_language_switch enforces the 2-language rule:
                        # - preferred_language ↔ alternate_language only
                        # - Any third language is ignored
                        language_switched = handler.handle_language_switch(detected_lang)
                        
                        if language_switched:
                            # Set context flag so AI knows to respond in new language
                            handler.context["language_switched"] = True
                            handler.context["previous_language"] = handler.language_history[-1]["from"] if handler.language_history else handler.preferred_language
                            preferred_name = settings.LANGUAGE_CONFIG.get(handler.preferred_language, {}).get('name', handler.preferred_language)
                            alt_name = settings.LANGUAGE_CONFIG.get(handler.alternate_language, {}).get('name', handler.alternate_language) if handler.alternate_language else 'None'
                            current_name = settings.LANGUAGE_CONFIG.get(handler.current_language, {}).get('name', handler.current_language)
                            print(f"[WS] 🌐 Language switched! Preferred: {preferred_name}, Alternate: {alt_name}, Current: {current_name}, Total switches: {handler.language_switch_count}")
                        else:
                            # Clear the switch flag if no switch happened
                            handler.context["language_switched"] = False
                        
                        # Process user speech
                        handler.add_entry("User", clean_text)
                        ai_response = generate_ai_response(
                            clean_text, 
                            handler.current_language, 
                            handler.context
                        )
                        handler.add_entry("AI", ai_response)
                        
                        # Clear the language switch flag after AI response is generated
                        handler.context["language_switched"] = False
                        
                        # Convert AI response to audio and send
                        audio_response = synthesize_sarvam(ai_response, handler.current_language)
                        if audio_response:
                            ws.send(audio_response)
                            
                            # ──── SET COOLDOWN ────
                            # Calculate how long this audio will play on the user's phone
                            # and ignore incoming audio for that duration + 1.5s buffer
                            audio_duration_secs = len(audio_response) / (16000 * 2)
                            ai_speaking_until = time.time() + audio_duration_secs + 1.5
                            
                            # Flush the audio buffer so we start fresh after AI finishes
                            audio_buffer.get_audio()
                            
                            print(f"[WS] 🔊 AI response sent ({audio_duration_secs:.1f}s) in {handler.current_language}, cooldown {audio_duration_secs + 1.5:.1f}s")
                        
                        # ──── AUTO-HANGUP DETECTION ────
                        # If AI said a farewell ("Thank you sir/ma'am, have a good day!"),
                        # wait for audio to finish playing, then disconnect and save report
                        if is_farewell_response(ai_response, handler.current_language):
                            print(f"[WS] 👋 Farewell detected! Auto-disconnecting call {call_uuid} after audio plays...")
                            
                            # Wait for the farewell audio to finish playing
                            if audio_response:
                                farewell_duration = len(audio_response) / (16000 * 2)
                                time.sleep(farewell_duration + 0.5)  # Wait for audio + small buffer
                            
                            # Mark handler as inactive and trigger report save
                            handler.is_active = False
                            print(f"[WS] 📊 Triggering parallel report update for call {call_uuid}...")
                            if handler.language_switch_count > 0:
                                print(f"[WS] 🌐 Call had {handler.language_switch_count} language switch(es): {handler.preferred_language} ↔ {handler.alternate_language}")
                            
                            # Save transcript & update report in parallel via main event loop
                            try:
                                if main_event_loop and main_event_loop.is_running():
                                    future = asyncio.run_coroutine_threadsafe(
                                        handler.save_transcript(),
                                        main_event_loop
                                    )
                                    # Don't block - let it save in parallel
                                    print(f"[WS] 📊 Report save scheduled in background for {call_uuid}")
                                else:
                                    print(f"[WS] ⚠️ Main loop not available for report save")
                            except Exception as save_err:
                                print(f"[WS] ❌ Error scheduling report save: {save_err}")
                            
                            # Close WebSocket to disconnect the call
                            break
                            
    except Exception as e:
        print(f"[WS] Error: {e}")
    finally:
        print(f"[WS] Disconnected: {call_uuid}")
        if handler.language_switch_count > 0:
            print(f"[WS] 📋 Language switch summary: {handler.language_switch_count} switch(es), preferred={handler.preferred_language}, alternate={handler.alternate_language}, final={handler.current_language}")


def run_flask_server():
    """Run Flask server"""
    flask_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

if __name__ == '__main__':
    run_flask_server()