from database import db_manager
from datetime import datetime
from typing import Optional, List, Dict, Any

COLLECTION_NAME = "call_sessions"

def _get_collection():
    return db_manager.get_async_collection(COLLECTION_NAME)

async def create_call_session(user_id: str, session_data: Dict[str, Any]) -> str:
    """Insert a new call session record for a specific user"""
    collection = _get_collection()
    
    data = session_data.copy()
    data["user_id"] = user_id
    if "borrower_id" in data and "loan_no" not in data:
        data["loan_no"] = data.pop("borrower_id")
            
    data["created_at"] = datetime.utcnow()
    data["status"] = data.get("status", "completed")
    
    result = await collection.insert_one(data)
    return str(result.inserted_id)

async def get_call_session_by_uuid(user_id: str, call_uuid: str) -> Optional[Dict[str, Any]]:
    """Fetch a specific call session by its UUID for a specific user"""
    collection = _get_collection()
    return await collection.find_one({"call_uuid": call_uuid, "user_id": user_id})

async def get_sessions_by_loan(user_id: str, loan_no: str) -> List[Dict[str, Any]]:
    """Fetch all sessions related to a specific loan number for a specific user"""
    collection = _get_collection()
    cursor = collection.find({"loan_no": loan_no, "user_id": user_id}).sort("created_at", -1)
    return await cursor.to_list(length=100)

async def get_all_call_sessions(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch latest call sessions for a specific user"""
    collection = _get_collection()
    cursor = collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)
