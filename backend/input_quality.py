"""
Input Quality Analyzer for M-S2C Diagnostic Engine.

Computes the GATING WEIGHT (α) for the user-provided bug description and screenshot.

The gating weight is computed dynamically by the neural model:
- α_text: Weight for text (CodeBERT) input
- α_visual: Weight for visual (ViT) input
- Sum = 1.0 always

This represents how much the model "trusts" each modality based on input quality.
"""

import os
import logging
import torch
from PIL import Image
from transformers import AutoTokenizer, ViTImageProcessor
from ms2c import MS2CModel

logger = logging.getLogger(__name__)


class InputQualityAnalyzer:
    """Computes gating weight for bug description + screenshot."""
    
    def __init__(self):
        """Initialize the gating weight analyzer."""
        logger.info("🧠 Gating Weight Analyzer initialized")
        
        # Initialize neural model for gating
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = MS2CModel().to(self.device)
        self.model.eval()
        
        self.text_tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
        self.image_processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224-in21k")
        
        print(f"🧠 Gating network ready on device: {self.device}")
    
    def compute_gating_weight(self, description: str = None, screenshot_path: str = None) -> dict:
        """
        Compute the neural gating weight for text vs visual input.
        
        Args:
            description: Bug description text
            screenshot_path: Path to screenshot image
            
        Returns:
            dict: {
                'alpha_text': float - text confidence (0.0-1.0),
                'alpha_visual': float - visual confidence (0.0-1.0),
                'input_type': str - 'text_only', 'visual_only', 'multimodal', 'empty',
                'details': str - explanation
            }
        """
        print(f"\n🧠 Computing gating weight...")
        print(f"  Description: {'✓' if description else '✗'}")
        print(f"  Screenshot: {'✓' if screenshot_path and os.path.exists(screenshot_path) else '✗'}")
        
        # Check inputs
        has_text = description and len(description.strip()) > 0
        has_image = screenshot_path and os.path.exists(screenshot_path)
        
        if not has_text and not has_image:
            print(f"  ❌ No input provided")
            return {
                'alpha_text': 0.5,
                'alpha_visual': 0.5,
                'input_type': 'empty',
                'details': 'No description or screenshot provided'
            }
        
        # TEXT-ONLY mode
        if has_text and not has_image:
            print(f"  📝 TEXT-ONLY MODE")
            return {
                'alpha_text': 1.0,
                'alpha_visual': 0.0,
                'input_type': 'text_only',
                'details': 'Text input only. Full weight to CodeBERT, no visual input.'
            }
        
        # VISUAL-ONLY mode
        if has_image and not has_text:
            print(f"  🖼️  VISUAL-ONLY MODE")
            return {
                'alpha_text': 0.0,
                'alpha_visual': 1.0,
                'input_type': 'visual_only',
                'details': 'Visual input only. Full weight to ViT, no text input.'
            }
        
        # MULTIMODAL mode - compute gating weight
        print(f"  🎯 MULTIMODAL MODE - Computing neural gating weight...")
        try:
            with torch.no_grad():
                # Encode text
                text_inputs = self.text_tokenizer(
                    description.lower(),
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                    padding=True
                ).to(self.device)
                text_emb = self.model.forward_text(
                    text_inputs["input_ids"],
                    text_inputs["attention_mask"]
                )
                print(f"     Text embedding shape: {text_emb.shape}")
                
                # Encode image
                image = Image.open(screenshot_path).convert("RGB")
                image_inputs = self.image_processor(images=image, return_tensors="pt").to(self.device)
                visual_emb = self.model.forward_image(image_inputs["pixel_values"])
                print(f"     Visual embedding shape: {visual_emb.shape}")
                
                # Compute raw gating weight
                gating_output = self.model.compute_gating_weight(text_emb, visual_emb)
                alpha_text_raw = gating_output.item()
                print(f"     Raw gating: α_text = {alpha_text_raw:.4f}")
                
                # Apply MS2C retrieval pipeline clamping (from ms2c.py Stage 3)
                # Rules:
                #   1. Add +0.20 bias to text (text is structural foundation)
                #   2. Clamp to [0.70, 0.95] (text gets 70-95% weight always)
                alpha_text_clamped = min(0.95, max(0.70, alpha_text_raw + 0.20))
                alpha_visual_clamped = 1.0 - alpha_text_clamped
                
                print(f"     ✅ Gating with clamping (MS2C Stage 3):")
                print(f"        Raw: α_text = {alpha_text_raw:.4f}")
                print(f"        +0.20 bias: {alpha_text_raw + 0.20:.4f}")
                print(f"        Clamped [0.70, 0.95]: α_text = {alpha_text_clamped:.4f}")
                print(f"        → α_text = {alpha_text_clamped:.4f}, α_visual = {alpha_visual_clamped:.4f}")
                
                return {
                    'alpha_text': float(alpha_text_clamped),
                    'alpha_visual': float(alpha_visual_clamped),
                    'input_type': 'multimodal',
                    'details': f'Multimodal (clamped): Text weight {alpha_text_clamped:.2%}, Visual weight {alpha_visual_clamped:.2%}'
                }
                
        except Exception as e:
            print(f"     ❌ Gating computation failed: {e}")
            logger.error(f"❌ Gating weight computation failed: {e}")
            # Fallback to equal weights
            return {
                'alpha_text': 0.5,
                'alpha_visual': 0.5,
                'input_type': 'multimodal',
                'details': f'Gating computation error, using equal weights: {str(e)}'
            }
    
    def analyze_description(self, description: str) -> dict:
        """
        DEPRECATED: Kept for backward compatibility.
        Now just returns basic description info.
        """
        if not description:
            return {
                'text': 'Empty',
                'score': 0,
                'length': 0
            }
        
        return {
            'text': 'Provided',
            'score': 100 if len(description) > 20 else 50,
            'length': len(description)
        }
    
    def analyze_screenshot(self, screenshot_path: str = None) -> dict:
        """
        DEPRECATED: Kept for backward compatibility.
        Now just returns basic file info.
        """
        result = {
            'text': 'None',
            'score': 0,
            'file_exists': False
        }
        
        if screenshot_path and os.path.exists(screenshot_path):
            result['file_exists'] = True
            result['text'] = 'Exists'
            result['score'] = 100
        
        return result
    
    def analyze_combined_input(self, description: str = None, screenshot_path: str = None) -> dict:
        """
        Analyze combined input by computing gating weight.
        
        Returns the gating weight as the input quality metric.
        """
        gating_result = self.compute_gating_weight(description, screenshot_path)
        
        return {
            'gating_weight': gating_result,
            'alpha_text': gating_result['alpha_text'],
            'alpha_visual': gating_result['alpha_visual'],
            'input_type': gating_result['input_type'],
            'details': gating_result['details']
        }
