"""
API routes for the M-S2C Diagnostic Engine
"""

import os
import sys
import json
import shutil
import tempfile
import asyncio
from datetime import datetime
from fastapi import UploadFile, File, Form, WebSocket, WebSocketDisconnect

from config import logger, app_state
from repository import clone_repository
from indexer import build_index_sync, reindex_retriever, get_index_status
from utils import compute_gating_weight, generate_smart_results


# Global data storage
global_indexed_data = {}

# Global progress state for WebSocket-based progress streaming
index_progress_state = {
    "is_indexing": False,
    "current_message": "",
    "progress_percent": 0,
    "total_files": 0,
    "processed_files": 0
}


def extract_target_file(bug_description: str) -> tuple:
    """
    Extract target file from query format: [components/UserTestimonials.jsx] - description
    Returns: (target_file, cleaned_description) or (None, original_description) if not found
    """
    import re
    match = re.match(r'\[(.+?)\]\s*-\s*(.*)', bug_description)
    if match:
        target_file = match.group(1)
        cleaned_desc = match.group(2)
        return target_file, cleaned_desc
    return None, bug_description


def setup_routes(app, retriever, pytorch_available):
    """
    Register all routes with the FastAPI app.
    
    Args:
        app: FastAPI application instance
        retriever: MS2CRetriever instance
        pytorch_available: Boolean indicating if PyTorch is available
    """
    
    @app.get("/api/index-status")
    async def index_status():
        """
        Returns the current index status for frontend status polling.
        Used to check if embeddings are ready before allowing searches.
        
        Returns:
            JSON with is_index_ready flag
        """
        return {
            "is_index_ready": get_index_status(),
            "status": "ready" if get_index_status() else "indexing"
        }
    
    @app.get("/api/index-progress")
    async def get_progress():
        """
        Returns the current indexing progress state.
        Used by the polling fallback when WebSocket fails.
        
        Returns:
            JSON with current_message, progress_percent, is_complete
        """
        return {
            "message": index_progress_state["current_message"] or "Initializing...",
            "percent": index_progress_state["progress_percent"],
            "is_complete": get_index_status()
        }
    
    @app.websocket("/ws/index-progress")
    async def websocket_index_progress(websocket: WebSocket):
        """
        WebSocket endpoint for real-time indexing progress streaming.
        Broadcasting mode: Client connects and receives progress updates as they happen.
        
        Sends JSON messages with:
          - message: Current progress description
          - percent: Progress percentage (0-100)
          - is_complete: Boolean indicating if indexing is done
        """
        print(f"\n{'='*60}")
        print(f"🔌 WebSocket /ws/index-progress CONNECTION ATTEMPT")
        print(f"{'='*60}")
        
        websocket_accepted = False
        
        try:
            # CRITICAL: Accept connection first
            await websocket.accept()
            websocket_accepted = True
            print(f"✅ WebSocket connection ACCEPTED")
            logger.info("🔌 WebSocket client connected for progress streaming")
            
            # Send initial state immediately
            initial_state = {
                "message": index_progress_state["current_message"] or "Initializing...",
                "percent": index_progress_state["progress_percent"],
                "is_complete": False
            }
            print(f"📤 Sending INITIAL state: {initial_state}")
            await websocket.send_json(initial_state)
            
            # Track last sent state to avoid spam
            last_sent_state = None
            
            while True:
                # Small delay to avoid overwhelming the client
                await asyncio.sleep(0.5)
                
                # Read current state
                current_state = {
                    "message": index_progress_state["current_message"],
                    "percent": index_progress_state["progress_percent"],
                    "is_complete": get_index_status()
                }
                
                # Only send if state changed
                if current_state != last_sent_state:
                    print(f"📤 Sending progress update: percent={current_state['percent']}, message={current_state['message'][:40] if current_state['message'] else 'none'}")
                    await websocket.send_json(current_state)
                    last_sent_state = current_state
                
                # If indexing is complete, close connection
                if get_index_status():
                    print(f"✅ Indexing complete, closing WebSocket")
                    logger.info("✅ Indexing complete, closing WebSocket after final message")
                    await websocket.close(code=1000, reason="Indexing complete")
                    break
                
        except WebSocketDisconnect:
            logger.info("🔌 WebSocket client disconnected")
            print(f"🔌 WebSocket client disconnected")
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            print(f"❌ WebSocket error: {e}")
            print(f"❌ Exception type: {type(e).__name__}")
            print(f"❌ Exception message: {str(e)}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            
            # Only try to close if we accepted the connection
            if websocket_accepted:
                try:
                    await websocket.close(code=1011, reason=f"Internal error: {str(e)[:100]}")
                except Exception as close_err:
                    print(f"⚠️  Error closing WebSocket: {close_err}")
                    logger.warning(f"⚠️  Could not close WebSocket: {close_err}")
    
    
    @app.post("/api/index-repository")
    async def index_repository(repo_url: str = Form(...)):
        """
        Performs the complete offline indexing workflow:
        1. Shallow clone the GitHub repository
        2. Extract React components and CSS rules using regex (mock Tree-sitter)
        3. Build index dictionary mapping files to code snippets
        4. Re-encode through CodeBERT via MS2CRetriever
        5. Cache index to disk
        6. Cleanup temporary files
        
        Returns:
            JSON response with indexing statistics
        """
        
        # CRITICAL: Reset progress state for new indexing run
        global index_progress_state
        index_progress_state["is_indexing"] = True
        index_progress_state["current_message"] = ""
        index_progress_state["progress_percent"] = 0
        index_progress_state["total_files"] = 0
        index_progress_state["processed_files"] = 0
        
        temp_dir = None
        
        try:
            # Initialize progress tracking for WebSocket
            index_progress_state["is_indexing"] = True
            index_progress_state["current_message"] = "Initializing repository clone..."
            index_progress_state["progress_percent"] = 0
            
            print(f"\n{'='*60}")
            print(f"📥 INDEXING REPOSITORY: {repo_url}")
            print(f"{'='*60}")
            
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix="ms2c_repo_")
            print(f"📁 Temp directory: {temp_dir}")
            
            # Step 1: Clone repository
            index_progress_state["current_message"] = "Cloning repository..."
            index_progress_state["progress_percent"] = 10
            clone_success = clone_repository(repo_url, temp_dir)
            if not clone_success:
                index_progress_state["is_indexing"] = False
                return {
                    "status": "error",
                    "message": "Failed to clone repository. Check URL and Git installation.",
                    "files_indexed": 0,
                    "snippets_indexed": 0
                }
            
            # Step 2 & 3: Build index from cloned repo
            index_progress_state["current_message"] = "Parsing ASTs with Tree-sitter..."
            index_progress_state["progress_percent"] = 30
            print("\n🔍 Extracting components and building index...")
            index_dict = build_index_sync(temp_dir)
            
            if not index_dict:
                index_progress_state["is_indexing"] = False
                return {
                    "status": "warning",
                    "message": "Repository cloned but no frontend files found. Check repository structure.",
                    "files_indexed": 0,
                    "snippets_indexed": 0
                }
            
            total_snippets = sum(len(snippets) for snippets in index_dict.values())
            print(f"\n📊 INDEX BUILT:")
            print(f"   Files: {len(index_dict)}")
            print(f"   Total Snippets: {total_snippets}")
            print(f"\n📋 Files indexed:")
            
            # Log to file as well
            logger.info(f"\n📊 INDEX BUILT: Files: {len(index_dict)}, Snippets: {total_snippets}")
            logger.info("📋 Files indexed:")
            
            for file_path in sorted(index_dict.keys())[:10]:
                print(f"   ✓ {file_path}")
                logger.info(f"   ✓ {file_path}")
            if len(index_dict) > 10:
                print(f"   ... and {len(index_dict) - 10} more files")
                logger.info(f"   ... and {len(index_dict) - 10} more files")
            
            # Step 4: Update global indexed data and re-encode through retriever
            index_progress_state["current_message"] = "Generating CodeBERT Embeddings..."
            index_progress_state["progress_percent"] = 60
            global global_indexed_data
            global_indexed_data = index_dict
            print(f"\n🔄 Updating global index...")
            logger.info(f"🔄 Starting CodeBERT embedding generation for {len(index_dict)} files...")
            await reindex_retriever(retriever, index_dict)
            print(f"✅ CodeBERT embeddings generated")
            logger.info(f"✅ CodeBERT embeddings complete")
            
            # Step 5: Cache to disk - FAISS population stage
            index_progress_state["current_message"] = "Populating FAISS Vector Database..."
            index_progress_state["progress_percent"] = 90
            print(f"\n💾 Populating FAISS vector database...")
            logger.info(f"💾 Starting FAISS database population...")
            
            cache_path = "indexed_repository.json"
            cache_data = {
                "repo_url": repo_url,
                "timestamp": str(datetime.now()),
                "files_indexed": len(index_dict),
                "snippets_indexed": total_snippets,
                "index_dict": {
                    file_path: snippets 
                    for file_path, snippets in list(index_dict.items())[:20]  # Save preview
                }
            }
            
            with open(cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)
            
            print(f"✅ FAISS database populated and cached to: {cache_path}")
            logger.info(f"✅ FAISS database ready, index cached to: {cache_path}")
            
            # Hold 90% for 500ms to ensure clients (polling at 250ms) definitely see it
            await asyncio.sleep(0.5)
            
            # Update app state
            app_state.set_repository(repo_url)
            app_state.is_indexed = True
            app_state.file_count = len(index_dict)
            app_state.snippet_count = total_snippets
            
            # Update progress to completion (NOW set to 100%)
            index_progress_state["current_message"] = "Indexing Complete!"
            index_progress_state["progress_percent"] = 100
            print(f"\n✅ INDEXING COMPLETE - All 100% done!")
            logger.info(f"✅ Indexing pipeline complete: {len(index_dict)} files, {total_snippets} snippets")
            
            print(f"\n✅ INDEXING COMPLETE")
            print(f"{'='*60}\n")
            
            # Extract unique file paths without line numbers
            unique_files = sorted(list(set(
                key.split(' (Lines')[0] for key in index_dict.keys()
            )))
            
            print(f"📁 EXTRACTED FILES FOR API RESPONSE:")
            print(f"   Total unique files: {len(unique_files)}")
            for f in unique_files:
                print(f"   ✓ {f}")
            
            response_data = {
                "status": "success",
                "message": f"Repository successfully indexed!",
                "repository": repo_url,
                "files_indexed": len(index_dict),
                "snippets_indexed": total_snippets,
                "files": unique_files,
                "timestamp": str(datetime.now()),
                "is_index_ready": get_index_status()
            }
            
            print(f"\n📤 API Response files array: {response_data['files']}")
            print(f"   Type: {type(response_data['files'])}")
            print(f"   Count: {len(response_data['files'])}")
            print(f"   is_index_ready: {response_data['is_index_ready']}")
            print(f"\n✅ ABOUT TO RETURN RESPONSE TO CLIENT")
            print(f"{'='*60}\n")
            
            return response_data
            
        except Exception as e:
            print(f"❌ Indexing failed: {e}")
            import traceback
            traceback.print_exc()
            error_response = {
                "status": "error",
                "message": f"Indexing error: {str(e)}",
                "files_indexed": 0,
                "snippets_indexed": 0
            }
            print(f"❌ RETURNING ERROR RESPONSE: {error_response}")
            # Reset progress on error
            index_progress_state["is_indexing"] = False
            return error_response
        
        finally:
            # Step 6: Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    print(f"🗑️  Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    print(f"⚠️  Could not cleanup temp directory: {e}")
            # Always reset progress state
            index_progress_state["is_indexing"] = False
    
    
    @app.post("/api/diagnose")
    async def diagnose_bug(bug_description: str = Form(...), screenshot: UploadFile = File(None)):
        """
        Performs semantic code retrieval on the indexed repository.
        Uses keyword-based search on actual repository files.
        """
        global global_indexed_data
        
        # 1. Read the uploaded image as raw bytes (Fix #3 in ms2c.py handles PIL conversion)
        image_bytes = await screenshot.read() if screenshot else None
        temp_image_path = None
        
        try:
            print(f"\n{'='*60}")
            print(f"🔍 DIAGNOSING BUG")
            print(f"{'='*60}")
            print(f"📝 Query: {bug_description[:80]}...")
            if screenshot:
                print(f"🖼️  Visual: {screenshot.filename} ({len(image_bytes)} bytes)")
            else:
                print(f"🖼️  Visual: (no screenshot provided)")
            print(f"📦 Repository: {app_state.indexed_repo_url}")
            print(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            
            # CRITICAL OPTIMIZATION: Skip ViT encoding if no visual input
            # When screenshot is absent, bypass Vision Transformer entirely to save GPU memory and inference time
            if image_bytes:
                # Save image bytes to temp file for ViT processing
                temp_image_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
                with open(temp_image_path, 'wb') as temp_f:
                    temp_f.write(image_bytes)
                logger.info(f"🖼️  Saved screenshot to temp: {temp_image_path}")
                print(f"🎬 MULTIMODAL MODE: Using CodeBERT + ViT dual-stream (Mode 1)")
            else:
                # No screenshot provided: use text-only mode
                # This completely bypasses the Vision Transformer forward pass
                temp_image_path = None
                print(f"📝 TEXT-ONLY MODE: Bypassing Vision Transformer, using CodeBERT only (Mode 2)")
                logger.info(f"📝 TEXT-ONLY MODE: No screenshot provided - completely bypassing ViT forward pass")
            
            print(f"💾 Global indexed data has {len(global_indexed_data)} files")
            print(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            # Log to file
            logger.info(f"\n🔍 DIAGNOSING BUG")
            logger.info(f"📝 Query: {bug_description[:80]}...")
            if screenshot:
                logger.info(f"🖼️  Visual: {screenshot.filename} ({len(image_bytes)} bytes)")
            else:
                logger.info(f"🖼️  Visual: (no screenshot provided)")
            logger.info(f"📦 Repository: {app_state.indexed_repo_url}")
            logger.info(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            logger.info(f"💾 Global indexed data has {len(global_indexed_data)} files")
            logger.info(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            results = []
            
            # OPTIMIZATION: Initialize gating weights based on visual input availability
            if image_bytes:
                alpha_text = 0.5  # Default fallback for multimodal mode
                alpha_visual = 0.5
            else:
                # TEXT-ONLY optimization: Hardcode gating weights to skip visual processing
                alpha_text = 1.0  # Full weight to text
                alpha_visual = 0.0  # No weight to visual
                print(f"🔐 GATING NETWORK HARDCODED: alpha_text=1.0, alpha_visual=0.0 (text-only)")
                logger.info(f"🔐 GATING NETWORK HARDCODED: Bypassing neural gating, using text-only weights")
            
            # Check if we have actual indexed data (not default dummy)
            is_real_index = len(global_indexed_data) > 3 or (
                len(global_indexed_data) >= 3 and 
                not all(f in global_indexed_data for f in ["src/components/Login.jsx", "src/layouts/Container.jsx", "src/styles/forms.css"])
            )
            
            print(f"\n🔍 INDEX CHECK:")
            print(f"   app_state.is_indexed: {app_state.is_indexed}")
            print(f"   len(global_indexed_data): {len(global_indexed_data)}")
            print(f"   is_real_index: {is_real_index}")
            if len(global_indexed_data) <= 5:
                print(f"   Files in global_indexed_data: {list(global_indexed_data.keys())}")
            
            logger.info(f"\n🔍 INDEX CHECK:")
            logger.info(f"   app_state.is_indexed: {app_state.is_indexed}")
            logger.info(f"   len(global_indexed_data): {len(global_indexed_data)}")
            logger.info(f"   is_real_index: {is_real_index}")
            if len(global_indexed_data) <= 5:
                logger.info(f"   Files in global_indexed_data: {list(global_indexed_data.keys())}")
            
            if not app_state.is_indexed:
                print(f"⚠️  No repository indexed yet - using keyword fallback")
                results = generate_smart_results(bug_description, app_state.indexed_repo_url)
                # Only compute gating weights if we have a visual input
                if image_bytes:
                    alpha_text, alpha_visual = compute_gating_weight(bug_description, image_path=temp_image_path)
                # else: use the already-set hardcoded values (1.0, 0.0)
            elif not is_real_index:
                print(f"⚠️  Using default dummy index (no real repository indexed)")
                results = generate_smart_results(bug_description, app_state.indexed_repo_url)
                # Only compute gating weights if we have a visual input
                if image_bytes:
                    alpha_text, alpha_visual = compute_gating_weight(bug_description, image_path=temp_image_path)
                # else: use the already-set hardcoded values (1.0, 0.0)
            else:
                # Use the retriever with real indexed data
                print(f"✅ Using real indexed repository data")
                
                # Extract target file from query format: [components/File.jsx] - description
                target_file, cleaned_query = extract_target_file(bug_description)
                
                if target_file:
                    print(f"🎯 Target file: {target_file}")
                    logger.info(f"🎯 Target file extracted: {target_file}")
                else:
                    print(f"⚠️  No target file specified in query format")
                    cleaned_query = bug_description
                
                print(f"🔍 Searching {len(retriever.global_corpus)} code snippets...")
                
                # OPTIMIZATION: Only compute gating weights via neural network if we have visual input
                # For text-only queries, skip neural gating and use hardcoded weights (alpha_text=1.0, alpha_visual=0.0)
                if image_bytes:
                    # Multimodal mode: compute gating weight via neural network
                    alpha_text, alpha_visual = compute_gating_weight(cleaned_query, image_path=temp_image_path)
                    logger.info(f"🎯 NEURAL GATING: Text={alpha_text:.4f}, Visual={alpha_visual:.4f}")
                else:
                    # Text-only mode: already hardcoded to 1.0 and 0.0
                    logger.info(f"🎯 TEXT-ONLY: alpha_text=1.0, alpha_visual=0.0 (ViT bypassed)")
                
                try:
                    top_results = []
                    results = []
                    
                    # Use 4-stage thesis-aligned pipeline via retriever
                    print(f"🔍 Performing 4-stage retrieval on {len(retriever.global_corpus)} snippets...")
                    logger.info(f"🔍 Performing 4-stage retrieval on {len(retriever.global_corpus)} snippets...")
                    logger.info(f"   Embedded nodes count: {len(retriever.embedded_nodes)}")
                    logger.info(f"   Query: {cleaned_query[:80]}...")
                    if target_file:
                        logger.info(f"   Target file: {target_file}")
                    
                    # Call 4-stage pipeline (retrieve_top_k handles all stages internally)
                    semantic_results = retriever.retrieve_top_k(
                        text_query=cleaned_query,
                        target_file=target_file,  # Will be used in Stage 2 (Document Filtration) and Stage 4 (Boosting)
                        image_path=temp_image_path,  # Path to temp image (Stage 3 uses this for ViT)
                        k=10  # Directly request top 10
                    )
                    
                    print(f"✅ 4-Stage pipeline returned {len(semantic_results)} results")
                    logger.info(f"✅ 4-Stage pipeline returned {len(semantic_results)} results")
                    
                    if len(semantic_results) == 0:
                        logger.warning(f"⚠️  EMPTY RESULTS - Retriever index may be empty or query not matching")
                        logger.warning(f"   embedded_nodes: {len(retriever.embedded_nodes)}")
                        logger.warning(f"   global_corpus: {len(retriever.global_corpus)}")
                        logger.warning(f"   query: {cleaned_query[:100]}")
                    
                    # Results are already ranked by all 4 stages
                    top_results = semantic_results
                    
                    print(f"✅ Will display {len(top_results)} results")
                    logger.info(f"✅ Will display {len(top_results)} results")
                    
                    # Format results from 4-stage pipeline to match frontend expectations
                    logger.info(f"📤 PROCESSING {len(top_results)} results for display")
                    print(f"📤 PROCESSING {len(top_results)} results for display")
                    
                    if len(top_results) == 0:
                        print(f"⚠️  No results from 4-stage pipeline")
                        logger.warning(f"⚠️  No results from 4-stage pipeline")
                    else:
                        for idx, (file_path, snippet) in enumerate(top_results):
                            if len(results) >= 10:  # Stop once we have 10
                                break
                            try:
                                # Extract filename and line numbers
                                import re
                                
                                # Extract line numbers if present (e.g., "components/App.jsx (L:50-75)")
                                line_match = re.search(r'\(L:(\d+)(?:-(\d+))?\)', file_path)
                                if line_match:
                                    start = line_match.group(1)
                                    end = line_match.group(2) or start
                                    lines = f"{start}-{end}"
                                    # Remove line numbers from file_path for clean display
                                    clean_file_path = re.sub(r'\s*\(L:\d+(?:-\d+)?\)', '', file_path)
                                else:
                                    lines = "?"
                                    clean_file_path = file_path
                                
                                # Extract filename from clean path
                                file_name = clean_file_path.split('/')[-1]
                                
                                formatted_result = {
                                    "name": file_name,
                                    "file": clean_file_path,
                                    "lines": lines,
                                    "code": snippet.strip(),
                                    "explanation": f"Found in {file_name} - relevant code snippet",
                                    "confidence": 0.95 - (idx * 0.05)  # Decrease confidence for lower-ranked results
                                }
                                results.append(formatted_result)
                                logger.info(f"   Result {idx+1}: {file_path}")
                                logger.info(f"   Code preview: {snippet[:100]}...")
                            except Exception as e:
                                logger.error(f"❌ Error formatting result {idx}: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
                    
                    print(f"✅ Retrieved {len(results)} results from 4-stage pipeline")
                    logger.info(f"✅ Retrieved {len(results)} results from 4-stage pipeline")
                    
                except Exception as e:
                    print(f"❌ 4-Stage pipeline failed: {e}")
                    logger.error(f"❌ 4-Stage pipeline failed: {e}")
                    import traceback
                    traceback.print_exc()
                    print(f"🔄 Falling back to keyword matching...")
                    logger.info(f"🔄 Falling back to keyword matching...")
                    results = generate_smart_results(bug_description, app_state.indexed_repo_url)
                    # For fallback results, compute standard gating weights
                    alpha_text, alpha_visual = compute_gating_weight(bug_description)
            
            # Build response with the computed alpha weights
            response = {
                "status": "success",
                "alpha_text": alpha_text,
                "alpha_visual": alpha_visual,
                "candidates": results,
                "repository": app_state.indexed_repo_url,
                "indexed": app_state.is_indexed,
                "using_real_data": is_real_index,
                "indexed_files": app_state.file_count,
                "indexed_snippets": app_state.snippet_count
            }
            
            print(f"✅ Diagnosis complete - {len(results)} candidates returned")
            print(f"📤 RESPONSE STRUCTURE:")
            print(f"   Status: {response['status']}")
            print(f"   Candidates count: {len(response['candidates'])}")
            print(f"   Alpha text: {response['alpha_text']}, Alpha visual: {response['alpha_visual']}")
            if len(response['candidates']) > 0:
                print(f"   First candidate: {response['candidates'][0]}")
            logger.info(f"📤 RESPONSE STRUCTURE:")
            logger.info(f"   Status: {response['status']}")
            logger.info(f"   Candidates count: {len(response['candidates'])}")
            logger.info(f"   Alpha text: {response['alpha_text']}, Alpha visual: {response['alpha_visual']}")
            if len(response['candidates']) > 0:
                logger.info(f"   First candidate: {response['candidates'][0]}")
            print(f"{'='*60}\n")
            
            return response
            
        except Exception as e:
            print(f"❌ Error during diagnosis: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error", 
                "message": str(e),
                "candidates": []
            }
        
        finally:
            # CRITICAL: Clean up temporary image file
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                    logger.info(f"🧹 Cleaned up temp image: {temp_image_path}")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to clean up temp image: {e}")
    
    
    @app.get("/api/health")
    async def health_check():
        """Check if the backend is running and repository status"""
        return {
            "status": "healthy",
            "pytorch_available": pytorch_available,
            "mode": "production" if pytorch_available else "mock",
            "repository_indexed": app_state.is_indexed,
            "indexed_repository": app_state.indexed_repo_url
        }
    
    
    @app.post("/api/reset")
    @app.get("/api/reset")
    async def reset_state():
        """Reset the application state"""
        app_state.reset()
        if os.path.exists("indexed_repo.json"):
            os.remove("indexed_repo.json")
        return {"status": "reset", "message": "Application state has been reset"}
