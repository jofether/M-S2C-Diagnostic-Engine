"""
Input Quality Analyzer for M-S2C Diagnostic Engine.

Analyzes user-provided bug descriptions and screenshots to compute
input quality metrics. Completely independent from retrieval pipeline.

Metrics:
- Description Quality: Analyzed on word count, technical terms, clarity
- Screenshot Quality: Checked for existence, validity, dimensions
- Input Quality Score: Combined quality percentage
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class InputQualityAnalyzer:
    """Analyzes input description and screenshot quality independently."""
    
    # Configuration thresholds for quality scoring
    MIN_DESCRIPTION_LENGTH = 20      # Minimum characters for "poor" description
    GOOD_DESCRIPTION_LENGTH = 50     # Characters for "good" description
    EXCELLENT_DESCRIPTION_LENGTH = 100  # Characters for "excellent" description
    
    TECHNICAL_KEYWORDS = {
        'button', 'click', 'error', 'bug', 'issue', 'icon', 'text', 'input',
        'form', 'submit', 'page', 'load', 'fail', 'crash', 'missing', 'broken',
        'display', 'alignment', 'color', 'size', 'responsive', 'mobile', 'desktop',
        'component', 'element', 'style', 'css', 'javascript', 'react', 'animation'
    }
    
    MIN_SCREENSHOT_WIDTH = 400      # Minimum screenshot width (pixels)
    MIN_SCREENSHOT_HEIGHT = 300     # Minimum screenshot height (pixels)
    MAX_SCREENSHOT_SIZE = 10 * 1024 * 1024  # 10MB max
    
    def __init__(self):
        """Initialize the input quality analyzer."""
        logger.info("📊 Input Quality Analyzer initialized")
    
    def analyze_description(self, description: str) -> dict:
        """
        Analyze bug description quality.
        
        Args:
            description: User-provided bug description text
            
        Returns:
            dict: {
                'text': str - quality grade (Poor/Fair/Good/Excellent),
                'score': float - 0-100 quality percentage,
                'length': int - character count,
                'word_count': int - word count,
                'technical_keywords_found': int - count of technical terms,
                'details': str - explanation of scoring
            }
        """
        if not description:
            return {
                'text': 'No Input',
                'score': 0,
                'length': 0,
                'word_count': 0,
                'technical_keywords_found': 0,
                'details': 'No description provided'
            }
        
        description = description.strip()
        char_count = len(description)
        word_count = len(description.split())
        
        # Find technical keywords in description
        description_lower = description.lower()
        keywords_found = sum(1 for kw in self.TECHNICAL_KEYWORDS if kw in description_lower)
        
        # Calculate quality score (0-100)
        score = 0
        grade = 'Poor'
        
        # Length scoring (0-40 points)
        if char_count >= self.EXCELLENT_DESCRIPTION_LENGTH:
            score += 40
            length_rating = "Excellent"
        elif char_count >= self.GOOD_DESCRIPTION_LENGTH:
            score += 30
            length_rating = "Good"
        elif char_count >= self.MIN_DESCRIPTION_LENGTH:
            score += 15
            length_rating = "Fair"
        else:
            score += 0
            length_rating = "Too short"
        
        # Technical keywords scoring (0-30 points)
        keyword_score = min(30, keywords_found * 5)  # 5 points per keyword, max 30
        score += keyword_score
        keyword_rating = f"{keywords_found} technical terms"
        
        # Word count diversity (0-20 points)
        unique_words = len(set(description_lower.split()))
        diversity_ratio = unique_words / max(word_count, 1)
        if diversity_ratio > 0.7:
            score += 20
            diversity_rating = "Excellent"
        elif diversity_ratio > 0.5:
            score += 15
            diversity_rating = "Good"
        elif diversity_ratio > 0.3:
            score += 8
            diversity_rating = "Fair"
        else:
            score += 0
            diversity_rating = "Repetitive"
        
        # Punctuation/completeness (0-10 points)
        if description.endswith(('.', '!', '?')):
            score += 5
        if description.count('\n') > 0:  # Multi-line suggests detail
            score += 5
        
        # Clamp score to 100
        score = min(100, score)
        
        # Grade assignment
        if score >= 80:
            grade = 'Excellent'
        elif score >= 60:
            grade = 'Good'
        elif score >= 40:
            grade = 'Fair'
        else:
            grade = 'Poor'
        
        return {
            'text': grade,
            'score': score,
            'length': char_count,
            'word_count': word_count,
            'technical_keywords_found': keywords_found,
            'details': f"{length_rating} length ({char_count} chars), {keyword_rating}, {diversity_rating} word diversity"
        }
    
    def analyze_screenshot(self, screenshot_path: str = None) -> dict:
        """
        Analyze screenshot quality.
        
        Args:
            screenshot_path: Path to screenshot file, or None if no screenshot
            
        Returns:
            dict: {
                'text': str - quality grade (None/Poor/Fair/Good),
                'score': float - 0-100 quality percentage,
                'file_exists': bool,
                'file_size_mb': float,
                'dimensions': tuple or None - (width, height),
                'details': str - explanation of scoring
            }
        """
        result = {
            'text': None,
            'score': 0,
            'file_exists': False,
            'file_size_mb': 0,
            'dimensions': None,
            'details': ''
        }
        
        if not screenshot_path:
            result['details'] = 'No screenshot provided'
            return result
        
        # Check if file exists
        if not os.path.exists(screenshot_path):
            result['details'] = f'File not found: {screenshot_path}'
            result['text'] = 'Missing'
            return result
        
        result['file_exists'] = True
        
        try:
            # Get file size
            file_size = os.path.getsize(screenshot_path)
            result['file_size_mb'] = file_size / (1024 * 1024)
            
            # Check file size validity
            score = 0
            if file_size > self.MAX_SCREENSHOT_SIZE:
                result['details'] = f'File too large: {result["file_size_mb"]:.2f}MB (max {self.MAX_SCREENSHOT_SIZE / (1024*1024):.0f}MB)'
                result['text'] = 'Poor'
                return result
            
            # Try to open and check dimensions
            from PIL import Image
            try:
                img = Image.open(screenshot_path)
                width, height = img.size
                result['dimensions'] = (width, height)
                
                # Dimension scoring (0-60 points)
                if width >= 1920 and height >= 1080:
                    score += 60
                    dimension_rating = "Excellent"
                elif width >= self.MIN_SCREENSHOT_WIDTH and height >= self.MIN_SCREENSHOT_HEIGHT:
                    score += 40
                    dimension_rating = "Good"
                else:
                    score += 20
                    dimension_rating = "Acceptable"
                
                # File format scoring (0-20 points)
                fmt = img.format
                if fmt in ['PNG', 'JPEG', 'JPG', 'WEBP']:
                    score += 20
                    format_rating = f"{fmt} (good)"
                else:
                    score += 10
                    format_rating = f"{fmt} (ok)"
                
                # File size efficiency (0-20 points)
                if result['file_size_mb'] < 2:
                    score += 20
                    size_rating = f"{result['file_size_mb']:.2f}MB (efficient)"
                elif result['file_size_mb'] < 5:
                    score += 10
                    size_rating = f"{result['file_size_mb']:.2f}MB (acceptable)"
                else:
                    size_rating = f"{result['file_size_mb']:.2f}MB (large)"
                
                score = min(100, score)
                result['score'] = score
                
                # Grade assignment
                if score >= 80:
                    result['text'] = 'Excellent'
                elif score >= 60:
                    result['text'] = 'Good'
                elif score >= 40:
                    result['text'] = 'Fair'
                else:
                    result['text'] = 'Poor'
                
                result['details'] = f"{dimension_rating} dimensions ({width}x{height}), {format_rating}, {size_rating}"
                
            except Exception as e:
                result['text'] = 'Invalid'
                result['details'] = f'Cannot read image: {str(e)}'
                result['score'] = 0
        
        except Exception as e:
            result['details'] = f'Error analyzing screenshot: {str(e)}'
            result['text'] = 'Error'
            result['score'] = 0
        
        return result
    
    def analyze_combined_input(self, description: str = None, screenshot_path: str = None) -> dict:
        """
        Analyze combined input quality (description + screenshot).
        
        Args:
            description: User-provided bug description
            screenshot_path: Path to screenshot file
            
        Returns:
            dict: {
                'description_quality': dict - analysis of description,
                'screenshot_quality': dict - analysis of screenshot,
                'overall_score': float - 0-100 combined score,
                'overall_grade': str - Poor/Fair/Good/Excellent,
                'recommendation': str - feedback for user,
                'input_type': str - 'text_only' / 'screenshot_only' / 'combined'
            }
        """
        desc_quality = self.analyze_description(description)
        screenshot_quality = self.analyze_screenshot(screenshot_path)
        
        # Determine input type
        has_desc = desc_quality['score'] > 0
        has_screenshot = screenshot_quality['file_exists']
        
        if has_desc and has_screenshot:
            input_type = 'combined'
        elif has_desc:
            input_type = 'text_only'
        elif has_screenshot:
            input_type = 'screenshot_only'
        else:
            input_type = 'empty'
        
        # Calculate combined score
        if input_type == 'empty':
            overall_score = 0
            overall_grade = 'No Input'
            recommendation = 'Please provide a bug description and/or screenshot'
        elif input_type == 'text_only':
            overall_score = desc_quality['score']
            recommendation = 'Consider providing a screenshot for better results'
        elif input_type == 'screenshot_only':
            overall_score = screenshot_quality['score']
            recommendation = 'Please add a description to help identify the bug'
        else:  # combined
            # Weight description 60%, screenshot 40%
            overall_score = (desc_quality['score'] * 0.6) + (screenshot_quality['score'] * 0.4)
            recommendation = 'Input quality is good - ready to analyze'
        
        # Grade assignment
        if overall_score >= 80:
            overall_grade = 'Excellent'
        elif overall_score >= 60:
            overall_grade = 'Good'
        elif overall_score >= 40:
            overall_grade = 'Fair'
        elif overall_score > 0:
            overall_grade = 'Poor'
        else:
            overall_grade = 'None'
        
        return {
            'description_quality': desc_quality,
            'screenshot_quality': screenshot_quality,
            'overall_score': round(overall_score, 1),
            'overall_grade': overall_grade,
            'recommendation': recommendation,
            'input_type': input_type
        }
    
    def log_analysis(self, analysis: dict):
        """Log input quality analysis results."""
        logger.info(f"\n📋 INPUT QUALITY ANALYSIS:")
        logger.info(f"   Overall Grade: {analysis['overall_grade']} ({analysis['overall_score']}%)")
        logger.info(f"   Input Type: {analysis['input_type']}")
        
        desc_q = analysis['description_quality']
        if desc_q['score'] > 0:
            logger.info(f"   Description Quality: {desc_q['text']} ({desc_q['score']}%)")
            logger.info(f"     → {desc_q['details']}")
        
        screen_q = analysis['screenshot_quality']
        if screen_q['file_exists']:
            logger.info(f"   Screenshot Quality: {screen_q['text']} ({screen_q['score']}%)")
            logger.info(f"     → {screen_q['details']}")
        
        logger.info(f"   💡 Recommendation: {analysis['recommendation']}\n")
