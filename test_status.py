#!/usr/bin/env python3
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
