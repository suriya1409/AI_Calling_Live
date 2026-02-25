from database import db_manager
from datetime import datetime
from typing import Optional, List, Dict, Any
from pymongo import UpdateOne

COLLECTION_NAME = "borrowers"

def _get_collection():
    return db_manager.get_async_collection(COLLECTION_NAME)

async def get_all_borrowers(user_id: str, query: Dict[str, Any] = None, limit: int = 100, skip: int = 0) -> List[Dict[str, Any]]:
    """Fetch borrowers for a specific user with optional filtering and pagination"""
    collection = _get_collection()
    full_query = query or {}
    full_query["user_id"] = user_id
    cursor = collection.find(full_query).skip(skip).limit(limit)
    return await cursor.to_list(length=limit)

async def get_borrower_by_no(user_id: str, borrower_no: Any) -> Optional[Dict[str, Any]]:
    """Fetch a specific borrower by their NO identifier for a specific user"""
    collection = _get_collection()
    query_ids = [str(borrower_no)]
    
    if str(borrower_no).upper().startswith("BRW"):
        numeric_part = str(borrower_no)[3:]
        query_ids.append(numeric_part)
        try:
            query_ids.append(int(numeric_part))
        except: pass
    
    try:
        query_ids.append(int(borrower_no))
    except: pass
    
    return await collection.find_one({"NO": {"$in": query_ids}, "user_id": user_id})

async def bulk_upsert_borrowers(user_id: str, borrowers_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """Bulk insert/update borrowers for a specific user"""
    collection = _get_collection()
    if not borrowers_list:
        return {"upserted": 0, "modified": 0}

    operations = []
    for borrower in borrowers_list:
        borrower_no = borrower.get('NO')
        if borrower_no:
            # Set metadata
            borrower['user_id'] = user_id
            borrower['call_completed'] = borrower.get('call_completed', False)
            borrower['call_in_progress'] = borrower.get('call_in_progress', False)
            borrower['transcript'] = borrower.get('transcript', [])
            borrower['ai_summary'] = borrower.get('ai_summary', "")
            borrower['payment_confirmation'] = borrower.get('payment_confirmation', "")
            borrower['follow_up_date'] = borrower.get('follow_up_date', "")
            borrower['call_frequency'] = borrower.get('call_frequency', "")
            borrower['updated_at'] = datetime.utcnow()
            
            # Upsert logic: unique per (user_id, NO)
            operations.append(
                UpdateOne(
                    {"NO": borrower_no, "user_id": user_id},
                    {"$set": borrower},
                    upsert=True
                )
            )
    
    if operations:
        result = await collection.bulk_write(operations)
        return {
            "upserted": result.upserted_count,
            "modified": result.modified_count
        }
    return {"upserted": 0, "modified": 0}

async def update_borrower(user_id: str, borrower_no: Any, update_data: Dict[str, Any]) -> bool:
    """Update a borrower record for a specific user"""
    collection = _get_collection()
    query_ids = [str(borrower_no)]
    try:
        query_ids.append(int(borrower_no))
    except: pass
    
    update_data["updated_at"] = datetime.utcnow()
    result = await collection.update_one(
        {"NO": {"$in": query_ids}, "user_id": user_id},
        {"$set": update_data}
    )
    return result.matched_count > 0

async def delete_borrower(user_id: str, borrower_no: Any) -> bool:
    """Delete a borrower record for a specific user"""
    collection = _get_collection()
    query_ids = [str(borrower_no)]
    try:
        query_ids.append(int(borrower_no))
    except: pass
    
    result = await collection.delete_one({"NO": {"$in": query_ids}, "user_id": user_id})
    return result.deleted_count > 0

async def delete_all_borrowers(user_id: str) -> int:
    """Delete all borrowers for a specific user"""
    collection = _get_collection()
    result = await collection.delete_many({"user_id": user_id})
    return result.deleted_count

async def reset_all_borrower_calls(user_id: str) -> int:
    """Reset call flags for all borrowers belonging to a specific user"""
    collection = _get_collection()
    result = await collection.update_many(
        {"user_id": user_id}, 
        {"$set": {
            "call_completed": False,
            "call_in_progress": False,
            "transcript": [],
            "ai_summary": "",
            "payment_confirmation": "",
            "follow_up_date": "",
            "call_frequency": ""
        }}
    )
    return result.modified_count

async def get_global_borrower_stats() -> Dict[str, Any]:
    """Get statistics across all users (Admin view)"""
    collection = _get_collection()
    total_records = await collection.count_documents({})
    
    # Get count per user
    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}}
    ]
    user_breakdown = await collection.aggregate(pipeline).to_list(length=100)
    
    return {
        "total_borrowers_in_db": total_records,
        "user_breakdown": {item["_id"]: item["count"] for item in user_breakdown if item["_id"]}
    }
