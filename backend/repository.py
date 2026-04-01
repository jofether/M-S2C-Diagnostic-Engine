"""
Repository management module.
Handles GitHub repository cloning with git command-line interface.
"""

import subprocess
from config import logger


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
            if branch_name:
                print(f"✅ Using branch: {branch_name}")
                logger.info(f"✅ Using branch: {branch_name}")
            return True
        else:
            print(f"❌ Clone failed: {result.stderr}")
            logger.error(f"❌ Clone failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Clone timed out after 60 seconds")
        logger.error(f"❌ Clone timed out after 60 seconds")
        return False
    except FileNotFoundError:
        print(f"❌ Git not found. Install Git to use repository indexing")
        logger.error(f"❌ Git not found. Install Git to use repository indexing")
        return False
    except Exception as e:
        print(f"❌ Clone error: {e}")
        logger.error(f"❌ Clone error: {e}")
        return False
