"""
Utility functions for the Question Generator Tool.
Includes file operations, backup creation, and terminal interactions.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import sys



def load_json_file(file_path: Path) -> List[Dict[str, Any]]:
    """Load and parse a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in {file_path}: {e}")
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")

def save_json_file(file_path: Path, data: List[Dict[str, Any]]) -> None:
    """Save data to a JSON file with proper formatting."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise IOError(f"Failed to save file {file_path}: {e}")

def display_file_selection(files: List[Path]) -> List[Path]:
    """Display available files and let user select which ones to process."""
    if not files:
        print("❌ No JSON files found in the data directory.")
        return []
    
    print("\n📁 Available JSON files:")
    print("=" * 50)
    
    for i, file_path in enumerate(files, 1):
        file_size = file_path.stat().st_size / 1024  # Size in KB
        print(f"{i:2d}. {file_path.name} ({file_size:.1f} KB)")
    
    print("\n" + "=" * 50)
    print("Options:")
    print("  • Enter file numbers separated by commas (e.g., 1,3,5)")
    print("  • Enter 'all' to process all files")
    print("  • Enter 'q' to quit")
    
    while True:
        try:
            choice = input("\n🎯 Select files to process: ").strip().lower()
            
            if choice == 'q':
                print("👋 Goodbye!")
                sys.exit(0)
            
            if choice == 'all':
                return files
            
            # Parse comma-separated numbers
            selected_indices = [int(x.strip()) - 1 for x in choice.split(',')]
            
            # Validate indices
            if any(i < 0 or i >= len(files) for i in selected_indices):
                print("❌ Invalid file number. Please try again.")
                continue
            
            selected_files = [files[i] for i in selected_indices]
            return selected_files
            
        except ValueError:
            print("❌ Invalid input. Please enter numbers separated by commas.")
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            sys.exit(0)

def display_processing_progress(current: int, total: int, file_name: str) -> None:
    """Display processing progress."""
    percentage = (current / total) * 100
    bar_length = 30
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    print(f"\r🔄 Processing {file_name}: [{bar}] {percentage:.1f}% ({current}/{total})", end='', flush=True)

def display_summary(processed_files: List[Path], total_questions: int) -> None:
    """Display processing summary."""
    print("\n\n" + "=" * 60)
    print("📊 PROCESSING SUMMARY")
    print("=" * 60)
    print(f"✅ Files processed: {len(processed_files)}")
    print(f"📝 Total questions generated: {total_questions}")
    print("\n📁 Processed files:")
    for file_path in processed_files:
        print(f"   • {file_path.name}")
    print("=" * 60)

def validate_article_structure(article: Dict[str, Any]) -> bool:
    """Validate that an article has the required fields for question generation."""
    required_fields = ['text', 'title']
    return all(field in article and article[field] for field in required_fields)

def extract_article_content(article: Dict[str, Any]) -> str:
    """Extract the main content from an article for question generation."""
    # Prefer 'text' field, fallback to 'raw_text' if 'text' is empty
    content = article.get('text', '') or article.get('raw_text', '')
    
    if not content:
        return ""
    
    # Clean up the content - remove excessive whitespace and normalize
    content = ' '.join(content.split())
    
    # Limit content length to avoid token limits
    max_length = 4000  # Conservative limit
    if len(content) > max_length:
        content = content[:max_length] + "..."
    
    return content
