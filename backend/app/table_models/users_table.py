from database import db_manager
from datetime import datetime
from bson import ObjectId
from typing import Optional, Dict, Any

COLLECTION_NAME = "users"

def _get_collection():
    return db_manager.get_async_collection(COLLECTION_NAME)

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Fetch a user by their username"""
    collection = _get_collection()
    return await collection.find_one({"username": username})

async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a user by their ObjectId string"""
    collection = _get_collection()
    try:
        return await collection.find_one({"_id": ObjectId(user_id)})
    except:
        return None

async def get_user_by_any(identifier: str) -> Optional[Dict[str, Any]]:
    """Find user by username OR ID"""
    user = await get_user_by_username(identifier)
    if not user:
        user = await get_user_by_id(identifier)
    return user

async def create_user(user_data: Dict[str, Any]) -> str:
    """Create a new user and return the string ID"""
    collection = _get_collection()
    user_data["created_at"] = datetime.utcnow()
    user_data["updated_at"] = datetime.utcnow()
    result = await collection.insert_one(user_data)
    return str(result.inserted_id)

async def update_user_tokens(username: str, update_data: Dict[str, Any]) -> bool:
    """Update tokens and expiration times for a user"""
    collection = _get_collection()
    update_data["updated_at"] = datetime.utcnow()
    result = await collection.update_one(
        {"username": username},
        {"$set": update_data}
    )
    return result.modified_count > 0

async def revoke_user_tokens(username: str) -> bool:
    """Clear tokens for a user (logout)"""
    collection = _get_collection()
    result = await collection.update_one(
        {"username": username},
        {"$set": {
            "refresh_token": None,
            "access_token": None,
            "updated_at": datetime.utcnow()
        }}
    )
    return result.modified_count > 0

async def delete_user(username: str) -> bool:
    """Delete a user by username"""
    collection = _get_collection()
    result = await collection.delete_one({"username": username})
    return result.deleted_count > 0
