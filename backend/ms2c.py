import os
import re
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer, ViTModel, ViTImageProcessor
from PIL import Image
import io
import base64
from config import logger

"""
=========================================================================================
Multimodal Semantic-to-Code (MS2C) Engine - Thesis-Aligned Implementation
=========================================================================================
Architecture: Multi-Stage Cascading Retrieval Pipeline

1. NLP Token Generation: Stopword removal + stemming for robust query normalization
2. Document Filtration: File-level semantic matching + lexical word boosting  
3. Multimodal Fused Scoring: CodeBERT + ViT with dynamic alpha gating
4. Heuristic Matrix Boosting: 4-tier boosting (file/tag/css/attribute)

Thesis References:
- Section 3.1: CodeBERT embeddings for semantic code representation
- Section 3.2: Vector similarity search via L2-normalized cosine similarity
- Section 3.2.4: Adaptive score-level fusion with multimodal gating
=========================================================================================
"""

class MS2CModel(nn.Module):
    """
    Dual-Encoder Multimodal Transformer Architecture.
    Combines CodeBERT (Text/Code) and ViT (Vision) representations.
    """
    def __init__(self, hidden_dim=768):
        super(MS2CModel, self).__init__()
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🚀 Initializing MS2CModel on device: {self.device}")
        
        # Load CodeBERT for text encoding
        logger.info("📦 Loading CodeBERT model: microsoft/codebert-base")
        self.codebert = AutoModel.from_pretrained("microsoft/codebert-base").to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
        
        # Load ViT for image encoding
        logger.info("📦 Loading ViT model: google/vit-base-patch16-224-in21k")
        self.vit = ViTModel.from_pretrained("google/vit-base-patch16-224-in21k").to(self.device)
        self.image_processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224-in21k")
        
        # Image projection head for dimension alignment (ViT only)
        self.mlp_projection = nn.Sequential(
            nn.Linear(self.vit.config.hidden_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim)
        ).to(self.device)
        
        # Neural Gating Network for dynamic multimodal weighting
        # Learns to assess input quality and balance text vs visual contributions
        self.gating_network = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid()
        ).to(self.device)
        logger.info(f"📊 Gating Network initialized for dynamic alpha weighting")
        
        # Freeze base models for zero-shot (no fine-tuning in deployment)
        for param in self.codebert.parameters():
            param.requires_grad = False
        for param in self.vit.parameters():
            param.requires_grad = False

        self.eval()
        logger.info(f"✅ MS2CModel initialized on {self.device}")

    def encode_text(self, text: str) -> torch.Tensor:
        """Generate L2-normalized CodeBERT embeddings for text."""
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512, padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.codebert(**inputs)
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            return F.normalize(cls_embedding, p=2, dim=1)

    def encode_image(self, image: Image.Image) -> torch.Tensor:
        """Generate L2-normalized ViT embeddings for image."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        inputs = self.image_processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.vit(**inputs)
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            projected = self.mlp_projection(cls_embedding)
            return F.normalize(projected, p=2, dim=1)
    
    def compute_gating_weight(self, text_emb: torch.Tensor, visual_emb: torch.Tensor) -> torch.Tensor:
        """
        Neural Gating Network: Learns to dynamically weight text vs visual contributions.
        
        Provides more accurate input quality assessment than heuristics by analyzing embeddings:
        - text_emb: CodeBERT embedding of bug description (semantic coherence)
        - visual_emb: ViT embedding of screenshot (visual relevance)
        
        Returns:
            base_alpha: Scalar between 0.0-1.0 representing text quality weight
        """
        # Concatenate embeddings and pass through gating network
        concatenated = torch.cat([text_emb, visual_emb], dim=1)  # Shape: (1, 1536)
        with torch.no_grad():
            base_alpha = self.gating_network(concatenated).squeeze()  # Shape: (1,) -> scalar
        return base_alpha


# MS2CRetriever has been moved to retriever.py for better module organization
# Import it from there: from retriever import MS2CRetriever

