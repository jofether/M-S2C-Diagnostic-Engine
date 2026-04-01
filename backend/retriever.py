"""
MS2CRetriever - Mock semantic code retriever using keyword matching and scoring
"""

import logging

logger = logging.getLogger(__name__)


class MS2CRetriever:
    """Mock retriever that uses keyword-based ranking on indexed files"""
    
    def __init__(self, model_path="", index_dict=None):
        self.index_dict = index_dict or {}
        self.unique_files = list(index_dict.keys()) if index_dict else []
        self.global_corpus = []
        
        # Flatten the index
        for file_path, snippets in index_dict.items():
            for snippet in snippets:
                self.global_corpus.append((file_path, snippet))
        
        print(f"✅ Mock MS2CRetriever initialized with {len(self.unique_files)} files and {len(self.global_corpus)} snippets")
    
    def retrieve_top_k(self, text_query, image_path=None, k=3, mode="multimodal", scope="file"):
        """
        Mock retrieval using keyword matching and snippet similarity.
        Returns top-k results from the indexed corpus.
        """
        if not self.global_corpus:
            print("⚠️  No indexed corpus available")
            return [], 1.0
        
        query_lower = text_query.lower()
        query_words = set(query_lower.split())
        
        logger.info(f"🔍 RETRIEVER: Query = '{text_query}'")
        logger.info(f"📝 RETRIEVER: Query words = {query_words}")
        
        # Score each file based on keyword matches in snippets
        file_scores = {}
        file_score_details = {}  # For logging
        
        for file_path, snippet in self.global_corpus:
            if file_path not in file_scores:
                file_scores[file_path] = 0.0
                file_score_details[file_path] = []
            
            snippet_lower = snippet.lower()
            file_name_lower = file_path.lower()
            
            # All query words combined (for substring matching)
            full_query = " ".join(query_words)
            
            # Strong bonus: query appears as substring in filename
            if full_query in file_name_lower:
                score = 1000  # Very high score for exact substring match
                file_score_details[file_path].append(f"Full query substring in filename: +1000")
            else:
                # Regular word-based matching
                snippet_matches = sum(1 for word in query_words if len(word) > 2 and word in snippet_lower)
                
                # Bonus for file name matches (higher weight: 10x for semantic matching)  
                file_name_matches = sum(1 for word in query_words if len(word) > 2 and word in file_name_lower)
                
                # Enhanced scoring for CSS/styling-related keywords
                css_keywords = {'opacity', 'transparent', 'css', 'badge', 'className', 'style', 'washed', 'rendered'}
                styling_bonus = sum(10 for word in query_words if word in css_keywords and word in snippet_lower)
                
                # Component-specific bonus for contextual features
                # If query mentions "hero" or "banner" and file is *Hero, give big bonus
                semantic_bonus = 0
                if any(word in query_lower for word in ['hero', 'banner', 'recipe']):
                    if 'hero' in file_name_lower:
                        semantic_bonus += 50
                    if 'recipe' in file_name_lower:
                        semantic_bonus += 20
                
                # Search/input field related bonus
                if any(word in query_lower for word in ['search', 'input', 'type', 'field', 'query', 'text', 'enter']):
                    if 'app' in file_name_lower or 'main' in file_name_lower or 'index' in file_name_lower:
                        semantic_bonus += 40  # These are likely root-level files
                    if any(term in snippet_lower for term in ['search', 'input', 'type', 'query', 'placeholder']):
                        semantic_bonus += 30
                
                # Give bonus for UI component terms appearing in both query and filename
                ui_terms = {'badge', 'difficulty', 'level', 'rating', 'card', 'display', 'show', 'render'}
                for term in ui_terms:
                    if term in query_lower and term in file_name_lower:
                        semantic_bonus += 30  # Strong bonus for semantic match
                    elif term in query_lower and term in snippet_lower:
                        semantic_bonus += 5
                
                score = snippet_matches + (file_name_matches * 10) + styling_bonus + semantic_bonus
                
                if snippet_matches > 0:
                    file_score_details[file_path].append(f"Snippet matches: +{snippet_matches}")
                if file_name_matches > 0:
                    file_score_details[file_path].append(f"Filename matches (×10): +{file_name_matches * 10}")
                if styling_bonus > 0:
                    file_score_details[file_path].append(f"CSS keywords bonus: +{styling_bonus}")
                if semantic_bonus > 0:
                    file_score_details[file_path].append(f"Semantic bonus: +{semantic_bonus}")
            
            file_scores[file_path] += score
        
        # LOG: Show all scored files
        logger.info(f"📊 SCORING DETAILS:")
        for file_path, score in sorted(file_scores.items(), key=lambda x: x[1], reverse=True):
            details = " | ".join(file_score_details[file_path]) if file_score_details[file_path] else "No matches"
            logger.info(f"  [{score:6.1f}] {file_path} → {details}")
        
        # Sort by score
        sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
        logger.info(f"🏆 RETRIEVER: Top {k} results selected:")
        
        # Get top k files with their snippets
        results = []
        for i, (file_path, score) in enumerate(sorted_files[:k]):
            # Find first snippet for this file
            for fp, snippet in self.global_corpus:
                if fp == file_path:
                    results.append((file_path, snippet))
                    logger.info(f"  {i+1}. {file_path} (score: {score:.1f})")
                    break
        
        # Ensure we have exactly k results
        if len(results) < k:
            # Fill with remaining snippets
            used_files = {r[0] for r in results}
            for fp, snippet in self.global_corpus:
                if fp not in used_files and len(results) < k:
                    results.append((fp, snippet))
                    used_files.add(fp)
        
        alpha = 0.5 if mode == "multimodal" else 1.0
        return results[:k], alpha
    
    def _flatten_and_encode(self, index_dict, batch_size=64):
        """Mock method to accept index dict updates"""
        self.index_dict = index_dict
        self.unique_files = list(index_dict.keys())
        self.global_corpus = []
        for file_path, snippets in index_dict.items():
            for snippet in snippets:
                self.global_corpus.append((file_path, snippet))
        print(f"✅ Mock retriever updated with {len(self.unique_files)} files")


async def reindex_retriever(retriever, index_dict, pytorch_available=False):
    """Update the global retriever with newly indexed data"""
    try:
        retriever._flatten_and_encode(index_dict, batch_size=64)
        logger.info(f"✅ Retriever re-indexed with {len(index_dict)} files")
    except Exception as e:
        logger.error(f"❌ Failed to re-index retriever: {e}")
        raise
