"""
Configuration module for M-S2C Diagnostic Engine.
Handles logging setup, constants, and application state management.
"""

import logging
import os
from pathlib import Path


# ============================================================
# LOGGING CONFIGURATION
# ============================================================

LOG_FILE = "backend_debug.log"

def setup_logging():
    """Configure logging to both console and file with UTF-8 encoding."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),  # UTF-8 for file
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    print(f"\n📝 Logging to: {os.path.abspath(LOG_FILE)}\n")
    return logger


logger = setup_logging()


# ============================================================
# CONSTANTS
# ============================================================

# CRITICAL: Only include files with AST structure (tags/functions)
# DO NOT include .css - extract_ast_nodes() looks for <tags>, not CSS rules
# Including .css would waste processing time and clutter the index with empty results
ALLOWED_EXTENSIONS = {'.jsx', '.js', '.tsx', '.ts', '.html'}

SEARCH_DIRECTORIES = ['src', 'components', 'pages', 'styles', 'features', 'UI', 'ui', 'lib', 'utils']

# Ignore directories that contain dependencies or build artifacts
IGNORE_DIRECTORIES = ['node_modules', '.git', '__pycache__', '.venv', 'venv', 'dist', 'build']

# Ignore specific files that don't contain code to be analyzed
IGNORE_FILES = {'.gitignore', 'package.json', 'tsconfig.json', 'vite.config.js'}

# AST extraction limits to prevent memory bloat
MAX_COMPONENTS_PER_FILE = 3
MAX_SNIPPET_LENGTH = 2000
MAX_CSS_RULES_LENGTH = 1000
MAX_FILE_PREVIEW_LENGTH = 500


# ============================================================
# APPLICATION STATE
# ============================================================

class AppState:
    """Manages the global application state for repository indexing."""
    
    def __init__(self):
        self.indexed_repo_url = None
        self.is_indexed = False
        self.file_count = 0
        self.snippet_count = 0
    
    def set_repository(self, repo_url: str):
        """Update the indexed repository URL."""
        self.indexed_repo_url = repo_url
    
    def reset(self):
        """Reset application state."""
        self.indexed_repo_url = None
        self.is_indexed = False
        self.file_count = 0
        self.snippet_count = 0
    
    def __repr__(self):
        return (
            f"AppState(repo={self.indexed_repo_url}, "
            f"indexed={self.is_indexed}, files={self.file_count}, "
            f"snippets={self.snippet_count})"
        )


# Global app state instance
app_state = AppState()


# ============================================================
# CONFIGURATION VERIFICATION
# ============================================================
# 
# VERIFY YOUR SETTINGS FOR YOUR PROJECT:
#
# 1. ALLOWED_EXTENSIONS
#    ✅ MUST include: .jsx, .js, .tsx, .ts, .html (AST-extractable files)
#    ❌ MUST NOT include: .css, .png, .json, .md (non-AST files)
#    Why: extract_ast_nodes() in indexer.py looks for JSX tags (<tag>)
#         CSS, images, etc. won't have tags and will waste resources
#    Custom Projects: Add .vue for Vue.js, .astro for Astro, etc.
#
# 2. SEARCH_DIRECTORIES
#    These folders will be SCANNED for source files
#    Update based on your project structure:
#    - Next.js: ['pages', 'components', 'lib']
#    - Vue.js: ['src/components', 'src/pages', 'src']
#    - Astro: ['src/components', 'src/pages']
#    - Svelte: ['src/components', 'src/routes']
#
# 3. IGNORE_DIRECTORIES
#    These will be SKIPPED during scanning
#    Usually safe, but if you have custom build/dist names, add them here
#    Common: node_modules, .git, dist, build, .next, .nuxt
#
# 4. IGNORE_FILES
#    These won't be searched if found
#    Mostly safe - these are config files with no executable code
#
# ============================================================
