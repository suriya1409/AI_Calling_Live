from app.db import db
from app.auth.utils import verify_password, hash_password
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_passwords():
    print("Testing password verification logic...")
    
    # Get users
    users = db.get_collection("users").find()
    
    for user in users:
        username = user.get("username")
        stored_hash = user.get("password")
        
        print(f"\nUser: {username}")
        print(f"Stored Hash: {stored_hash}")
        
        # Test common passwords
        test_passwords = ["admin", "admin123", "Shalini", "shalini123", "Shalini123", "password"]
        
        found = False
        for tp in test_passwords:
            if verify_password(tp, stored_hash):
                print(f"✅ FOUND! Password for {username} is: '{tp}'")
                found = True
                break
        
        if not found:
            print(f"❌ Could not verify password for {username} against common list.")

if __name__ == "__main__":
    test_passwords()
