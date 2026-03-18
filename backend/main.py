"""
AIaaS Finance Platform - Main Application
==========================================
Entry point for the FastAPI application
Runs both FastAPI (port 8000) and Flask WebSocket server (port 5000)
"""
import asyncio

import threading
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# from app.ai_calling.views_actual import router as ai_calling_router
from app.data_ingestion.views import router as data_ingestion_router
from app.ai_calling.views import router as ai_calling_router
from app.auth.views import router as auth_router
from app.governance.views import router as governance_router

app = FastAPI(
    title="AIaaS Finance Platform",
    version="1.0.0",
    description="AI as a Service for Finance Agencies"
)

# --- CORS (allow all for development; restrict in production) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (expand as phases progress)
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(ai_calling_router, prefix="/ai_calling", tags=["AI Calling"])
app.include_router(data_ingestion_router, prefix="/data_ingestion", tags=["Data Ingestion"])
app.include_router(governance_router, prefix="/governance", tags=["Governance"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AIaaS Finance Platform API",
        "version": "1.0.0",
        "status": "active",
        "endpoints": {
            "data_ingestion": "/data_ingestion",
            "ai_calling": "/ai_calling",
            "health": "/ai_calling/health",
            "flask_webhooks": "http://localhost:5000/webhooks/*",
            "flask_websocket": "ws://localhost:5000/socket/<uuid>"
        },
        "servers": {
            "fastapi": "http://127.0.0.1:8000 (API endpoints)",
            "flask": "http://127.0.0.1:5000 (Webhooks & WebSocket)"
        }
    }


@app.on_event("startup")
async def on_startup():
    """Store the main event loop so Flask can schedule async DB operations on it"""
    import flask_server
    flask_server.set_main_loop(asyncio.get_running_loop())


@app.get("/health", tags=["Health"])
async def health_check():
    """General health check endpoint"""
    return {
        "status": "healthy",
        "service": "AIaaS Finance Platform",
        "fastapi_port": 8000,
        "flask_port": 5000
    }


def run_flask_server():
    """Run Flask WebSocket server in a separate thread"""
    time.sleep(2)  # Wait for FastAPI to start first
    from flask_server import run_flask_server
    run_flask_server()


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("🚀 STARTING AIaaS FINANCE PLATFORM")
    print("="*60)
    print("📡 FastAPI Server: http://127.0.0.1:8000")
    print("   - API endpoints for triggering calls")
    print("   - Swagger UI: http://127.0.0.1:8000/docs")
    print("\n🔌 Flask WebSocket Server: http://127.0.0.1:5000")
    print("   - Vonage webhooks (/webhooks/answer, /webhooks/event)")
    print("   - WebSocket for real-time audio (/socket/<uuid>)")
    print("\n⚠️  IMPORTANT:")
    print("   Update your Vonage dashboard with:")
    print("   Answer URL: <YOUR_NGROK_URL>/webhooks/answer")
    print("   Event URL: <YOUR_NGROK_URL>/webhooks/event")
    print("="*60 + "\n")
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    
    # Start FastAPI server
    uvicorn.run(app, host="127.0.0.1", port=8000)