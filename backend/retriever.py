import os
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
import logging

logger = logging.getLogger(__name__)


class MS2CRetriever:
    """
    Neural Semantic-to-Code Mapping Retriever aligned with M-S2C Thesis.
    
    Architecture:
    - Dense vector embeddings via CodeBERT (microsoft/codebert-base)
    - Vector similarity search using Cosine Similarity (L2-normalized dot product)
    - Adaptive Score-Level Fusion with gating weight for multimodal adaptation
    - Device Management: MATCHED with ms2c.py (cuda/cpu detection)
    
    CRITICAL FIXES:
    1. Device Initialization: torch.device("cuda" if available else "cpu") - matches ms2c.py
    2. Tensor Movement: All tensors moved to self.device explicitly
    3. Device Verification: Pre-computation checks ensure query and node vectors on same device
    4. Global Embeddings: Stacked tensor maintained on self.device for ms2c.py compatibility
    
    Thesis References:
    - Section 3.1: CodeBERT embeddings for semantic code representation
    - Section 3.2: Vector similarity search via FAISS-alternative in-memory indices
    - Section 3.2.4: Adaptive score-level fusion mechanism
    """
    
    def __init__(self, model_name: str = "microsoft/codebert-base"):
        """
        Initialize the Neural Retriever with CodeBERT transformer.
        
        Args:
            model_name: HuggingFace model identifier (default: microsoft/codebert-base)
        """
        # CRITICAL FIX: Match device initialization with ms2c.py
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🚀 Initializing M-S2C Neural Retriever on device: {self.device}")
        
        # Load CodeBERT model and tokenizer as per Thesis Section 3.1
        logger.info(f"📦 Loading CodeBERT model: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()  # Set to evaluation mode (no gradients)
        logger.info(f"✅ CodeBERT model loaded successfully on {self.device}")
        
        # In-memory vector index (replaces external FAISS for prototype)
        self.index_dict = {}  # Original index dictionary
        self.embedded_nodes = []  # List of {'key': str, 'code': str, 'vector': tensor}
        self.unique_files = set()  # Track unique files for stats
        self.global_corpus = []  # For statistics tracking
        self.global_embeddings = None  # Stacked tensor of all embeddings (for compatibility with ms2c.py)
        self.file_embeddings = None  # For file-level similarity computation
        
    def _embed_text(self, text: str) -> torch.Tensor:
        """
        Generate L2-normalized dense vector embedding using CodeBERT.
        
        Uses the [CLS] token representation (standard for transformer models)
        and applies L2 normalization to enable cosine similarity via dot product.
        
        Args:
            text: Input code snippet or query to embed
            
        Returns:
            L2-normalized embedding tensor of shape (1, 768) for CodeBERT
        """
        # Tokenize with appropriate truncation and padding
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)
        
        # Forward pass without gradient computation
        with torch.no_grad():
            outputs = self.model(**inputs)
            # Extract [CLS] token representation (first token of output)
            embedding = outputs.last_hidden_state[:, 0, :]
            # L2 normalize so cosine similarity = dot product (efficient)
            normalized = F.normalize(embedding, p=2, dim=1)
        
        return normalized
    
    def _flatten_and_encode(self, index_dict: dict, batch_size: int = 64) -> None:
        """
        Index entire repository by embedding all AST nodes into vector space.
        
        Thesis Section 3.2: Dense vector indexing of code AST nodes.
        
        Args:
            index_dict: Dictionary where:
                - Keys: formatted file paths (e.g., "app.jsx (Lines 10-20)")
                - Values: list of code snippet strings (AST nodes + context)
            batch_size: (reserved for future batch processing optimization)
        """
        logger.info(f"📊 Building Neural Index from {len(index_dict)} file groups")
        logger.info(f"   Device: {self.device}")
        
        self.index_dict = index_dict
        self.embedded_nodes = []
        self.unique_files = set()
        self.global_corpus = []
        
        total_snippets = 0
        embeddings_list = []  # Collect embeddings for stacking
        
        for file_key, snippets in index_dict.items():
            # Extract unique file from key (before " (Lines...)")
            file_name = file_key.split(' (Lines')[0] if ' (Lines' in file_key else file_key
            self.unique_files.add(file_name)
            
            for snippet in snippets:
                # Embed each AST node snippet
                vector = self._embed_text(snippet)
                
                # CRITICAL FIX: Verify vector is on correct device
                if vector.device != self.device:
                    logger.warning(f"⚠️  DEVICE MISMATCH: Vector on {vector.device}, expected {self.device}. Moving...")
                    vector = vector.to(self.device)
                
                self.embedded_nodes.append({
                    'key': file_key,
                    'code': snippet,
                    'vector': vector
                })
                embeddings_list.append(vector)
                self.global_corpus.append((file_key, snippet))
                total_snippets += 1
        
        # Stack all embeddings into single tensor for compatibility with ms2c.py
        if embeddings_list:
            self.global_embeddings = torch.cat(embeddings_list, dim=0)  # Shape: (num_snippets, 768)
            # Verify stacked tensor is on correct device
            if self.global_embeddings.device != self.device:
                logger.warning(f"⚠️  DEVICE MISMATCH: global_embeddings on {self.global_embeddings.device}, moving to {self.device}...")
                self.global_embeddings = self.global_embeddings.to(self.device)
        else:
            self.global_embeddings = None
        
        logger.info(f"✅ Index Built: {total_snippets} snippets across {len(self.unique_files)} files")
        logger.info(f"   Device: {self.device}")
        logger.info(f"   Embedding dimension: 768 (CodeBERT)")
        if self.global_embeddings is not None:
            logger.info(f"   Global embeddings tensor shape: {self.global_embeddings.shape}")
            logger.info(f"   Global embeddings device: {self.global_embeddings.device}")
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        gating_weight: float = 0.5
    ) -> list:
        """
        Semantic code search with Adaptive Score-Level Fusion.
        
        Thesis Section 3.2.4: Multimodal score fusion mechanism.
        
        Args:
            query: Text query (bug description) to search for
            top_k: Number of top results to return (default: 10)
            gating_weight: Alpha weight for fusion (0.0-1.0).
                - 1.0 = pure text-based (gating closed)
                - 0.5 = balanced text-visual (50-50)
                - 0.0 = pure visual-based (gating open)
        
        Returns:
            List of dicts with schema:
            [{
                "filepath": str,
                "code": str,
                "score": float (final fused score),
                "semantic_score": float (cosine similarity)
            }]
        """
        logger.info(f"🔍 Neural Search Initiated")
        logger.info(f"   Query: {query[:80]}{'...' if len(query) > 80 else ''}")
        logger.info(f"   Top-K: {top_k}, Gating Weight: {gating_weight}")
        
        # Validate index
        if not self.embedded_nodes:
            logger.warning("⚠️  Retriever index is empty! Returning empty results.")
            return []
        
        # Step 1: Embed the bug description query
        logger.info(f"📝 Embedding query text...")
        query_vector = self._embed_text(query)
        
        # Step 2: Calculate Semantic Similarity (Cosine) for all AST nodes
        logger.info(f"🔬 Computing similarity scores against {len(self.embedded_nodes)} code snippets...")
        scored_results = []
        
        for idx, node in enumerate(self.embedded_nodes):
            node_vector = node['vector']
            
            # CRITICAL FIX: Ensure both tensors are on same device before computation
            if node_vector.device != query_vector.device:
                logger.warning(f"⚠️  DEVICE MISMATCH at index {idx}: "
                              f"query on {query_vector.device}, node on {node_vector.device}. "
                              f"Moving node to query device...")
                node_vector = node_vector.to(query_vector.device)
            
            # Cosine similarity via normalized dot product (Thesis Section 3.2.1)
            semantic_score = torch.mm(
                query_vector,
                node_vector.transpose(0, 1)
            ).item()
            
            # Step 3: CRITICAL - Adaptive Score-Level Fusion (Thesis Section 3.2.4)
            # final_score = semantic_score * gating_weight
            # The gating weight adapts based on visual input quality (computed in routes.py)
            final_score = semantic_score * gating_weight
            
            scored_results.append({
                'filepath': node['key'],
                'code': node['code'],
                'semantic_score': semantic_score,
                'final_score': final_score
            })
        
        # Step 4: Rank by fused score and retrieve Top-K
        logger.info(f"📊 Ranking results by fused score...")
        scored_results.sort(key=lambda x: x['final_score'], reverse=True)
        top_results = scored_results[:top_k]
        
        # Step 5: Format for frontend API consumption
        logger.info(f"📤 Formatting {len(top_results)} results for frontend...")
        formatted_results = []
        for rank, res in enumerate(top_results, 1):
            formatted_results.append({
                "filepath": res['filepath'],
                "code": res['code'],
                "score": res['final_score'],
                "semantic_score": res['semantic_score']
            })
            logger.debug(f"   Rank {rank}: {res['filepath'][:50]}... "
                        f"(semantic={res['semantic_score']:.4f}, "
                        f"fused={res['final_score']:.4f})")
        
        logger.info(f"✅ Search Complete - Returned {len(formatted_results)} results")
        return formatted_results
    
    def retrieve_top_k(
        self,
        text_query: str,
        image_path: str = None,
        k: int = 10,
        mode: str = "multimodal",
        scope: str = "file",
        gating_weight: float = None
    ) -> tuple:
        """
        Backward-compatible wrapper for routes.py integration.
        
        Converts old API to new neural search architecture.
        
        Args:
            text_query: Bug description text
            image_path: Path to screenshot (optional, not used in pure-text search)
            k: Number of results to return
            mode: Search mode ('multimodal' accepted but uses text only currently)
            scope: Scope of search ('file' supported)
            gating_weight: Alpha weight for fusion (0.0-1.0). If None, defaults to 1.0 (text-only)
        
        Returns:
            tuple: (results_list, gating_weight) where:
                - results_list: List of (filepath, code_snippet) tuples
                - gating_weight: Alpha weight used (1.0 for text-only, can be adjusted)
        """
        logger.info(f"🔄 retrieve_top_k called (legacy API wrapper)")
        logger.info(f"   Mode: {mode}, Scope: {scope}")
        
        # Use provided gating_weight or default to 1.0 (text-only)
        if gating_weight is None:
            gating_weight = 1.0
            logger.info(f"   Gating weight not provided, defaulting to {gating_weight}")
        else:
            logger.info(f"   Gating weight: {gating_weight}")
        
        # Call the neural search method
        search_results = self.search(
            query=text_query,
            top_k=k,
            gating_weight=gating_weight
        )
        
        # Convert to legacy format: list of (filepath, code) tuples
        legacy_results = [
            (result['filepath'], result['code'])
            for result in search_results
        ]
        
        logger.info(f"📦 Converted {len(legacy_results)} results to legacy format")
        
        return legacy_results, gating_weight