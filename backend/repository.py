"""
Repository management module.
Handles GitHub repository cloning with git command-line interface.

CRITICAL SAFETY FEATURES:
- Validates destination directory before cloning
- Cleans up failed clone attempts to prevent stale files
- Uses shallow clone (--depth 1) to minimize bandwidth
- Logs all operations for debugging
"""

import subprocess
import os
import shutil
from config import logger


def clone_repository(repo_url: str, destination: str) -> bool:
    """
    Shallow clone a GitHub repository to save time and bandwidth.
    Automatically extracts branch name from GitHub web URLs and clones that branch.
    
    CRITICAL SAFETY: 
    - Validates destination doesn't contain stale files
    - Cleans up failed attempts to prevent indexer.py from parsing outdated code
    - Uses tempfile.mkdtemp() source dictates unique, isolated directories
    
    Args:
        repo_url: GitHub URL - can be:
                  - Base: https://github.com/user/repo
                  - With branch: https://github.com/user/repo/tree/buggy
        destination: Local path where repo will be cloned
                     Should be created via tempfile.mkdtemp() to ensure isolation
        
    Returns:
        True if successful, False otherwise
    """
    branch_name = None
    
    # CRITICAL FIX #1: Validate destination safety
    if not destination:
        print(f"❌ Invalid destination: Empty path")
        logger.error(f"❌ Invalid destination: Empty path")
        return False
    
    if os.path.exists(destination):
        # Destination created but might be empty or contain failed clone
        # This is expected since routes.py creates it first via mkdtemp()
        print(f"📂 Destination exists: {destination}")
        logger.info(f"📂 Destination exists: {destination}")
        
        # Check if it already contains a .git folder (stale clone)
        if os.path.exists(os.path.join(destination, ".git")):
            print(f"⚠️  Stale clone detected in destination, cleaning up...")
            logger.warning(f"⚠️  Stale clone detected in destination, cleaning up...")
            try:
                shutil.rmtree(destination)
                os.makedirs(destination, exist_ok=True)
                print(f"🗑️  Cleaned up stale clone at: {destination}")
                logger.info(f"🗑️  Cleaned up stale clone at: {destination}")
            except Exception as e:
                print(f"❌ Failed to cleanup stale clone: {e}")
                logger.error(f"❌ Failed to cleanup stale clone: {e}")
                return False
    else:
        # Create destination if it doesn't exist
        try:
            os.makedirs(destination, exist_ok=True)
            print(f"📂 Created destination directory: {destination}")
            logger.info(f"📂 Created destination directory: {destination}")
        except Exception as e:
            print(f"❌ Failed to create destination: {e}")
            logger.error(f"❌ Failed to create destination: {e}")
            return False
    
    # Extract branch name from GitHub web URL
    if '/tree/' in repo_url:
        parts = repo_url.split('/tree/')
        repo_url = parts[0]  # Base repository URL
        branch_name = parts[1].rstrip('/')  # Branch name
        print(f"📌 Branch specified: {branch_name}")
        logger.info(f"📌 Branch specified: {branch_name}")
    
    try:
        print(f"🔄 Cloning repository: {repo_url}")
        logger.info(f"🔄 Cloning repository: {repo_url}")
        
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
            logger.info(f"✅ Repository cloned to: {destination}")
            
            # CRITICAL FIX #2: Verify clone succeeded by checking for source files
            if not os.path.exists(os.path.join(destination, ".git")):
                print(f"❌ Clone verification failed: .git folder not found")
                logger.error(f"❌ Clone verification failed: .git folder not found")
                return False
            
            if branch_name:
                print(f"✅ Using branch: {branch_name}")
                logger.info(f"✅ Using branch: {branch_name}")
            
            print(f"✅ Clone verified - repository is ready for indexing")
            logger.info(f"✅ Clone verified - repository is ready for indexing")
            return True
        else:
            print(f"❌ Clone failed: {result.stderr}")
            logger.error(f"❌ Clone failed: {result.stderr}")
            
            # CRITICAL FIX #3: Cleanup failed clone attempt
            print(f"🗑️  Cleaning up failed clone attempt...")
            logger.info(f"🗑️  Cleaning up failed clone attempt...")
            try:
                if os.path.exists(destination):
                    # Remove only the contents, keep the directory for routing.py
                    for item in os.listdir(destination):
                        item_path = os.path.join(destination, item)
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                    print(f"✅ Cleaned up failed clone contents")
                    logger.info(f"✅ Cleaned up failed clone contents")
            except Exception as cleanup_error:
                print(f"⚠️  Could not fully cleanup failed clone: {cleanup_error}")
                logger.warning(f"⚠️  Could not fully cleanup failed clone: {cleanup_error}")
            
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Clone timed out after 60 seconds")
        logger.error(f"❌ Clone timed out after 60 seconds")
        # Cleanup on timeout
        try:
            if os.path.exists(destination):
                for item in os.listdir(destination):
                    item_path = os.path.join(destination, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
        except:
            pass
        return False
    except FileNotFoundError:
        print(f"❌ Git not found. Install Git to use repository indexing")
        logger.error(f"❌ Git not found. Install Git to use repository indexing")
        return False
    except Exception as e:
        print(f"❌ Clone error: {e}")
        logger.error(f"❌ Clone error: {e}")
        # Cleanup on unexpected error
        try:
            if os.path.exists(destination):
                for item in os.listdir(destination):
                    item_path = os.path.join(destination, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
        except:
            pass
        return False
