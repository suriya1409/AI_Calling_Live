"""
Flask WebSocket Server for Vonage Integration - User Isolation Fix
==============================================
Handles Vonage webhooks and WebSocket connections for real-time audio
Supports User Isolation by tracking user_id from outbound calls
"""

import os
import json
import uuid
import threading
import asyncio
from flask import Flask, request, jsonify
from flask_sock import Sock

from app.ai_calling.service import (
    call_data,
    ConversationHandler,
    AudioBuffer,
    transcribe_sarvam,
    detect_language,
    generate_ai_response,
    synthesize_sarvam,
)
from config import settings

# ============================================================
# FLASK APP SETUP
# ============================================================

flask_app = Flask(__name__)
sock = Sock(flask_app)

print("[FLASK] WebSocket server initialized with User Isolation support")


# ============================================================
# WEBHOOK ENDPOINTS
# ============================================================

@flask_app.route('/webhooks/answer', methods=['GET', 'POST'])
def answer_webhook():
    """
    Handle incoming call - return NCCO with greeting in preferred language
    Extracted user_id from query params for isolation
    """
    
    # Handle both GET (query params) and POST (JSON body)
    if request.method == 'GET':
        data = request.args.to_dict()
    else:
        data = request.get_json() or {}
    
    if not data:
        return jsonify([]), 200
    
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    
    # Get Metadata for isolation
    preferred_language = data.get('preferred_language', 'en-IN')
    borrower_id = data.get('borrower_id')
    user_id = data.get('user_id') # CRITICAL for isolation
    
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
    
    # Get greeting
    lang_config = settings.LANGUAGE_CONFIG.get(preferred_language, settings.LANGUAGE_CONFIG['en-IN'])
    greeting = lang_config["greeting"]
    handler.add_entry("AI", greeting)
    
    # WebSocket URI
    base_url = settings.BASE_URL
    prefix = 'wss://' if base_url.startswith('https://') else 'ws://'
    clean_url = base_url.split('://')[-1]
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


@flask_app.route('/webhooks/event', methods=['GET', 'POST'])
async def event_webhook():
    """Handle call events - Support Async for isolated DB saves"""
    if request.method == 'GET':
        data = request.args.to_dict()
    else:
        data = request.get_json() or {}
    
    if not data: return ('', 200)
    
    event_type = data.get('status')
    call_uuid = data.get('uuid') or data.get('conversation_uuid')
    
    # Save transcript on completion
    if event_type == 'completed' and call_uuid in call_data:
        handler = call_data[call_uuid]
        handler.is_active = False
        
        # Save transcript is now async (handles isolated DB updates)
        await handler.save_transcript()
        
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
    """Handle WebSocket connection for real-time audio"""
    if call_uuid not in call_data: return
    
    handler = call_data[call_uuid]
    audio_buffer = AudioBuffer()
    
    # Send Greeting
    if hasattr(flask_app, 'greeting_cache') and call_uuid in flask_app.greeting_cache:
        ws.send(flask_app.greeting_cache[call_uuid])
    
    try:
        while True:
            message = ws.receive()
            if message is None: break
            
            if isinstance(message, bytes):
                if audio_buffer.add_chunk(message):
                    audio_data = audio_buffer.get_audio()
                    transcript = transcribe_sarvam(audio_data, handler.current_language)
                    
                    if transcript:
                        detected_lang = detect_language(transcript)
                        if detected_lang != handler.current_language:
                            handler.update_language(detected_lang)
                        
                        handler.add_entry("User", transcript)
                        ai_response = generate_ai_response(transcript, handler.current_language, handler.context)
                        handler.add_entry("AI", ai_response)
                        
                        audio_response = synthesize_sarvam(ai_response, handler.current_language)
                        if audio_response: ws.send(audio_response)
    except Exception as e:
        print(f"[WS] Error: {e}")
    finally:
        print(f"[WS] Disconnected: {call_uuid}")


def run_flask_server():
    """Run Flask server"""
    flask_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

if __name__ == '__main__':
    run_flask_server()