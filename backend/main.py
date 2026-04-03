"""
M-S2C Diagnostic Engine - Main FastAPI Application

CRITICAL STARTUP REQUIREMENT:
- The MS2CRetriever (with 1GB+ CodeBERT model) MUST be instantiated ONCE at startup
- NOT inside route handlers (would reload model on every request = CRASH)
- Model state persists across all requests in global module scope
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import asyncio
from contextlib import asynccontextmanager

# Import all modules
from config import logger, app_state
from routes import setup_routes

# Global model instance (loaded once at startup)
global_retriever = None
PYTORCH_AVAILABLE = False

# Try to import the retriever module - FAIL FAST if issues
try:
    from retriever import MS2CRetriever
    PYTORCH_AVAILABLE = True
    print("✅ Successfully imported MS2CRetriever from retriever.py")
except Exception as e:
    import traceback
    print(f"\n{'='*60}")
    print("❌ CRITICAL ERROR: Failed to import MS2CRetriever")
    print(f"{'='*60}")
    print(f"Error: {e}")
    print(f"\nFull traceback:")
    traceback.print_exc()
    print(f"{'='*60}")
    print("\n🛑 STARTUP FAILED - Fix the import error above")
    print("   This is likely a missing dependency or PyTorch installation issue")
    print(f"{'='*60}\n")
    exit(1)  # FAIL FAST - don't continue with mock mode


# CRITICAL: Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan manager handles model initialization at startup and cleanup at shutdown.
    
    CRITICAL SAFETY: Model is initialized ONCE here and reused for all requests.
    This prevents reloading the massive CodeBERT model (1GB+) on every request.
    """
    # STARTUP
    print(f"\n{'='*60}")
    print("🚀 M-S2C DIAGNOSTIC ENGINE - STARTUP PHASE")
    print(f"{'='*60}")
    
    global global_retriever
    
    if PYTORCH_AVAILABLE:
        try:
            print(f"💾 Instantiating MS2CRetriever model (CodeBERT)...")
            logger.info(f"💾 Instantiating MS2CRetriever model at startup")
            
            # Initialize the retriever ONCE
            # Model will be loaded on first use, then persisted in memory
            global_retriever = MS2CRetriever(
                model_name="microsoft/codebert-base"  # Will auto-download if not cached
            )
            
            print(f"✅ MS2CRetriever instantiated successfully")
            print(f"   Device: {global_retriever.device}")
            print(f"   Model: CodeBERT (768-dim embeddings)")
            logger.info(f"✅ MS2CRetriever ready on device: {global_retriever.device}")
            
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ CRITICAL ERROR: Failed to initialize MS2CRetriever")
            print(f"{'='*60}")
            print(f"Error: {e}")
            import traceback
            print(f"\nFull traceback:")
            traceback.print_exc()
            print(f"{'='*60}")
            print("\n🛑 STARTUP FAILED - Fix the CodeBERT initialization error above")
            print("   Possible causes:")
            print("   - Missing PyTorch installation")
            print("   - Insufficient GPU/CPU memory for CodeBERT model (1GB+)")
            print("   - Network issues downloading model from HuggingFace Hub")
            print("   - Corrupted model cache in ~/.cache/huggingface/")
            print(f"{'='*60}\n")
            logger.error(f"❌ MS2CRetriever initialization failed: {e}")
            exit(1)  # FAIL FAST - don't start server
    
    print(f"📡 API Server: http://0.0.0.0:8000")
    print(f"📚 API Docs: http://localhost:8000/docs")
    print(f"🧠 Mode: Production (CodeBERT)")
    print(f"{'='*60}\n")
    
    logger.info(f"📡 M-S2C Diagnostic Engine started - PRODUCTION MODE")
    logger.info(f"🧠 CodeBERT retriever ready")
    
    yield  # Request handling happens here
    
    # SHUTDOWN
    print(f"\n{'='*60}")
    print("🛑 M-S2C DIAGNOSTIC ENGINE - SHUTDOWN PHASE")
    print(f"{'='*60}")
    
    if global_retriever:
        print(f"💾 Model instance will be garbage collected")
        logger.info(f"💾 Cleaning up model resources")
        global_retriever = None
    
    print(f"✅ Shutdown complete")
    logger.info(f"✅ M-S2C Engine shutdown complete")
    print(f"{'='*60}\n")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="M-S2C Diagnostic Engine API",
    description="AI-Powered Frontend Bug Diagnostic Engine",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware to allow frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routes with the global retriever instance
# Note: PYTORCH_AVAILABLE is guaranteed true at this point (exit(1) on import failure)
setup_routes(app, global_retriever, True)




if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 STARTING M-S2C DIAGNOSTIC ENGINE")
    print("="*60)
    print(f"📝 Logging to: {os.path.abspath('backend_debug.log')}")
    print(f"📡 API Server: http://0.0.0.0:8000")
    print(f"📚 API Docs: http://localhost:8000/docs")
    print(f"🧠 Mode: PRODUCTION (CodeBERT - Required)")
    print(f"⚠️  DO NOT run multiple instances - model uses global memory")
    print(f"💡 If startup fails: Check PyTorch, GPU memory, or missing models")
    print("="*60 + "\n")
    
    # Start the server with lifespan management
    # Model initialization happens inside the lifespan context
    # Startup will FAIL if CodeBERT cannot be initialized (no silent fallback)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False  # CRITICAL: Never enable reload=True (would duplicate model loading)
    )
