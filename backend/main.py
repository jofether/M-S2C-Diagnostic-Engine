from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import shutil
import os
import json
import subprocess
import tempfile
import re
import logging
from pathlib import Path

# Setup logging to both console and file
log_file = "backend_debug.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),  # UTF-8 for file
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Print log file location to console
print(f"\n📝 Logging to: {os.path.abspath(log_file)}\n")

# Try to import the custom AI Retriever, fall back to mock if PyTorch issues
try:
    from ms2c import MS2CRetriever
    PYTORCH_AVAILABLE = True
except (ImportError, OSError) as e:
    print(f"⚠️  PyTorch import error: {e}")
    print("🔧 Running in mock mode - responses will use keyword-based ranking\n")
    PYTORCH_AVAILABLE = False
    
    # Mock retriever that uses actual indexed files with keyword-based ranking
    class MS2CRetriever:
        def __init__(self, model_path="", index_dict=None):
            self.index_dict = index_dict or {}
            self.unique_files = list(index_dict.keys()) if index_dict else []
            self.global_corpus = []
            
            # Flatten the index
            for file_path, snippets in index_dict.items():
                for snippet in snippets:
                    self.global_corpus.append((file_path, snippet))
            
            print(f"✅ Mock MS2CRetriever initialized with {len(self.unique_files)} files and {len(self.global_corpus)} snippets")
        
        def retrieve_top_k(self, text_query, image_path=None, k=3, mode="multimodal", scope="file"):
            """
            Mock retrieval using keyword matching and snippet similarity.
            Returns top-k results from the indexed corpus.
            """
            if not self.global_corpus:
                print("⚠️  No indexed corpus available")
                return [], 1.0
            
            query_lower = text_query.lower()
            query_words = set(query_lower.split())
            
            # Score each file based on keyword matches in snippets
            file_scores = {}
            
            for file_path, snippet in self.global_corpus:
                if file_path not in file_scores:
                    file_scores[file_path] = 0.0
                
                snippet_lower = snippet.lower()
                file_name_lower = file_path.lower()
                
                # All query words combined (for substring matching)
                full_query = " ".join(query_words)
                
                # Strong bonus: query appears as substring in filename
                if full_query in file_name_lower:
                    score = 1000  # Very high score for exact substring match
                else:
                    # Regular word-based matching
                    matches = sum(1 for word in query_words if len(word) > 2 and word in snippet_lower)
                    # Bonus for file name matches (higher weight now: 5x instead of 2x)  
                    file_matches = sum(1 for word in query_words if len(word) > 2 and word in file_name_lower)
                    score = matches + (file_matches * 5)  # Increased boost for file name matches
                
                file_scores[file_path] += score
            
            # Sort by score
            sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
            
            # Get top k files with their snippets
            results = []
            for file_path, score in sorted_files[:k]:
                # Find first snippet for this file
                for fp, snippet in self.global_corpus:
                    if fp == file_path:
                        results.append((file_path, snippet))
                        break
            
            # Ensure we have exactly k results
            if len(results) < k:
                # Fill with remaining snippets
                used_files = {r[0] for r in results}
                for fp, snippet in self.global_corpus:
                    if fp not in used_files and len(results) < k:
                        results.append((fp, snippet))
                        used_files.add(fp)
            
            alpha = 0.5 if mode == "multimodal" else 1.0
            return results[:k], alpha
        
        def _flatten_and_encode(self, index_dict, batch_size=64):
            """Mock method to accept index dict updates"""
            self.index_dict = index_dict
            self.unique_files = list(index_dict.keys())
            self.global_corpus = []
            for file_path, snippets in index_dict.items():
                for snippet in snippets:
                    self.global_corpus.append((file_path, snippet))
            print(f"✅ Mock retriever updated with {len(self.unique_files)} files")

app = FastAPI(title="M-S2C Diagnostic Engine API")

