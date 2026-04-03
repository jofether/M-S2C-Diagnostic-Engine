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
from routes import setup_routes

# Try to import the trained MS2C Model, fall back to mock if PyTorch issues
try:
    from ms2c import MS2CRetriever
    PYTORCH_AVAILABLE = True
    print("✅ PyTorch and CodeBERT models available - Loading trained MS2C retriever")
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

# Initialize retriever with trained checkpoint and empty index (will be populated via /api/index-repository)
# Using the trained MS2CModel from benchmarking: ms2c_E2E_JOINT_BEST.pt
retriever = None
if PYTORCH_AVAILABLE:
    try:
        checkpoint_path = "ms2c_E2E_JOINT_BEST.pt"
        empty_index = {}  # Will be populated via /api/index-repository
        retriever = MS2CRetriever(
            model_path=checkpoint_path,
            index_dict=empty_index,
            repos_dir=None,
            batch_size=64
        )
        print(f"✅ Loaded trained checkpoint: {checkpoint_path}")
    except Exception as e:
        print(f"⚠️  Failed to initialize retriever with checkpoint: {e}")
        import traceback
        traceback.print_exc()
        PYTORCH_AVAILABLE = False

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
