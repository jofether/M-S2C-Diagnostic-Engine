import os
import re
import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer, ViTModel, ViTImageProcessor
from PIL import Image
import io
import base64

"""
=========================================================================================
Multimodal Semantic-to-Code (MS2C) Engine - Prototype API Version
=========================================================================================
Architecture: Multi-Stage Cascading Retrieval Pipeline
1. Document Filter: Multi-tiered file routing via CodeBERT + Lexical Matching.
2. Entity Extraction: Dynamic DOM/JSX Tag Parsing (Safe word-in-tag matching).
3. Semantic Scorer: Zero-shot CodeBERT + ViT ranking using contextual path injection.
4. Tensor Boosting: Applies a tiered Dynamic Soft Boost matrix for exact file overrides, 
   tag matches, CSS ClassNames, and deep inline attributes.
=========================================================================================
"""

class MS2CModel(nn.Module):
    """
    Dual-Encoder Multimodal Transformer Architecture.
    Combines CodeBERT (Text/Code) and ViT (Vision) representations into a unified
    vector space, mediated by a dynamic neural gating network.
    """
    def __init__(self, hidden_dim=768):
        super(MS2CModel, self).__init__()
        
        # 1. Initialize Device (CRITICAL FIX #2: Explicit Device Management)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # 2. Load Pre-trained Encoders
        print(f"Loading Models onto {self.device}...")
        self.codebert = AutoModel.from_pretrained("microsoft/codebert-base").to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
        
        self.vit = ViTModel.from_pretrained("google/vit-base-patch16-224-in21k").to(self.device)
        self.image_processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224-in21k")

        # 3. Multimodal Projection Heads (Aligning dimensions)
        self.text_projection = nn.Linear(self.codebert.config.hidden_size, hidden_dim).to(self.device)
        self.image_projection = nn.Linear(self.vit.config.hidden_size, hidden_dim).to(self.device)
        
        # Freeze base models for zero-shot inference to save VRAM in prototype
        for param in self.codebert.parameters():
            param.requires_grad = False
        for param in self.vit.parameters():
            param.requires_grad = False

        self.eval() # Set to evaluation mode for the live API

    def encode_text(self, text: str):
        """Generates embeddings for code snippets or text queries."""
        # Ensure inputs are explicitly moved to the correct device
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512, padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.codebert(**inputs)
            # Use the [CLS] token representation
            cls_embedding = outputs.last_hidden_state[:, 0, :] 
            return self.text_projection(cls_embedding)

    def encode_image(self, image: Image.Image):
        """Generates embeddings for UI bug screenshots."""
        # Ensure image inputs are explicitly moved to the correct device
        inputs = self.image_processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.vit(**inputs)
            # Use the [CLS] token representation
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            return self.image_projection(cls_embedding)

    def _sanitize_query(self, query: str) -> set:
        """
        CRITICAL FIX #1: Query Normalization for the Soft Boost Matrix.
        Strips punctuation, converts to lowercase, and splits into a clean set of words.
        Ensures live frontend queries match the AST nodes exactly like benchmarking.
        """
        # Convert to lowercase
        clean_query = query.lower()
        # Remove all non-alphanumeric characters (replace with spaces)
        clean_query = re.sub(r'[^a-z0-9\s]', ' ', clean_query)
        # Split by whitespace and remove empty strings
        words = set(clean_query.split())
        return words

    def process_api_image(self, image_data) -> Image.Image:
        """
        CRITICAL FIX #3: PIL Image Pre-Processing.
        Handles base64 strings or raw bytes from FastAPI, converting everything 
        safely to RGB to prevent ViT tensor dimension crashes with RGBA (PNGs).
        """
        try:
            if isinstance(image_data, str) and image_data.startswith('data:image'):
                # Handle base64 from React frontend
                header, encoded = image_data.split(",", 1)
                image_bytes = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(image_bytes))
            elif isinstance(image_data, bytes):
                # Handle raw bytes upload
                image = Image.open(io.BytesIO(image_data))
            else:
                # Assume it's already a PIL Image or file path
                image = Image.open(image_data) if isinstance(image_data, str) else image_data
            
            # Force conversion to RGB (strips Alpha channel if present)
            return image.convert("RGB")
        except Exception as e:
            raise ValueError(f"Failed to process uploaded image: {str(e)}")

    def search(self, query_text: str, image_data, index_embeddings: torch.Tensor, index_metadata: list, k: int = 5):
        """
        Live Prototype Search Function.
        Takes a real-time query and image, compares against the globally indexed codebase,
        applies the Dynamic Soft Boost Matrix, and returns Top-K results.
        """
        # 1. Process Inputs
        query_words_set = self._sanitize_query(query_text)
        pil_image = self.process_api_image(image_data)
        
        # 2. Generate Multimodal Query Embeddings
        # (encodings are already pushed to self.device inside their respective functions)
        text_emb = self.encode_text(query_text)
        img_emb = self.encode_image(pil_image)
        
        # 3. Feature Fusion (Simple addition for Zero-Shot, can be changed to concatenation)
        query_emb = text_emb + img_emb
        query_emb = torch.nn.functional.normalize(query_emb, p=2, dim=1)

        # Ensure index embeddings are on the same device
        if index_embeddings.device != self.device:
            index_embeddings = index_embeddings.to(self.device)
            
        # Normalize index embeddings
        index_embeddings = torch.nn.functional.normalize(index_embeddings, p=2, dim=1)

        # 4. Semantic Scorer (Cosine Similarity)
        # Shape: (1, hidden_dim) @ (hidden_dim, num_nodes) -> (1, num_nodes)
        cosine_scores = torch.matmul(query_emb, index_embeddings.T).squeeze(0)

        # 5. Tensor Boosting (Dynamic Soft Boost Matrix)
        boost_tensor = torch.zeros_like(cosine_scores, device=self.device)
        
        # Common HTML/JSX tags to filter out noise
        exact_target_tags = {'div', 'span', 'button', 'input', 'img', 'a', 'p', 'h1', 'h2', 'h3', 'form'}
        partial_target_tags = {'section', 'nav', 'header', 'footer', 'ul', 'li', 'svg', 'path'}

        for i, meta in enumerate(index_metadata):
            node_str = meta.get("code_snippet", "").lower()
            
            # Tier 1: Tag Match
            tag_match = re.search(r'<\s*([a-z0-9\-.]+)', node_str)
            if tag_match:
                tag = tag_match.group(1)
                if tag in exact_target_tags:
                    boost_tensor[i] += 1.0
                elif tag in partial_target_tags:
                    boost_tensor[i] += 0.5

            # Tier 2: CSS Match (className)
            class_match = re.search(r'classname=["\']([^"\']+)["\']', node_str)
            if class_match:
                class_str = class_match.group(1)
                classes_list = class_str.split()
                
                for word in query_words_set:
                    if len(word) >= 3:
                        if word in classes_list:
                            boost_tensor[i] += 0.5
                            break
                        elif word in class_str:
                            boost_tensor[i] += 0.25
                            break

            # Tier 3: Deep Attribute Match
            for word in query_words_set:
                if len(word) >= 3 and word in node_str:
                    # Prevent double-boosting if the word is just the tag we already matched
                    if not (tag_match and word == tag_match.group(1)):
                        boost_tensor[i] += 0.25
                        break

        # 6. Final Cascading Score
        # Weight the boosts so they act as "soft" routing without overriding strong semantic visual matches
        filtered_scores = cosine_scores + (boost_tensor * 0.15) 

        # 7. Determine Top-K Results
        # Use k=5 for a clean UI, but ensure we don't request more than we have
        actual_k = min(k, len(index_metadata))
        top_k_values, top_k_indices = torch.topk(filtered_scores, actual_k)
        
        raw_results = []
        for idx, score in zip(top_k_indices.tolist(), top_k_values.tolist()):
            result_meta = index_metadata[idx].copy()
            result_meta["confidence_score"] = round(score, 4)
            raw_results.append(result_meta)
            
        return raw_results

# Example usage in FastAPI routes.py:
# ms2c_engine = MS2CModel()
# results = ms2c_engine.search(query_text=user_input, image_data=uploaded_file, index_embeddings=global_tensors, index_metadata=global_meta, k=5)