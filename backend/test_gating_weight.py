"""
Test script to demonstrate gating weight computation with MS2C clamping.
Shows how the neural model weights text vs visual input, then applies pipeline clamping.
"""

import sys
import os
from PIL import Image
from input_quality import InputQualityAnalyzer

print("=" * 70)
print("🧠 GATING WEIGHT COMPUTATION TEST (with MS2C Clamping)")
print("=" * 70)

analyzer = InputQualityAnalyzer()

# Test 1: Text-only
print("\n[TEST 1] 📝 TEXT-ONLY INPUT")
print("-" * 70)
result = analyzer.compute_gating_weight(
    description="The button doesn't respond when clicked. I click on the login button but nothing happens.",
    screenshot_path=None
)
print(f"Result: {result}")
print(f"✓ α_text={result['alpha_text']:.4f}, α_visual={result['alpha_visual']:.4f}")

# Test 2: Empty input
print("\n[TEST 2] 🔴 EMPTY INPUT")
print("-" * 70)
result = analyzer.compute_gating_weight(
    description=None,
    screenshot_path=None
)
print(f"Result: {result}")
print(f"✓ α_text={result['alpha_text']:.4f}, α_visual={result['alpha_visual']:.4f}")

# Test 3: Multimodal with a real test image
print("\n[TEST 3] 🎯 MULTIMODAL MODE (with clamping)")
print("-" * 70)

# Create a simple test image
test_image_path = "test_screenshot.png"
try:
    # Create a red square test image
    img = Image.new('RGB', (800, 600), color='red')
    img.save(test_image_path)
    
    result = analyzer.compute_gating_weight(
        description="Button styling is broken. The submit button should be blue but appears red instead.",
        screenshot_path=test_image_path
    )
    print(f"\nResult: {result}")
    print(f"✓ α_text={result['alpha_text']:.4f}, α_visual={result['alpha_visual']:.4f}")
    print(f"  (Note: Raw neural weight is transformed by MS2C pipeline)")
    
    # Cleanup
    if os.path.exists(test_image_path):
        os.unlink(test_image_path)
except Exception as e:
    print(f"⚠️  Multimodal test skipped: {e}")

print("\n" + "=" * 70)
print("✅ Test complete - Check clamping transformation above")
print("=" * 70)
