from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
import uuid
import random
import asyncio
import logging
from datetime import datetime, timedelta

from app.ai_calling.service import (
    make_outbound_call,
    get_call_data_store,
    gemini_client,
    analyze_conversation_with_gemini,
    analyze_conversation_with_groq,
    calculate_follow_up_schedule,
    determine_report_outcomes,
    ConversationHandler
)
from config import settings
from app.auth.utils import get_current_user
from app.data_ingestion.utils import sanitize_for_json
from database import db_manager

# Import standalone model functions
from app.table_models.borrowers_table import (
    get_borrower_by_no,
    update_borrower,
    reset_all_borrower_calls
)
from app.table_models.call_sessions import (
    create_call_session,
    get_call_session_by_uuid,
    get_sessions_by_loan,
    get_all_call_sessions
)

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_language(language: str) -> str:
    """Normalize language code to one of the supported formats"""
    if not language:
        return "en-IN"
        
    language_upper = language.upper().strip()
    
    language_map = {
        "ENGLISH": "en-IN",
        "HINDI": "hi-IN",
        "TAMIL": "ta-IN",
        "EN": "en-IN",
        "HI": "hi-IN",
        "TA": "ta-IN",
        "EN-IN": "en-IN",
        "HI-IN": "hi-IN",
        "TA-IN": "ta-IN"
    }
    
    if language_upper in language_map:
        return language_map[language_upper]
    
    # Check if the input starts with any of the primary names in case of variations like "English (UK)"
    if "ENGLISH" in language_upper: return "en-IN"
    if "HINDI" in language_upper: return "hi-IN"
    if "TAMIL" in language_upper: return "ta-IN"
    
    for config_key in settings.LANGUAGE_CONFIG.keys():
        if config_key.upper() == language_upper:
            return config_key
            
    if language_upper.startswith("EN"): return "en-IN"
    if language_upper.startswith("HI"): return "hi-IN"
    if language_upper.startswith("TA"): return "ta-IN"
        
    return language_map.get(language_upper, language)

# ============================================================
# PYDANTIC MODELS
# ============================================================

class BorrowerInfo(BaseModel):
    NO: str
    cell1: str
    preferred_language: str = "en-IN"
    intent_for_testing: Optional[str] = Field(None, description="Intent for dummy call testing: normal, abusive, threatening, stop_calling")

class BulkCallRequest(BaseModel):
    borrowers: List[BorrowerInfo]
    use_dummy_data: bool = True
    real_call_borrower_ids: List[str] = Field(default_factory=list, description="List of borrower NOs that should use REAL calls (use_dummy_data=False), overriding the global use_dummy_data flag")

class SingleCallRequest(BaseModel):
    to_number: str
    language: str = "en-IN"
    borrower_id: Optional[str] = None
    use_dummy_data: bool = True
    intent_for_testing: Optional[str] = Field(None, description="Intent for dummy call testing: normal, abusive, threatening, stop_calling")

class CallResponse(BaseModel):
    success: bool
    call_uuid: Optional[str] = None
    status: Optional[str] = None
    to_number: Optional[str] = None
    language: Optional[str] = None
    borrower_id: Optional[str] = None
    error: Optional[str] = None
    is_dummy: bool = False
    ai_analysis: Optional[dict] = None
    conversation: Optional[List[dict]] = None
    mid_call: bool = False
    next_step_summary: Optional[str] = None
    email_to_manager_preview: Optional[dict] = None
    require_manual_process: bool = False
    payment_confirmation: Optional[str] = None
    follow_up_date: Optional[str] = None
    call_frequency: Optional[str] = None

class BulkCallResponse(BaseModel):
    total_requests: int
    successful_calls: int
    failed_calls: int
    results: List[CallResponse]
    mode: str

# ============================================================
# DUMMY CONVERSATION DATA
# ============================================================