# VERY IMPORTANT: This allows your React app (Port 5173) to talk to Python (Port 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # <--- Change this to "*" for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state to track indexed repository
class AppState:
    def __init__(self):
        self.indexed_repo_url = None
        self.index_timestamp = None
        self.is_indexed = False
        self.file_count = 0
        self.snippet_count = 0
    
    def set_repository(self, repo_url):
        self.indexed_repo_url = repo_url
        self.index_timestamp = datetime.now()
        self.is_indexed = True
        print(f"📦 Repository stored: {repo_url}")
    
    def reset(self):
        self.indexed_repo_url = None
        self.index_timestamp = None
        self.is_indexed = False
        self.file_count = 0
        self.snippet_count = 0

app_state = AppState()

# ==================== INDEXING HELPER FUNCTIONS ====================

def clone_repository(repo_url: str, destination: str) -> bool:
    """
    Shallow clone a GitHub repository to save time and bandwidth.
    Automatically extracts branch name from GitHub web URLs and clones that branch.
    
    Args:
        repo_url: GitHub URL - can be:
                  - Base: https://github.com/user/repo
                  - With branch: https://github.com/user/repo/tree/buggy
        destination: Local path where repo will be cloned
        
    Returns:
        True if successful, False otherwise
    """
    branch_name = None
    
    # Extract branch name from GitHub web URL
    if '/tree/' in repo_url:
        parts = repo_url.split('/tree/')
        repo_url = parts[0]  # Base repository URL
        branch_name = parts[1].rstrip('/')  # Branch name
        print(f"📌 Branch specified: {branch_name}")
    
    try:
        print(f"🔄 Cloning repository: {repo_url}")
        
        # Build clone command with optional branch
        clone_cmd = ["git", "clone", "--depth", "1"]
        if branch_name:
            clone_cmd.extend(["--branch", branch_name])
        clone_cmd.extend([repo_url, destination])
        
        result = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print(f"✅ Repository cloned to: {destination}")
            if branch_name:
                print(f"✅ Using branch: {branch_name}")
            return True
        else:
            print(f"❌ Clone failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Clone timed out after 60 seconds")
        return False
    except FileNotFoundError:
        print(f"❌ Git not found. Install Git to use repository indexing")
        return False
    except Exception as e:
        print(f"❌ Clone error: {e}")
        return False


