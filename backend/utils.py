"""
Utility functions for bug diagnosis and weighting
"""

import os
from PIL import Image
from config import logger


def compute_visual_quality(image_path: str) -> float:
    """
    Analyze uploaded screenshot to compute visual information quality.
    Returns a weight between 0.0 (low quality/no image) and 1.0 (high quality).
    
    Quality factors:
    - File exists and is valid image
    - Image resolution (higher resolution = more detail)
    - Image size in bytes (larger = more information)
    """
    if not image_path or not os.path.exists(image_path):
        logger.info("📸 No screenshot provided")
        return 0.0
    
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            file_size_kb = os.path.getsize(image_path) / 1024
            
            # Quality score based on resolution
            # High quality: > 1000px width, medium: 500-1000px, low: < 500px
            resolution_score = min(1.0, (width * height) / (1920 * 1080))  # Normalize to 1080p
            
            # Quality score based on file size
            # High quality: > 100KB, medium: 50-100KB, low: < 50KB  
            size_score = min(1.0, file_size_kb / 200)  # Normalize to 200KB
            
            # Combined visual quality (average of dimensions)
            visual_quality = (resolution_score + size_score) / 2
            
            logger.info(f"📸 Screenshot Quality Analysis:")
            logger.info(f"   Resolution: {width}x{height} (score: {resolution_score:.2f})")
            logger.info(f"   File Size: {file_size_kb:.1f}KB (score: {size_score:.2f})")
            logger.info(f"   Overall Visual Quality: {visual_quality:.2f}")
            
            return visual_quality
            
    except Exception as e:
        logger.warning(f"⚠️  Failed to analyze image: {e}")
        return 0.1  # Slight credit for attempting to provide visual info


def compute_gating_weight(bug_description: str, image_path: str = None):
    """
    Compute multimodal fusion weight: Text vs Visual contribution.
    Integrates description quality + screenshot quality for adaptive scoring.
    
    Returns: (alpha_text, alpha_visual) where sum = 1.0
    - alpha_text: Weight for textual bug description (0.0-1.0)
    - alpha_visual: Weight for visual screenshot (0.0-1.0)
    
    Thesis: Adaptive Score-Level Fusion (Section 3.2.4)
    Final Score = Semantic Score × alpha_text
    """
    # Analyze text quality
    desc_length = len(bug_description)
    detail_keywords = ["specifically", "exactly", "however", "although", "instead of", "should be"]
    detail_count = sum(1 for kw in detail_keywords if kw in bug_description.lower())
    
    # Normalize text quality to 0.0-1.0 range
    if desc_length > 200 and detail_count > 0:
        text_quality = 0.8
    elif desc_length > 100:
        text_quality = 0.6
    elif desc_length > 50:
        text_quality = 0.4
    elif desc_length > 20:
        text_quality = 0.2
    else:
        text_quality = 0.1
    
    # Analyze visual quality
    visual_quality = compute_visual_quality(image_path) if image_path else 0.0
    
    logger.info(f"🎯 Multimodal Gating Weight Computation:")
    logger.info(f"   Text Quality (description): {text_quality:.2f}")
    logger.info(f"   Visual Quality (screenshot): {visual_quality:.2f}")
    
    # Thesis-Aligned: Adaptive fusion based on input quality
    # If both inputs are good: balanced (0.5/0.5)
    # If only text is good: heavily text-weighted (0.8/0.2)
    # If only visual is good: heavily visual-weighted (0.2/0.8)
    total_quality = text_quality + visual_quality
    
    if total_quality == 0:
        # Fallback: no useful input
        alpha_text = 0.5
        alpha_visual = 0.5
    else:
        # Normalize by quality scores
        alpha_text = text_quality / total_quality
        alpha_visual = visual_quality / total_quality
    
    # Ensure sum = 1.0 (with floating point tolerance)
    alpha_text = round(alpha_text, 4)
    alpha_visual = round(alpha_visual, 4)
    
    logger.info(f"   → Alpha(Text): {alpha_text:.4f}, Alpha(Visual): {alpha_visual:.4f}")
    
    return alpha_text, alpha_visual


def compute_gating_weight_legacy(bug_description: str):
    """
    Legacy text-only gating weight computation.
    Kept for backward compatibility.
    """
    return compute_gating_weight(bug_description, image_path=None)


