from database import db_manager
import logging
from datetime import datetime
from bson.objectid import ObjectId
from config import settings

# Configure logging
logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        # Now using the centralized handle from root database.py
        pass

    def get_collection(self, collection_name):
        return db_manager.get_collection(collection_name)

    # ==========================================
    # USER AUTHENTICATION METHODS
    # ==========================================
    def get_user(self, username):
        """Get a user by username from the users collection"""
        collection = self.get_collection("users")
        if collection is not None:
            return collection.find_one({"username": username})
        return None

    def get_user_by_id(self, user_id):
        """Get a user by ID (string or ObjectId) from the users collection"""
        collection = self.get_collection("users")
        if collection is not None:
            try:
                # Try as ObjectId first
                if isinstance(user_id, str):
                    return collection.find_one({"_id": ObjectId(user_id)})
                return collection.find_one({"_id": user_id})
            except Exception:
                # Fallback to direct match if not a valid ObjectId string
                return collection.find_one({"_id": user_id})
        return None

    def get_user_by_any(self, identifier):
        """Find user by username OR ID"""
        user = self.get_user(identifier)
        if not user:
            user = self.get_user_by_id(identifier)
        return user

    def create_user(self, user_data):
        """Create a new user"""
        collection = self.get_collection("users")
        if collection is not None:
            user_data["created_at"] = datetime.utcnow()
            user_data["updated_at"] = datetime.utcnow()
            return collection.insert_one(user_data)
        return None

    def update_user_tokens(self, username, refresh_token=None, refresh_expires=None, access_token=None, access_expires=None):
        """Update user tokens with actual token strings for visibility"""
        collection = self.get_collection("users")
        if collection is not None:
            update_data = {"updated_at": datetime.utcnow()}
            if refresh_token is not None:
                update_data["refresh_token"] = refresh_token
            if refresh_expires:
                update_data["refresh_token_expires_at"] = refresh_expires
            if access_token:
                update_data["access_token"] = access_token
            if access_expires:
                update_data["last_access_token_expires_at"] = access_expires
            
            return collection.update_one(
                {"username": username},
                {"$set": update_data}
            )
        return None

    def revoke_tokens(self, username):
        """Logout: Remove refresh and access tokens from DB"""
        collection = self.get_collection("users")
        if collection is not None:
            return collection.update_one(
                {"username": username},
                {"$set": {
                    "refresh_token": None, 
                    "access_token": None,
                    "updated_at": datetime.utcnow()
                }}
            )
        return None

    # ==========================================
    # BORROWERS PROFILE METHODS
    # ==========================================
    def bulk_upsert_borrowers(self, borrowers_list):
        """Bulk insert/update borrowers from dataset"""
        collection = self.get_collection("borrowers")
        if collection is not None:
            from pymongo import UpdateOne
            operations = []
            for borrower in borrowers_list:
                # Use 'NO' as the unique identifier for borrowers
                borrower_id = borrower.get('NO')
                if borrower_id:
                    # Reset call statuses on new upload/upsert
                    borrower['call_completed'] = False
                    borrower['call_in_progress'] = False
                    borrower['transcript'] = []
                    borrower['ai_summary'] = ""
                    
                    operations.append(
                        UpdateOne(
                            {"NO": borrower_id},
                            {"$set": borrower},
                            upsert=True
                        )
                    )
            
            if operations:
                result = collection.bulk_write(operations)
                logger.info(f"✅ Borrowers upserted: {result.upserted_count} new, {result.modified_count} updated")
                return result
        return None

    def get_all_borrowers(self, query=None, limit=100):
        """Fetch borrowers with optional filtering"""
        collection = self.get_collection("borrowers")
        if collection is not None:
            cursor = collection.find(query or {}).limit(limit)
            return list(cursor)
        return []

    def get_borrower_by_id(self, borrower_id):
        """Get a specific borrower by their NO identifier (handles string or int)"""
        collection = self.get_collection("borrowers")
        if collection is not None:
            # Try to match as both string and integer
            query_ids = [str(borrower_id)]
            
            # If ID starts with 'BRW', also try searching for the numeric part
            if str(borrower_id).upper().startswith("BRW"):
                numeric_part = str(borrower_id)[3:]
                query_ids.append(numeric_part)
                try:
                    query_ids.append(int(numeric_part))
                except: pass
            
            try:
                query_ids.append(int(borrower_id))
            except: pass
            
            return collection.find_one({"NO": {"$in": query_ids}})
        return None

    def delete_all_borrowers(self):
        """Delete all records from the borrowers collection"""
        collection = self.get_collection("borrowers")
        if collection is not None:
            result = collection.delete_many({})
            logger.info(f"🗑️ Deleted all borrowers: {result.deleted_count} records removed")
            return result.deleted_count
        return 0

    # ==========================================
    # CALL SESSION METHODS
    # ==========================================
    def insert_call_session(self, session_data):
        """
        Insert a full call session into MongoDB
        Schema includes: call_uuid, loan_no, phone, start/end times,
        duration, is_dummy, languages, conversation, ai_analysis, status
        """
        collection = self.get_collection("call_sessions")
        if collection is not None:
            try:
                # Ensure structure follows the requested schema
                data = session_data.copy()
                if "_id" in data:
                    del data["_id"]
                
                # Format mappings if needed
                if "borrower_id" in data and "loan_no" not in data:
                    data["loan_no"] = data.pop("borrower_id")
                
                if "end_time" in data and isinstance(data["end_time"], str):
                    try:
                        data["end_time"] = datetime.fromisoformat(data["end_time"])
                    except: pass
                
                if "start_time" in data and isinstance(data["start_time"], str):
                    try:
                        data["start_time"] = datetime.fromisoformat(data["start_time"])
                    except: pass

                data["created_at"] = datetime.utcnow()
                data["status"] = data.get("status", "completed")
                
                result = collection.insert_one(data)
                logger.info(f"✅ Call Session saved to MongoDB: {data.get('call_uuid')}")
                return result.inserted_id
            except Exception as e:
                logger.error(f"❌ Failed to insert call session: {e}")
        return None

    def get_call_session(self, call_uuid):
        """Get a specific call session by UUID"""
        collection = self.get_collection("call_sessions")
        if collection is not None:
            return collection.find_one({"call_uuid": call_uuid})
        return None

    def get_all_sessions_for_loan(self, loan_no):
        """Get all call sessions for a specific borrower/loan"""
        collection = self.get_collection("call_sessions")
        if collection is not None:
            return list(collection.find({"loan_no": loan_no}).sort("created_at", -1))
        return []

# Singleton instance
db = MongoDB()
