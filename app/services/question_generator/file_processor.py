"""
File processor module for handling JSON file operations.
Reads, processes, and updates files with generated questions.
"""

from pathlib import Path
from typing import List, Dict, Any
from .config import Config
from .utils import (
    load_json_file, save_json_file, 
    display_processing_progress, validate_article_structure
)
from .question_generator import QuestionGenerator

class FileProcessor:
    """Handles file processing operations for question generation."""
    
    def __init__(self):
        """Initialize the file processor."""
        self.question_generator = QuestionGenerator()
    
    def process_file(self, file_path: Path) -> int:
        """Process a single JSON file and generate questions for articles."""
        print(f"\n📖 Processing file: {file_path.name}")
        
        # Load the JSON data
        try:
            articles = load_json_file(file_path)
            print(f"   📊 Found {len(articles)} articles")
        except Exception as e:
            print(f"   ❌ Error loading file: {e}")
            return 0
        

        
        # Filter valid articles
        valid_articles = []
        for i, article in enumerate(articles):
            if validate_article_structure(article):
                valid_articles.append((i, article))
        
        if not valid_articles:
            print("   ⚠️  No valid articles found for question generation")
            return 0
        
        print(f"   ✅ {len(valid_articles)} valid articles found")
        
        # Generate questions for each article
        total_questions = 0
        updated_count = 0
        
        for idx, (article_idx, article) in enumerate(valid_articles):
            display_processing_progress(idx + 1, len(valid_articles), file_path.name)
            
            # Generate questions
            questions = self.question_generator.generate_questions_for_article(article)
            
            if questions:
                # Update the article with generated questions
                articles[article_idx]['question'] = questions[0] if len(questions) == 1 else questions
                total_questions += len(questions)
                updated_count += 1
        
        print()  # New line after progress bar
        
        # Save the updated file
        try:
            save_json_file(file_path, articles)
            print(f"   💾 File updated successfully")
            print(f"   📝 Generated {total_questions} questions for {updated_count} articles")
        except Exception as e:
            print(f"   ❌ Error saving file: {e}")
            return 0
        
        return total_questions
    
    def process_files(self, file_paths: List[Path]) -> Dict[Path, int]:
        """Process multiple files and return results."""
        results = {}
        
        for file_path in file_paths:
            try:
                questions_count = self.process_file(file_path)
                results[file_path] = questions_count
            except Exception as e:
                print(f"❌ Error processing {file_path.name}: {e}")
                results[file_path] = 0
        
        return results
    
    def preview_file(self, file_path: Path) -> Dict[str, Any]:
        """Preview a file's structure and content without processing."""
        try:
            articles = load_json_file(file_path)
            
            preview = {
                'file_name': file_path.name,
                'total_articles': len(articles),
                'valid_articles': 0,
                'sample_articles': [],
                'file_size_kb': file_path.stat().st_size / 1024
            }
            
            # Check first few articles
            for i, article in enumerate(articles[:3]):
                is_valid = validate_article_structure(article)
                if is_valid:
                    preview['valid_articles'] += 1
                
                sample = {
                    'index': i,
                    'title': article.get('title', 'No title'),
                    'has_text': bool(article.get('text')),
                    'has_raw_text': bool(article.get('raw_text')),
                    'has_question': bool(article.get('question')),
                    'is_valid': is_valid
                }
                preview['sample_articles'].append(sample)
            
            return preview
            
        except Exception as e:
            return {
                'file_name': file_path.name,
                'error': str(e)
            }
