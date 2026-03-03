import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from config import settings

logger = logging.getLogger(__name__)

async def send_email(to_email: str, subject: str, body: str):
    """
    Send an email using SMTP settings from config.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning(f"[EMAIL] ⚠️ SMTP credentials not configured. Email to {to_email} skipped.")
        print(f"[EMAIL] ⚠️ SMTP credentials not configured. Email to {to_email} skipped.")
        return False

    try:
        # If to_email is "Area Manager", use the configured MANAGER_EMAIL
        recipient = to_email
        if to_email.lower() == "area manager" and settings.MANAGER_EMAIL:
            recipient = settings.MANAGER_EMAIL
        elif to_email.lower() == "area manager":
             logger.warning("[EMAIL] ⚠️ 'Area Manager' requested but MANAGER_EMAIL not set in config.")
             return False

        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_USER
        msg['To'] = recipient
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        # Use SMTP_SSL if port is 465, otherwise use starttls
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"[EMAIL] ✅ Email sent successfully to {recipient}")
        print(f"[EMAIL] ✅ Email sent successfully to {recipient}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] ❌ Failed to send email: {e}")
        print(f"[EMAIL] ❌ Failed to send email: {e}")
        return False
