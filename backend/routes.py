"""
API routes for the M-S2C Diagnostic Engine
"""

import os
import json
import shutil
import tempfile
from datetime import datetime
from fastapi import UploadFile, File, Form

from config import logger, app_state
from repository import clone_repository
from indexer import build_index_from_repo, reindex_retriever
from utils import compute_gating_weight, generate_smart_results


# Global data storage
global_indexed_data = {}


def setup_routes(app, retriever, pytorch_available):
    """
    Register all routes with the FastAPI app.
    
    Args:
        app: FastAPI application instance
        retriever: MS2CRetriever instance
        pytorch_available: Boolean indicating if PyTorch is available
    """
    
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
        
        temp_dir = None
        
        try:
            print(f"\n{'='*60}")
            print(f"📥 INDEXING REPOSITORY: {repo_url}")
            print(f"{'='*60}")
            
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix="ms2c_repo_")
            print(f"📁 Temp directory: {temp_dir}")
            
            # Step 1: Clone repository
            clone_success = clone_repository(repo_url, temp_dir)
            if not clone_success:
                return {
                    "status": "error",
                    "message": "Failed to clone repository. Check URL and Git installation.",
                    "files_indexed": 0,
                    "snippets_indexed": 0
                }
            
            # Step 2 & 3: Build index from cloned repo
            print("\n🔍 Extracting components and building index...")
            index_dict = build_index_from_repo(temp_dir)
            
            if not index_dict:
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
            global global_indexed_data
            global_indexed_data = index_dict
            print(f"\n🔄 Updating global index...")
            await reindex_retriever(retriever, index_dict, pytorch_available)
            
            # Step 5: Cache to disk
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
            
            print(f"✅ Index cached to: {cache_path}")
            
            # Update app state
            app_state.set_repository(repo_url)
            app_state.is_indexed = True
            app_state.file_count = len(index_dict)
            app_state.snippet_count = total_snippets
            
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
                "timestamp": str(datetime.now())
            }
            
            print(f"\n📤 API Response files array: {response_data['files']}")
            print(f"   Type: {type(response_data['files'])}")
            print(f"   Count: {len(response_data['files'])}")
            
            return response_data
            
        except Exception as e:
            print(f"❌ Indexing failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": f"Indexing error: {str(e)}",
                "files_indexed": 0,
                "snippets_indexed": 0
            }
        
        finally:
            # Step 6: Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    print(f"🗑️  Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    print(f"⚠️  Could not cleanup temp directory: {e}")
    
    
    @app.post("/api/diagnose")
    async def diagnose_bug(bug_description: str = Form(...), screenshot: UploadFile = File(...)):
        """
        Performs semantic code retrieval on the indexed repository.
        Uses keyword-based search on actual repository files.
        """
        global global_indexed_data
        
        # 1. Save the uploaded image temporarily
        temp_image_path = f"temp_{screenshot.filename}"
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(screenshot.file, buffer)
            
        try:
            print(f"\n{'='*60}")
            print(f"🔍 DIAGNOSING BUG")
            print(f"{'='*60}")
            print(f"📝 Query: {bug_description[:80]}...")
            print(f"🖼️  Visual: {screenshot.filename}")
            print(f"📦 Repository: {app_state.indexed_repo_url}")
            print(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            print(f"💾 Global indexed data has {len(global_indexed_data)} files")
            print(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            # Log to file
            logger.info(f"\n🔍 DIAGNOSING BUG")
            logger.info(f"📝 Query: {bug_description[:80]}...")
            logger.info(f"🖼️  Visual: {screenshot.filename}")
            logger.info(f"📦 Repository: {app_state.indexed_repo_url}")
            logger.info(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            logger.info(f"💾 Global indexed data has {len(global_indexed_data)} files")
            logger.info(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            results = []
            
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
            elif not is_real_index:
                print(f"⚠️  Using default dummy index (no real repository indexed)")
                results = generate_smart_results(bug_description, app_state.indexed_repo_url)
            else:
                # Use the retriever with real indexed data
                print(f"✅ Using real indexed repository data")
                print(f"🔍 Searching {len(retriever.global_corpus)} code snippets...")
                
                try:
                    top_results, alpha_val = retriever.retrieve_top_k(
                        text_query=bug_description,
                        image_path=temp_image_path if os.path.exists(temp_image_path) else None,
                        k=3,
                        mode="multimodal",
                        scope="file"
                    )
                    
                    # Format results from retriever in format frontend expects: [[filepath_with_lines, code], ...]
                    logger.info(f"📤 RETRIEVER RETURNED {len(top_results)} results")
                    for idx, (file_path, snippet) in enumerate(top_results):
                        # file_path already contains line numbers in format "path/file.jsx (Lines X-Y)"
                        formatted_result = [
                            file_path,  # First element: filepath with line numbers
                            snippet[:500].strip()  # Second element: code snippet
                        ]
                        results.append(formatted_result)
                        logger.info(f"   Result {idx+1}: {file_path}")
                        logger.info(f"   Code preview: {snippet[:100]}...")
                    
                    print(f"✅ Retrieved {len(results)} results from repository")
                    logger.info(f"✅ Retrieved {len(results)} results from repository")
                    
                except Exception as e:
                    print(f"❌ Search failed: {e}")
                    logger.error(f"❌ Search failed: {e}")
                    import traceback
                    traceback.print_exc()
                    print(f"🔄 Falling back to keyword matching...")
                    logger.info(f"🔄 Falling back to keyword matching...")
                    results = generate_smart_results(bug_description, app_state.indexed_repo_url)
            
            # Determine alpha weights based on description length and type
            alpha_text, alpha_visual = compute_gating_weight(bug_description)
            
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
            print(f"{'='*60}\n")
            
            # Clean up the temp image
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
            
            return response
            
        except Exception as e:
            print(f"❌ Error during diagnosis: {e}")
            import traceback
            traceback.print_exc()
            # Make sure we clean up the image even if the model crashes
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
            return {
                "status": "error", 
                "message": str(e),
                "candidates": []
            }
    
    
    @app.get("/api/health")
    async def health_check():
        """Check if the backend is running and repository status"""
        return {
            "status": "healthy",
            "pytorch_available": pytorch_available,
            "mode": "production" if pytorch_available else "mock",
            "repository_indexed": app_state.is_indexed,
            "indexed_repository": app_state.indexed_repo_url,
            "index_timestamp": str(app_state.index_timestamp) if app_state.index_timestamp else None
        }
    
    
    @app.post("/api/reset")
    @app.get("/api/reset")
    async def reset_state():
        """Reset the application state"""
        app_state.reset()
        if os.path.exists("indexed_repo.json"):
            os.remove("indexed_repo.json")
        return {"status": "reset", "message": "Application state has been reset"}
