"""
Repository indexing module.
Handles traversal, extraction, and indexing of frontend code files.
"""

import os
from pathlib import Path
from config import logger, ALLOWED_EXTENSIONS, SEARCH_DIRECTORIES, IGNORE_DIRECTORIES, IGNORE_FILES
from extractors import extract_react_components, extract_css_rules


def build_index_from_repo(repo_path: str) -> dict:
    """
    Traverse cloned repository and build index dictionary with line numbers.
    Explicit file extension filtering for UI-relevant files.
    
    Structure: { "file/path/Component.jsx (Lines 45-60)": ["component code 1", ...] }
    
    Requirements:
    - Only process: .jsx, .js, .tsx, .ts, .html, .css
    - Extract React components and CSS rules
    - Track line numbers for all extractions
    - Format keys with line numbers: "path (Lines X-Y)"
    
    Args:
        repo_path: Path to cloned repository
        
    Returns:
        Dictionary mapping file paths with line numbers to lists of code snippets
    """
    index_dict = {}
    
    logger.info("🔍 INDEXING REPOSITORY - Starting file traversal")
    
    # Phase 1: Search through defined directories
    for search_dir in SEARCH_DIRECTORIES:
        full_path = os.path.join(repo_path, search_dir)
        if not os.path.exists(full_path):
            continue
        
        logger.info(f"📂 Scanning directory: {search_dir}/")
        print(f"📂 Scanning {search_dir}/")
        
        for root, dirs, files in os.walk(full_path):
            # Skip irrelevant directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRECTORIES]
            
            for file in files:
                file_ext = Path(file).suffix.lower()
                
                # STRICT: Only process allowed extensions
                if file_ext not in ALLOWED_EXTENSIONS:
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    relative_path = os.path.relpath(file_path, repo_path)
                    
                    # Extract code snippets with line numbers based on file type
                    if file_ext == '.css':
                        snippets_with_lines = extract_css_rules(file_path)
                    elif file_ext == '.html':
                        # For HTML files, extract content within function components
                        snippets_with_lines = extract_react_components(file_path)
                    else:  # .jsx, .js, .tsx, .ts
                        snippets_with_lines = extract_react_components(file_path)
                    
                    # Add to index if snippets were extracted
                    if snippets_with_lines:
                        for code_snippet, start_line, end_line in snippets_with_lines:
                            # FORMAT KEY with line numbers as required
                            key = f"{relative_path} (Lines {start_line}-{end_line})"
                            if key not in index_dict:
                                index_dict[key] = []
                            index_dict[key].append(code_snippet)
                        
                        logger.info(f"  ✓ {relative_path} ({len(snippets_with_lines)} snippet(s) extracted)")
                        print(f"  ✓ {relative_path} ({len(snippets_with_lines)} snippet(s))")
                    else:
                        logger.debug(f"  - {relative_path} (no extractable content)")
                
                except Exception as e:
                    logger.warning(f"  ⚠️  Error processing {file_path}: {e}")
                    print(f"  ⚠️  Could not process {file}: {str(e)[:100]}")
    
    # Phase 2: Scan root directory for root-level UI files
    logger.info("📂 Scanning root directory for root-level UI files...")
    print(f"📂 Scanning root level for root UI files...")
    
    try:
        for file in os.listdir(repo_path):
            file_ext = Path(file).suffix.lower()
            
            # STRICT: Only allowed extensions
            if file_ext not in ALLOWED_EXTENSIONS:
                continue
            
            # Skip hidden files and common non-UI files
            if file.startswith('.') or file in IGNORE_FILES:
                continue
            
            file_path = os.path.join(repo_path, file)
            
            # Only process files, not directories
            if not os.path.isfile(file_path):
                continue
            
            try:
                relative_path = file  # Root-level file, no "src/" prefix
                
                # Extract code snippets with line numbers
                if file_ext == '.css':
                    snippets_with_lines = extract_css_rules(file_path)
                elif file_ext == '.html':
                    snippets_with_lines = extract_react_components(file_path)
                else:  # .jsx, .js, .tsx, .ts
                    snippets_with_lines = extract_react_components(file_path)
                
                if snippets_with_lines:
                    for code_snippet, start_line, end_line in snippets_with_lines:
                        # FORMAT KEY with line numbers
                        key = f"{relative_path} (Lines {start_line}-{end_line})"
                        if key not in index_dict:
                            index_dict[key] = []
                        index_dict[key].append(code_snippet)
                    
                    logger.info(f"  ✓ {relative_path} ({len(snippets_with_lines)} snippet(s) extracted)")
                    print(f"  ✓ {relative_path} ({len(snippets_with_lines)} snippet(s))")
            
            except Exception as e:
                logger.warning(f"  ⚠️  Error processing root {file}: {e}")
                print(f"  ⚠️  Could not process {file}: {str(e)[:100]}")
    
    except Exception as e:
        logger.error(f"Error scanning root directory: {e}")
        print(f"⚠️  Error scanning root directory: {e}")
    
    logger.info(f"✅ INDEXING COMPLETE: {len(index_dict)} unique file/line combinations indexed")
    return index_dict


async def reindex_retriever(retriever, index_dict: dict, pytorch_available: bool):
    """
    Update the global retriever with new index dictionary.
    Works with both real CodeBERT retriever and mock keyword-based retriever.
    
    Args:
        retriever: The retriever instance to update
        index_dict: Dictionary of file paths to code snippets
        pytorch_available: Whether PyTorch is available
    """
    try:
        print(f"🔄 Re-indexing retriever with {len(index_dict)} files...")
        logger.info(f"🔄 Re-indexing retriever with {len(index_dict)} files...")
        
        # Re-encode through retriever
        retriever._flatten_and_encode(index_dict, batch_size=64)
        
        print(f"✅ Retriever re-indexed successfully")
        logger.info(f"✅ Retriever re-indexed successfully")
    except Exception as e:
        print(f"❌ Reindexing failed: {e}")
        logger.error(f"❌ Reindexing failed: {e}")
        import traceback
        traceback.print_exc()
