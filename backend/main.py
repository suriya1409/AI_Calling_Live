import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.data_ingestion.views import router as data_ingestion_router
from app.ai_calling.views import router as ai_calling_router
from app.ai_calling.unified_api import router as unified_router
from app.auth.views import router as auth_router
from app.governance.views import router as governance_router

app = FastAPI(
    title="AIaaS Finance Platform",
    version="1.1.0",
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

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(ai_calling_router, prefix="/ai_calling", tags=["AI Calling"])
app.include_router(unified_router, prefix="/ai_calling", tags=["Unified Voice/Webhooks"])
app.include_router(data_ingestion_router, prefix="/data_ingestion", tags=["Data Ingestion"])
app.include_router(governance_router, prefix="/governance", tags=["Governance"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AIaaS Finance Platform API",
        "version": "1.1.0",
        "status": "active",
        "unified": True,
        "endpoints": {
            "auth": "/auth",
            "ai_calling": "/ai_calling",
            "data_ingestion": "/data_ingestion",
            "governance": "/governance"
        }
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """General health check endpoint"""
    return {
        "status": "healthy",
        "service": "AIaaS Finance Platform (Unified)",
        "version": "1.1.0"
    }


if __name__ == "__main__":
    # Get port from environment variable (default to 8000 for local dev)
    port = int(os.getenv("PORT", 8000))
    
    print("\n" + "="*60)
    print("🚀 STARTING UNIFIED AIaaS FINANCE PLATFORM")
    print("="*60)
    print(f"📡 API Server: http://0.0.0.0:{port}")
    print(f"   - Swagger UI: http://0.0.0.0:{port}/docs")
    print("\n⚠️  DEPROYMENT READY:")
    print("   This application is now unified and ready for Render/Vercel.")
    print("   All webhooks and sockets are available under /ai_calling")
    print("="*60 + "\n")
    
    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=port)