def generate_smart_results(bug_description: str, repo_url: str):
    """
    Generate smarter mock results based on bug description keywords.
    Analyzes specific keywords to suggest relevant source files.
    """
    description_lower = bug_description.lower()
    
    # More specific keyword categories
    authentication_keywords = ["login", "auth", "password", "signin", "sign-in", "account", "user account", "credentials"]
    layout_keywords = ["layout", "container", "wrapper", "spacing", "alignment", "grid", "flex", "arrange", "organize"]
    ingredient_keywords = ["ingredient", "list", "item", "select", "choice", "option", "add item", "ingredient row"]
    button_keywords = ["button", "click", "clickable", "interactive", "click handler", "onclick", "cursor"]
    style_keywords = ["css", "style", "color", "theme", "background", "font", "padding", "margin", "border", "appearance"]
    form_keywords = ["form", "input", "field", "text field", "label", "validation", "submit"]
    
    # Calculate specificity scores (higher = more specific match)
    def count_keywords(text, keywords):
        return sum(1 for kw in keywords if kw in text)
    
    auth_score = count_keywords(description_lower, authentication_keywords)
    layout_score = count_keywords(description_lower, layout_keywords)
    ingredient_score = count_keywords(description_lower, ingredient_keywords)
    button_score = count_keywords(description_lower, button_keywords)
    style_score = count_keywords(description_lower, style_keywords)
    form_score = count_keywords(description_lower, form_keywords)
    
    # Sort by score to determine best fits
    scores = [
        ("auth", auth_score),
        ("layout", layout_score),
        ("ingredient", ingredient_score),
        ("button", button_score),
        ("style", style_score),
        ("form", form_score)
    ]
    sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
    
    results = []
    suggested_categories = set()
    
    # Primary result - highest scoring category
    if sorted_scores[0][1] > 0:  # Only if we have a match
        top_category = sorted_scores[0][0]
        suggested_categories.add(top_category)
        
        if top_category == "ingredient":
            results.append({
                "file": "src/components/IngredientList.jsx",
                "lines": "45-68",
                "code": """<label key={ingredient.id} className="ingredient-row flex items-center flex-col group cursor-pointer py-1 px-0 -mx-3 rounded-xl hover:bg-stone-50 transition-all border-b border-stone-50 last:border-0">
  <span className="font-medium text-sm">{ingredient.name}</span>
  <span className="text-xs text-stone-500">{ingredient.quantity} {ingredient.unit}</span>
</label>""",
                "confidence": 0.94
            })
        elif top_category == "button":
            results.append({
                "file": "src/components/Button.jsx",
                "lines": "12-35",
                "code": """export function Button({ children, ...props }) {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
      {children}
    </button>
  )
}""",
                "confidence": 0.93
            })
        elif top_category == "auth":
            results.append({
                "file": "src/components/Login.jsx",
                "lines": "42-55",
                "code": """export function LoginButton() {
  return (
    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg">
      Login
    </button>
  )
}""",
                "confidence": 0.95
            })
        elif top_category == "form":
            results.append({
                "file": "src/components/FormField.jsx",
                "lines": "15-30",
                "code": """export function FormField({ label, type = "text", ...props }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <input type={type} className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" {...props} />
    </div>
  )
}""",
                "confidence": 0.88
            })
        elif top_category == "layout":
            results.append({
                "file": "src/layouts/AccessibleContainer.jsx",
                "lines": "89-102",
                "code": """function AccessibleContainer({ children }) {
  return (
    <div className="w-full overflow-hidden px-4 max-w-container mx-auto">
      {children}
    </div>
  )
}""",
                "confidence": 0.91
            })
        elif top_category == "style":
            results.append({
                "file": "src/styles/theme.css",
                "lines": "1-25",
                "code": """:root {
  --primary-color: #3b82f6;
  --secondary-color: #ef4444;
  --text-color: #1f2937;
  --bg-color: #ffffff;
  --border-color: #e5e7eb;
  --spacing-unit: 0.5rem;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto;
  color: var(--text-color);
  background-color: var(--bg-color);
}""",
                "confidence": 0.89
            })
    
    # Secondary result - second highest scoring category (different from first)
    if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 and sorted_scores[1][0] not in suggested_categories:
        second_category = sorted_scores[1][0]
        suggested_categories.add(second_category)
        
        if second_category == "style":
            results.append({
                "file": "src/styles/layout.css",
                "lines": "128-145",
                "code": """.ingredient-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
}

.ingredient-row:hover {
  background-color: #f5f5f0;
  border-radius: 0.5rem;
}""",
                "confidence": 0.82
            })
        elif second_category == "layout":
            results.append({
                "file": "src/layouts/PageLayout.jsx",
                "lines": "23-41",
                "code": """export function PageLayout({ children }) {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      <main className="flex-1 container mx-auto px-4 py-8">
        {children}
      </main>
      <Footer />
    </div>
  )
}""",
                "confidence": 0.79
            })
        elif second_category == "button":
            results.append({
                "file": "src/components/IconButton.jsx",
                "lines": "5-20",
                "code": """export function IconButton({ icon: Icon, ...props }) {
  return (
    <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
      <Icon className="w-5 h-5" />
    </button>
  )
}""",
                "confidence": 0.80
            })
        elif second_category == "form":
            results.append({
                "file": "src/components/SearchForm.jsx",
                "lines": "10-28",
                "code": """export function SearchForm() {
  const [query, setQuery] = useState("");
  
  return (
    <form onSubmit={(e) => { e.preventDefault(); }}>
      <input
        type="text"
        placeholder="Search ingredients..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full px-4 py-2 border rounded-lg"
      />
    </form>
  )
}""",
                "confidence": 0.85
            })
    
    return results
