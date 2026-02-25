from database import db_manager
import logging

# Configure logging to see the output
logging.basicConfig(level=logging.INFO)

print("--- Testing Centralized Database Handle ---")
if db_manager.db is not None:
    print(f"✅ Success! Connected to: {db_manager.db_name}")
    borrowers_count = db_manager.get_collection("borrowers").count_documents({})
    print(f"Total Borrowers in DB: {borrowers_count}")
else:
    print("❌ Failure: Could not connect to MongoDB")