def extract_react_components(file_path: str) -> list:
    """
    Extract React components from a JavaScript/JSX file using regex.
    Returns tuples of (code, start_line, end_line) to preserve line numbers.
    
    Args:
        file_path: Path to the .jsx/.js/.tsx file
        
    Returns:
        List of tuples: [(code_string, start_line, end_line), ...]
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"⚠️  Could not read {file_path}: {e}")
        return []
    
    if not content.strip() or len(content) < 30:
        return []
    
    components = []
    
    # Split content into lines for line number calculation
    lines = content.split('\n')
    
    # Pattern 1: export function Component() or export default function Component()
    pattern1 = r'export\s+(?:default\s+)?function\s+\w+\s*\([^)]*\)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # Pattern 2: const Component = () => or const Component = function() or function Component()
    pattern2 = r'(?:export\s+)?(?:default\s+)?(?:const|var|let)\s+\w+\s*=\s*(?:\([^)]*\))?\s*(?:=>|function)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # Pattern 3: Plain function Component()
    pattern3 = r'(?<!export\s)function\s+\w+\s*\([^)]*\)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # Pattern 4: Default export - export default (catchall for any export pattern)
    pattern4 = r'export\s+default\s+[^;]+?(?=\n(?:export|const|var|let|function|class|import|$))'
    
    patterns = [pattern1, pattern2, pattern3, pattern4]
    
    for pattern in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
            component_code = match.group(0).strip()
            
            # Only add if it's reasonable length and contains JSX markers or function definition
            if len(component_code) > 50 and ('return' in component_code or 'jsx' in component_code.lower() or '<' in component_code):
                # Calculate line number by counting newlines before match start
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:match.end()].count('\n') + 1
                
                components.append((component_code[:2000], start_line, end_line))
    
    # If nothing found with patterns, extract any return statement with JSX
    if not components:
        jsx_pattern = r'(?:function|const|=>)[^}]*?return\s*\([^)]*<[^>]+>[^}]*\)'
        for match in re.finditer(jsx_pattern, content, re.MULTILINE | re.DOTALL):
            code = match.group(0).strip()
            if len(code) > 40:
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:match.end()].count('\n') + 1
                components.append((code[:1500], start_line, end_line))
    
    # Fallback: if still nothing, return the first 1500 chars if file looks like a component
    if not components and any(keyword in content for keyword in ['return', 'useState', 'useEffect', 'React', 'jsx']):
        components.append((content[:1500], 1, len(lines)))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_components = []
    for code, start, end in components:
        if code not in seen:
            seen.add(code)
            unique_components.append((code, start, end))
    
    return unique_components[:3]  # Return max 3 per file


def extract_css_rules(file_path: str) -> list:
    """
    Extract CSS rules from .css files.
    Returns tuples of (code, start_line, end_line) to preserve line numbers.
    
    Args:
        file_path: Path to the .css file
        
    Returns:
        List of tuples: [(rule_string, start_line, end_line), ...]
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"⚠️  Could not read {file_path}: {e}")
        return []
    
    rules = []
    
    # Match CSS rules: .class-name { ... }
    css_pattern = r'[\.#]?[\w\-:]+\s*\{[^}]*(?:\{[^}]*\}[^}]*)*\}'
    
    for match in re.finditer(css_pattern, content, re.MULTILINE | re.DOTALL):
        rule = match.group(0)
        if len(rule) > 20:  # Skip very short rules
            start_line = content[:match.start()].count('\n') + 1
            end_line = content[:match.end()].count('\n') + 1
            rules.append((rule[:1000], start_line, end_line))
    
    # If no rules found, return the file content
    if not rules and len(content.strip()) > 50:
        lines = content.split('\n')
        rules.append((content[:1500], 1, len(lines)))
    
    return rules


def build_index_from_repo(repo_path: str) -> dict:
    """
    Traverse cloned repository and build index dictionary with line numbers.
    Structure: { "file/path/Component.jsx (Lines 45-60)": ["component code 1", ...] }
    
    Args:
        repo_path: Path to cloned repository
        
    Returns:
        Dictionary mapping file paths with line numbers to lists of code snippets
    """
    index_dict = {}
    
    frontend_extensions = {'.jsx', '.js', '.tsx', '.ts', '.css'}
    
    # Common frontend directories to search
    search_dirs = ['src', 'components', 'pages', 'styles', 'features', 'UI', 'ui']
    
    for search_dir in search_dirs:
        full_path = os.path.join(repo_path, search_dir)
        if not os.path.exists(full_path):
            continue
        
        print(f"📂 Scanning {search_dir}/")
        
        for root, dirs, files in os.walk(full_path):
            for file in files:
                file_ext = Path(file).suffix
                
                if file_ext not in frontend_extensions:
                    continue
                
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, repo_path)
                
                # Extract code snippets with line numbers
                if file_ext == '.css':
                    snippets_with_lines = extract_css_rules(file_path)
                else:  # .jsx, .js, .tsx, .ts
                    snippets_with_lines = extract_react_components(file_path)
                
                if snippets_with_lines:
                    # Create entries with line numbers in the key
                    for code_snippet, start_line, end_line in snippets_with_lines:
                        key = f"{relative_path} (Lines {start_line}-{end_line})"
                        if key not in index_dict:
                            index_dict[key] = []
                        index_dict[key].append(code_snippet)
                    
                    print(f"  ✓ {relative_path} ({len(snippets_with_lines)} snippets with line numbers)")
    
    return index_dict