DUMMY_CONVERSATIONS = {
    "normal": {
        "en-IN": [
            {"speaker": "AI", "text": "Hi Mr Rajesh, hope you are doing well today. We are calling from the Loan sector, this is a general check-up call regarding the Loan amount that you have borrowed. Your due date is coming up soon on March 5th 2026. Can you please let us know if you will be paying the balance amount before the due date?"},
            {"speaker": "User", "text": "Hi, yes I will be paying the amount before the due date."},
            {"speaker": "AI", "text": "Good to know sir, we will update our records accordingly. Do you have any questions for us?"},
            {"speaker": "User", "text": "Yes could you please let me know what my current loan due amount is and after the payment for this month how much it would be totally?"},
            {"speaker": "AI", "text": "Sure sir, your current outstanding loan amount is ₹50,000 and after payment of the due this month your loan amount would be ₹45,000."},
            {"speaker": "User", "text": "Thank you for the information."},
            {"speaker": "AI", "text": "Thank you sir, have a good day!"}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते श्री राजेश जी, आशा है आप अच्छे हैं। हम लोन सेक्टर से कॉल कर रहे हैं, यह आपके उधार लिए गए लोन के बारे में एक सामान्य फॉलो-अप कॉल है। आपकी ड्यू डेट जल्द आ रही है 5 मार्च 2026। क्या आप ड्यू डेट से पहले बकाया राशि का भुगतान कर देंगे?"},
            {"speaker": "User", "text": "हां, मैं ड्यू डेट से पहले भुगतान कर दूंगा।"},
            {"speaker": "AI", "text": "यह सुनकर अच्छा लगा श्रीमान, हम अपने रिकॉर्ड अपडेट कर देंगे। क्या आपका कोई सवाल है?"},
            {"speaker": "User", "text": "हां, कृपया बताइए कि मेरी वर्तमान लोन बकाया राशि कितनी है और इस महीने के भुगतान के बाद कुल कितनी रहेगी?"},
            {"speaker": "AI", "text": "जी श्रीमान, आपकी वर्तमान कुल बकाया लोन राशि ₹50,000 है और इस महीने के भुगतान के बाद आपकी बकाया राशि ₹45,000 होगी।"},
            {"speaker": "User", "text": "जानकारी के लिए धन्यवाद।"},
            {"speaker": "AI", "text": "धन्यवाद श्रीमान, आपका दिन शुभ हो!"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம் திரு ராஜேஷ், நலமாக இருப்பீர்கள் என நம்புகிறேன். கடன் பிரிவிலிருந்து அழைக்கிறோம், நீங்கள் பெற்ற கடன் தொகை குறித்த வழக்கமான பின்தொடர் அழைப்பு. உங்கள் செலுத்த வேண்டிய தேதி விரைவில் வரவிருக்கிறது மார்ச் 5, 2026. நிலுவைத் தொகையை ட்யூ டேட்-க்கு முன் செலுத்துவீர்களா?"},
            {"speaker": "User", "text": "ஆமாம், நான் ட்யூ டேட்-க்கு முன் தொகையை செலுத்துவேன்."},
            {"speaker": "AI", "text": "நல்லது ஐயா, நாங்கள் எங்கள் பதிவுகளை அதற்கேற்ப புதுப்பிப்போம். உங்களுக்கு ஏதாவது கேள்விகள் உள்ளதா?"},
            {"speaker": "User", "text": "ஆமாம், என் தற்போதைய கடன் நிலுவை தொகை என்ன மற்றும் இந்த மாத கட்டணத்திற்குப் பிறகு மொத்தமாக எவ்வளவு இருக்கும் என்று கூற முடியுமா?"},
            {"speaker": "AI", "text": "நிச்சயமாக ஐயா, உங்கள் தற்போதைய கடன் நிலுவை ₹50,000 மற்றும் இந்த மாத கட்டணத்திற்குப் பிறகு உங்கள் கடன் நிலுவை ₹45,000 ஆகும்."},
            {"speaker": "User", "text": "தகவலுக்கு நன்றி."},
            {"speaker": "AI", "text": "நன்றி ஐயா, நல்ல நாள் வாழ்த்துகள்!"}
        ]
    },
    "abusive": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "Why are you calling me again? You guys are useless! Stop wasting my time, you idiots."},
            {"speaker": "AI", "text": "Sir, please maintain professional language so I can assist you better."},
            {"speaker": "User", "text": "Go away! I don't want to talk to you."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "तुम लोग फिर से क्यों कॉल कर रहे हो? तुम सब बेकार हो! मेरा समय बर्बाद करना बंद करो, बेवकूफों।"},
            {"speaker": "AI", "text": "श्रीमान, कृपया पेशेवर भाषा बनाए रखें ताकि मैं आपकी बेहतर सहायता कर सकूं।"},
            {"speaker": "User", "text": "चले जाओ! मैं तुमसे बात नहीं करना चाहता।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "ஏன் மீண்டும் அழைக்கிறீர்கள்? நீங்கள் அனைவரும் பயனற்றவர்கள்! என் நேரத்தை வீணடிக்காதீர்கள், முட்டாள்களே."},
            {"speaker": "AI", "text": "ஐயா, தயவுசெய்து மரியாதையான மொழியைப் பயன்படுத்துங்கள்."},
            {"speaker": "User", "text": "போய்விடு! நான் உன்னிடம் பேச விரும்பவில்லை."}
        ]
    },
    "threatening": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "If you call me one more time, I will find out where your office is and come there with my friends. You will regret it."},
            {"speaker": "AI", "text": "Sir, I must inform you that this call is recorded. Please refrain from making threats."},
            {"speaker": "User", "text": "Record whatever you want. Just stay away from me."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "अगर तुमने मुझे एक बार और कॉल किया, तो मैं पता लगा लूंगा कि तुम्हारा ऑफिस कहां है और अपने दोस्तों के साथ वहां आऊंगा। तुम पछताओगे।"},
            {"speaker": "AI", "text": "श्रीमान, मुझे आपको सूचित करना चाहिए कि यह कॉल रिकॉर्ड की जा रही है। कृपया धमकी देने से बचें।"},
            {"speaker": "User", "text": "जो चाहो रिकॉर्ड करो। बस मुझसे दूर रहो।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "இன்னொரு முறை அழைத்தால், உங்கள் அலுவலகம் எங்கே என்று கண்டுபிடித்து என் நண்பர்களுடன் அங்கு வருவேன். நீங்கள் வருத்தப்படுவீர்கள்."},
            {"speaker": "AI", "text": "ஐயா, இந்த அழைப்பு பதிவு செய்யப்படுகிறது என்பதை நான் உங்களுக்குத் தெரிவிக்க வேண்டும். அச்சுறுத்தல் விடுக்க வேண்டாம்."},
            {"speaker": "User", "text": "நீங்கள் விரும்புவதைப் பதிவு செய்யுங்கள். என்னிடமிருந்து விலகி இருங்கள்."}
        ]
    },
    "stop_calling": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "Listen to me carefully. I am telling you to stop calling me. Never call this number again."},
            {"speaker": "AI", "text": "I will pass this request to my supervisor. Thank you for your time."},
            {"speaker": "User", "text": "Just do it and don't call back."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "मेरी बात ध्यान से सुनो। मैं तुम्हें कॉल करना बंद करने के लिए कह रहा हूँ। इस नंबर पर दोबारा कभी कॉल मत करना।"},
            {"speaker": "AI", "text": "मैं यह अनुरोध अपने सुपरवाइजर को भेज दूंगा। आपके समय के लिए धन्यवाद।"},
            {"speaker": "User", "text": "बस इसे करो और वापस कॉल मत करो।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "நான் சொல்வதை கவனமாக கேளுங்கள். என்னை அழைப்பதை நிறுத்துங்கள். இந்த எண்ணிற்கு மீண்டும் அழைக்க வேண்டாம்."},
            {"speaker": "AI", "text": "இந்த கோரிக்கையை எனது மேற்பார்வையாளருக்கு அனுப்புகிறேன். உங்கள் நேரத்திற்கு நன்றி."},
            {"speaker": "User", "text": "அதைச் செய்துவிட்டு மீண்டும் அழைக்க வேண்டாம்."}
        ]
    },
    "paid": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "But I already paid the amount yesterday morning."},
            {"speaker": "AI", "text": "Could you please tell me the transaction reference number or through which mode you paid?"},
            {"speaker": "User", "text": "I paid via UPI. I have the screenshot also."},
            {"speaker": "AI", "text": "Thank you. I will inform the team to verify this. Have a good day."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "लेकिन मैंने कल सुबह ही भुगतान कर दिया है।"},
            {"speaker": "AI", "text": "क्या आप मुझे ट्रांजैक्शन नंबर बता सकते हैं या आपने किस माध्यम से भुगतान किया है?"},
            {"speaker": "User", "text": "मैंने UPI के ज़रिए पेमेंट किया है। मेरे पास स्क्रीनशॉट भी है।"},
            {"speaker": "AI", "text": "धन्यवाद। मैं टीम को इसे सत्यापित करने के लिए कहूंगा। आपका दिन शुभ हो।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "ஆனால் நான் ஏற்கனவே நேற்று காலையிலேயே பணம் செலுத்திவிட்டேன்."},
            {"speaker": "AI", "text": "பரிவர்த்தனை குறிப்பு எண் அல்லது எந்த முறையில் பணம் செலுத்தினீர்கள் என்று தயவுசெய்து கூற முடியுமா?"},
            {"speaker": "User", "text": "நான் UPI மூலம் பணம் செலுத்தினேன். என்னிடம் ஸ்கிரீன்ஷாட்டும் உள்ளது."},
            {"speaker": "AI", "text": "நன்றி. இதைச் சரிபார்க்க குழுவிடம் தெரிவிக்கிறேன். நல்ல நாள்."}
        ]
    },
    "needs_extension": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "I am facing some financial issues right now. Can I get an extension for two weeks?"},
            {"speaker": "AI", "text": "I understand. Until what date exactly are you requesting an extension?"},
            {"speaker": "User", "text": "Please give me time until 10th March 2026. I will surely pay then."},
            {"speaker": "AI", "text": "I will note down your request for 10th March. Our manager will review it. Thank you."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "मुझे अभी कुछ आर्थिक तंगी है। क्या मुझे दो हफ्ते का समय और मिल सकता है?"},
            {"speaker": "AI", "text": "मैं समझता हूँ। आप ठीक किस तारीख तक का समय मांग रहे हैं?"},
            {"speaker": "User", "text": "कृपया मुझे 10 मार्च 2026 तक का समय दें। मैं तब निश्चित रूप से भुगतान कर दूंगा।"},
            {"speaker": "AI", "text": "मैं 10 मार्च के लिए आपका अनुरोध नोट कर लेता हूँ। हमारे मैनेजर इसकी समीक्षा करेंगे। धन्यवाद।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "எனக்கு இப்போது சில நிதிச் சிக்கல்கள் உள்ளன. எனக்கு இரண்டு வார கால நீட்டிப்பு கிடைக்குமா?"},
            {"speaker": "AI", "text": "எனக்கு புரிகிறது. எந்த தேதி வரை உங்களுக்கு கால அவகாசம் தேவை?"},
            {"speaker": "User", "text": "தயவுசெய்து எனக்கு மார்ச் 10, 2026 வரை அவகாசம் கொடுங்கள். நான் அப்போது கண்டிப்பாக செலுத்துவேன்."},
            {"speaker": "AI", "text": "மார்ச் 10-க்கான உங்கள் கோரிக்கையை நான் குறித்துக் கொள்கிறேன். எங்கள் மேலாளர் இதை ஆய்வு செய்வார். நன்றி."}
        ]
    },
    "dispute": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "I don't agree with the interest amount you have calculated. It's wrong according to my papers."},
            {"speaker": "AI", "text": "I see. Could you explain what exactly is the discrepancy?"},
            {"speaker": "User", "text": "Your team promised a lower rate but now you are charging more. I won't pay until this is fixed."},
            {"speaker": "AI", "text": "I will escalate this dispute to our manual process for detailed investigation. Thank you."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "मैं आपके द्वारा कैलकुलेट किए गए ब्याज की राशि से सहमत नहीं हूं। यह मेरे कागजों के हिसाब से गलत है।"},
            {"speaker": "AI", "text": "अच्छा। क्या आप बता सकते हैं कि असल में क्या अंतर है?"},
            {"speaker": "User", "text": "आपकी टीम ने कम रेट का वादा किया था लेकिन अब आप ज़्यादा चार्ज कर रहे हैं। जब तक यह ठीक नहीं होगा, मैं भुगतान नहीं करूँगा।"},
            {"speaker": "AI", "text": "मैं इस विवाद को विस्तृत जांच के लिए हमारी मैनुअल प्रोसेस में भेज रहा हूँ। धन्यवाद।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "நீங்கள் கணக்கிட்டுள்ள வட்டித் தொகையை நான் ஏற்கவில்லை. என் ஆவணங்களின்படி அது தவறு."},
            {"speaker": "AI", "text": "சரி. சரியாக என்ன வித்தியாசம் என்று விளக்க முடியுமா?"},
            {"speaker": "User", "text": "உங்கள் குழு குறைந்த வட்டி விகிதத்தை உறுதி அளித்தது, ஆனால் இப்போது நீங்கள் அதிகமாக வசூலிக்கிறீர்கள். இதை சரிசெய்யும் வரை நான் பணம் செலுத்த மாட்டேன்."},
            {"speaker": "AI", "text": "விரிவான விசாரணைக்காக இந்த விவாதத்தை எங்கள் மேனுவல் செயல்முறைக்கு மாற்றுகிறேன். நன்றி."}
        ]
    },
    "no_response": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency... Hello? Can you hear me?"},
            {"speaker": "User", "text": "... [silence] ..."},
            {"speaker": "AI", "text": "I am calling regarding your loan payment. Are you there?"},
            {"speaker": "User", "text": "... [muffled noise, no clear words] ..."},
            {"speaker": "AI", "text": "Since I cannot get a clear response, I will have our team contact you later. Goodbye."}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से... नमस्ते? क्या आप मुझे सुन पा रहे हैं?"},
            {"speaker": "User", "text": "... [मौन] ..."},
            {"speaker": "AI", "text": "मैं आपके लोन भुगतान के संबंध में कॉल कर रहा हूं। क्या आप वहां हैं?"},
            {"speaker": "User", "text": "... [अस्पष्ट शोर, कोई शब्द नहीं] ..."},
            {"speaker": "AI", "text": "चूंकि मुझे कोई स्पष्ट जवाब नहीं मिल रहा है, इसलिए हमारी टीम आपसे बाद में संपर्क करेगी। नमस्ते।"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து... வணக்கம்? நான் பேசுவது கேட்கிறதா?"},
            {"speaker": "User", "text": "... [நிசப்தம்] ..."},
            {"speaker": "AI", "text": "உங்கள் கடன் செலுத்துதல் குறித்து நான் அழைக்கிறேன். நீங்கள் லைனில் இருக்கிறீர்களா?"},
            {"speaker": "User", "text": "... [தெளிவற்ற சத்தம், வார்த்தைகள் இல்லை] ..."},
            {"speaker": "AI", "text": "தங்களிடமிருந்து தெளிவான பதில் கிடைக்காததால், எங்கள் குழுவினர் பின்னர் உங்களைத் தொடர்புகொள்வார்கள். வணக்கம்."}
        ]
    },
    "mid_call": {
        "en-IN": [
            {"speaker": "AI", "text": "Hello, I am calling from the finance agency regarding your loan payment."},
            {"speaker": "User", "text": "Hello, who is this? I can't hear you clearly..."},
            {"speaker": "AI", "text": "I am calling about your overdue loan amount of ₹5,000. Can you hear me now?"},
            {"speaker": "User", "text": "Yes, I hear you but I'm in a meeting right now, I will— [Call Disconnected]"}
        ],
        "hi-IN": [
            {"speaker": "AI", "text": "नमस्ते, मैं वित्त एजेंसी से आपके लोन भुगतान के बारे में कॉल कर रहा हूं।"},
            {"speaker": "User", "text": "नमस्ते, कौन बोल रहा है? मुझे आपकी आवाज़ साफ़ नहीं आ रही..."},
            {"speaker": "AI", "text": "मैं आपके ₹5,000 के बकाया लोन के बारे में बात कर रहा हूँ। क्या अब आप मुझे सुन पा रहे हैं?"},
            {"speaker": "User", "text": "हां, सुनाई दे रहा है पर मैं अभी मीटिंग में हूँ, मैं— [कॉल कट गया]"}
        ],
        "ta-IN": [
            {"speaker": "AI", "text": "வணக்கம், நான் நிதி நிறுவனத்திலிருந்து உங்கள் கடன் செலுத்துதல் பற்றி அழைக்கிறேன்."},
            {"speaker": "User", "text": "வணக்கம், யார் பேசுகிறீர்கள்? உங்கள் குரல் தெளிவாக கேட்கவில்லை..."},
            {"speaker": "AI", "text": "உங்கள் ₹5,000 கடன் நிலுவைத் தொகை குறித்து நான் அழைக்கிறேன். இப்போது கேட்கிறதா?"},
            {"speaker": "User", "text": "ஆம், கேட்கிறது ஆனால் நான் இப்போது ஒரு கூட்டத்தில் இருக்கிறேன், நான்— [அழைப்பு துண்டிக்கப்பட்டது]"}
        ]
    },
    "failed_pickup": {
        "en-IN": [],
        "hi-IN": [],
        "ta-IN": []
    }
}


