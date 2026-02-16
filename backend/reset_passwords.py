from app.db import db
from app.auth.utils import hash_password

def reset_passwords():
    print("Resetting passwords...")
    collection = db.get_collection("users")
    
    # Reset admin to admin
    collection.update_one(
        {"username": "admin"},
        {"$set": {"password": hash_password("admin")}}
    )
    print("✅ Reset 'admin' password to 'admin'")
    
    # Reset Shalini to shalini123
    collection.update_one(
        {"username": "Shalini"},
        {"$set": {"password": hash_password("shalini123")}}
    )
    print("✅ Reset 'Shalini' password to 'shalini123'")

if __name__ == "__main__":
    reset_passwords()