async def reindex_retriever(index_dict: dict):
    """
    Update the global retriever with new index dictionary.
    This works with both real CodeBERT retriever and mock keyword-based retriever.
    
    Args:
        index_dict: Dictionary of file paths to code snippets
    """
    global retriever
    
    try:
        print(f"🔄 Re-indexing retriever with {len(index_dict)} files...")
        
        if PYTORCH_AVAILABLE:
            print(f"   Using CodeBERT semantic vectorization...")
            retriever._flatten_and_encode(index_dict, batch_size=64)
        else:
            print(f"   Using keyword-based mock retriever...")
            retriever._flatten_and_encode(index_dict, batch_size=64)
        
        print(f"✅ Retriever re-indexed successfully")
    except Exception as e:
        print(f"❌ Reindexing failed: {e}")
        import traceback
        traceback.print_exc()

# ==================== END HELPER FUNCTIONS ====================

# Global variable to store indexed repository data
global_indexed_data = {
    "src/components/Login.jsx": ["export function LoginButton() { ... }"],
    "src/layouts/Container.jsx": ["function Container() { ... }"],
    "src/styles/forms.css": [".login-btn { position: absolute; }"]
}

print("=" * 60)
print("🚀 M-S2C Diagnostic Engine Backend Starting...")
print("=" * 60)

try:
    retriever = MS2CRetriever(model_path="ms2c_E2E_JOINT_BEST.pt", index_dict=global_indexed_data)
    print("✅ Model loaded successfully!")
except Exception as e:
    print(f"⚠️  Model initialization error: {e}")
    print("✅ Using mock retriever instead")

print("=" * 60)

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
        await reindex_retriever(index_dict)
        
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
        
        return {
            "status": "success",
            "message": f"Repository successfully indexed!",
            "repository": repo_url,
            "files_indexed": len(index_dict),
            "snippets_indexed": total_snippets,
            "timestamp": str(app_state.index_timestamp)
        }
        
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
                for idx, (file_path, snippet) in enumerate(top_results):
                    # file_path already contains line numbers in format "path/file.jsx (Lines X-Y)"
                    results.append([
                        file_path,  # First element: filepath with line numbers
                        snippet[:500].strip()  # Second element: code snippet
                    ])
                
                print(f"✅ Retrieved {len(results)} results from repository")
                
            except Exception as e:
                print(f"❌ Search failed: {e}")
                import traceback
                traceback.print_exc()
                print(f"🔄 Falling back to keyword matching...")
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

