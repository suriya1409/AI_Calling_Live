from pymongo import MongoClient
import certifi
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

print(f"Connecting to: {MONGO_URI}")
print(f"DB Name: {MONGO_DB_NAME}")

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[MONGO_DB_NAME]

borrowers_count = db.borrowers.count_documents({})
print(f"Total Borrowers in DB: {borrowers_count}")

collections = db.list_collection_names()
print(f"Collections: {collections}")
