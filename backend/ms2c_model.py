"""
M-S2C E2E JOINT TRAINING ENGINE
================================
Multimodal Fusion Architecture for End-to-End Training:

Dual-Stream Processing:
  Visual Stream: Screenshot → ViT → v_visual → MLP → Aligned Code Space
  Textual Stream: Bug Description → CodeBERT → v_text → Code Space
  Code Space: Positive/Negative AST → CodeBERT → Reference Embeddings

Adaptive Gating:
  Learns dynamic balance between visual and textual modalities
  Alpha ∈ [0,1] computed via concatenated embeddings

Key Features:
  - CodeBERT: Code semantic understanding (can update with differential LR)
  - ViT: Visual/spatial feature extraction (standard fine-tuning)
  - MLP Projection: Maps vision to code semantic space (aggressive learning)
  - Gating Network: Dynamic modality weighting (aggressive learning)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, ViTModel

class MS2CFusionEngine(nn.Module):
    """
    E2E Joint Training Multimodal Fusion Engine
    
    Architecture Overview:
    ┌─────────────────────────────────────────────────────┐
    │ DUAL-STREAM TRIPLET LOSS TRAINING                  │
    ├─────────────────────────────────────────────────────┤
    │ Visual Stream:                                       │
    │   Image → ViT [CLS] → MLP Projection → v_visual    │
    │                                                      │
    │ Textual Stream:                                      │
    │   Text → CodeBERT [CLS] → v_text                   │
    │                                                      │
    │ Code Space Anchors:                                  │
    │   Pos Code → CodeBERT [CLS] → v_pos                │
    │   Neg Code → CodeBERT [CLS] → v_neg                │
    │                                                      │
    │ Gating Network:                                      │
    │   [v_text || v_visual] → α ∈ [0,1]                │
    │                                                      │
    │ Loss: 0.7 * L_visual + 0.3 * L_textual            │
    └─────────────────────────────────────────────────────┘
    
    Trainable Components (via differential learning rates):
    - CodeBERT: 2e-6 (slow fine-tuning)
    - ViT: 2e-5 (standard fine-tuning)
    - MLP Projection: 5e-5 (aggressive learning)
    - Gating Network: 5e-5 (aggressive learning)
    
    All embeddings are L2-normalized before similarity computation.
    """
    def __init__(self, 
                 text_model_name="microsoft/codebert-base", 
                 vision_model_name="google/vit-base-patch16-224-in21k", 
                 code_dim=768, 
                 vision_dim=768):
        super(MS2CFusionEngine, self).__init__()
        
        # --- ENCODERS ---
        print("Loading CodeBERT and ViT models...")
        self.codebert = AutoModel.from_pretrained(text_model_name)
        self.vit = ViTModel.from_pretrained(vision_model_name)
        print("[OK] Encoders loaded (trainability controlled by optimizer setup)")
            
        # --- MLP PROJECTION HEAD ---
        # Maps 768-D vision embeddings to 768-D code semantic space
        # Aggressively learned with LR=5e-5
        self.mlp_projection = nn.Sequential(
            nn.Linear(vision_dim, code_dim),
            nn.ReLU(),
            nn.Linear(code_dim, code_dim),
            nn.Dropout(0.1)
        )
        
        # --- ADAPTIVE GATING NETWORK ---
        # Computes dynamic weight α ∈ [0,1] for visual vs textual modality
        # Takes concatenated [v_text || v_visual_aligned] as input
        # Aggressively learned with LR=5e-5
        self.gating_network = nn.Sequential(
            nn.Linear(code_dim * 2, code_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(code_dim, 1),
            nn.Sigmoid()  # Constrains output to [0,1]
        )

    def forward(self, input_ids, attention_mask, pixel_values):
        """
        E2E Joint Training Forward Pass - Dual-Stream Processing
        
        Supports 3 usage modes:
        
        Mode 1 - VISUAL STREAM ONLY:
            forward(input_ids=None, attention_mask=None, pixel_values=image)
            Returns: (v_visual_aligned, None, None)
        
        Mode 2 - TEXTUAL STREAM ONLY:
            forward(input_ids=text, attention_mask=mask, pixel_values=None)
            Returns: (None, v_text, None)
        
        Mode 3 - FULL DUAL-STREAM (Gating):
            forward(input_ids=text, attention_mask=mask, pixel_values=image)
            Returns: (v_visual_aligned, v_text, alpha)
        
        Args:
            input_ids (Tensor | None): CodeBERT input token IDs [batch, seq_len]
            attention_mask (Tensor | None): CodeBERT attention mask [batch, seq_len]
            pixel_values (Tensor | None): ViT input images [batch, 3, 224, 224]
        
        Returns:
            v_visual_aligned (Tensor): L2-normalized visual embedding [batch, 768]
            v_text (Tensor): L2-normalized textual embedding [batch, 768]
            alpha (Tensor): Gating weight ∈ [0,1] [batch, 1]
        """
        v_text = None
        v_visual_aligned = None
        alpha = None
        
        # --- TEXTUAL STREAM ---
        if input_ids is not None and attention_mask is not None:
            text_outputs = self.codebert(input_ids=input_ids, attention_mask=attention_mask)
            v_text_raw = text_outputs.last_hidden_state[:, 0, :]  # [CLS] token
            v_text = F.normalize(v_text_raw, p=2, dim=1)
        
        # --- VISUAL STREAM ---
        if pixel_values is not None:
            vision_outputs = self.vit(pixel_values=pixel_values)
            v_visual_raw = vision_outputs.last_hidden_state[:, 0, :]  # [CLS] token
            v_visual_aligned = self.mlp_projection(v_visual_raw)
            v_visual_aligned = F.normalize(v_visual_aligned, p=2, dim=1)
        
        # --- ADAPTIVE GATING ---
        if v_text is not None and v_visual_aligned is not None:
            fused_features = torch.cat((v_text, v_visual_aligned), dim=1)
            alpha = self.gating_network(fused_features)
        
        return v_visual_aligned, v_text, alpha

# --- E2E JOINT TRAINING TEST SCRIPT ---
if __name__ == "__main__":
    """
    Test the E2E Joint Training model architecture with dual-stream processing.
    Verifies that all components initialize correctly and process dummy tensors.
    """
    print("\n" + "="*70)
    print("E2E JOINT TRAINING MODEL - ARCHITECTURE TEST")
    print("="*70)
    
    # Initialize model
    model = MS2CFusionEngine()
    model.eval()
    
    print("\n✅ Model initialized successfully!")
    print("\n" + "-"*70)
    print("COMPONENT DETAILS:")
    print("-"*70)
    print(f"CodeBERT parameters: {sum(p.numel() for p in model.codebert.parameters()):,}")
    print(f"ViT parameters: {sum(p.numel() for p in model.vit.parameters()):,}")
    print(f"MLP Projection parameters: {sum(p.numel() for p in model.mlp_projection.parameters()):,}")
    print(f"Gating Network parameters: {sum(p.numel() for p in model.gating_network.parameters()):,}")
    
    # Dummy batch size = 2
    dummy_input_ids = torch.randint(0, 50000, (2, 128))
    dummy_attention_mask = torch.ones((2, 128))
    dummy_pixel_values = torch.randn(2, 3, 224, 224)
    
    print("\n" + "-"*70)
    print("DUAL-STREAM FORWARD PASS TEST:")
    print("-"*70)
    
    with torch.no_grad():
        # Test Mode 1: Visual Stream Only
        print("\n[Mode 1] Visual Stream Only (Screenshot):")
        v_visual, _, _ = model(input_ids=None, attention_mask=None, pixel_values=dummy_pixel_values)
        print(f"  v_visual shape: {v_visual.shape}")
        print(f"  L2-norm: {torch.norm(v_visual[0]).item():.4f} (should be ~1.0)")
        
        # Test Mode 2: Textual Stream Only
        print("\n[Mode 2] Textual Stream Only (Bug Description):")
        _, v_text, _ = model(input_ids=dummy_input_ids, attention_mask=dummy_attention_mask, pixel_values=None)
        print(f"  v_text shape: {v_text.shape}")
        print(f"  L2-norm: {torch.norm(v_text[0]).item():.4f} (should be ~1.0)")
        
        # Test Mode 3: Full Dual-Stream with Gating
        print("\n[Mode 3] Full Dual-Stream (Gating Network):")
        v_visual, v_text, alpha = model(
            input_ids=dummy_input_ids, 
            attention_mask=dummy_attention_mask, 
            pixel_values=dummy_pixel_values
        )
        print(f"  v_visual shape: {v_visual.shape}")
        print(f"  v_text shape: {v_text.shape}")
        print(f"  alpha shape: {alpha.shape}")
        print(f"  alpha values: {alpha.squeeze().tolist()}")
        print(f"  (alpha ∈ [0,1], learned weight for visual vs textual)")
    
    print("\n" + "="*70)
    print("✅ E2E JOINT TRAINING MODEL TEST PASSED!")
    print("="*70)
    print("\nModel is ready for:")
    print("  • Differential learning rate training")
    print("  • Dual-stream triplet loss computation")
    print("  • E2E joint optimization with model_training_colab.py")