def generate_smart_results(bug_description: str, repo_url: str):
    """
    Generate smarter mock results based on bug description keywords.
    Analyzes specific keywords to suggest relevant source files.
    """
    description_lower = bug_description.lower()
    
    # More specific keyword categories
    authentication_keywords = ["login", "auth", "password", "signin", "sign-in", "account", "user account", "credentials"]
    layout_keywords = ["layout", "container", "wrapper", "spacing", "alignment", "grid", "flex", "arrange", "organize"]
    ingredient_keywords = ["ingredient", "list", "item", "select", "choice", "option", "add item", "ingredient row"]
    button_keywords = ["button", "click", "clickable", "interactive", "click handler", "onclick", "cursor"]
    style_keywords = ["css", "style", "color", "theme", "background", "font", "padding", "margin", "border", "appearance"]
    form_keywords = ["form", "input", "field", "text field", "label", "validation", "submit"]
    
    # Calculate specificity scores (higher = more specific match)
    def count_keywords(text, keywords):
        return sum(1 for kw in keywords if kw in text)
    
    auth_score = count_keywords(description_lower, authentication_keywords)
    layout_score = count_keywords(description_lower, layout_keywords)
    ingredient_score = count_keywords(description_lower, ingredient_keywords)
    button_score = count_keywords(description_lower, button_keywords)
    style_score = count_keywords(description_lower, style_keywords)
    form_score = count_keywords(description_lower, form_keywords)
    
    # Sort by score to determine best fits
    scores = [
        ("auth", auth_score),
        ("layout", layout_score),
        ("ingredient", ingredient_score),
        ("button", button_score),
        ("style", style_score),
        ("form", form_score)
    ]
    sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
    
    results = []
    suggested_categories = set()
    
    # Primary result - highest scoring category
    if sorted_scores[0][1] > 0:  # Only if we have a match
        top_category = sorted_scores[0][0]
        suggested_categories.add(top_category)
        
        if top_category == "ingredient":
            results.append({
                "file": "src/components/IngredientList.jsx",
                "lines": "45-68",
                "code": """<label key={ingredient.id} className="ingredient-row flex items-center flex-col group cursor-pointer py-1 px-0 -mx-3 rounded-xl hover:bg-stone-50 transition-all border-b border-stone-50 last:border-0">
  <span className="font-medium text-sm">{ingredient.name}</span>
  <span className="text-xs text-stone-500">{ingredient.quantity} {ingredient.unit}</span>
</label>""",
                "confidence": 0.94
            })
        elif top_category == "button":
            results.append({
                "file": "src/components/Button.jsx",
                "lines": "12-35",
                "code": """export function Button({ children, ...props }) {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
      {children}
    </button>
  )
}""",
                "confidence": 0.93
            })
        elif top_category == "auth":
            results.append({
                "file": "src/components/Login.jsx",
                "lines": "42-55",
                "code": """export function LoginButton() {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg">
      Login
    </button>
  )
}""",
                "confidence": 0.95
            })
        elif top_category == "form":
            results.append({
                "file": "src/components/FormField.jsx",
                "lines": "15-30",
                "code": """export function FormField({ label, type = "text", ...props }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <input type={type} className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" {...props} />
    </div>
  )
}""",
                "confidence": 0.88
            })
        elif top_category == "layout":
            results.append({
                "file": "src/layouts/AccessibleContainer.jsx",
                "lines": "89-102",
                "code": """function AccessibleContainer({ children }) {
  return (
    <div className="w-full overflow-hidden px-4 max-w-container mx-auto">
      {children}
    </div>
  )
}""",
                "confidence": 0.91
            })
        elif top_category == "style":
            results.append({
                "file": "src/styles/theme.css",
                "lines": "1-25",
                "code": """:root {
  --primary-color: #3b82f6;
  --secondary-color: #ef4444;
  --text-color: #1f2937;
  --bg-color: #ffffff;
  --border-color: #e5e7eb;
  --spacing-unit: 0.5rem;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto;
  color: var(--text-color);
  background-color: var(--bg-color);
}""",
                "confidence": 0.89
            })
    
    # Secondary result - second highest scoring category (different from first)
    if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 and sorted_scores[1][0] not in suggested_categories:
        second_category = sorted_scores[1][0]
        suggested_categories.add(second_category)
        
        if second_category == "style":
            results.append({
                "file": "src/styles/layout.css",
                "lines": "128-145",
                "code": """.ingredient-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
}

.ingredient-row:hover {
  background-color: #f5f5f0;
}""",
                "confidence": 0.87
            })
        elif second_category == "form":
            results.append({
                "file": "src/styles/forms.css",
                "lines": "128-145",
                "code": """.login-btn {
  position: absolute;
  right: -20px;
  width: 140px;
  overflow: visible;
  z-index: 999;
}""",
                "confidence": 0.85
            })
        elif second_category == "layout":
            results.append({
                "file": "src/layouts/Container.jsx",
                "lines": "89-102",
                "code": """function Container({ children }) {
  return (
    <div className="w-full overflow-hidden px-4">
      {children}
    </div>
  )
}""",
                "confidence": 0.83
            })
        elif second_category == "button":
            results.append({
                "file": "src/components/Button.jsx",
                "lines": "12-35",
                "code": """export function Button({ children, ...props }) {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
      {children}
    </button>
  )
}""",
                "confidence": 0.87
            })
        elif second_category == "auth":
            results.append({
                "file": "src/components/Login.jsx",
                "lines": "42-55",
                "code": """export function LoginButton() {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg">
      Login
    </button>
  )
}""",
                "confidence": 0.84
            })
    
    # Tertiary result - fill with most common if needed
    if len(results) < 3:
        for category, score in sorted_scores:
            if category not in suggested_categories and score >= 0:
                suggested_categories.add(category)
                
                if category == "layout":
                    results.append({
                        "file": "src/layouts/Container.jsx",
                        "lines": "89-102",
                        "code": """function Container({ children }) {
  return (
    <div className="w-full overflow-hidden px-4">
      {children}
    </div>
  )
}""",
                        "confidence": 0.79
                    })
                elif category == "style":
                    results.append({
                        "file": "src/styles/forms.css",
                        "lines": "128-145",
                        "code": """.login-btn {
  position: absolute;
  right: -20px;
  width: 140px;
  overflow: visible;
  z-index: 999;
}""",
                        "confidence": 0.81
                    })
                elif category == "ingredient":
                    results.append({
                        "file": "src/components/IngredientList.jsx",
                        "lines": "45-68",
                        "code": """<label key={ingredient.id} className="ingredient-row flex items-center flex-col group cursor-pointer py-1 px-0 -mx-3 rounded-xl hover:bg-stone-50 transition-all border-b border-stone-50 last:border-0">
  <span className="font-medium text-sm">{ingredient.name}</span>
  <span className="text-xs text-stone-500">{ingredient.quantity} {ingredient.unit}</span>
</label>""",
                        "confidence": 0.82
                    })
                else:
                    results.append({
                        "file": "src/App.jsx",
                        "lines": "1-25",
                        "code": """import { useState } from 'react'
import './App.css'

export default function App() {
  const [darkMode, setDarkMode] = useState(false)
  
  return (
    <div className={darkMode ? 'dark' : ''}>
      <header className="p-4 bg-white dark:bg-gray-900 shadow">
        <h1 className="text-2xl font-bold text-blue-600">M-S2C Diagnostic Engine</h1>
      </header>
    </div>
  )
}""",
                        "confidence": 0.75
                    })
                break
    
    return results[:3]  # Return top 3 results

