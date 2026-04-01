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

ALLOWED_EXTENSIONS = {'.jsx', '.js', '.tsx', '.ts', '.html', '.css'}
SEARCH_DIRECTORIES = ['src', 'components', 'pages', 'styles', 'features', 'UI', 'ui', 'lib', 'utils']
IGNORE_DIRECTORIES = ['node_modules', '.git', '__pycache__', '.venv', 'venv', 'dist', 'build']
IGNORE_FILES = {'.gitignore', 'package.json', 'tsconfig.json', 'vite.config.js'}

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
