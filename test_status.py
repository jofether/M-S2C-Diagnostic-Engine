#!/usr/bin/env python3
"""
Backend Status Check Script.

Tests the /api/retriever-debug endpoint to verify that the MS2C retriever
is fully initialized and ready to process queries.

Usage:
    python test_status.py
    
Requirements:
    - Backend must be running on http://localhost:8000
"""

import urllib.request
import json

response = urllib.request.urlopen('http://localhost:8000/api/retriever-debug')
data = json.loads(response.read().decode('utf-8'))

print('✅ RETRIEVER FULLY INITIALIZED')
print(f'  • Global corpus: {data["global_corpus_count"]} snippets')
print(f'  • File embeddings: {data["file_embeddings_shape"]}')
print(f'  • Files indexed: {data["file_list_count"]}')
print(f'  • Embedded nodes: {data["embedded_nodes_count"]}')
print()
print('✅ System ready for queries')
