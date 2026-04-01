"""
Extraction module for code snippets from frontend files.
Handles React component and CSS rule extraction with line number tracking.
"""

import re
import logging
from config import logger


def _count_braces_smart(text, start_pos):
    """
    Count braces from start_pos and return the end position of matching closing brace.
    Handles nested braces properly.
    Returns position of closing brace or -1 if not found.
    """
    brace_count = 0
    in_string = False
    string_char = None
    escape_next = False
    
    for i in range(start_pos, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            continue
        
        if not in_string:
            if char in ('"', "'", '`'):
                in_string = True
                string_char = char
            elif char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i
        else:
            if char == string_char:
                in_string = False
    
    return -1


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
    
    # IMPROVED APPROACH: Find function/component declarations and extract their bodies with proper brace counting
    
    # Pattern to find component declarations (function or const arrow function)
    declaration_pattern = r'(?:export\s+)?(?:default\s+)?(?:function|const|var|let)\s+\w+\s*(?:\([^)]*\))?\s*(?:=>)?\s*(?:\()?'
    
    try:
        for match in re.finditer(declaration_pattern, content, re.MULTILINE):
            # Find the opening brace after the declaration
            brace_start = content.find('{', match.end())
            if brace_start == -1:
                continue
            
            # Use smart brace counting to find the matching closing brace
            brace_end = _count_braces_smart(content, brace_start)
            if brace_end == -1:
                continue
            
            # Extract code from declaration start to closing brace
            component_code = content[match.start():brace_end + 1].strip()
            
            # Validate extracted code
            if len(component_code) > 50 and any(
                keyword in component_code 
                for keyword in ['return', '<', 'jsx', 'function', 'const', 'export']
            ):
                # LINE NUMBER CALCULATION: count newlines before match
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:brace_end + 1].count('\n') + 1
                
                components.append((component_code[:2000], start_line, end_line))
    except Exception as e:
        logger.warning(f"⚠️  Error extracting components from {file_path}: {e}")
    
    # FALLBACK 1: If no components found, try JSX block extraction
    if not components:
        try:
            jsx_pattern = r'<[A-Z]\w*(?:\s+[^>]*)?\s*>(?:[^<]|<(?!/))*?</[A-Z]\w*>'
            match = re.search(jsx_pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                code = match.group(0).strip()[:2000]
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:match.end()].count('\n') + 1
                components.append((code, start_line, end_line))
        except Exception as e:
            logger.debug(f"JSX fallback regex failed for {file_path}: {e}")
    
    # FALLBACK 2: Look for any substantial exported content
    if not components:
        try:
            export_match = re.search(r'export\s+(default\s+)?(function|const|class|let|var)\s+(\w+).*', content, re.MULTILINE | re.DOTALL)
            if export_match:
                # Find opening brace and use smart counting
                brace_pos = content.find('{', export_match.start())
                if brace_pos != -1:
                    brace_end = _count_braces_smart(content, brace_pos)
                    if brace_end != -1:
                        code = content[export_match.start():brace_end + 1].strip()[:2000]
                        start_line = content[:export_match.start()].count('\n') + 1
                        end_line = content[:brace_end + 1].count('\n') + 1
                        components.append((code, start_line, end_line))
        except Exception as e:
            logger.debug(f"Export fallback failed for {file_path}: {e}")
    
    # FALLBACK 3: Last resort - entire file if it looks like a component
    # BUT: Only if we can identify actual component structure
    if not components and any(kw in content for kw in ['return', 'useState', 'useEffect', 'React', '<', '>']):
        try:
            # Find first declaration line and last closing brace
            first_decl = re.search(r'(export\s+)?(default\s+)?(function|const|var|let|class)\s+\w+', content)
            if first_decl:
                # Find last closing brace that matches
                last_brace_pos = content.rfind('}')
                if last_brace_pos > first_decl.start():
                    # Verify this is a matching brace
                    brace_start = content.find('{', first_decl.end())
                    if brace_start != -1:
                        actual_end = _count_braces_smart(content, brace_start)
                        if actual_end != -1:
                            code = content[first_decl.start():actual_end + 1].strip()[:2000]
                            start_line = content[:first_decl.start()].count('\n') + 1
                            end_line = content[:actual_end + 1].count('\n') + 1
                            # Only add if it's a reasonable-sized component (not entire file)
                            if end_line - start_line < len(lines):  # Not the entire file
                                components.append((code, start_line, end_line))
        except Exception as e:
            logger.debug(f"File content fallback failed for {file_path}: {e}")
    
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
    
    # CSS PATTERN: Find CSS selectors and extract their bodies with proper brace counting
    # Pattern to match CSS selectors (can be multiple, like .class, #id, element, etc.)
    selector_pattern = r'[\w\-\.\#\[\]="\':\s,>+~*]*?\{'
    
    try:
        for match in re.finditer(selector_pattern, content, re.MULTILINE):
            # Find opening brace position
            brace_pos = content.rfind('{', match.start(), match.end())
            if brace_pos == -1:
                continue
            
            # Use smart brace counting to find the matching closing brace
            brace_end = _count_braces_smart(content, brace_pos)
            if brace_end == -1:
                continue
            
            # Extract the CSS rule from selector to closing brace
            rule = content[match.start():brace_end + 1].strip()
            
            # Skip very short or invalid rules
            if len(rule) > 20 and '{' in rule and '}' in rule:
                # LINE NUMBER CALCULATION: count newlines before match
                start_line = content[:match.start()].count('\n') + 1
                end_line = content[:brace_end + 1].count('\n') + 1
                rules.append((rule[:1000], start_line, end_line))
    except Exception as e:
        logger.warning(f"⚠️  Regex parsing error in CSS file {file_path}: {e}")
    
    # FALLBACK: If no rules extracted, look for @media queries or keyframes
    if not rules:
        try:
            special_patterns = [
                r'@media\s*[^{]*\{[^{}]*(?:\{[^}]*\}[^{}]*)*\}',
                r'@keyframes\s+\w+\s*\{[^{}]*(?:\{[^}]*\}[^{}]*)*\}',
                r'@supports\s*[^{]*\{[^{}]*(?:\{[^}]*\}[^{}]*)*\}'
            ]
            for pattern in special_patterns:
                for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                    rule = match.group(0).strip()
                    if len(rule) > 20:
                        start_line = content[:match.start()].count('\n') + 1
                        end_line = content[:match.end()].count('\n') + 1
                        rules.append((rule[:1000], start_line, end_line))
        except Exception as e:
            logger.debug(f"Special CSS patterns failed for {file_path}: {e}")
    
    # FALLBACK: If no rules extracted, return the whole file if it has substantial CSS
    if not rules and len(content.strip()) > 50:
        try:
            rules.append((content[:1500], 1, len(lines)))
        except Exception as e:
            logger.debug(f"Failed to extract CSS fallback for {file_path}: {e}")
    
    return rules