# ============================================================
# CORE LOGIC
# ============================================================

# Global semaphore to limit concurrent AI analysis requests (prevent 429)
ai_semaphore = asyncio.Semaphore(2)

async def create_dummy_call(user_id: str, phone_number: str, language: str, borrower_id: str = None, intent: str = "normal") -> dict:
    """Async helper to generate a dummy call and save to DB using model functions with User Isolation"""
    try:
        call_uuid = f"dummy-{uuid.uuid4()}"
        start_time = datetime.now()
        
        # Select intent category
        intent_cat = intent if intent in DUMMY_CONVERSATIONS else "normal"
        
        # SPECIAL CASE: Simulate Failed Pickup (Zero Duration)
        if intent_cat == "failed_pickup":
            return {
                "success": False,
                "error": "Call failed to connect (Simulation)",
                "duration_seconds": 0,
                "call_uuid": call_uuid
            }
            
        # Select language within that intent
        lang_key = language if language in DUMMY_CONVERSATIONS[intent_cat] else "en-IN"
        
        template = DUMMY_CONVERSATIONS[intent_cat][lang_key]
        conversation = []
        current_time = start_time
        
        for entry in template:
            current_time += timedelta(seconds=random.uniform(2, 5))
            conversation.append({
                **entry,
                "timestamp": current_time.isoformat(),
                "language": lang_key
            })
            
        # Use semaphore to limit global concurrent AI requests
        async with ai_semaphore:
            # Consistent with save_transcript, use Groq for the report logic
            ai_analysis = await analyze_conversation_with_groq(conversation)
            if not ai_analysis:
                ai_analysis = await analyze_conversation_with_gemini(conversation)
        
        # Extract payment information from AI analysis
        intent = ai_analysis.get("intent", "No Response") if ai_analysis else "No Response"
        payment_date = ai_analysis.get("payment_date") if ai_analysis else None
        extension_date = ai_analysis.get("extension_date") if ai_analysis else None
        is_mid_call = ai_analysis.get("mid_call", False) if ai_analysis else False
        
        transcript_data = {
            "call_uuid": call_uuid,
            "borrower_id": borrower_id,
            "phone_number": phone_number,
            "start_time": start_time.isoformat(),
            "end_time": current_time.isoformat(),
            "duration_seconds": (current_time - start_time).total_seconds(),
            "preferred_language": language,
            "conversation": conversation,
            "ai_analysis": ai_analysis,
            "is_dummy": True,
            "mid_call": is_mid_call
        }
        
        # Save Session (Standalone function with isolation)
        await create_call_session(user_id, transcript_data)
        
        # Set payment confirmation based on intent
        payment_confirmation = intent
        
        # Determine Next Step Summary and Email Draft logic
        next_step_summary = ""
        email_draft = None
        require_manual_process = False
        
        # Get borrower details for email (dummy/placeholder if not available)
        borrower_name = "Borrower"
        if borrower_id:
            # We could fetch from DB, but for MVP we use placeholder
            borrower_name = f"Borrower {borrower_id}"
            
        # 1. Get current borrower to check category
        borrower_in_db = await get_borrower_by_no(user_id, borrower_id) if borrower_id else None
        category = borrower_in_db.get("Payment_Category", "Consistent") if borrower_in_db else "Consistent"
        borrower_name = borrower_in_db.get("BORROWER", "Borrower") if borrower_in_db else f"Borrower {borrower_id}"
        
        # 2. Use helper to determine all reporting values
        outcomes = determine_report_outcomes(
            intent,
            payment_date,
            category,
            borrower_name=borrower_name,
            borrower_id=borrower_id or "",
            is_mid_call=is_mid_call
        )

        # Update Borrower (Standalone function with isolation)
        if borrower_id:
            await update_borrower(user_id, borrower_id, {
                "call_completed": True,
                "call_in_progress": False,
                "transcript": conversation,
                "ai_summary": outcomes["next_step_summary"] or ai_analysis.get("summary", "Done"),
                "payment_confirmation": outcomes["payment_confirmation"],
                "follow_up_date": outcomes["follow_up_date"],
                "call_frequency": outcomes["call_frequency"],
                "require_manual_process": outcomes["require_manual_process"],
                "email_to_manager_preview": outcomes["email_to_manager_preview"]
            })
            
        return {
            "success": True,
            "call_uuid": call_uuid,
            "status": "completed",
            "ai_analysis": ai_analysis,
            "conversation": conversation,
            "payment_confirmation": outcomes["payment_confirmation"],
            "follow_up_date": outcomes["follow_up_date"],
            "call_frequency": outcomes["call_frequency"],
            "next_step_summary": outcomes["next_step_summary"],
            "email_to_manager_preview": outcomes["email_to_manager_preview"],
            "require_manual_process": outcomes["require_manual_process"],
            "mid_call": is_mid_call
        }
    except Exception as e:
        logger.error(f"Dummy call error for user {user_id}: {e}")
        return {"success": False, "error": str(e)}

