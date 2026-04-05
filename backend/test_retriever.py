#!/usr/bin/env python
"""Quick test of retrieve_top_k function"""

from retriever import MS2CRetriever

print('Creating retriever...')
retriever = MS2CRetriever()
print('✓ retriever created')

# Check state
print(f'Global corpus: {len(retriever.global_corpus) if retriever.global_corpus else "N/A"}')
print(f'Global embeddings: {retriever.global_embeddings is not None}')

# Try a retrieval
try:
    print('\n🔍 Attempting retrieve_top_k with test query...')
    results, alpha_text, alpha_visual = retriever.retrieve_top_k('navigation menu display issue')
    print(f'✓ Results: {len(results)} candidates')
    print(f'✓ Alpha text: {alpha_text}, Alpha visual: {alpha_visual}')
    
    if results:
        print(f'\nFirst result:')
        file_path, code, score = results[0]
        print(f'  File: {file_path}')
        print(f'  Code: {code[:100]}...')
        print(f'  Score: {score}')
    
except Exception as e:
    print(f'❌ ERROR: {e}')
    import traceback
    traceback.print_exc()
