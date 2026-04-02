"""
M-S2C Diagnostic Engine - Main FastAPI Application
Modular refactored version with separated concerns
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# Import all modules
from config import logger, app_state
from retriever import MS2CRetriever
from routes import setup_routes

# Try to import the custom AI Retriever, fall back to mock if PyTorch issues
try:
    from ms2c import MS2CRetriever as CustomRetriever
    PYTORCH_AVAILABLE = True
    print("✅ PyTorch and CodeBERT models available")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"⚠️  PyTorch import error: {e}")
    print("🔧 Running in mock mode - responses will use keyword-based ranking\n")
    PYTORCH_AVAILABLE = False

# Initialize FastAPI app
app = FastAPI(title="M-S2C Diagnostic Engine API")

# Add CORS middleware to allow frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize retriever with empty index (will be populated via /api/index-repository)
retriever = MS2CRetriever(model_path="", index_dict={})

# Register all routes
setup_routes(app, retriever, PYTORCH_AVAILABLE)

# Log configuration summary
logger.info(f"📡 Starting M-S2C Diagnostic Engine")
logger.info(f"🧠 Mode: {'Production (CodeBERT)' if PYTORCH_AVAILABLE else 'Mock (Keyword-based)'}")
logger.info(f"🌐 CORS enabled for all origins")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 M-S2C DIAGNOSTIC ENGINE")
    print("="*60)
    print(f"📝 Logging to: {os.path.abspath('backend_debug.log')}")
    print(f"📡 API at: http://0.0.0.0:8000")
    print(f"📚 Docs at: http://localhost:8000/docs")
    print(f"🧠 Mode: {'Production' if PYTORCH_AVAILABLE else 'Mock'}")
    print("="*60 + "\n")
    
    # Start the server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False
    )
