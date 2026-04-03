"""
API routes for the M-S2C Diagnostic Engine
"""

import os
import sys
import json
import shutil
import tempfile
from datetime import datetime
from fastapi import UploadFile, File, Form

from config import logger, app_state
from repository import clone_repository
from indexer import build_index_from_repo, reindex_retriever, get_index_status
from utils import compute_gating_weight, generate_smart_results


# Global data storage
global_indexed_data = {}


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
            return error_response
        
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
        
        # 1. Read the uploaded image as raw bytes (Fix #3 in ms2c.py handles PIL conversion)
        image_bytes = await screenshot.read()
            
        try:
            print(f"\n{'='*60}")
            print(f"🔍 DIAGNOSING BUG")
            print(f"{'='*60}")
            print(f"📝 Query: {bug_description[:80]}...")
            print(f"🖼️  Visual: {screenshot.filename} ({len(image_bytes)} bytes)")
            print(f"📦 Repository: {app_state.indexed_repo_url}")
            print(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            print(f"💾 Global indexed data has {len(global_indexed_data)} files")
            print(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            # Log to file
            logger.info(f"\n🔍 DIAGNOSING BUG")
            logger.info(f"📝 Query: {bug_description[:80]}...")
            logger.info(f"🖼️  Visual: {screenshot.filename} ({len(image_bytes)} bytes)")
            logger.info(f"📦 Repository: {app_state.indexed_repo_url}")
            logger.info(f"📊 Indexed: {app_state.file_count} files, {app_state.snippet_count} snippets")
            logger.info(f"💾 Global indexed data has {len(global_indexed_data)} files")
            logger.info(f"🧠 Retriever has {len(retriever.unique_files)} files")
            
            results = []
            alpha_text = 0.5  # Default fallback
            alpha_visual = 0.5
            
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
                alpha_text, alpha_visual = compute_gating_weight(bug_description, image_path=image_bytes)
            elif not is_real_index:
                print(f"⚠️  Using default dummy index (no real repository indexed)")
                results = generate_smart_results(bug_description, app_state.indexed_repo_url)
                alpha_text, alpha_visual = compute_gating_weight(bug_description, image_path=image_bytes)
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
                
                # Compute MULTIMODAL gating weight (text + visual)
                alpha_text, alpha_visual = compute_gating_weight(cleaned_query, image_path=temp_image_path)
                logger.info(f"🎯 MULTIMODAL Gating Weights: Text={alpha_text:.4f}, Visual={alpha_visual:.4f}")
                
                try:
                    top_results = []
                    results = []
                    
                    # Use semantic search via retriever to get ranked results
                    print(f"🔍 Performing semantic search on {len(retriever.global_corpus)} snippets...")
                    logger.info(f"🔍 Performing semantic search on {len(retriever.global_corpus)} snippets...")
                    
                    semantic_results, alpha_val = retriever.retrieve_top_k(
                        text_query=cleaned_query,
                        target_key=None,
                        image_path=image_bytes,  # Pass raw bytes directly (Fix #3 in ms2c.py handles PIL conversion)
                        k=300,  # Get many results
                        mode="multimodal",
                        scope="file"
                    )
                    
                    # If target file is specified, prioritize results from that file
                    if target_file:
                        print(f"🎯 Target file specified: {target_file}")
                        logger.info(f"🎯 Target file specified: {target_file}")
                        
                        # Split semantic results into target and non-target
                        target_results = [r for r in semantic_results if target_file in r[0]]
                        other_results = [r for r in semantic_results if target_file not in r[0]]
                        
                        print(f"📊 Semantic search returned {len(target_results)} from target file, {len(other_results)} from others")
                        logger.info(f"📊 Semantic search returned {len(target_results)} from target file, {len(other_results)} from others")
                        
                        # Combine: prioritize target file results, then fill with others
                        combined = target_results[:10]
                        if len(combined) < 10:
                            combined.extend(other_results[:10 - len(combined)])
                        
                        top_results = combined
                    else:
                        # No target file - just use top semantic results
                        top_results = semantic_results[:10]
                    
                    print(f"✅ Will display {len(top_results)} results")
                    logger.info(f"✅ Will display {len(top_results)} results")
                    
                    # Format results from indexed data to match frontend expectations
                    logger.info(f"📤 PROCESSING {len(top_results)} results for display")
                    print(f"📤 PROCESSING {len(top_results)} results for display")
                    
                    if len(top_results) == 0:
                        print(f"⚠️  No results from semantic search, attempting fallback...")
                        logger.warning(f"⚠️  No results from semantic search, attempting fallback...")
                        results = generate_smart_results(cleaned_query, app_state.indexed_repo_url)
                    else:
                        for idx, item in enumerate(top_results):
                            if len(results) >= 10:  # Stop once we have 10
                                break
                            try:
                                # Unpack tuple (file_path, snippet)
                                if isinstance(item, tuple) and len(item) >= 2:
                                    file_path, snippet = item[0], item[1]
                                else:
                                    logger.warning(f"⚠️  Unexpected result format at index {idx}: {type(item)}")
                                    continue
                                
                                # Extract filename and line numbers from file_path like "path/file.jsx (Lines X-Y)"
                                import re
                                line_match = re.search(r'\(Lines\s+(\d+)-(\d+)\)', file_path)
                                lines = f"{line_match.group(1)}-{line_match.group(2)}" if line_match else "?"
                                
                                # Extract just the filename
                                file_name = file_path.split('/')[-1].split(' ')[0]
                                
                                formatted_result = {
                                    "name": file_name,
                                    "file": file_path,
                                    "lines": lines,
                                    "code": snippet[:500].strip(),
                                    "explanation": f"Found in {file_name} - relevant code snippet",
                                    "confidence": 0.85 + (idx * 0.05)  # Decrease confidence for lower-ranked results
                                }
                                results.append(formatted_result)
                                logger.info(f"   Result {idx+1}: {file_path}")
                                logger.info(f"   Code preview: {snippet[:100]}...")
                            except Exception as e:
                                logger.error(f"❌ Error formatting result {idx}: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
                    
                    print(f"✅ Retrieved {len(results)} results from repository")
                    logger.info(f"✅ Retrieved {len(results)} results from repository")
                    
                    # ENSURE TOP 10: If we have fewer than 10 results, supplement with smart results
                    if len(results) < 10:
                        print(f"⚠️  Only {len(results)} results from semantic search, supplementing with keyword-based results...")
                        logger.info(f"⚠️  Only {len(results)} results from semantic search, supplementing with keyword-based results...")
                        smart_results = generate_smart_results(cleaned_query, app_state.indexed_repo_url)
                        
                        # Filter out duplicates and add to reach 10
                        existing_files = {r["file"] for r in results}
                        results_needed = 10 - len(results)
                        
                        for smart_result in smart_results:
                            if len(results) >= 10:
                                break
                            if smart_result["file"] not in existing_files:
                                results.append(smart_result)
                                existing_files.add(smart_result["file"])
                        
                        print(f"✅ Supplemented to {len(results)} total results")
                        logger.info(f"✅ Supplemented to {len(results)} total results")
                    
                except Exception as e:
                    print(f"❌ Search failed: {e}")
                    logger.error(f"❌ Search failed: {e}")
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
