import os
import sys
from bson.objectid import ObjectId

# Add the project root to sys.path
sys.path.append(os.getcwd())

from app.db import db

def check_users():
    print("Checking database connection...")
    collection = db.get_collection("users")
    if collection is None:
        print("Error: Could not access 'users' collection.")
        return

    print("Users in database:")
    users = list(collection.find({}))
    for u in users:
        print(f"- ID: {u.get('_id')}, Username: '{u.get('username')}', Password Hash: {u.get('password')[:10]}...")
    
    # Try finding by exact username
    admin = db.get_user("admin")
    if admin:
        print(f"\nFound 'admin' user by username. ID: {admin['_id']}")
    else:
        print("\nCould NOT find 'admin' user by username.")

if __name__ == "__main__":
    check_users()