async def process_single_call(user_id: str, borrower: BorrowerInfo, use_dummy_data: bool, normalized_language: str) -> CallResponse:
    """Process call with 3 attempts. Continue if duration=0, escalate if disconnected mid-call, or process if successful."""
    max_attempts = 3
    last_res = {"success": False, "error": "All attempts failed after 3 tries"}
    
    for attempt in range(max_attempts):
        if use_dummy_data:
            res = await create_dummy_call(user_id, borrower.cell1, normalized_language, borrower.NO, borrower.intent_for_testing)
        else:
            res = make_outbound_call(user_id, borrower.cell1, normalized_language, borrower.NO)
        
        last_res = res
        
        # Scenario: Duration == 0 (Not picked up/hard error)
        # We assume success=False or duration_seconds=0 in the actual call data
        # For dummy, we'll check if it succeeded but has no transcript or duration (though dummy always has)
        # To simulate a 'no pickup' in dummy, we could use a specific error
        if not res.get("success"):
            print(f"❌ Attempt {attempt+1} failed to connect. Retrying...")
            await asyncio.sleep(1)
            continue
            
        # Scenario: Duration > 0 (Call picked up)
        if res.get("mid_call"):
            # if mid_call == True -> Stop and schedule follow-up
            print(f"⚠️ Call for {borrower.NO} cut mid-conversation. Scheduling follow-up.")
            break
        else:
            # if mid_call == False -> Processed successfully and break
            print(f"✅ Call for {borrower.NO} completed successfully on attempt {attempt+1}.")
            break
            
    # After 3 attempts, if last_res is still unsuccessful (failed to connect all 3 times)
    if not last_res.get("success"):
        email_failure_preview = {
            "to": "Area Manager",
            "subject": f"Action Required: Multiple Call Failures - Borrower {borrower.NO}",
            "body": f"Hi Area Manager,\n\nWe attempted to call Borrower (No: {borrower.NO}) 3 times, but all calls failed to connect (Zero duration).\n\nWe are escalating this to the Manual Process for you to initiate manual intervention.\n\nBest regards,\nAI Collection System"
        }
        
        # Update borrower status to failed but with escalation
        await update_borrower(user_id, borrower.NO, {
            "call_completed": True,
            "ai_summary": "All call attempts failed to connect (3 retries). Initiating Manual Process.",
            "require_manual_process": True,
            "email_to_manager_preview": email_failure_preview
        })
        
        return CallResponse(
            success=True, # Mark as 'Success' in terms of processing finished
            borrower_id=borrower.NO,
            ai_analysis={"summary": "All attempts failed."},
            status="Failed pickup",
            next_step_summary="All call attempts failed after 3 tries. Escalating to Manual Process.",
            email_to_manager_preview=email_failure_preview,
            require_manual_process=True
        )
        
    # If it was a success (either full completion or mid-call escalation)
    return CallResponse(
        success=True,
        call_uuid=last_res.get("call_uuid"),
        status=last_res.get("status"),
        to_number=borrower.cell1,
        language=normalized_language,
        borrower_id=borrower.NO,
        is_dummy=use_dummy_data,
        ai_analysis=last_res.get("ai_analysis"),
        conversation=last_res.get("conversation"),
        mid_call=last_res.get("mid_call", False),
        next_step_summary=last_res.get("next_step_summary"),
        email_to_manager_preview=last_res.get("email_to_manager_preview"),
        require_manual_process=last_res.get("require_manual_process", False)
    )

