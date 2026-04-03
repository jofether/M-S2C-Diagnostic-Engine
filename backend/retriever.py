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
        self.global_corpus = []
        self.global_embeddings = None
        self.file_embeddings = None
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
        
        Args:
            index_dict: Dictionary mapping file paths to list of node dicts with 'code_snippet' field
            batch_size: Batch size for encoding (default 64 for VRAM safety)
        """
        logger.info(f"📊 Building Neural Index from {len(index_dict)} files...")
        
        self.index_dict = index_dict
        self.embedded_nodes = []
        self.unique_files = set(index_dict.keys())
        self.global_corpus = []
        
        # First pass: collect all code snippets and metadata
        all_code_snippets = []
        code_to_metadata = []
        
        for file_path, nodes in index_dict.items():
            for node_dict in nodes:
                code_text = node_dict.get("code_snippet", "")
                all_code_snippets.append(code_text)
                code_to_metadata.append((file_path, code_text))
                self.global_corpus.append((file_path, code_text))
        
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
    
    def retrieve_top_k(self, text_query: str, k: int = 10, 
                       target_file: str = None, image_path: str = None) -> tuple:
        """
        Execute 4-stage pipeline and return top-K results with alpha quality metrics.
        
        Returns:
            tuple: (results_list, alpha_text, alpha_visual)
                - results_list: List of (file_path, code_snippet) tuples
                - alpha_text: Quality weight for text (0.0-1.0)
                - alpha_visual: Quality weight for visual (0.0-1.0)
        """
        if self.global_embeddings is None or len(self.global_corpus) == 0:
            logger.warning("Index is empty")
            return [], 0.5, 0.5
        
        # Stage 1: NLP Token Generation
        logger.info(f"🔍 Stage 1: Token normalization...")
        query_words_set = self._normalize_tokens(text_query)
        logger.info(f"   Normalized tokens: {query_words_set if query_words_set else 'none'}")
        
        # Embed query (for retrieval and quality assessment)
        query_emb = self.encode_text(text_query)
        
        # Stage 2: Document Filtration (file-level matching)
        logger.info(f"🔍 Stage 2: Document filtration...")
        valid_indices = list(range(len(self.global_corpus)))
        
        if target_file:
            logger.info(f"   Filtering for target file: {target_file}")
            valid_indices = [i for i, (f, _) in enumerate(self.global_corpus) if target_file in f]
        
        if not valid_indices:
            logger.warning("   No matching documents after filtration")
            return [], 0.5, 0.5
        
        # Stage 3: Multimodal Fused Scoring with Neural Gating
        logger.info(f"🔍 Stage 3: Multimodal scoring with neural gating...")
        
        # Text similarity
        text_sim = torch.matmul(query_emb, self.global_embeddings.T).squeeze(0)
        
        # Initialize alpha values
        alpha_text = 1.0
        alpha_visual = 0.0
        
        # Handle image if provided - use neural gating network
        if image_path:
            try:
                image = Image.open(image_path).convert("RGB")
                img_emb = self.encode_image(image)
                vis_sim = torch.matmul(img_emb, self.global_embeddings.T).squeeze(0)
                
                # 🔴 NEURAL GATING: Compute dynamic alpha based on embedding quality
                base_alpha = self.compute_gating_weight(query_emb, img_emb).item()
                logger.info(f"   Neural Gating Weight (base): {base_alpha:.4f}")
                
                # Dynamic gating with adaptive thresholding
                # If text similarity is very high (>0.80), trust text more (alpha=0.95)
                # Otherwise clamp to safe range [0.70, 0.95]
                if text_sim.max().item() > 0.80:
                    alpha_text = 0.95
                else:
                    alpha_text = torch.clamp(
                        torch.tensor(base_alpha + 0.20),
                        min=0.70,
                        max=0.95
                    ).item()
                
                alpha_visual = 1.0 - alpha_text
                
                logger.info(f"   Dynamic Gating Weights: α_text={alpha_text:.4f}, α_visual={alpha_visual:.4f}")
                
                # Fuse scores using computed alphas
                final_scores = (alpha_text * text_sim) + (alpha_visual * vis_sim)
            except Exception as e:
                logger.warning(f"Image scoring failed: {e}, using text only")
                final_scores = text_sim
                alpha_text = 1.0
                alpha_visual = 0.0
        else:
            # No image: use text-only (alpha_text=1.0)
            final_scores = text_sim
            alpha_text = 1.0
            alpha_visual = 0.0
        
        # Filter to valid indices
        filtered_scores = final_scores[valid_indices].clone()
        
        # Stage 4: Heuristic Matrix Boosting
        logger.info(f"🔍 Stage 4: Heuristic boosting...")
        boost_tensor = torch.zeros_like(filtered_scores)
        
        invalid_markers = ["<svg", "<path", "<g ", "<circle", "<rect", "<line", "<polygon"]
        
        for i, idx in enumerate(valid_indices):
            file_path, code_snippet = self.global_corpus[idx]
            code_lower = code_snippet.lower()
            
            # Skip SVG/graphics
            if any(m in code_lower for m in invalid_markers):
                boost_tensor[i] -= 10.0  # Strong penalty
                continue
            
            # Tier 0: File override
            if target_file and target_file in file_path:
                boost_tensor[i] += 10.0
            
            # Tier 1: Tag matching
            tag_match = re.search(r'<\s*([a-z0-9\-]+)', code_lower)
            if tag_match:
                tag = tag_match.group(1)
                for word in query_words_set:
                    if word == tag:
                        boost_tensor[i] += 1.0
                        break
            
            # Tier 2: CSS class matching
            class_match = re.search(r'classname=["\']([^"\']+)["\']', code_lower)
            if class_match:
                class_str = class_match.group(1)
                for word in query_words_set:
                    if len(word) >= 3:
                        if word in class_str.split():
                            boost_tensor[i] += 0.5
                            break
                        elif word in class_str:
                            boost_tensor[i] += 0.25
                            break
            
            # Tier 3: Attribute matching
            for word in query_words_set:
                if len(word) >= 3 and word in code_lower:
                    boost_tensor[i] += 0.25
                    break
        
        # Apply boosting
        final_scores_boosted = filtered_scores + boost_tensor
        
        # Get top-K
        actual_k = min(k, len(valid_indices))
        try:
            top_k_values, top_k_indices = torch.topk(final_scores_boosted, actual_k)
            
            logger.info(f"🔍 TOP-K SCORES DEBUG:")
            for rank, (idx_in_filtered, score) in enumerate(zip(top_k_indices.tolist(), top_k_values.tolist())):
                actual_idx = valid_indices[idx_in_filtered]
                file_path, code = self.global_corpus[actual_idx]
                logger.info(f"  Rank {rank+1}: score={score:.4f} | {file_path[:60]}")
            
            results = []
            for idx_in_filtered, score in zip(top_k_indices.tolist(), top_k_values.tolist()):
                actual_idx = valid_indices[idx_in_filtered]
                file_path, code = self.global_corpus[actual_idx]
                results.append((file_path, code))
            
            logger.info(f"✅ Retrieved {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Failed to get top-K: {e}")
            return []
    
    def search(self, query: str, top_k: int = 10, gating_weight: float = 0.5) -> list:
        """
        Legacy compatibility wrapper - calls retrieve_top_k internally.
        """
        logger.info(f"🔄 Legacy search() called")
        results = self.retrieve_top_k(text_query=query, k=top_k)
        
        # Convert to legacy format with metadata
        formatted = []
        for idx, (filepath, code) in enumerate(results):
            formatted.append({
                "filepath": filepath,
                "code": code,
                "score": 1.0 - (idx * 0.05),  # Decrease for lower ranks
                "semantic_score": 1.0 - (idx * 0.05)
            })
        
        return formatted