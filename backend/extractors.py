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
    
    # STRATEGY: Extract the minimal code snippet that contains the actual bug/content
    # NOT the entire function declaration and wrapper
    
    # Find all JSX/return blocks (the actual content, not the wrapper)
    try:
        # Look for "return" statements followed by JSX
        return_pattern = r'return\s*\(\s*<'
        for match in re.finditer(return_pattern, content, re.MULTILINE):
            # Find the opening tag mark (<)
            tag_start = content.find('<', match.end() - 1)
            if tag_start == -1:
                continue
            
            # Find the matching closing tag/paren
            # Get the tag name
            tag_name_match = re.match(r'<([A-Za-z][A-Za-z0-9]*)', content[tag_start:])
            if not tag_name_match:
                continue
            
            tag_name = tag_name_match.group(1)
            
            # Find the closing tag
            closing_pattern = f'</{tag_name}>|</{tag_name}'
            closing_match = re.search(closing_pattern, content[tag_start:])
            
            if not closing_match:
                # Look for self-closing or single tag
                closing_pos = content.find('/>', tag_start)
                if closing_pos == -1:
                    closing_pos = content.find(')', content.find('>', tag_start))
                if closing_pos == -1:
                    continue
            else:
                closing_pos = tag_start + closing_match.end()
            
            # Extract just the JSX content
            snippet = content[tag_start:closing_pos].strip()
            
            # Validate and store with correct line numbers
            if len(snippet) > 20 and snippet.startswith('<'):
                start_line = content[:tag_start].count('\n') + 1
                end_line = content[:closing_pos].count('\n') + 1
                components.append((snippet[:2000], start_line, end_line))
    except Exception as e:
        logger.debug(f"JSX return block extraction failed: {e}")
    
    # FALLBACK 1: If no return blocks, try direct JSX/HTML extraction
    if not components:
        try:
            # Match opening and closing JSX tags
            jsx_pattern = r'<[A-Z]\w*[^>]*>[\s\S]*?</[A-Z]\w*>|<[a-z]+[^>]*>[\s\S]*?</[a-z]+>'
            for match in re.finditer(jsx_pattern, content):
                snippet = match.group(0).strip()
                if len(snippet) > 30 and snippet.count('<') == snippet.count('>'):
                    start_line = content[:match.start()].count('\n') + 1
                    end_line = content[:match.end()].count('\n') + 1
                    components.append((snippet[:2000], start_line, end_line))
        except Exception as e:
            logger.debug(f"Direct JSX extraction failed: {e}")
    
    # FALLBACK 2: Function body content (but trim to actual content lines, not wrapper)
    if not components:
        try:
            declaration_pattern = r'(?:export\s+)?(?:default\s+)?(?:function|const|var|let)\s+\w+\s*(?:\([^)]*\))?\s*(?:=>)?\s*(?:\()?'
            for match in re.finditer(declaration_pattern, content, re.MULTILINE):
                brace_start = content.find('{', match.end())
                if brace_start == -1:
                    continue
                
                brace_end = _count_braces_smart(content, brace_start)
                if brace_end == -1:
                    continue
                
                # Extract full component for validation
                full_component = content[match.start():brace_end + 1]
                
                # Find the first meaningful content (JSX or return statement)
                content_start = full_component.find('<')
                if content_start == -1:
                    content_start = full_component.find('return')
                
                if content_start > 0:
                    # Calculate actual positions in original content
                    actual_content_start = match.start() + content_start
                    snippet = full_component[content_start:].strip()[:2000]
                    
                    if len(snippet) > 30:
                        start_line = content[:actual_content_start].count('\n') + 1
                        end_line = content[:actual_content_start + len(snippet)].count('\n') + 1
                        components.append((snippet, start_line, end_line))
        except Exception as e:
            logger.debug(f"Function content extraction failed: {e}")
    
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