# ============================================================
# API ENDPOINTS
# ============================================================

@router.get("/")
async def ai_calling_root():
    return {"message": "AI Calling Module (User Isolated)", "status": "active"}

@router.post("/reset_calls")
async def reset_calls(current_user: dict = Depends(get_current_user)):
    """Reset call flags for all borrowers belonging to the current user"""
    user_id = str(current_user["_id"])
    modified_count = await reset_all_borrower_calls(user_id)
    return {
        "status": "success", 
        "message": f"All {modified_count} of your borrower call statuses have been reset"
    }

@router.post("/trigger_calls", response_model=BulkCallResponse)
async def trigger_bulk_calls(request: BulkCallRequest, current_user: dict = Depends(get_current_user)):
    """Trigger bulk calls for current user only.
    
    Per-borrower override: If real_call_borrower_ids is provided, borrowers whose
    NO is in that list will use REAL calls (use_dummy_data=False), regardless of
    the global use_dummy_data flag. All other borrowers use the global flag.
    """
    user_id = str(current_user["_id"])
    if not request.borrowers:
        raise HTTPException(status_code=400, detail="No borrowers")
    
    # Build a set for fast lookup of borrower IDs that should use real calls
    real_call_ids = set(request.real_call_borrower_ids)
    has_real_overrides = len(real_call_ids) > 0
    has_any_real = False
        
    async_tasks = []
    for b in request.borrowers:
        lang = normalize_language(b.preferred_language)
        
        # Per-borrower use_dummy_data decision:
        # If this borrower's NO is in real_call_borrower_ids → real call (False)
        # Otherwise → use the global flag from the request
        if has_real_overrides and b.NO in real_call_ids:
            borrower_use_dummy = False
            has_any_real = True
            logger.info(f"[BULK CALL] Borrower {b.NO} → REAL call (override)")
        else:
            borrower_use_dummy = request.use_dummy_data
            logger.info(f"[BULK CALL] Borrower {b.NO} → {'DUMMY' if borrower_use_dummy else 'REAL'} call (global)")
        
        async_tasks.append(process_single_call(user_id, b, borrower_use_dummy, lang))
        
    results = await asyncio.gather(*async_tasks)
    
    successful = len([r for r in results if r.success])
    
    # Determine mode label
    if has_real_overrides and has_any_real:
        mode = "mixed" if request.use_dummy_data else "real"
    else:
        mode = "dummy" if request.use_dummy_data else "real"
    
    return BulkCallResponse(
        total_requests=len(request.borrowers),
        successful_calls=successful,
        failed_calls=len(results) - successful,
        results=list(results),
        mode=mode
    )

