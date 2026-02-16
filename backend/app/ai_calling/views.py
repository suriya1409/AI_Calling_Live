from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
import uuid
import random
import asyncio
import logging
from datetime import datetime, timedelta

from app.ai_calling.service import (
    make_outbound_call,
    get_call_data_store,
    gemini_client,
    analyze_conversation_with_gemini,
    ConversationHandler
)
from config import settings
from app.auth.utils import get_current_user
from app.data_ingestion.utils import sanitize_for_json
from database import db_manager

# Import standalone model functions
from app.table_models.borrowers_table import (
    get_borrower_by_no,
    update_borrower,
    reset_all_borrower_calls
)
from app.table_models.call_sessions import (
    create_call_session,
    get_call_session_by_uuid,
    get_sessions_by_loan,
    get_all_call_sessions
)

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_language(language: str) -> str:
    """Normalize language code to one of the supported formats"""
    if not language:
        return "en-IN"
        
    language_upper = language.upper().strip()
    
    language_map = {
        "ENGLISH": "en-IN",
        "HINDI": "hi-IN",
        "TAMIL": "ta-IN",
        "EN": "en-IN",
        "HI": "hi-IN",
        "TA": "ta-IN",
        "EN-IN": "en-IN",
        "HI-IN": "hi-IN",
        "TA-IN": "ta-IN"
    }
    
    if language_upper in language_map:
        return language_map[language_upper]
    
    for config_key in settings.LANGUAGE_CONFIG.keys():
        if config_key.upper() == language_upper:
            return config_key
            
    if language_upper.startswith("EN"): return "en-IN"
    if language_upper.startswith("HI"): return "hi-IN"
    if language_upper.startswith("TA"): return "ta-IN"
        
    return language_map.get(language_upper, language)

# ============================================================
# PYDANTIC MODELS
# ============================================================

class BorrowerInfo(BaseModel):
    NO: str
    cell1: str
    preferred_language: str = "en-IN"

class BulkCallRequest(BaseModel):
    borrowers: List[BorrowerInfo]
    use_dummy_data: bool = True

class SingleCallRequest(BaseModel):
    to_number: str
    language: str = "en-IN"
    borrower_id: Optional[str] = None
    use_dummy_data: bool = True

class CallResponse(BaseModel):
    success: bool
    call_uuid: Optional[str] = None
    status: Optional[str] = None
    to_number: Optional[str] = None
    language: Optional[str] = None
    borrower_id: Optional[str] = None
    error: Optional[str] = None
    is_dummy: bool = False
    ai_analysis: Optional[dict] = None
    conversation: Optional[List[dict]] = None

class BulkCallResponse(BaseModel):
    total_requests: int
    successful_calls: int
    failed_calls: int
    results: List[CallResponse]
    mode: str

# ============================================================
# DUMMY CONVERSATION DATA
# ============================================================

DUMMY_CONVERSATIONS = {
    "en-IN": {
        "conversation": [
            {"speaker": "AI", "text": "Hello, I am calling regarding your loan payment. May I know the status?"},
            {"speaker": "User", "text": "I will pay by the 12th of February."},
            {"speaker": "AI", "text": "Thank you. We have noted that down. Have a great day."}
        ]
    },
    "hi-IN": {
        "conversation": [
            {"speaker": "AI", "text": "नमस्ते, मैं आपके लोन भुगतान के बारे में कॉल कर रहा हूं। स्थिति क्या है?"},
            {"speaker": "User", "text": "मैं 12 फरवरी तक भुगतान कर दूंगा।"},
            {"speaker": "AI", "text": "धन्यवाद। हमने इसे नोट कर लिया है। आपका दिन शुभ हो।"}
        ]
    },
    "ta-IN": {
        "conversation": [
            {"speaker": "AI", "text": "வணக்கம், உங்கள் கடன் செலுத்துதல் குறித்து அழைக்கிறேன். நிலை என்ன?"},
            {"speaker": "User", "text": "பிப்ரவரி 12-க்குள் செலுத்திவிடுகிறேன்."},
            {"speaker": "AI", "text": "நன்றி. குறித்துக்கொண்டோம். இனிய நாள்."}
        ]
    }
}

# ============================================================
# CORE LOGIC
# ============================================================

async def create_dummy_call(user_id: str, phone_number: str, language: str, borrower_id: str = None) -> dict:
    """Async helper to generate a dummy call and save to DB using model functions with User Isolation"""
    try:
        call_uuid = f"dummy-{uuid.uuid4()}"
        start_time = datetime.now()
        
        if language not in DUMMY_CONVERSATIONS:
            return {"success": False, "error": f"No dummy template for {language}"}
            
        template = DUMMY_CONVERSATIONS[language]["conversation"]
        conversation = []
        current_time = start_time
        
        for entry in template:
            current_time += timedelta(seconds=random.uniform(2, 5))
            conversation.append({
                **entry,
                "timestamp": current_time.isoformat(),
                "language": language
            })
            
        ai_analysis = analyze_conversation_with_gemini(conversation)
        
        transcript_data = {
            "call_uuid": call_uuid,
            "borrower_id": borrower_id,
            "phone_number": phone_number,
            "start_time": start_time.isoformat(),
            "end_time": current_time.isoformat(),
            "duration_seconds": (current_time - start_time).total_seconds(),
            "preferred_language": language,
            "conversation": conversation,
            "ai_analysis": ai_analysis,
            "is_dummy": True
        }
        
        # Save Session (Standalone function with isolation)
        await create_call_session(user_id, transcript_data)
        
        # Update Borrower (Standalone function with isolation)
        if borrower_id:
            await update_borrower(user_id, borrower_id, {
                "call_completed": True,
                "call_in_progress": False,
                "transcript": conversation,
                "ai_summary": ai_analysis.get("summary", "Done") if ai_analysis else "Done"
            })
            
        return {
            "success": True,
            "call_uuid": call_uuid,
            "status": "completed",
            "ai_analysis": ai_analysis,
            "conversation": conversation
        }
    except Exception as e:
        logger.error(f"Dummy call error for user {user_id}: {e}")
        return {"success": False, "error": str(e)}

