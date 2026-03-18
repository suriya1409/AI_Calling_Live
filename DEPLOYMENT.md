# Deployment Guide: AIaaS Finance Platform

This guide explains how to deploy the **Unified** AIaaS Finance Platform to Render (Backend) and Vercel (Frontend).

## 1. Backend Deployment (Render)

1.  **Create a New Web Service**:
    - Repository: `https://github.com/suriya1409/AI_Calling_Live.git` (Branch: `main`)
    - Root Directory: `backend`
    - Runtime: `Python 3`
    - Build Command: `pip install -r requirements.txt` (Move `requirements.txt` to `backend/` if needed, or use `pip install -r ../requirements.txt`)
    - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

2.  **Environment Variables**:
    Add the following in Render's "Environment" tab:
    - `VONAGE_API_KEY`: `893f1604`
    - `VONAGE_API_SECRET`: `uiaV@Ch35`
    - `VONAGE_APPLICATION_ID`: `2a77b2dc-0ca2-41f0-94e8-0eebd5286153`
    - `VONAGE_FROM_NUMBER`: `12345678901`
    - `VONAGE_PRIVATE_KEY_CONTENT`: (Paste the entire content of your `private.key` here)
    - `GEMINI_API_KEY`: `AIzaSyCHKMUkhzVHfaKoRpSaG6VQRBZtXlyZzmU`
    - `SARVAM_API_KEY`: `sk_1q8t02gh_pXaWELrVOfyOgFlWd3e9AFRa`
    - `MONGO_URI`: `mongodb+srv://shalini04doodleblue_db_user:4gmBRfAifxwR1kKH@cluster0.bnr9oy1.mongodb.net/`
    - `MONGO_DB_NAME`: `ai_finance_platform`
    - `BASE_URL`: (The URL Render gives you, e.g., `https://ai-calling-live.onrender.com`)
    - `PORT`: `8000` (Render will override this, but good to have)

3.  **Vonage Dashboard Update**:
    - Update your Answer URL to: `https://your-render-url.onrender.com/ai_calling/webhooks/answer`
    - Update your Event URL to: `https://your-render-url.onrender.com/ai_calling/webhooks/event`

---

## 2. Frontend Deployment (Vercel)

1.  **Create a New Project**:
    - Repository: `https://github.com/suriya1409/AI_Calling_Live.git` (Branch: `main`)
    - Root Directory: `frontend`
    - Framework Preset: `Other` (Static site)

2.  **Configuration**:
    - Vercel will automatically detect the `index.html` and deploy it.
    - Ensure your `frontend/js/app.js` has the correct `API_BASE_URL` pointing to your Render backend.

---

## 3. Important Notes

- **Unified API**: The backend now runs everything (API, Webhooks, WebSockets) on a single port.
- **Private Key**: Using `VONAGE_PRIVATE_KEY_CONTENT` env var is safer and easier than managing a file on Render.
- **WebSocket URL**: The frontend should use the same base URL for WebSocket connections. The code handles this automatically.