@router.post("/make_call", response_model=CallResponse)
async def make_single_call(request: SingleCallRequest, current_user: dict = Depends(get_current_user)):
    """Trigger a single call manually for current user"""
    user_id = str(current_user["_id"])
    lang = normalize_language(request.language)
    if request.use_dummy_data:
        res = await create_dummy_call(user_id, request.to_number, lang, request.borrower_id, request.intent_for_testing)
    else:
        res = make_outbound_call(user_id, request.to_number, lang, request.borrower_id)
        
    if res.get("success"):
        return CallResponse(
            success=True,
            call_uuid=res.get("call_uuid"),
            status=res.get("status"),
            to_number=request.to_number,
            language=lang,
            borrower_id=request.borrower_id,
            is_dummy=request.use_dummy_data,
            ai_analysis=res.get("ai_analysis"),
            conversation=res.get("conversation")
        )
    raise HTTPException(status_code=500, detail=res.get("error"))

@router.get("/sessions/{loan_no}")
async def get_loan_sessions_api(loan_no: str, current_user: dict = Depends(get_current_user)):
    """Get history for a specific loan number (Isolated to current user)"""
    user_id = str(current_user["_id"])
    sessions = await get_sessions_by_loan(user_id, loan_no)
    return sanitize_for_json(sessions)

