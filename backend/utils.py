"""
Utility functions for bug diagnosis and weighting
"""


def compute_gating_weight(bug_description: str):
    """
    Compute text vs visual contribution based on description quality and length.
    Better descriptions → higher text weight
    Shorter/vague descriptions → higher visual weight (screenshot more important)
    Returns normalized values between 0 and 1 (not percentages).
    """
    desc_length = len(bug_description)
    detail_keywords = ["specifically", "specifically", "exactly", "exactly", "however", "although", "instead of", "should be"]
    detail_count = sum(1 for kw in detail_keywords if kw in bug_description.lower())
    
    # Longer, more detailed descriptions get higher text weight
    if desc_length > 200 and detail_count > 0:
        text_weight = 0.7
        visual_weight = 0.3
    elif desc_length > 100:
        text_weight = 0.5
        visual_weight = 0.5
    elif desc_length > 50:
        text_weight = 0.35
        visual_weight = 0.65
    else:
        text_weight = 0.2
        visual_weight = 0.8
    
    return text_weight, visual_weight


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
