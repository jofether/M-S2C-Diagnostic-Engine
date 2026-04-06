"""
API routes for the M-S2C Diagnostic Engine
"""

import os
import sys
import json
import shutil
import tempfile
import asyncio
import subprocess
from datetime import datetime
from fastapi import UploadFile, File, Form, WebSocket, WebSocketDisconnect

from config import logger, app_state
from repository import clone_repository
from indexer import build_index_sync, reindex_retriever, get_index_status, extract_nodes_from_file, extract_branch_from_url
from utils import compute_gating_weight, generate_smart_results
from input_quality import InputQualityAnalyzer


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
    
    # Initialize input quality analyzer (independent from retrieval pipeline)
    input_analyzer = InputQualityAnalyzer()
    
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
    
    @app.get("/api/retriever-debug")
    async def retriever_debug():
        """DEBUG ENDPOINT: Returns retriever state info"""
        return {
            "global_corpus_count": len(retriever.global_corpus) if retriever else 0,
            "embedded_nodes_count": len(retriever.embedded_nodes) if retriever else 0,
            "file_list_count": len(retriever.file_list) if retriever else 0,
            "file_to_node_indices_count": len(retriever.file_to_node_indices) if retriever else 0,
            "file_embeddings_exists": retriever.file_embeddings is not None if retriever else False,
            "file_embeddings_shape": str(retriever.file_embeddings.shape) if (retriever and retriever.file_embeddings is not None) else None,
            "sample_files": list(retriever.file_list)[:5] if retriever else [],
            "sample_file_to_node_keys": list(retriever.file_to_node_indices.keys())[:5] if retriever else []
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
        Performs indexing using the new validate.py workflow:
        1. Parses GitHub URL (handles branch: /tree/branch)
        2. Clones repository (or branch-specific version)
        3. Extracts JSX/TSX/JS/TS components using regex state-machine
        4. Saves to indexed_nodes/repo_name.json
        5. Initializes MS2CRetriever for frontend queries
        
        Returns:
            JSON response with indexing statistics
        """
        
        global index_progress_state, global_indexed_data
        
        index_progress_state["is_indexing"] = True
        index_progress_state["current_message"] = "Initializing repository clone..."
        index_progress_state["progress_percent"] = 0
        
        try:
            print(f"\n{'='*60}")
            print(f"📥 MS2C INDEXING: {repo_url}")
            print(f"{'='*60}")
            
            # Parse repository URL and extract branch if present
            repo_url_clean, branch_name = extract_branch_from_url(repo_url)
            repo_name = repo_url_clean.split("/")[-1].replace(".git", "")
            display_name = f"{repo_name} (branch: {branch_name})" if branch_name else repo_name
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            repos_dir = os.path.join(current_dir, "cloned_repos")
            results_dir = os.path.join(current_dir, "indexed_nodes")
            os.makedirs(repos_dir, exist_ok=True)
            os.makedirs(results_dir, exist_ok=True)
            
            # Determine repository path (include branch in folder name)
            if branch_name:
                repo_path = os.path.join(repos_dir, f"{repo_name}_{branch_name}")
            else:
                repo_path = os.path.join(repos_dir, repo_name)
            
            # Clone repository
            index_progress_state["current_message"] = f"Cloning {display_name}..."
            index_progress_state["progress_percent"] = 10
            
            if not os.path.exists(repo_path):
                print(f"📥 Cloning: {display_name}")
                try:
                    if branch_name:
                        subprocess.run(
                            ["git", "clone", "-b", branch_name, "--single-branch", repo_url_clean, repo_path],
                            check=True,
                            capture_output=True
                        )
                    else:
                        subprocess.run(
                            ["git", "clone", repo_url_clean, repo_path],
                            check=True,
                            capture_output=True
                        )
                    print(f"✅ Repository cloned successfully")
                except subprocess.CalledProcessError as e:
                    print(f"❌ Clone failed: {e}")
                    index_progress_state["is_indexing"] = False
                    return {
                        "status": "error",
                        "message": f"Failed to clone repository: {str(e)}",
                        "files_indexed": 0,
                        "snippets_indexed": 0
                    }
            else:
                print(f"✅ Repository already exists, skipping clone")
            
            # Extract AST nodes from repository
            index_progress_state["current_message"] = "Parsing ASTs with Regex State Machine..."
            index_progress_state["progress_percent"] = 40
            
            print(f"🔍 Extracting components from: {repo_path}")
            repo_index = {}
            total_nodes = 0
            
            for root, dirs, files in os.walk(repo_path):
                # Filter out heavy folders
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'dist', 'build', 'coverage']]
                
                for file in files:
                    if file.endswith((".jsx", ".js", ".tsx", ".ts")):
                        full_filepath = os.path.join(root, file)
                        relative_path = os.path.relpath(full_filepath, repo_path).replace("\\", "/")
                        
                        nodes = extract_nodes_from_file(full_filepath)
                        if nodes:
                            repo_index[relative_path] = nodes
                            total_nodes += len(nodes)
            
            if not repo_index:
                index_progress_state["is_indexing"] = False
                return {
                    "status": "warning",
                    "message": "Repository cloned but no frontend files (.jsx, .js, .tsx, .ts) found.",
                    "files_indexed": 0,
                    "snippets_indexed": 0
                }
            
            print(f"✅ Extracted {total_nodes} nodes from {len(repo_index)} files")
            
            # Save index to disk
            index_progress_state["current_message"] = "Saving index to disk..."
            index_progress_state["progress_percent"] = 60
            
            output_path = os.path.join(results_dir, f"{repo_name}.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(repo_index, f, indent=4)
            
            print(f"💾 Index saved to: {output_path}")
            
            # Initialize MS2CRetriever for this repository
            index_progress_state["current_message"] = "Generating CodeBERT Embeddings..."
            index_progress_state["progress_percent"] = 80
            
            print(f"🧠 Initializing MS2CRetriever...")
            from ms2c import MS2CRetriever
            model_weights = os.path.join(current_dir, "ms2c_E2E_JOINT_BEST.pt")
            retriever_instance = MS2CRetriever(model_weights, repo_index, repos_dir=repos_dir)
            
            print(f"✅ MS2CRetriever ready with {len(retriever_instance.global_corpus)} code snippets")
            
            # Update global state
            global_indexed_data = repo_index
            app_state.set_repository(repo_url)
            app_state.is_indexed = True
            app_state.file_count = len(repo_index)
            app_state.snippet_count = total_nodes
            
            # Complete
            index_progress_state["current_message"] = "Indexing Complete!"
            index_progress_state["progress_percent"] = 100
            index_progress_state["is_indexing"] = False
            
            print(f"\n✅ INDEXING COMPLETE")
            print(f"{'='*60}\n")
            
            # Extract unique file paths
            unique_files = sorted(list(repo_index.keys()))
            
            return {
                "status": "success",
                "message": f"Repository successfully indexed!",
                "repository": display_name,
                "files_indexed": len(repo_index),
                "snippets_indexed": total_nodes,
                "files": unique_files,
                "timestamp": str(datetime.now()),
                "is_index_ready": True
            }
            
        except Exception as e:
            print(f"❌ Indexing failed: {e}")
            import traceback
            traceback.print_exc()
            index_progress_state["is_indexing"] = False
            logger.error(f"❌ Indexing error: {e}\n{traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Indexing failed: {str(e)}",
                "files_indexed": 0,
                "snippets_indexed": 0
            }
        
        finally:
            # Ensure progress state is reset
            await asyncio.sleep(0.1)  # Brief pause before next operation
    
    
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
        input_quality_analysis = None
        
        try:
            # ======================== INPUT QUALITY ANALYSIS ========================
            # Analyze user input INDEPENDENTLY from retrieval pipeline
            screenshot_path_for_analysis = None
            if image_bytes:
                # Save temporarily for quality analysis
                temp_analysis_image = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                temp_analysis_image.write(image_bytes)
                temp_analysis_image.close()
                screenshot_path_for_analysis = temp_analysis_image.name
            
            input_quality_analysis = input_analyzer.analyze_combined_input(
                description=bug_description,
                screenshot_path=screenshot_path_for_analysis
            )
            input_analyzer.log_analysis(input_quality_analysis)
            
            # Clean up temporary analysis file if created
            if screenshot_path_for_analysis and os.path.exists(screenshot_path_for_analysis):
                try:
                    os.unlink(screenshot_path_for_analysis)
                except:
                    pass
            
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
                    logger.info(f"   File list count: {len(retriever.file_list)}")
                    logger.info(f"   file_to_node_indices keys: {len(retriever.file_to_node_indices)}")
                    logger.info(f"   Query: {cleaned_query[:80]}...")
                    if target_file:
                        logger.info(f"   Target file: {target_file}")
                        logger.info(f"   Looking for target file in: {list(retriever.file_to_node_indices.keys())[:5]}...")
                    
                    # DEBUG: Check if file embeddings exist
                    if retriever.file_embeddings is not None:
                        logger.info(f"   File embeddings shape: {retriever.file_embeddings.shape}")
                    else:
                        logger.warning(f"   File embeddings is NONE - Phase 2 will skip semantic filtering!")
                    
                    # Call 4-stage pipeline (retrieve_top_k handles all stages internally)
                    # Returns: (results_list, alpha_text, alpha_visual)
                    semantic_results, alpha_text, alpha_visual = retriever.retrieve_top_k(
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
                        logger.warning(f"   file_list: {len(retriever.file_list)}")
                        logger.warning(f"   file_to_node_indices: {len(retriever.file_to_node_indices)}")
                        logger.warning(f"   query: {cleaned_query[:100]}")
                        if target_file:
                            matching_files = [f for f in retriever.file_list if target_file in f]
                            logger.warning(f"   matching target files: {matching_files}")
                    
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
                        for idx, (file_path, snippet, actual_score) in enumerate(top_results):
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
                                    "confidence": round(float(actual_score), 4)  # Real mathematical score from 4-stage pipeline
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
                "indexed_snippets": app_state.snippet_count,
                "input_quality": input_quality_analysis  # Separate from retrieval pipeline
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
    
    
    @app.post("/api/ms2c-search")
    async def ms2c_search(repo_url: str = Form(...), bug_description: str = Form(...), 
                          screenshot: UploadFile = File(None), target_file: str = Form(None)):
        """
        MS2C Unified Search Endpoint - Uses validate.py workflow
        
        This is the primary search endpoint that:
        1. Extracts branch from GitHub URL (if provided in /tree/ format)
        2. Loads the indexed JSON from indexed_nodes/
        3. Initializes MS2CRetriever with the loaded index
        4. Executes 4-stage retrieval pipeline
        5. Returns top 10 results with confidence scores
        
        Args:
            repo_url: GitHub repository URL (can include branch: https://github.com/user/repo/tree/branch)
            bug_description: User's bug description or search query
            screenshot: Optional screenshot image for multimodal search
            target_file: Optional target file to scope search to
        
        Returns:
            JSON with 10 search results and gating weights
        """
        from ms2c import MS2CRetriever
        import re
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Extract branch from URL if present
        def extract_branch_from_url(url):
            if '/tree/' in url:
                parts = url.split('/tree/')
                base_url = parts[0]
                branch_name = parts[1].strip().replace('.git', '')
                return base_url, branch_name
            return url, None
        
        try:
            print(f"\n{'='*60}")
            print(f"🔍 MS2C SEARCH ENDPOINT")
            print(f"{'='*60}")
            print(f"📝 Query: {bug_description[:80]}...")
            print(f"📦 Repository: {repo_url}")
            if screenshot:
                print(f"🖼️  Screenshot: {screenshot.filename}")
            if target_file:
                print(f"🎯 Target file: {target_file}")
            
            # 1. Parse repository URL
            repo_url_clean, branch_name = extract_branch_from_url(repo_url)
            repo_name = repo_url_clean.split("/")[-1].replace(".git", "")
            
            # 2. Load indexed repository
            index_dir = os.path.join(current_dir, "indexed_nodes")
            index_path = os.path.join(index_dir, f"{repo_name}.json")
            
            print(f"\n🔍 INDEX LOOKUP:")
            print(f"   Repo URL: {repo_url}")
            print(f"   Cleaned URL: {repo_url_clean}")
            print(f"   Repo name extracted: {repo_name}")
            print(f"   Looking for: {index_path}")
            
            # List what's available in indexed_nodes
            if os.path.exists(index_dir):
                available_indexes = os.listdir(index_dir)
                print(f"   Available indexes: {available_indexes}")
            else:
                print(f"   indexed_nodes directory doesn't exist yet!")
            
            if not os.path.exists(index_path):
                print(f"❌ Index not found: {index_path}")
                logger.error(f"❌ Index not found for {repo_name}")
                return {
                    "status": "error",
                    "message": f"Repository '{repo_name}' not indexed. Please index it first. Available indexes: {os.listdir(index_dir) if os.path.exists(index_dir) else 'none'}",
                    "results": [],
                    "alpha_text": 0.5,
                    "alpha_visual": 0.5
                }
            
            # 3. Load index and initialize retriever
            print(f"✅ Loading index from: {index_path}")
            with open(index_path, 'r', encoding='utf-8') as f:
                repo_index = json.load(f)
            
            print(f"\n📊 INDEX LOADED:")
            print(f"   Total files in index: {len(repo_index)}")
            total_nodes = sum(len(nodes) for nodes in repo_index.values())
            print(f"   Total nodes: {total_nodes}")
            if len(repo_index) <= 5:
                for file_path, nodes in repo_index.items():
                    print(f"     {file_path}: {len(nodes)} nodes")
            
            if not repo_index:
                print(f"❌ Index is empty!")
                return {
                    "status": "error",
                    "message": "Index loaded but is empty. Try indexing again.",
                    "results": [],
                    "alpha_text": 0.5,
                    "alpha_visual": 0.5
                }
            
            # Directory structure: cloned_repos/Apex_buggy/
            repos_root = os.path.join(current_dir, "cloned_repos")
            model_weights = os.path.join(current_dir, "ms2c_E2E_JOINT_BEST.pt")
            
            print(f"🧠 Initializing MS2CRetriever with {len(repo_index)} files ({total_nodes} total nodes)...")
            retriever = MS2CRetriever(model_weights, repo_index, repos_dir=repos_root)
            
            print(f"\n✅ MS2CRetriever initialized:")
            print(f"   global_corpus length: {len(retriever.global_corpus)}")
            print(f"   global_embeddings: {retriever.global_embeddings is not None}")
            if retriever.global_embeddings is not None:
                print(f"   global_embeddings shape: {retriever.global_embeddings.shape}")
            print(f"   unique_files: {len(retriever.unique_files)}")
            
            if len(retriever.global_corpus) == 0:
                print(f"❌ ERROR: Retriever corpus is empty after initialization!")
                return {
                    "status": "error",
                    "message": "Retriever corpus is empty. Check index format.",
                    "results": [],
                    "alpha_text": 0.5,
                    "alpha_visual": 0.5
                }
            
            # 4. Handle screenshot if provided
            temp_image_path = None
            if screenshot:
                image_bytes = await screenshot.read()
                temp_image_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
                with open(temp_image_path, 'wb') as f:
                    f.write(image_bytes)
                print(f"💾 Saved screenshot to: {temp_image_path}")
                mode = "multimodal"
            else:
                mode = "unimodal"
                print(f"📝 Running in TEXT-ONLY mode")
            
            # 5. Execute MS2C retrieval pipeline
            print(f"🔍 Running 4-stage retrieval pipeline...")
            print(f"   Query: {bug_description[:80]}...")
            print(f"   Corpus size: {len(retriever.global_corpus)}")
            
            try:
                results, alpha_val = retriever.retrieve_top_k(
                    text_query=bug_description,
                    target_key=target_file,
                    image_path=temp_image_path,
                    k=10,
                    mode=mode,
                    scope="repository"
                )
                
                # ms2c.py returns (results, alpha_val) where alpha_val is 0.0-1.0
                alpha_text = alpha_val
                alpha_visual = 1.0 - alpha_val
                
                print(f"✅ retrieve_top_k returned {len(results)} results")
                print(f"   Alpha value: {alpha_val:.4f}")
                
                if len(results) == 0:
                    print(f"   ⚠️  EMPTY RESULTS - Pipeline filtering excluded everything")
                    print(f"   This likely means the document filtration step (Stage 2) rejected all items")
                    
            except Exception as e:
                print(f"❌ retrieve_top_k error: {e}")
                import traceback
                print(traceback.format_exc())
                logger.error(f"❌ Retrieval failed: {e}\n{traceback.format_exc()}")
                return {
                    "status": "error",
                    "message": f"Retrieval pipeline error: {str(e)[:100]}",
                    "results": [],
                    "alpha_text": 0.5,
                    "alpha_visual": 0.5
                }
            
            # 6. Format results for frontend
            formatted_results = []
            print(f"\n📋 FORMATTING RESULTS:")
            print(f"   Total results from pipeline: {len(results)}")
            print(f"   Result type: {type(results)}")
            if len(results) > 0:
                print(f"   First result type: {type(results[0])}")
                if isinstance(results[0], (tuple, list)) and len(results[0]) > 0:
                    print(f"   First result length: {len(results[0])}")
                    print(f"   First result sample: {str(results[0])[:100]}...")
            
            for idx, result in enumerate(results):
                try:
                    # Results format depends on retrieve_top_k return structure
                    # Typically: (file_path, code_snippet) or (file_path, code_snippet, score)
                    if isinstance(result, dict):
                        # If it's already a dict, use as-is
                        formatted_results.append(result)
                        continue
                    
                    if isinstance(result, tuple):
                        if len(result) == 3:
                            file_path, code_snippet, score = result
                        elif len(result) == 2:
                            file_path, code_snippet = result
                            score = 0.85 - (idx * 0.05)  # Fallback scoring
                        else:
                            print(f"   ⚠️  Unexpected tuple length: {len(result)}")
                            continue
                    else:
                        print(f"   ⚠️  Unexpected result type: {type(result)}")
                        continue
                    
                    # Extract line numbers if present
                    line_match = re.search(r'\(L:(\d+)(?:-(\d+))?\)', file_path)
                    if line_match:
                        start = line_match.group(1)
                        end = line_match.group(2) or start
                        lines = f"{start}-{end}"
                        clean_file_path = re.sub(r'\s*\(L:\d+(?:-\d+)?\)', '', file_path)
                    else:
                        lines = "?"
                        clean_file_path = file_path
                    
                    file_name = clean_file_path.split('/')[-1]
                    
                    formatted_results.append({
                        "rank": idx + 1,
                        "name": file_name,
                        "file": clean_file_path,
                        "lines": lines,
                        "code": code_snippet.strip() if isinstance(code_snippet, str) else str(code_snippet),
                        "confidence": round(float(score), 4) if isinstance(score, (int, float)) else 0.5,
                        "explanation": f"Found in {file_name} - relevant code snippet"
                    })
                    
                except Exception as e:
                    logger.error(f"❌ Error formatting result {idx}: {e}")
                    continue
            
            # Clean up temp image if created
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.unlink(temp_image_path)
                except:
                    pass
            
            print(f"📤 Returning {len(formatted_results)} formatted results to frontend")
            logger.info(f"✅ MS2C search completed: {len(formatted_results)} results")
            
            return {
                "status": "success",
                "results": formatted_results,
                "alpha_text": float(alpha_text),
                "alpha_visual": float(alpha_visual),
                "repository": repo_name,
                "branch": branch_name or "default",
                "query": bug_description,
                "result_count": len(formatted_results)
            }
            
        except Exception as e:
            logger.error(f"❌ MS2C search failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"Search failed: {str(e)}",
                "results": [],
                "alpha_text": 0.5,
                "alpha_visual": 0.5
            }
    
    
    @app.post("/api/reset")
    @app.get("/api/reset")
    async def reset_state():
        """Reset the application state"""
        app_state.reset()
        if os.path.exists("indexed_repo.json"):
            os.remove("indexed_repo.json")
        return {"status": "reset", "message": "Application state has been reset"}
