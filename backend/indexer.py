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
Repository AST Indexer - Thesis-Aligned (Based on indexer_basis.py)
=========================================================================================
Scans repositories and extracts opening JSX/HTML tags with intelligent parsing.
Uses custom state-machine parser to handle JSX complexities.

THESIS IMPROVEMENTS:
- Maintains chronological order (no deduplication)
- Injects line number ranges: (L:x-y) or (L:x)
- Brace-aware look-ahead: Strips JS logic, extracts inner text
- Depth tracking with silent closing tag handling
- Fixes self-closing tags and trailing JS debris

Supports async/await for web API integration.
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
    Thesis-Aligned: Synchronous State-Machine Parser with Brace-Aware Look-ahead.
    
    CRITICAL IMPROVEMENTS:
    - Maintains chronological order (no deduplication)
    - Injects line number ranges: (L:x-y) for multi-line, (L:x) for single-line
    - Brace-aware look-ahead: Strips JS logic from inner text
    - Fixes self-closing tag handling
    - Fixes trailing JS debris in inner text
    
    This function is CPU-bound and MUST remain synchronous.
    """
    raw_tags = []
    i = 0
    n = len(content)

    while i < n:
        if content[i] == '<':
            if i + 1 < n and (content[i + 1].isalpha() or content[i + 1] in ['/', '>']):
                start = i
                in_quotes = None
                brace_depth = 0
                j = i + 1

                while j < n:
                    char = content[j]

                    if char in ["'", '"', '`']:
                        if in_quotes == char:
                            if j > 0 and content[j - 1] != '\\':
                                in_quotes = None
                        elif not in_quotes:
                            in_quotes = char
                            
                    elif char == '{' and not in_quotes:
                        brace_depth += 1
                    elif char == '}' and not in_quotes:
                        brace_depth = max(0, brace_depth - 1)
                        
                    elif char == '>' and not in_quotes and brace_depth == 0:
                        tag_string = content[start:j + 1]
                        
                        # Calculate line ranges
                        start_line = content.count('\n', 0, start) + 1
                        end_line = content.count('\n', 0, j) + 1

                        lookahead_info = ""

                        # Brace-aware look-ahead for inner text (skip JS logic)
                        if not tag_string.strip().endswith('/>'):
                            k = j + 1
                            inner_content = ""
                            lookahead_brace_depth = 0

                            while k < n and content[k] != '<':
                                la_char = content[k]

                                if la_char == '{':
                                    lookahead_brace_depth += 1
                                elif la_char == '}':
                                    lookahead_brace_depth = max(0, lookahead_brace_depth - 1)
                                elif lookahead_brace_depth == 0:
                                    inner_content += la_char
                                k += 1

                            stripped_inner = inner_content.strip()
                            if stripped_inner:
                                # Remove trailing JS debris: ];,}])
                                clean_text = re.sub(r'^[\]\};,\s]+|[\]\};,\s]+$', '', stripped_inner)
                                if clean_text:
                                    clean_text = " ".join(clean_text.split())
                                    lookahead_info = f" | [Text: {clean_text}]"

                        raw_tags.append((tag_string, start_line, end_line, lookahead_info))
                        i = j
                        break
                    j += 1
        i += 1

    # Depth tracking (silent closing tags)
    parsed_nodes = []
    current_depth = 0

    for tag_string, s_line, e_line, lookahead_info in raw_tags:
        clean_tag = " ".join(tag_string.split())

        if clean_tag.startswith("</"):
            current_depth = max(0, current_depth - 1)
        else:
            node_depth = current_depth + 1

            # Line range formatting
            if s_line == e_line:
                line_marker = f"(L:{s_line})"
            else:
                line_marker = f"(L:{s_line}-{e_line})"

            formatted_node = f"[{node_depth}] {line_marker} {clean_tag}{lookahead_info}"
            parsed_nodes.append({
                "file_path": filepath,
                "line_number": s_line,
                "code_snippet": formatted_node
            })

            if not clean_tag.endswith("/>") and clean_tag != "<>":
                current_depth += 1

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