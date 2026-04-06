import os
import json
import re
import subprocess

"""
=========================================================================================
Repository AST Indexer
=========================================================================================
Scans full repositories and extracts opening JSX/HTML tags.
Uses a custom state-machine parser to handle JSX complexities like arrow functions 
(e.g., () =>) and inline conditional rendering without breaking string capture.

UPDATES:
- Maintains perfect chronological order (No deduplication).
- Injects line number ranges: (L:x-y) for multi-line tags, (L:x) for single-line.
- Brace-Aware Look-ahead context: Strips JS logic, captures STRICTLY immediate inner text.
- REMOVED closing tags from output (tracks depth silently).
- FIXED trailing JS bleed (e.g., ];) in inner text extraction.
- FIXED self-closing tag bug (aborts look-ahead for tags ending in />).
- Git Fallback: Safely attempts 'buggy' branch, falls back to default branch if missing.
=========================================================================================
"""

# ==============================================================================
# MASTER CONFIGURATION TOGGLES
# ==============================================================================
IS_TESTING = True  # False = validation dataset, True = testing dataset


# ==============================================================================

def extract_nodes_from_file(filepath):
    """
    Scans an entire file and extracts every opening JSX/HTML tag as an AST node,
    appending a [n] depth level indicator, line ranges, and text-only look-ahead.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            content = file.read()
    except Exception as e:
        print(f"      -> [WARNING] Could not read {filepath}: {e}")
        return []

    # =========================================================================
    # CUSTOM JSX STATE MACHINE PARSER
    # =========================================================================
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
                            if content[j - 1] != '\\':
                                in_quotes = None
                        elif not in_quotes:
                            in_quotes = char

                    elif char == '{' and not in_quotes:
                        brace_depth += 1
                    elif char == '}' and not in_quotes:
                        brace_depth = max(0, brace_depth - 1)

                    elif char == '>' and not in_quotes and brace_depth == 0:
                        tag_string = content[start:j + 1]

                        # Calculate Start and End Lines
                        start_line = content.count('\n', 0, start) + 1
                        end_line = content.count('\n', 0, j) + 1

                        lookahead_info = ""

                        if not tag_string.strip().endswith('/>'):
                            k = j + 1
                            inner_content = ""
                            lookahead_brace_depth = 0

                            while k < n and content[k] != '<':
                                la_char = content[k]

                                if la_char == '{':
                                    lookahead_brace_depth += 1
                                elif la_char == '}':
                                    lookahead_brace_depth = max(0, lookahead_brace_depth - 1)
                                elif lookahead_brace_depth == 0:
                                    inner_content += la_char
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

    # =========================================================================
    # DEPTH TRACKING & FORMATTING (SILENT CLOSING TAGS)
    # =========================================================================
    nodes = []
    current_depth = 0

    for tag_string, s_line, e_line, lookahead_info in raw_tags:
        clean_tag = " ".join(tag_string.split())

        if clean_tag.startswith("</"):
            current_depth = max(0, current_depth - 1)
        else:
            node_depth = current_depth + 1

            # Line Range Formatting
            if s_line == e_line:
                line_marker = f"(L:{s_line})"
            else:
                line_marker = f"(L:{s_line}-{e_line})"

            formatted_node = f"[{node_depth}] {line_marker} {clean_tag}{lookahead_info}"
            nodes.append(formatted_node)

            if not clean_tag.endswith("/>") and clean_tag != "<>":
                current_depth += 1

    return nodes


def run_repo_indexer():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    prefix = "testing_repository" if IS_TESTING else "validation_repository"
    res_prefix = f"{prefix}_results"

    json_path = os.path.join(base_dir, prefix, f"{prefix.split('_')[0]}_dataset.json")
    results_dir = os.path.join(base_dir, res_prefix, "indexed_nodes")
    repos_dir = os.path.join(base_dir, prefix, "cloned_repos")

    os.makedirs(repos_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)

    print(f"[TRACE] Loading repository queries from {json_path}...")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            queries_data = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Could not find query dataset at {json_path}")
        return

    unique_repos = list(set([item["github_repo"] for item in queries_data]))
    print(f"[TRACE] Processing {len(unique_repos)} repositories.")

    for repo_url in unique_repos:
        repo_name = repo_url.split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        repo_path = os.path.join(repos_dir, repo_name)

        if not os.path.exists(repo_path):
            print(f"\n[TRACE] Attempting to clone the 'buggy' branch of {repo_name} from GitHub...")
            try:
                subprocess.run(["git", "clone", "-b", "buggy", "--single-branch", repo_url, repo_path], check=True)
            except subprocess.CalledProcessError:
                print(f"[WARNING] The 'buggy' branch does not exist for {repo_name}. Falling back to default branch...")
                try:
                    subprocess.run(["git", "clone", repo_url, repo_path], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] Failed to clone {repo_name} completely: {e}")
                    continue
        else:
            print(f"\n[TRACE] Repository {repo_name} already cloned locally. Skipping download.")

        print(f"[TRACE] Traversing files and indexing AST nodes in {repo_name}...")
        repo_index = {}
        total_nodes = 0

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if
                       not d.startswith('.') and d not in ['node_modules', 'dist', 'build', 'coverage']]

            for file in files:
                if file.endswith((".jsx", ".js", ".tsx", ".ts")):
                    full_filepath = os.path.join(root, file)

                    relative_path = os.path.relpath(full_filepath, repo_path)
                    relative_path = relative_path.replace("\\", "/")

                    nodes = extract_nodes_from_file(full_filepath)

                    if nodes:
                        repo_index[relative_path] = nodes
                        total_nodes += len(nodes)

        output_path = os.path.join(results_dir, f"{repo_name}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(repo_index, f, indent=4)

        print(f"[TRACE] SUCCESS: Indexed {total_nodes} nodes across {len(repo_index)} files in {repo_name}.")
        print(f"[TRACE] Library saved to {output_path}")


if __name__ == "__main__":
    run_repo_indexer()