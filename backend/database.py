from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
import certifi
import logging
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MongoDBConnection:
    """
    Centralized MongoDB connection handler.
    Provides both synchronous and asynchronous access to the database.
    """
    def __init__(self):
        self.uri = settings.MONGO_URI
        self.db_name = settings.MONGO_DB_NAME
        self.client = None
        self.db = None
        self.async_client = None
        self.async_db = None
        self.connect()

    def connect(self):
        """Initialize both synchronous and asynchronous MongoDB clients"""
        try:
            # Synchronous Client
            self.client = MongoClient(self.uri, tlsCAFile=certifi.where())
            self.db = self.client[self.db_name]
            
            # Asynchronous Client (Motor)
            self.async_client = AsyncIOMotorClient(self.uri, tlsCAFile=certifi.where())
            self.async_db = self.async_client[self.db_name]
            
            # Test synchronous connection
            self.client.admin.command('ping')
            logger.info(f"✅ Root Database Handle: Connected to '{self.db_name}' (Sync & Async)")
        except Exception as e:
            logger.error(f"❌ Root Database Handle: Connection failed: {e}")
            self.db = None
            self.async_db = None

    def get_collection(self, collection_name):
        """Generic helper to get a synchronous collection handle"""
        if self.db is not None:
            return self.db[collection_name]
        return None
        
    def get_async_collection(self, collection_name):
        """Generic helper to get an asynchronous collection handle"""
        if self.async_db is not None:
            return self.async_db[collection_name]
        return None

# Combined handle for both sync and async access
db_manager = MongoDBConnection()
