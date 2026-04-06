import os
import json
import re
import subprocess
import sys

"""
=========================================================================================
Repository AST Indexer (Single Repo Mode)
=========================================================================================
Scans a specific repository and extracts opening JSX/HTML tags.
- Accepts a direct GitHub URL via command line or input.
- Maintains chronological order and depth tracking.
- Extracts line numbers and immediate inner text.
=========================================================================================
"""

def extract_branch_from_url(repo_url):
    """
    Extract branch name from GitHub URL if present.
    Handles formats like:
    - https://github.com/user/repo/tree/branch-name → branch_name
    - https://github.com/user/repo → None (uses default)
    
    Returns:
        tuple: (cleaned_url, branch_name_or_none)
    """
    # Check if URL contains /tree/ indicating a branch
    if '/tree/' in repo_url:
        parts = repo_url.split('/tree/')
        base_url = parts[0]
        branch_name = parts[1].strip()
        # Remove .git if present in branch name
        if branch_name.endswith('.git'):
            branch_name = branch_name[:-4]
        return base_url, branch_name
    else:
        # No branch specified, return None
        return repo_url, None

def extract_nodes_from_file(filepath):
    """
    Scans an entire file and extracts every opening JSX/HTML tag as an AST node.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            content = file.read()
    except Exception as e:
        print(f"      -> [WARNING] Could not read {filepath}: {e}")
        return []

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
                            if content[j - 1] != '\\': in_quotes = None
                        elif not in_quotes: in_quotes = char
                    elif char == '{' and not in_quotes:
                        brace_depth += 1
                    elif char == '}' and not in_quotes:
                        brace_depth = max(0, brace_depth - 1)
                    elif char == '>' and not in_quotes and brace_depth == 0:
                        tag_string = content[start:j + 1]
                        start_line = content.count('\n', 0, start) + 1
                        end_line = content.count('\n', 0, j) + 1
                        lookahead_info = ""

                        if not tag_string.strip().endswith('/>'):
                            k = j + 1
                            inner_content = ""
                            lookahead_brace_depth = 0
                            while k < n and content[k] != '<':
                                la_char = content[k]
                                if la_char == '{': lookahead_brace_depth += 1
                                elif la_char == '}': lookahead_brace_depth = max(0, lookahead_brace_depth - 1)
                                elif lookahead_brace_depth == 0: inner_content += la_char
                                k += 1
                            stripped_inner = inner_content.strip()
                            if stripped_inner:
                                clean_text = re.sub(r'^[\]\};,\s]+|[\]\};,\s]+$', '', stripped_inner)
                                if clean_text:
                                    clean_text = " ".join(clean_text.split())
                                    lookahead_info = f" | [Text: {clean_text}]"

                        raw_tags.append((tag_string, start_line, end_line, lookahead_info))
                        i = j
                        break
                    j += 1
        i += 1

    nodes = []
    current_depth = 0
    for tag_string, s_line, e_line, lookahead_info in raw_tags:
        clean_tag = " ".join(tag_string.split())
        if clean_tag.startswith("</"):
            current_depth = max(0, current_depth - 1)
        else:
            node_depth = current_depth + 1
            line_marker = f"(L:{s_line})" if s_line == e_line else f"(L:{s_line}-{e_line})"
            nodes.append(f"[{node_depth}] {line_marker} {clean_tag}{lookahead_info}")
            if not clean_tag.endswith("/>") and clean_tag != "<>":
                current_depth += 1
    return nodes

def run_repo_indexer(repo_url):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Extract branch from URL if present
    repo_url_clean, branch_name = extract_branch_from_url(repo_url)
    
    # Setup directories
    repos_dir = os.path.join(base_dir, "cloned_repos")
    results_dir = os.path.join(base_dir, "indexed_nodes")
    os.makedirs(repos_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)

    # Resolve Repo Name (use cleaned URL without /tree/)
    repo_name = repo_url_clean.split("/")[-1].replace(".git", "")
    
    # Include branch in folder name to avoid conflicts between different branches
    if branch_name:
        repo_path = os.path.join(repos_dir, f"{repo_name}_{branch_name}")
        display_name = f"{repo_name} (branch: {branch_name})"
    else:
        repo_path = os.path.join(repos_dir, repo_name)
        display_name = repo_name

    # Cloning Logic
    if not os.path.exists(repo_path):
        print(f"\n[TRACE] Attempting to clone {display_name}...")
        try:
            if branch_name:
                print(f"[TRACE] Cloning specified branch: '{branch_name}'")
                subprocess.run(["git", "clone", "-b", branch_name, "--single-branch", repo_url_clean, repo_path], check=True)
            else:
                print(f"[TRACE] Cloning default branch...")
                subprocess.run(["git", "clone", repo_url_clean, repo_path], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to clone: {e}")
            return
    else:
        print(f"\n[TRACE] Repository {display_name} already exists. Skipping clone.")

    # Indexing Logic
    repo_index = {}
    total_nodes = 0
    print(f"[TRACE] Indexing AST nodes in {display_name}...")

    for root, dirs, files in os.walk(repo_path):
        # Filter directories to skip heavy folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'dist', 'build', 'coverage']]
        
        for file in files:
            if file.endswith((".jsx", ".js", ".tsx", ".ts")):
                full_filepath = os.path.join(root, file)
                relative_path = os.path.relpath(full_filepath, repo_path).replace("\\", "/")
                
                nodes = extract_nodes_from_file(full_filepath)
                if nodes:
                    repo_index[relative_path] = nodes
                    total_nodes += len(nodes)

    # Save output
    output_path = os.path.join(results_dir, f"{repo_name}.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(repo_index, f, indent=4)

    print(f"\n[TRACE] SUCCESS: Indexed {total_nodes} nodes in {display_name}.")
    print(f"[TRACE] Results saved to: {output_path}")

if __name__ == "__main__":
    # Check if URL is provided via CLI argument, otherwise prompt for it
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    else:
        target_url = input("Enter GitHub Repository URL: ").strip()

    if target_url:
        run_repo_indexer(target_url)
    else:
        print("[ERROR] No URL provided.")


# ========================================================================================
# STUB FUNCTIONS (Required by routes.py for backward compatibility)
# These are not used in the new validate.py workflow, but routes.py imports them
# ========================================================================================

def build_index_sync(repo_path):
    """
    STUB: Build index synchronously from repository path.
    Used by old routes.py workflow. Not used in new validate.py workflow.
    """
    return {}

def reindex_retriever(index_dict):
    """
    STUB: Re-index retriever with new index dictionary.
    Used by old routes.py workflow. Not used in new validate.py workflow.
    """
    pass

def get_index_status():
    """
    Returns the current indexing status.
    Returns True only when indexing is NOT in progress.
    """
    # This will be imported from routes.py to check the actual state
    try:
        from routes import index_progress_state
        # Indexing is "done" when is_indexing is False
        return not index_progress_state.get("is_indexing", False)
    except:
        # Fallback to True if we can't import
        return True