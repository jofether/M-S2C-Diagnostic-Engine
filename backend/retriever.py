"""
M-S2C Thesis-Aligned 4-Stage Cascading Retrieval Pipeline

Implements the complete neural retrieval architecture from the MS2C thesis:
  Stage 1: NLP Token Generation (stopword removal + stemming)
  Stage 2: Document Filtration (file-level semantic + lexical matching)
  Stage 3: Multimodal Fused Scoring (CodeBERT + ViT with gating)
  Stage 4: Heuristic Matrix Boosting (4-tier boosting system)

Author: MS2C Thesis Implementation
"""

import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel, ViTModel, ViTImageProcessor
from PIL import Image
import logging
import re
from config import (
    ALPHA_CONFIDENCE_THRESHOLD, ALPHA_HIGH_CONFIDENCE_LOCK,
    ALPHA_MIN_FLOOR, ALPHA_MAX_CEILING, ALPHA_BASE_BONUS,
    BOOST_TIER_0_FILENAME, BOOST_TIER_1_TAG,
    BOOST_TIER_2_CLASS_FULL, BOOST_TIER_2_PARTIAL,
    BOOST_SVG_PENALTY, WORD_MIN_LENGTH
)

logger = logging.getLogger(__name__)


class MS2CRetriever:
    """
    Thesis-Aligned 4-Stage Cascading Retrieval Pipeline.
    
    Core Architecture:
    - CodeBERT for text embeddings (768-dim)
    - ViT for image embeddings (768-dim)
    - NLP token normalization with stemming
    - Document-level and node-level heuristic boosting
    
    Thesis References:
    - Section 3.1: CodeBERT embeddings for semantic code representation
    - Section 3.2: Vector similarity search via dense embeddings
    - Section 3.3: NLP token processing with stemming and stopwords
    - Section 3.4: Heuristic matrix boosting with 4-tier system
    - Section 3.5: Multimodal score fusion with gating weights
    """
    
    # Stopwords for stage 1
    STOPWORDS = {
        "the", "are", "was", "were", "been", "being", "for", "with", "from", "into", "after", "then",
        "once", "here", "there", "when", "where", "why", "how", "both", "each", "few", "such", "nor",
        "not", "only", "own", "than", "too", "very", "can", "will", "just", "now", "its", "they",
        "them", "their", "this", "that", "these", "those", "our", "you", "your", "yours", "him", "his",
        "she", "her", "hers", "and", "but", "while", "until", "does", "did", "doing", "has", "have",
        "had", "a", "an", "in", "on", "at", "to", "by", "is", "be", "as", "or"
    }
    

    
    def __init__(self, model_name: str = "microsoft/codebert-base"):
        """Initialize the retriever with CodeBERT and ViT models."""
        
        # Device management
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🚀 Initializing M-S2C Retriever on device: {self.device}")
        
        # Load CodeBERT for text embeddings
        logger.info(f"📦 Loading CodeBERT: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.codebert_model = AutoModel.from_pretrained(model_name).to(self.device)
        self.codebert_model.eval()
        logger.info(f"✅ CodeBERT loaded successfully")
        
        # Load ViT for image embeddings
        logger.info(f"📦 Loading ViT: google/vit-base-patch16-224-in21k")
        self.vit_model = ViTModel.from_pretrained("google/vit-base-patch16-224-in21k").to(self.device)
        self.image_processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224-in21k")
        self.vit_model.eval()
        logger.info(f"✅ ViT loaded successfully")
        
        # Neural Gating Network for multimodal fusion
        # Learns to dynamically weight text vs visual contributions
        hidden_dim = 768
        self.gating_network = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid()
        ).to(self.device)
        logger.info(f"📊 Gating Network initialized for dynamic alpha weighting")
        
        # Index storage
        self.index_dict = {}
        self.embedded_nodes = []
        self.unique_files = set()
        self.file_list = []  # ORDERED list of files (for consistent indexing)
        self.global_corpus = []
        self.global_embeddings = None
        self.file_embeddings = None  # Phase 2: File-level embeddings for document filtration
        self.file_to_node_indices = {}  # Mapping: file_path → list of node indices
        logger.info("✅ MS2CRetriever initialized")
    
    def encode_text(self, text: str) -> torch.Tensor:
        """
        Encode text using CodeBERT and return L2-normalized embedding.
        
        Returns:
            Tensor of shape (1, 768)
        """
        if not isinstance(text, str):
            text = str(text)
        
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.codebert_model(**inputs)
            embedding = outputs.last_hidden_state[:, 0, :]
            normalized = F.normalize(embedding, p=2, dim=1)
        
        return normalized
    
    def encode_image(self, image: Image.Image) -> torch.Tensor:
        """
        Encode image using ViT and return L2-normalized embedding.
        
        Returns:
            Tensor of shape (1, 768)
        """
        # Ensure RGB
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        inputs = self.image_processor(images=image, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.vit_model(**inputs)
            embedding = outputs.last_hidden_state[:, 0, :]
            normalized = F.normalize(embedding, p=2, dim=1)
        
        return normalized
    
    def compute_gating_weight(self, text_emb: torch.Tensor, visual_emb: torch.Tensor) -> torch.Tensor:
        """
        Neural Gating Network: Learns to dynamically weight text vs visual contributions.
        
        Args:
            text_emb: CodeBERT embedding (1, 768)
            visual_emb: ViT embedding (1, 768)
        
        Returns:
            Scalar weight for text (0.0-1.0) representing confidence in text input
        """
        with torch.no_grad():
            combined = torch.cat([text_emb, visual_emb], dim=1)
            gate_weight = self.gating_network(combined)
        return gate_weight
    
    def _normalize_tokens(self, text: str) -> set:
        """
        Stage 1: NLP Token Generation
        - Remove stopwords
        - Apply stemming (plurals, -ies, -es, -s)
        - Apply semantic mapping (generic terms → technical tags)
        - Return normalized word set
        """
        query_lower = text.lower()
        
        # Remove non-alphanumeric  
        query_lower = re.sub(r'[^a-z0-9\s]', ' ', query_lower)
        
        # Split and filter
        query_words_set = set()
        for word in query_lower.split():
            if len(word) > 2 and word not in self.STOPWORDS:
                query_words_set.add(word)
                
                # Apply stemming variants
                if len(word) > 4 and word.endswith('ies'):
                    query_words_set.update([word[:-3], word[:-3] + 'y'])
                elif len(word) > 3 and word.endswith('es') and not word.endswith('ses'):
                    query_words_set.update([word[:-1], word[:-2]])
                elif len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
                    query_words_set.add(word[:-1])
        
        return query_words_set
    
    def _flatten_and_encode(self, index_dict: dict, batch_size: int = 64) -> None:
        """
        Build index and encode all nodes into embeddings using batch processing.
        Also computes file-level embeddings for Phase 2 document filtration.
        
        Args:
            index_dict: Dictionary mapping file paths to list of node dicts with 'code_snippet' field
            batch_size: Batch size for encoding (default 64 for VRAM safety)
        """
        logger.info(f"📊 Building Neural Index from {len(index_dict)} files...")
        
        self.index_dict = index_dict
        self.embedded_nodes = []
        self.unique_files = set(index_dict.keys())
        self.file_list = []  # CLEAR old file list for new repo
        self.global_corpus = []
        self.file_to_node_indices = {}  # Phase 2: Map files to node indices
        
        # First pass: collect all code snippets and metadata
        all_code_snippets = []
        code_to_metadata = []
        file_aggregates = {}  # Aggregate snippets per file
        node_idx = 0
        
        for file_path, nodes in index_dict.items():
            self.file_list.append(file_path)  # MAINTAIN ORDERED FILE LIST
            file_aggregates[file_path] = []
            self.file_to_node_indices[file_path] = []
            
            for node_dict in nodes:
                code_text = node_dict.get("code_snippet", "")
                line_number = node_dict.get("line_number", "?")
                
                # Extract full line range from code_snippet (e.g., "[7] (L:115-119)" → "L:115-119")
                # This ensures the file_path has the complete range, not just the start line
                line_range = "?"
                if code_text:
                    import re
                    line_match = re.search(r'\(L:(\d+(?:-\d+)?)\)', code_text)
                    if line_match:
                        line_range = f"L:{line_match.group(1)}"
                
                # Store file_path with full line range for display
                file_with_line = f"{file_path} ({line_range})" if line_range != "?" else file_path
                all_code_snippets.append(code_text)
                code_to_metadata.append((file_with_line, code_text))
                self.global_corpus.append((file_with_line, code_text))
                
                # Track node index for this file (Phase 2)
                self.file_to_node_indices[file_path].append(node_idx)
                node_idx += 1
                
                # Aggregate for file-level embedding
                file_aggregates[file_path].append(code_text)
        
        logger.info(f"   Encoding {len(all_code_snippets)} snippets with batch_size={batch_size}...")
        
        # Second pass: encode in batches for VRAM efficiency
        all_embeddings = []
        with torch.no_grad():
            for batch_start in range(0, len(all_code_snippets), batch_size):
                batch_end = min(batch_start + batch_size, len(all_code_snippets))
                batch_texts = all_code_snippets[batch_start:batch_end]
                
                try:
                    # Batch encode using tokenizer
                    batch_inputs = self.tokenizer(
                        batch_texts,
                        return_tensors="pt",
                        truncation=True,
                        max_length=512,
                        padding=True
                    ).to(self.device)
                    
                    batch_outputs = self.codebert_model(**batch_inputs)
                    batch_embeddings = batch_outputs.last_hidden_state[:, 0, :]
                    batch_embeddings = F.normalize(batch_embeddings, p=2, dim=1)
                    
                    all_embeddings.append(batch_embeddings.cpu())
                    
                    # Update embedded_nodes
                    for i, (file_path, code_text) in enumerate(code_to_metadata[batch_start:batch_end]):
                        self.embedded_nodes.append({
                            'file': file_path,
                            'code': code_text,
                            'vector': batch_embeddings[i].cpu()
                        })
                    
                except Exception as e:
                    logger.warning(f"Failed to encode batch [{batch_start}:{batch_end}]: {e}")
                    continue
        
        if all_embeddings:
            self.global_embeddings = torch.cat(all_embeddings, dim=0).to(self.device)
            logger.info(f"✅ Index Built: {len(self.embedded_nodes)} snippets, shape: {self.global_embeddings.shape}")
        else:
            logger.warning("⚠️  No embeddings created!")
        
        # Phase 2 Enhancement: Compute file-level embeddings by aggregating node embeddings
        logger.info(f"📊 Computing file-level embeddings for document filtration...")
        file_embeddings_list = []
        
        for file_path in self.file_list:  # Use ordered file_list instead of unordered set
            node_indices = self.file_to_node_indices[file_path]
            if node_indices and self.global_embeddings is not None:
                # Average pooling of node embeddings to create file-level representation
                file_node_embeddings = self.global_embeddings[node_indices]
                file_embedding = file_node_embeddings.mean(dim=0, keepdim=True)
                file_embedding = F.normalize(file_embedding, p=2, dim=1)
                file_embeddings_list.append(file_embedding)
        
        if file_embeddings_list:
            self.file_embeddings = torch.cat(file_embeddings_list, dim=0)
            logger.info(f"✅ File-level embeddings computed: {self.file_embeddings.shape}")
    
    def retrieve_top_k(self, text_query: str, k: int = 10, 
                       target_file: str = None, image_path: str = None) -> tuple:
        """
        Execute 4-stage cascading retrieval pipeline.
        
        Phase 1: NLP Token Generation → normalized tokens
        Phase 2: Document Filtration → Top 5 candidate files via semantic similarity
        Phase 3: Multimodal Scoring (CodeBERT + ViT with gating) → node-level scores within Top 5
        Phase 4: Heuristic Reranking → 4-tier boosting
        
        Returns:
            tuple: (results_list, alpha_text, alpha_visual)
                - results_list: List of (file_path, code_snippet) tuples
                - alpha_text: Quality weight for text (0.0-1.0)
                - alpha_visual: Quality weight for visual (0.0-1.0)
        """
        print(f"\n\n🚀🚀🚀 RETRIEVE_TOP_K ENTRY POINT 🚀🚀🚀", flush=True)
        
        try:
            logger.info(f"🔍 RETRIEVE_TOP_K() CALLED")
            logger.info(f"   global_embeddings is None: {self.global_embeddings is None}")
            logger.info(f"   global_embeddings shape: {self.global_embeddings.shape if self.global_embeddings is not None else 'N/A'}")
            logger.info(f"   global_corpus length: {len(self.global_corpus)}")
            logger.info(f"   text_query: {text_query[:60]}...")
            
            print(f"🔍 RETRIEVE_TOP_K() CALLED - STDOUT")
            print(f"   global_corpus: {len(self.global_corpus)}")
            print(f"   global_embeddings: {self.global_embeddings is not None}")
            
            if self.global_embeddings is None or len(self.global_corpus) == 0:
                logger.warning(f"🛑 Index is empty! Returning empty results")
                logger.warning(f"   global_embeddings is None: {self.global_embeddings is None}")
                logger.warning(f"   len(global_corpus): {len(self.global_corpus)}")
                print(f"🛑 INDEX EMPTY - STDOUT")
                return [], 0.5, 0.5
            
            # ============= PHASE 1: NLP TOKEN GENERATION =============
            logger.info(f"🔍 PHASE 1: NLP Token normalization...")
            query_words_set = self._normalize_tokens(text_query)
            logger.info(f"   Normalized tokens: {query_words_set if query_words_set else 'none'}")
            
            # Embed query (for phases 2 & 3)
            query_emb = self.encode_text(text_query)
            logger.info(f"   Query embedding shape: {query_emb.shape}")
            
        except Exception as e:
            logger.error(f"🛑 ERROR IN RETRIEVE_TOP_K PHASE 1: {e}")
            import traceback
            traceback.print_exc()
            return [], 0.5, 0.5
        
        # ============= PHASE 2: DOCUMENT FILTRATION =============
        logger.info(f"🔍 PHASE 2: Document filtration (rough pass)...")
        logger.info(f"   file_list size: {len(self.file_list)}")
        logger.info(f"   file_embeddings available: {self.file_embeddings is not None}")
        if self.file_embeddings is not None:
            logger.info(f"   file_embeddings shape: {self.file_embeddings.shape}")
        
        # Rough Pass: File-level semantic similarity (if file embeddings available)
        candidate_files = list(self.file_list)  # Use ordered file list
        
        if self.file_embeddings is not None and len(self.file_embeddings) > 0:
            # Compute file-level similarities
            file_similarities = torch.matmul(query_emb, self.file_embeddings.T).squeeze(0)
            
            # TIER 0 PRIORITY: If target_file is provided, GUARANTEE it's in Top 5
            if target_file:
                # Find the target file in our file list
                target_file_candidates = [f for f in self.file_list if target_file in f]
                logger.info(f"   🔴 TIER 0: Target file priority check - looking for '{target_file}'")
                
                if target_file_candidates:
                    # Get remaining files based on semantic similarity (exclude target file)
                    target_idx_in_similarities = None
                    for i, f in enumerate(self.file_list):
                        if f in target_file_candidates:
                            target_idx_in_similarities = i
                            break
                    
                    # Get top 4 other files (to make 5 total including target)
                    other_indices = []
                    for idx in torch.topk(file_similarities, min(5, len(self.file_list))).indices.tolist():
                        if idx != target_idx_in_similarities:
                            other_indices.append(idx)
                        if len(other_indices) >= 4:
                            break
                    
                    # Build final candidate list: target file FIRST, then 4 others
                    candidate_files = target_file_candidates + [self.file_list[idx] for idx in other_indices]
                    candidate_files = candidate_files[:5]  # Ensure max 5 files
                    
                    logger.info(f"   ✅ TIER 0 APPLIED: Target file guaranteed in Top 5")
                    logger.info(f"   File-level filtering: {len(self.file_list)} → {len(candidate_files)} files")
                    for i, fname in enumerate(candidate_files):
                        logger.info(f"     {i+1}. {fname}")
                else:
                    logger.warning(f"   ⚠️  Target file '{target_file}' not found in index")
                    # Fall back to semantic ranking
                    top_file_count = min(5, len(candidate_files))
                    top_file_indices = torch.topk(file_similarities, top_file_count).indices.tolist()
                    candidate_files = [self.file_list[idx] for idx in top_file_indices]
            else:
                # No target file: use pure semantic similarity
                top_file_count = min(5, len(candidate_files))
                top_file_indices = torch.topk(file_similarities, top_file_count).indices.tolist()
                candidate_files = [self.file_list[idx] for idx in top_file_indices]
                
                logger.info(f"   File-level filtering: {len(self.file_list)} → {len(candidate_files)} files")
                for i, fname in enumerate(candidate_files):
                    logger.info(f"     {i+1}. {fname}")
        else:
            logger.warning("   File embeddings not available, including all files")
        
        # Build valid node indices from candidate files only
        logger.info(f"   Building valid_indices from {len(candidate_files)} candidate files...")
        valid_indices = []
        for file_path in candidate_files:
            if file_path in self.file_to_node_indices:
                node_count = len(self.file_to_node_indices[file_path])
                valid_indices.extend(self.file_to_node_indices[file_path])
                logger.info(f"     ✓ {file_path}: {node_count} nodes")
            else:
                logger.warning(f"     ✗ {file_path}: NOT FOUND in file_to_node_indices!")
        
        if not valid_indices:
            logger.warning("   No nodes found in candidate files")
            logger.warning(f"   Available keys in file_to_node_indices: {list(self.file_to_node_indices.keys())}")
            return [], 0.5, 0.5
        
        logger.info(f"   Phase 2 Result: {len(valid_indices)} nodes from top-5 files")
        
        # ============= PHASE 3: MULTIMODAL FUSION & GATING =============
        logger.info(f"🔍 PHASE 3: Multimodal scoring with neural gating...")
        
        # Compute text similarity ONLY for valid_indices (Top 5 files)
        valid_embeddings = self.global_embeddings[valid_indices]
        text_sim_all = torch.matmul(query_emb, self.global_embeddings.T).squeeze(0)
        text_sim_filtered = text_sim_all[valid_indices]
        
        # Initialize alpha values
        alpha_text = 1.0
        alpha_visual = 0.0
        
        # Handle multimodal case (image provided)
        if image_path:
            logger.info(f"🎬 MULTIMODAL MODE: Vision Transformer will be used for visual scoring")
            try:
                image = Image.open(image_path).convert("RGB")
                img_emb = self.encode_image(image)
                
                # Compute visual similarity ONLY for valid_indices (Top 5 files)
                vis_sim_all = torch.matmul(img_emb, self.global_embeddings.T).squeeze(0)
                vis_sim_filtered = vis_sim_all[valid_indices]
                
                # 🔴 NEURAL GATING: Compute base alpha
                base_alpha = self.compute_gating_weight(query_emb, img_emb).item()
                logger.info(f"   Neural Gating Weight (base): {base_alpha:.4f}")
                
                # ⚠️  CRITICAL SAFETY CLAMPING (Thesis Rule 2: High-Confidence Lock)
                # If top text confidence is very high (>threshold), lock alpha to configured value (trust text)
                top_text_confidence = text_sim_filtered.max().item()
                logger.info(f"   Top text confidence in Top-5 files: {top_text_confidence:.4f}")
                
                if top_text_confidence > ALPHA_CONFIDENCE_THRESHOLD:
                    # Rule 2: High-Confidence Lock
                    alpha_text = ALPHA_HIGH_CONFIDENCE_LOCK
                    logger.info(f"   🔴 RULE 2 TRIGGERED: Text confidence > {ALPHA_CONFIDENCE_THRESHOLD}, locking alpha_text = {ALPHA_HIGH_CONFIDENCE_LOCK}")
                else:
                    # Rule 1: Minimum floor enforcement
                    base_clamped = torch.clamp(
                        torch.tensor(base_alpha + ALPHA_BASE_BONUS),
                        min=ALPHA_MIN_FLOOR,
                        max=ALPHA_MAX_CEILING
                    ).item()
                    alpha_text = base_clamped
                    logger.info(f"   🔴 RULE 1 APPLIED: Clamping alpha to [{ALPHA_MIN_FLOOR}, {ALPHA_MAX_CEILING}] range")
                
                alpha_visual = 1.0 - alpha_text
                
                logger.info(f"   ✅ Final Gating Weights: α_text={alpha_text:.4f}, α_visual={alpha_visual:.4f}")
                
                # Fuse scores using final alpha (ONLY within Top-5 files)
                final_scores = (alpha_text * text_sim_filtered) + (alpha_visual * vis_sim_filtered)
                
            except Exception as e:
                logger.warning(f"Image scoring failed: {e}, using text only")
                final_scores = text_sim_filtered
                alpha_text = 1.0
                alpha_visual = 0.0
        else:
            # TEXT-ONLY MODE: Use text similarity only
            final_scores = text_sim_filtered
            alpha_text = 1.0
            alpha_visual = 0.0
            logger.info(f"📝 TEXT-ONLY MODE: No image provided (alpha_text=1.0, alpha_visual=0.0)")
        
        # ============= PHASE 4: HEURISTIC MATRIX BOOSTING =============
        logger.info(f"🔍 PHASE 4: Heuristic boosting (4-tier system)...")
        boost_tensor = torch.zeros_like(final_scores)
        
        invalid_markers = ["<svg", "<path", "<g ", "<circle", "<rect", "<line", "<polygon"]
        
        for i, global_idx in enumerate(valid_indices):
            file_path, code_snippet = self.global_corpus[global_idx]
            code_lower = code_snippet.lower()
            
            # Skip SVG/graphics (penalty)
            if any(m in code_lower for m in invalid_markers):
                boost_tensor[i] += BOOST_SVG_PENALTY
                continue
            
            # Tier 0: Exact filename match (+config)
            if target_file and target_file in file_path:
                boost_tensor[i] += BOOST_TIER_0_FILENAME
            
            # Tier 1: HTML tag matching (+config)
            tag_match = re.search(r'<\s*([a-z0-9\-]+)', code_lower)
            if tag_match:
                tag = tag_match.group(1)
                for word in query_words_set:
                    if word == tag:
                        boost_tensor[i] += BOOST_TIER_1_TAG
                        break
            
            # Tier 2: CSS class matching (+config)
            class_match = re.search(r'classname=["\']([^"\']+)["\']', code_lower)
            if class_match:
                class_str = class_match.group(1)
                for word in query_words_set:
                    if len(word) >= WORD_MIN_LENGTH:
                        if word in class_str.split():
                            boost_tensor[i] += BOOST_TIER_2_CLASS_FULL
                            break
                        elif word in class_str:
                            boost_tensor[i] += BOOST_TIER_2_PARTIAL
                            break
            
            # Tier 3: Attribute metadata matching (+config)
            for word in query_words_set:
                if len(word) >= WORD_MIN_LENGTH and word in code_lower:
                    boost_tensor[i] += BOOST_TIER_2_PARTIAL
                    break
        
        # Apply boosting
        final_scores_boosted = final_scores + boost_tensor
        
        # Get top-K from boosted scores
        actual_k = min(k, len(valid_indices))
        try:
            top_k_values, top_k_indices = torch.topk(final_scores_boosted, actual_k)
            
            logger.info(f"🔍 TOP-K SCORES DEBUG:")
            for rank, (idx_in_filtered, score) in enumerate(zip(top_k_indices.tolist(), top_k_values.tolist())):
                global_idx = valid_indices[idx_in_filtered]
                file_path, code = self.global_corpus[global_idx]
                logger.info(f"  Rank {rank+1}: score={score:.4f} | {file_path[:60]}")
            
            results = []
            for idx_in_filtered, score in zip(top_k_indices.tolist(), top_k_values.tolist()):
                global_idx = valid_indices[idx_in_filtered]
                file_path, code = self.global_corpus[global_idx]
                results.append((file_path, code, float(score)))  # Include real mathematical score
            
            logger.info(f"✅ Retrieved {len(results)} results")
            return results, alpha_text, alpha_visual
        except Exception as e:
            logger.error(f"Failed to get top-K: {e}")
            return [], alpha_text, alpha_visual
    
    def search(self, query: str, top_k: int = 10, gating_weight: float = 0.5) -> list:
        """
        Legacy compatibility wrapper - calls retrieve_top_k internally.
        Returns list of results with legacy format for backward compatibility.
        """
        logger.info(f"🔄 Legacy search() called")
        results, alpha_text, alpha_visual = self.retrieve_top_k(text_query=query, k=top_k)
        
        # Convert to legacy format with metadata
        formatted = []
        for idx, (filepath, code, score) in enumerate(results):
            formatted.append({
                "filepath": filepath,
                "code": code,
                "score": float(score),  # Real mathematical score from 4-stage pipeline
                "semantic_score": float(score),  # Same as score from pipeline
                "alpha_text": alpha_text,
                "alpha_visual": alpha_visual
            })
        
        return formatted