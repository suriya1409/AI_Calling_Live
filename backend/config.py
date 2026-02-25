"""
Application Configuration
=========================
Central configuration for all environment variables and settings
"""

from dotenv import load_dotenv, find_dotenv
import os

# Load environment variables from .env file
load_dotenv(find_dotenv())


class Settings:
    """Application Settings"""
    
    # ---------- Gemini AI ----------
    # GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()  # Alternative name
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

    
    # ---------- Vonage Configuration ----------
    VONAGE_API_KEY = os.getenv("VONAGE_API_KEY", "")
    VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET", "")
    VONAGE_APPLICATION_ID = os.getenv("VONAGE_APPLICATION_ID", "")
    VONAGE_PRIVATE_KEY = os.getenv("VONAGE_PRIVATE_KEY", "") # Actual key content as string
    VONAGE_PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
    
    # Handle private key path: look in both backend and root
    if not os.path.isabs(VONAGE_PRIVATE_KEY_PATH) and not os.path.exists(VONAGE_PRIVATE_KEY_PATH):
        # Look in the root (one level up from /backend)
        root_key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), VONAGE_PRIVATE_KEY_PATH)
        if os.path.exists(root_key_path):
            VONAGE_PRIVATE_KEY_PATH = root_key_path
            
    VONAGE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER", "")
    
    # ---------- Sarvam AI Configuration ----------
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
    
    # ---------- Server Configuration ----------
    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))

    # ---------- MongoDB Configuration ----------
    MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://shalini04doodleblue_db_user:4gmBRfAifxwR1kKH@cluster0.bnr9oy1.mongodb.net/")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "ai_finance_platform")
    
    # ---------- Audio Configuration ----------
    SAMPLE_RATE = 22050  # Upgraded to 22.05kHz as requested
    CHANNELS = 1         # Mono
    SAMPLE_WIDTH = 2     # 16-bit
    
    # ---------- Language Configuration ----------
    LANGUAGE_CONFIG = {
        "en-IN": {
            "name": "English",
            "speaker": "vidya",
            "enable_preprocessing": False,
            "greeting": "Hello, hope you are doing well today. We are calling from the Loan sector, this is a general check-up call regarding the Loan amount that you have borrowed. Your due date is coming up soon. Can you please let us know if you will be paying the balance amount before the due date?"
        },
        "hi-IN": {
            "name": "Hindi",
            "speaker": "vidya",
            "enable_preprocessing": True,
            "greeting": "नमस्ते, आशा है आप अच्छे हैं। हम लोन सेक्टर से कॉल कर रहे हैं, यह आपके उधार लिए गए लोन के बारे में एक सामान्य फॉलो-अप कॉल है। आपकी ड्यू डेट जल्द आ रही है। क्या आप ड्यू डेट से पहले बकाया राशि का भुगतान कर देंगे?"
        },
        "ta-IN": {
            "name": "Tamil",
            "speaker": "manisha",
            "enable_preprocessing": True,
            "greeting": "வணக்கம், நலமாக இருப்பீர்கள் என நம்புகிறேன். கடன் பிரிவிலிருந்து அழைக்கிறோம், நீங்கள் பெற்ற கடன் தொகை குறித்த வழக்கமான பின்தொடர் அழைப்பு. உங்கள் செலுத்த வேண்டிய தேதி விரைவில் வரவிருக்கிறது. நிலுவைத் தொகையை ட்யூ டேட்-க்கு முன் செலுத்துவீர்களா?"
        }
    }
    
    @classmethod
    def validate(cls):
        """Validate that required settings are present"""
        required_settings = {
            "VONAGE_API_KEY": cls.VONAGE_API_KEY,
            "VONAGE_API_SECRET": cls.VONAGE_API_SECRET,
            "VONAGE_APPLICATION_ID": cls.VONAGE_APPLICATION_ID,
            "SARVAM_API_KEY": cls.SARVAM_API_KEY,
        }
        
        missing = [key for key, value in required_settings.items() if not value]
        
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please set them in your .env file"
            )
        
        return True


# Create a singleton instance
settings = Settings()