async def process_single_call(user_id: str, borrower: BorrowerInfo, use_dummy_data: bool, normalized_language: str) -> CallResponse:
    """Process one call async for a specific user"""
    if use_dummy_data:
        res = await create_dummy_call(user_id, borrower.cell1, normalized_language, borrower.NO)
    else:
        # Note: Real calls currently don't handle user_id in the service layer yet, 
        # but the DB update at the end of the call should use it.
        res = make_outbound_call(borrower.cell1, normalized_language, borrower.NO)
        
    if res.get("success"):
        return CallResponse(
            success=True,
            call_uuid=res.get("call_uuid"),
            status=res.get("status"),
            to_number=borrower.cell1,
            language=normalized_language,
            borrower_id=borrower.NO,
            is_dummy=use_dummy_data,
            ai_analysis=res.get("ai_analysis"),
            conversation=res.get("conversation")
        )
    return CallResponse(success=False, error=res.get("error"), borrower_id=borrower.NO)

# ============================================================
# API ENDPOINTS
# ============================================================

@router.get("/")
async def ai_calling_root():
    return {"message": "AI Calling Module (User Isolated)", "status": "active"}

@router.post("/reset_calls")
async def reset_calls(current_user: dict = Depends(get_current_user)):
    """Reset call flags for all borrowers belonging to the current user"""
    user_id = str(current_user["_id"])
    modified_count = await reset_all_borrower_calls(user_id)
    return {
        "status": "success", 
        "message": f"All {modified_count} of your borrower call statuses have been reset"
    }

@router.post("/trigger_calls", response_model=BulkCallResponse)
async def trigger_bulk_calls(request: BulkCallRequest, current_user: dict = Depends(get_current_user)):
    """Trigger bulk calls for current user only"""
    user_id = str(current_user["_id"])
    if not request.borrowers:
        raise HTTPException(status_code=400, detail="No borrowers")
        
    async_tasks = []
    for b in request.borrowers:
        lang = normalize_language(b.preferred_language)
        async_tasks.append(process_single_call(user_id, b, request.use_dummy_data, lang))
        
    results = await asyncio.gather(*async_tasks)
    
    successful = len([r for r in results if r.success])
    return BulkCallResponse(
        total_requests=len(request.borrowers),
        successful_calls=successful,
        failed_calls=len(results) - successful,
        results=list(results),
        mode="dummy" if request.use_dummy_data else "real"
    )

@router.post("/make_call", response_model=CallResponse)
async def make_single_call(request: SingleCallRequest, current_user: dict = Depends(get_current_user)):
    """Trigger a single call manually for current user"""
    user_id = str(current_user["_id"])
    lang = normalize_language(request.language)
    if request.use_dummy_data:
        res = await create_dummy_call(user_id, request.to_number, lang, request.borrower_id)
    else:
        res = make_outbound_call(request.to_number, lang, request.borrower_id)
        
    if res.get("success"):
        return CallResponse(
            success=True,
            call_uuid=res.get("call_uuid"),
            status=res.get("status"),
            to_number=request.to_number,
            language=lang,
            borrower_id=request.borrower_id,
            is_dummy=request.use_dummy_data,
            ai_analysis=res.get("ai_analysis"),
            conversation=res.get("conversation")
        )
    raise HTTPException(status_code=500, detail=res.get("error"))

@router.get("/sessions/{loan_no}")
async def get_loan_sessions_api(loan_no: str, current_user: dict = Depends(get_current_user)):
    """Get history for a specific loan number (Isolated to current user)"""
    user_id = str(current_user["_id"])
    sessions = await get_sessions_by_loan(user_id, loan_no)
    return sanitize_for_json(sessions)

@router.get("/session/{call_uuid}")
async def get_call_session_api(call_uuid: str, current_user: dict = Depends(get_current_user)):
    """Get details of a specific session (Isolated to current user)"""
    user_id = str(current_user["_id"])
    session = await get_call_session_by_uuid(user_id, call_uuid)
    if not session: raise HTTPException(status_code=404, detail="Session not found in your account")
    return sanitize_for_json(session)

@router.get("/sessions")
async def list_sessions_api(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """List recent sessions (Isolated to current user)"""
    user_id = str(current_user["_id"])
    sessions = await get_all_call_sessions(user_id, limit=limit)
    return sanitize_for_json(sessions)

@router.get("/analysis/{call_uuid}")
async def get_call_analysis_api(call_uuid: str, current_user: dict = Depends(get_current_user)):
    """Get only the AI analysis for a specific call session (Isolated to current user)"""
    user_id = str(current_user["_id"])
    session = await get_call_session_by_uuid(user_id, call_uuid)
    if session and 'ai_analysis' in session:
        return {
            "call_uuid": call_uuid,
            "loan_no": session.get("loan_no"),
            "is_dummy": session.get("is_dummy", False),
            "ai_analysis": session['ai_analysis']
        }
    raise HTTPException(status_code=404, detail="Analysis not found or access denied")

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "AI Calling"}