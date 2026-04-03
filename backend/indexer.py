import os
import re
import asyncio
from pathlib import Path

# Fallback imports assuming your config.py structure
try:
    from config import logger, ALLOWED_EXTENSIONS, SEARCH_DIRECTORIES, IGNORE_DIRECTORIES, IGNORE_FILES
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    ALLOWED_EXTENSIONS = {'.jsx', '.js', '.tsx', '.ts', '.html'}
    SEARCH_DIRECTORIES = ['src', 'components', 'pages', 'app', 'public']
    IGNORE_DIRECTORIES = {'node_modules', 'build', 'dist', '.git', '__pycache__'}
    IGNORE_FILES = {'package.json', 'package-lock.json'}

"""
=========================================================================================
Multimodal Semantic-to-Code (MS2C) - Live Indexer
=========================================================================================
CRITICAL PROTOTYPE FIXES INCLUDED:
1. Synchronous AST Parsing: extract_ast_nodes is strictly CPU-bound.
2. Async Threading: build_index_async prevents FastAPI Event Loop blocking.
3. Global State Lock: indexing_lock ensures searches wait until the index is ready.
4. VRAM Safety: Reduced batch size in reindex_retriever to prevent silent node dropping.
=========================================================================================
"""

# Global lock to prevent the API from processing searches while the index is building
indexing_lock = asyncio.Lock()
# Global flag to check if the retriever is fully loaded
is_index_ready = False


def get_index_status():
    """Returns the current index ready status."""
    return is_index_ready


def extract_ast_nodes(content: str, filepath: str) -> list:
    """
    CRITICAL FIX #4: Synchronous State-Machine Parser.
    This function iterates character-by-character. It is highly CPU-bound.
    Making this `async` in FastAPI causes race conditions and blocks I/O.
    It MUST remain a synchronous `def`.
    """
    parsed_nodes = []
    i = 0
    n = len(content)

    while i < n:
        if content[i] == '<':
            # Check if it's a valid opening tag, closing tag, or fragment
            if i + 1 < n and (content[i + 1].isalpha() or content[i + 1] in ['/', '>']):
                start = i
                in_quotes = None
                brace_depth = 0
                j = i + 1

                while j < n:
                    char = content[j]

                    # Handle string literals to ignore brackets inside them
                    if char in ["'", '"', '`']:
                        if in_quotes == char:
                            # Make sure it's not escaped
                            if content[j - 1] != '\\':
                                in_quotes = None
                        elif not in_quotes:
                            in_quotes = char
                            
                    # Handle JSX curly braces mapping (if not in quotes)
                    elif char == '{' and not in_quotes:
                        brace_depth += 1
                    elif char == '}' and not in_quotes:
                        brace_depth -= 1
                        
                    # Find the closing bracket of the tag
                    elif char == '>' and not in_quotes and brace_depth == 0:
                        snippet = content[start:j + 1].strip()
                        # Only add meaningful snippets, ignore pure closing tags or fragments
                        if len(snippet) > 3 and not snippet.startswith('</'):
                            # Basic line number calculation (can be optimized)
                            line_number = content.count('\n', 0, start) + 1
                            parsed_nodes.append({
                                "file_path": filepath,
                                "line_number": line_number,
                                "code_snippet": snippet
                            })
                        i = j
                        break
                    j += 1
        i += 1
        
    return parsed_nodes


def build_index_sync(repo_path: str) -> dict:
    """
    Synchronous directory traversal and AST extraction.
    This performs heavy file I/O and CPU-bound parsing.
    """
    index_dict = {}
    repo_root = Path(repo_path)
    
    if not repo_root.exists():
        logger.error(f"Repository path does not exist: {repo_path}")
        return index_dict

    logger.info(f"Starting synchronous file scan at: {repo_path}")

    for root, dirs, files in os.walk(repo_root):
        # Mutate dirs in-place to skip ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRECTORIES]
        
        # Optional: Only scan inside specific frontend folders if defined
        rel_path = Path(root).relative_to(repo_root).parts
        if SEARCH_DIRECTORIES and rel_path and rel_path[0] not in SEARCH_DIRECTORIES:
            continue

        for file in files:
            if file in IGNORE_FILES:
                continue
                
            filepath = Path(root) / file
            if filepath.suffix in ALLOWED_EXTENSIONS:
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    relative_filepath = str(filepath.relative_to(repo_root)).replace('\\', '/')
                    nodes = extract_ast_nodes(content, relative_filepath)
                    
                    if nodes:
                        index_dict[relative_filepath] = nodes
                        
                except Exception as e:
                    logger.warning(f"Failed to read/parse {filepath}: {e}")

    logger.info(f"✅ Scanning complete: {len(index_dict)} files indexed with AST nodes.")
    return index_dict


async def build_index_async(repo_path: str) -> dict:
    """
    CRITICAL FIX #4: Async Wrapper for Web API.
    Uses asyncio.to_thread() to offload the heavy CPU-bound state-machine parser
    to a background thread. This allows FastAPI to continue serving other network
    requests (like health checks or image uploads) while the codebase is indexed.
    """
    logger.info("Offloading AST parsing to background thread...")
    index_dict = await asyncio.to_thread(build_index_sync, repo_path)
    return index_dict


async def reindex_retriever(retriever, index_dict: dict):
    """
    CRITICAL FIX #5: Global Retriever State & VRAM Management.
    Updates the MS2C vectors globally. Uses an async lock so users cannot search 
    while the model is pushing batches to the GPU.
    """
    global is_index_ready
    
    # 1. Lock the global state so no searches happen during embedding
    async with indexing_lock:
        is_index_ready = False
        try:
            import torch
            # Clear CUDA cache before starting a massive embedding run
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            total_snippets = sum(len(snippets) for snippets in index_dict.values())
            logger.info(f"🔄 Re-indexing retriever with {len(index_dict)} files ({total_snippets} snippets)...")
            
            # 2. VRAM Safety: Reduce batch size.
            # You previously used 128 which caused OOM crashes and silent node dropping. 
            # A batch size of 32 or 64 is much safer for a live API processing CodeBERT vectors.
            SAFE_BATCH_SIZE = 64
            
            # Assuming your retriever has a synchronous _flatten_and_encode method.
            # If the CodeBERT encoding takes too long, we also offload it to a thread.
            await asyncio.to_thread(
                retriever._flatten_and_encode, 
                index_dict, 
                batch_size=SAFE_BATCH_SIZE
            )
            
            # 3. Mark the index as ready for API consumption
            is_index_ready = True
            logger.info(f"✅ Global Retriever re-indexed successfully. Ready for searches.")
            
        except Exception as e:
            is_index_ready = False
            logger.error(f"❌ Fatal error re-indexing retriever: {str(e)}")
            raise e

# Example usage in FastAPI main.py or routes.py during startup:
# @app.on_event("startup")
# async def startup_event():
#     index_data = await build_index_async("./my_frontend_repo")
#     await reindex_retriever(app.state.retriever, index_data)