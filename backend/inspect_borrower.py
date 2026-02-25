from pymongo import MongoClient
import certifi
import os
import json
from bson import json_util
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[MONGO_DB_NAME]

print("--- Sample Borrower ---")
sample = db.borrowers.find_one()
if sample:
    print(json.dumps(sample, indent=2, default=str))
else:
    print("No borrowers found in DB")
