from app.db import db
from app.auth.utils import verify_password
import json

def test_user():
    collection = db.get_collection("users")
    if collection is not None:
        users = list(collection.find({}))
        print(f"Total users found: {len(users)}")
        for i, user in enumerate(users):
            print(f"User {i+1}: {user.get('username')} (ID: {user.get('_id')})")
            # print(f"  Password: {user.get('password')}") # Optional: debug password hash
    else:
        print("Could not access 'users' collection.")

if __name__ == "__main__":
    test_user()
