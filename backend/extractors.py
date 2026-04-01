"""
Extraction module for code snippets from frontend files.
Handles React component and CSS rule extraction with line number tracking.
"""

import re
import logging
from config import logger


def extract_react_components(file_path: str) -> list:
    """
    Extract React components from JavaScript/JSX/TypeScript files using regex.
    Robust error handling with UTF-8 encoding.
    
    Returns tuples of (code, start_line, end_line) to preserve line numbers.
    
    Requirements:
    - Robust try/except for file reading
    - UTF-8 encoding with error handling
    - Line number calculation via newline counting
    
    Args:
        file_path: Path to the .jsx/.js/.tsx/.ts file
        
    Returns:
        List of tuples: [(code_string, start_line, end_line), ...]
    """
    # ROBUST FILE READING with proper encoding
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except UnicodeDecodeError as e:
        logger.warning(f"⚠️  Unicode error reading {file_path}: {e}")
        print(f"⚠️  Could not read {file_path} (encoding issue)")
        return []
    except IOError as e:
        logger.warning(f"⚠️  IO error reading {file_path}: {e}")
        print(f"⚠️  Could not read {file_path} (file access error)")
        return []
    except Exception as e:
        logger.error(f"❌ Unexpected error reading {file_path}: {e}")
        print(f"❌ Error reading {file_path}: {type(e).__name__}")
        return []
    
    # Skip empty or too-small files
    if not content.strip() or len(content) < 30:
        return []
    
    components = []
    lines = content.split('\n')
    
    # PATTERN 1: export function Component() or export default function Component()
    pattern1 = r'export\s+(?:default\s+)?function\s+\w+\s*\([^)]*\)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # PATTERN 2: const Component = () => {} or export const Component = () => {}
    pattern2 = r'(?:export\s+)?(?:default\s+)?(?:const|var|let)\s+\w+\s*=\s*(?:\([^)]*\))?\s*(?:=>|function)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # PATTERN 3: Plain function Component()
    pattern3 = r'(?<!export\s)function\s+\w+\s*\([^)]*\)\s*\{(?:[^{}]|{[^}]*})*\}'
    
    # PATTERN 4: Default export
    pattern4 = r'export\s+default\s+[^;]+?(?=\n(?:export|const|var|let|function|class|import|$))'
    
    patterns = [pattern1, pattern2, pattern3, pattern4]
    
    try:
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                component_code = match.group(0).strip()
                
                # Validate extracted code
                if len(component_code) > 50 and any(
                    keyword in component_code 
                    for keyword in ['return', 'jsx', '<', 'function', 'const', 'export']
                ):
                    # LINE NUMBER CALCULATION: count newlines before match
                    start_line = content[:match.start()].count('\n') + 1
                    end_line = content[:match.end()].count('\n') + 1
                    
                    components.append((component_code[:2000], start_line, end_line))
    except Exception as e:
        logger.warning(f"⚠️  Regex parsing error in {file_path}: {e}")
    
    # FALLBACK 1: Try to extract JSX blocks
    if not components:
        try:
            jsx_pattern = r'(?:return|<[A-Z])[^;]*?<[A-Za-z][^>]*>(?:[^<]|<(?!/))*?<\/[A-Za-z]+>'
            match = re.search(jsx_pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                code = match.group(0).strip()[:2000]
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:match.end()].count('\n') + 1
                components.append((code, start_line, end_line))
        except Exception as e:
            logger.debug(f"JSX fallback regex failed for {file_path}: {e}")
    
    # FALLBACK 2: Function/const declaration with code body
    if not components:
        try:
            main_pattern = r'(?:export\s+)?(?:default\s+)?(?:function|const|var|let|class)\s+\w+[^}]*?\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            match = re.search(main_pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                code = match.group(0).strip()[:2000]
                if len(code) > 100 and any(kw in code for kw in ['return', 'useState', '<', '>']):
                    start_line = content[:match.start()].count('\n') + 1
                    end_line = content[:match.end()].count('\n') + 1
                    components.append((code, start_line, end_line))
        except Exception as e:
            logger.debug(f"Function fallback regex failed for {file_path}: {e}")
    
    # FALLBACK 3: Last resort - extract substantial file content if it looks like a React component
    if not components and any(kw in content for kw in ['return', 'useState', 'useEffect', 'React', '<', '>']):
        try:
            if len(content) > 500:
                components.append((content[:2000], 1, len(lines)))
            elif len(content) > 100:
                components.append((content, 1, len(lines)))
        except Exception as e:
            logger.debug(f"Fallback extraction failed for {file_path}: {e}")
    
    # DEDUPLICATE while preserving order
    try:
        seen = set()
        unique_components = []
        for code, start, end in components:
            # Use code hash to avoid storing duplicate code snippets
            code_hash = hash(code[:100])
            if code_hash not in seen:
                seen.add(code_hash)
                unique_components.append((code, start, end))
        
        return unique_components[:3]  # Max 3 components per file
    except Exception as e:
        logger.error(f"Error during deduplication in {file_path}: {e}")
        return components[:3]


def extract_css_rules(file_path: str) -> list:
    """
    Extract CSS rules from .css files with robust error handling.
    Returns tuples of (code, start_line, end_line) to preserve line numbers.
    
    Requirements:
    - Robust try/except for file reading
    - UTF-8 encoding with error tolerance
    - Line number calculation via newline counting
    
    Args:
        file_path: Path to the .css file
        
    Returns:
        List of tuples: [(rule_string, start_line, end_line), ...]
    """
    # ROBUST FILE READING with proper encoding
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except UnicodeDecodeError as e:
        logger.warning(f"⚠️  Unicode error reading {file_path}: {e}")
        return []
    except IOError as e:
        logger.warning(f"⚠️  IO error reading {file_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Unexpected error reading CSS file {file_path}: {e}")
        return []
    
    rules = []
    lines = content.split('\n')
    
    # CSS PATTERN: Extract rule blocks
    css_pattern = r'[\.#]?[\w\-:]+\s*\{[^}]*(?:\{[^}]*\}[^}]*)*\}'
    
    try:
        for match in re.finditer(css_pattern, content, re.MULTILINE | re.DOTALL):
            rule = match.group(0)
            
            # Skip very short rules
            if len(rule) > 20:
                # LINE NUMBER CALCULATION: count newlines before match
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:match.end()].count('\n') + 1
                rules.append((rule[:1000], start_line, end_line))
    except Exception as e:
        logger.warning(f"⚠️  Regex parsing error in CSS file {file_path}: {e}")
    
    # FALLBACK: If no rules extracted, return the whole file if it has substantial CSS
    if not rules and len(content.strip()) > 50:
        try:
            rules.append((content[:1500], 1, len(lines)))
        except Exception as e:
            logger.debug(f"Failed to extract CSS fallback for {file_path}: {e}")
    
    return rules
