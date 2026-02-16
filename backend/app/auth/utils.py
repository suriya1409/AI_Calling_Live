import jwt
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from config import settings
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Security configuration
SECRET_KEY = getattr(settings, "SECRET_KEY", "your-secret-key-for-jwt-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# ==========================================
# PASSWORD HASHING
# ==========================================
def hash_password(password: str) -> str:
    """Hash a password for storing"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a stored password against one provided by user"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except:
        return False

# ==========================================
# TOKEN MANAGEMENT
# ==========================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a new JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict):
    """Create a new JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    """Verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ==========================================
# AUTH DECORATOR / DEPENDENCY
# ==========================================
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Dependency to get the current authenticated user.
    Acts as a @login_required decorator for FastAPI endpoints.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = verify_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception
    
    identifier: str = payload.get("sub")
    if identifier is None:
        raise credentials_exception
    
    # Verify user exists in DB
    from app.table_models.users_table import get_user_by_any
    user = await get_user_by_any(identifier)
    
    if user is None:
        raise credentials_exception
        
    # LOGOUT CHECK: 
    # Compare incoming token with the 'access_token' stored in DB.
    # If DB token is None or doesn't match, the user has logged out.
    if user.get("access_token") != token:
        logger.warning(f"Revoked token attempt for user: {user.get('username')}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user