@router.get("/session/{call_uuid}")
async def get_call_session_api(call_uuid: str, current_user: dict = Depends(get_current_user)):
    """Get details of a specific session (Isolated to current user)"""
    user_id = str(current_user["_id"])
    session = await get_call_session_by_uuid(user_id, call_uuid)
    if not session: raise HTTPException(status_code=404, detail="Session not found in your account")
    return sanitize_for_json(session)

@router.get("/sessions")
async def list_sessions_api(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """List recent sessions (Isolated to current user)"""
    user_id = str(current_user["_id"])
    sessions = await get_all_call_sessions(user_id, limit=limit)
    return sanitize_for_json(sessions)

@router.get("/analysis/{call_uuid}")
async def get_call_analysis_api(call_uuid: str, current_user: dict = Depends(get_current_user)):
    """Get only the AI analysis for a specific call session (Isolated to current user)"""
    user_id = str(current_user["_id"])
    session = await get_call_session_by_uuid(user_id, call_uuid)
    if session and 'ai_analysis' in session:
        return {
            "call_uuid": call_uuid,
            "loan_no": session.get("loan_no"),
            "is_dummy": session.get("is_dummy", False),
            "ai_analysis": session['ai_analysis']
        }
    raise HTTPException(status_code=404, detail="Analysis not found or access denied")

@router.get("/borrower_call_status/{borrower_no}")
async def get_borrower_call_status(borrower_no: str, current_user: dict = Depends(get_current_user)):
    """Get the latest call status for a borrower from the DB (used for polling real call results)"""
    user_id = str(current_user["_id"])
    borrower = await get_borrower_by_no(user_id, borrower_no)
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return {
        "NO": borrower.get("NO"),
        "call_completed": borrower.get("call_completed", False),
        "call_in_progress": borrower.get("call_in_progress", False),
        "transcript": borrower.get("transcript"),
        "ai_summary": borrower.get("ai_summary"),
        "payment_confirmation": borrower.get("payment_confirmation"),
        "follow_up_date": borrower.get("follow_up_date"),
        "call_frequency": borrower.get("call_frequency"),
        "require_manual_process": borrower.get("require_manual_process", False),
        "email_to_manager_preview": borrower.get("email_to_manager_preview"),
    }

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "AI Calling"}