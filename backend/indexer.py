"""
Repository indexing module.
Handles traversal, extraction, and indexing of frontend code files using AST-level parsing.
Aligned with M-S2C Thesis Architecture.
"""

import os
import re
from pathlib import Path
from config import logger, ALLOWED_EXTENSIONS, SEARCH_DIRECTORIES, IGNORE_DIRECTORIES, IGNORE_FILES

def extract_ast_nodes(content: str, filepath: str) -> list:
    """
    State-machine parser derived from the benchmarking script.
    Extracts precise AST nodes for vector embedding (AST-Level Retrieval).
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

                    # Handle JS expression brackets
                    elif char == '{' and not in_quotes:
                        brace_depth += 1
                    elif char == '}' and not in_quotes:
                        brace_depth = max(0, brace_depth - 1)

                    # Find end of the tag
                    elif char == '>' and not in_quotes and brace_depth == 0:
                        tag_string = content[start:j + 1]

                        # Calculate Start and End Lines
                        start_line = content.count('\n', 0, start) + 1
                        end_line = content.count('\n', 0, j) + 1

                        lookahead_info = ""

                        # If not self-closing, look ahead for immediate inner text
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
                                # Clean up trailing JS syntax bleeding into the text
                                clean_text = re.sub(r'^[\}\];,\s]+|[\}\];,\s]+$', '', stripped_inner)
                                if clean_text:
                                    clean_text = " ".join(clean_text.split())
                                    lookahead_info = f" // Inner Text: {clean_text}"

                        # Append to parsed nodes dictionary
                        parsed_nodes.append({
                            'line_range': [start_line, end_line],
                            'code_snippet': tag_string + lookahead_info,
                            'context_hierarchy': 'UI Node' # Fallback structural context
                        })
                        i = j
                        break
                    j += 1
        i += 1
        
    return parsed_nodes


def build_index_from_repo(repo_path: str) -> dict:
    """
    Traverse cloned repository and build index dictionary using AST nodes.
    Formats the output to match the prototype's expected string schema to prevent KeyErrors.
    """
    index_dict = {}
    
    logger.info("🔍 INDEXING REPOSITORY - Starting AST-level file traversal")
    print(f"🔍 Recursively searching {repo_path} for UI AST nodes...")
    
    try:
        for root, dirs, files in os.walk(repo_path):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRECTORIES and not d.startswith('.')]
            
            for file in files:
                if file in IGNORE_FILES:
                    continue
                    
                ext = Path(file).suffix.lower()
                if ext in ALLOWED_EXTENSIONS:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, repo_path).replace("\\", "/")
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # --- THESIS ALIGNMENT: AST NODE EXTRACTION ---
                        if ext in ['.jsx', '.tsx', '.js', '.ts', '.html']:
                            ast_nodes = extract_ast_nodes(content, file_path)
                            
                            for node in ast_nodes:
                                # Format key exactly as the prototype expects for the frontend highlight mapping
                                start_line = node.get('line_range', [0, 0])[0]
                                end_line = node.get('line_range', [0, 0])[1]
                                dict_key = f"{relative_path} (Lines {start_line}-{end_line})"
                                
                                # Inject context for CodeBERT embeddings
                                hierarchy = node.get('context_hierarchy', '')
                                raw_code = node.get('code_snippet', '')
                                
                                # Prepend the context as a comment so FAISS embeds it structurally
                                semantic_snippet = f"// Context: {hierarchy}\n{raw_code}"
                                
                                # Store as a list of strings (Prototype schema requirement)
                                if dict_key not in index_dict:
                                    index_dict[dict_key] = []
                                index_dict[dict_key].append(semantic_snippet)
                                
                        # Extract CSS (Fallback to existing extractor for pure CSS files)
                        elif ext == '.css':
                            try:
                                # Ensure extract_css_rules is in your extractors.py file
                                from extractors import extract_css_rules
                                css_rules = extract_css_rules(content)
                                for rule in css_rules:
                                    dict_key = f"{relative_path} (Lines {rule['start_line']}-{rule['end_line']})"
                                    if dict_key not in index_dict:
                                        index_dict[dict_key] = []
                                    index_dict[dict_key].append(rule['code'])
                            except ImportError:
                                logger.warning(f"Could not import extract_css_rules for {file_path}. Skipping CSS extraction.")
                                
                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        print(f"  ⚠️  Could not process {file}: {str(e)[:100]}")
                        
    except Exception as e:
        logger.error(f"Error during repository traversal: {e}")
        print(f"⚠️  Error during repository traversal: {e}")
    
    logger.info(f"✅ AST INDEXING COMPLETE: {len(index_dict)} unique nodes indexed")
    print(f"✅ Indexing complete: {len(index_dict)} AST nodes found")
    return index_dict


async def reindex_retriever(retriever, index_dict: dict, pytorch_available: bool):
    """
    Update the global retriever with the new index dictionary.
    Uses larger batch size for faster embedding of dual-encoder model.
    """
    try:
        total_snippets = sum(len(snippets) for snippets in index_dict.values())
        print(f"🔄 Re-indexing retriever with {len(index_dict)} AST files ({total_snippets} total snippets)...")
        logger.info(f"🔄 Re-indexing retriever with {len(index_dict)} AST files ({total_snippets} total snippets)...")
        print(f"⏳ This will embed through CodeBERT+ViT dual-encoder - may take 3-5 minutes...")
        logger.info(f"⏳ Embedding snippets through trained MS2C dual-encoder...")
        
        # Re-encode through retriever using larger batch size for efficiency
        # Increased from 64 to 128 for faster processing with dual-encoder
        retriever._flatten_and_encode(index_dict, batch_size=128)
        
        print(f"✅ Retriever re-indexed successfully - {total_snippets} snippets embedded")
        logger.info(f"✅ Retriever re-indexed successfully - {total_snippets} snippets embedded")
    except Exception as e:
        logger.error(f"Error re-indexing retriever: {e}")
        print(f"❌ Error during re-indexing: {e}")
        import traceback
        traceback.print_exc()