def compute_gating_weight(bug_description: str):
    """
    Compute text vs visual contribution based on description quality and length.
    Better descriptions → higher text weight
    Shorter/vague descriptions → higher visual weight (screenshot more important)
    Returns normalized values between 0 and 1 (not percentages).
    """
    desc_length = len(bug_description)
    detail_keywords = ["specifically", "specifically", "exactly", "exactly", "however", "although", "instead of", "should be"]
    detail_count = sum(1 for kw in detail_keywords if kw in bug_description.lower())
    
    # Longer, more detailed descriptions get higher text weight
    if desc_length > 200 and detail_count > 0:
        text_weight = 0.7
        visual_weight = 0.3
    elif desc_length > 100:
        text_weight = 0.5
        visual_weight = 0.5
    elif desc_length > 50:
        text_weight = 0.35
        visual_weight = 0.65
    else:
        text_weight = 0.2
        visual_weight = 0.8
    
    return text_weight, visual_weight

@app.get("/api/health")
async def health_check():
    """Check if the backend is running and repository status"""
    return {
        "status": "healthy",
        "pytorch_available": PYTORCH_AVAILABLE,
        "mode": "production" if PYTORCH_AVAILABLE else "mock",
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

if __name__ == "__main__":
    import uvicorn
    print("\n📡 Starting FastAPI server on http://0.0.0.0:8000")
    print("📚 API docs available at http://localhost:8000/docs\n")
    # Starts the server on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)