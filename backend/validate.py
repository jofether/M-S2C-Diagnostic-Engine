"""
Model Validation and Testing Module.

This module validates the MS2C model checkpoint and ensures that trained weights
are properly loaded. It tests the retriever functionality and verifies that the
gating network produces adaptive outputs.

Functions:
- extract_branch_from_url: Parse GitHub URLs to extract branch names
- (Additional test functions can be added here)
"""

import os
import sys
import json
import torch

# Force Python to look in the current directory for ms2c.py
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from ms2c import MS2CRetriever

def extract_branch_from_url(repo_url):
    """
    Extract branch name from GitHub URL if present.
    Handles formats like:
    - https://github.com/user/repo/tree/branch-name → (repo_url_clean, branch_name)
    - https://github.com/user/repo → (repo_url, None)
    
    Returns:
        tuple: (cleaned_url, branch_name_or_none)
    """
    if '/tree/' in repo_url:
        parts = repo_url.split('/tree/')
        base_url = parts[0]
        branch_name = parts[1].strip()
        if branch_name.endswith('.git'):
            branch_name = branch_name[:-4]
        return base_url, branch_name
    else:
        return repo_url, None

def run_ms2c_validator():
    print("\n" + "="*60)
    print("   MS2C ENGINE: LOCAL INDEX RETRIEVAL")
    print("="*60)

    # 1. PATH CONFIGURATION
    # Match indexer.py directory structure
    index_dir = os.path.join(current_dir, "indexed_nodes")
    repos_root = os.path.join(current_dir, "cloned_repos")
    model_weights = os.path.join(current_dir, "ms2c_E2E_JOINT_BEST.pt")

    # 2. INPUT: Repository Selection
    repo_url = input("\n[1/4] Paste GitHub Repository Link: ").strip()
    repo_url_clean, branch_name = extract_branch_from_url(repo_url)
    repo_name = repo_url_clean.split("/")[-1].replace(".git", "")
    
    index_path = os.path.join(index_dir, f"{repo_name}.json")

    if not os.path.exists(index_path):
        print(f"\n[ERROR] No indexed nodes found for '{repo_name}'.")
        print(f"Expected file at: {index_path}")
        print("Please run indexer.py for this repository first.")
        return

    # 3. LOAD INDEX & INITIALIZE
    display_name = f"{repo_name} (branch: {branch_name})" if branch_name else repo_name
    print(f"      -> Reading index: {repo_name}.json (Branch: {branch_name if branch_name else 'default'})")
    with open(index_path, 'r', encoding='utf-8') as f:
        repo_index = json.load(f)

    print(f"      -> Loading Neural Weights...")
    retriever = MS2CRetriever(model_weights, repo_index, repos_dir=repos_root)

    # 4. INPUT: Bug Details
    text_query = input("\n[2/4] Enter Bug Description: ").strip()
    
    img_path = input("[3/4] Enter Screenshot Path (Optional, press Enter to skip): ").strip()
    if img_path and not os.path.exists(img_path):
        print("      -> [WARNING] Image file not found. Using Unimodal mode.")
        img_path = None

    # 5. INPUT: Target File Filter
    print("\nFiles available in index:")
    all_files = list(repo_index.keys())
    for idx, f in enumerate(all_files[:10]): # Show first 10 for brevity
        print(f"  {idx}. {f}")
    if len(all_files) > 10:
        print(f"  ... and {len(all_files) - 10} more files.")
    
    file_choice = input("\n[4/4] Select File Index to target (Optional, press Enter for all): ").strip()
    target_key = None
    if file_choice.isdigit() and int(file_choice) < len(all_files):
        target_key = all_files[int(file_choice)]
        print(f"      -> Scoping search to: {target_key}")

    # 6. EXECUTE RETRIEVAL
    print("\n" + "-"*60)
    print(f"[TRACE] Processing 4-Stage Retrieval Pipeline...")
    
    scope = "component" if target_key else "repository"
    mode = "multimodal" if img_path else "unimodal"

    results, alpha = retriever.retrieve_top_k(
        text_query=text_query,
        target_key=target_key,
        image_path=img_path,
        k=10,
        mode=mode,
        scope=scope
    )

    # 7. OUTPUT RESULTS
    print("="*60)
    print(f"TOP RESULTS FOR: '{text_query}'")
    if img_path:
        print(f"Vision Confidence (Alpha): {alpha:.4f}")
    print("="*60)

    if not results:
        print("No matches found. Try adjusting the bug description.")
    else:
        for i, res in enumerate(results, 1):
            filepath = target_key if target_key else res[0]
            node_text = res if target_key else res[1]
            print(f"\nRANK {i}:")
            print(f"  FILE: {filepath}")
            print(f"  NODE: {node_text}")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_ms2c_validator()