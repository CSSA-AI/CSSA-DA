#!/usr/bin/env python3
"""
Main execution script for the Question Generator Tool.
Provides interactive terminal interface for file selection and processing.
"""

import sys
from pathlib import Path
from typing import List

from .config import Config
from .utils import display_file_selection, display_summary
from .file_processor import FileProcessor

def main():
    """Main execution function."""
    print("🤖 Question Generator Tool")
    print("=" * 50)
    print("Generate Chinese questions for articles using GPT-4")
    print("=" * 50)
    
    try:
        # Validate configuration
        Config.validate_config()
        print("✅ Configuration validated")
        
        # Get available files
        available_files = Config.get_available_files()
        if not available_files:
            print("❌ No JSON files found in the data directory.")
            print(f"   Please add JSON files to: {Config.DATA_DIR}")
            return
        
        # Display file selection interface
        selected_files = display_file_selection(available_files)
        if not selected_files:
            print("❌ No files selected for processing.")
            return
        
        # Confirm processing
        print(f"\n🎯 Selected {len(selected_files)} file(s) for processing:")
        for file_path in selected_files:
            print(f"   • {file_path.name}")
        
        confirm = input("\n❓ Proceed with question generation? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("👋 Operation cancelled.")
            return
        
        # Initialize file processor
        processor = FileProcessor()
        
        # Process files
        print(f"\n🚀 Starting question generation for {len(selected_files)} file(s)...")
        results = processor.process_files(selected_files)
        
        # Display summary
        total_questions = sum(results.values())
        display_summary(selected_files, total_questions)
        
        # Show detailed results
        print("\n📋 Detailed Results:")
        for file_path, questions_count in results.items():
            status = "✅" if questions_count > 0 else "❌"
            print(f"   {status} {file_path.name}: {questions_count} questions")
        
        print(f"\n🎉 Processing completed!")
        
    except KeyboardInterrupt:
        print("\n\n👋 Operation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

def preview_files():
    """Preview files without processing them."""
    print("🔍 File Preview Mode")
    print("=" * 30)
    
    try:
        Config.validate_config()
        available_files = Config.get_available_files()
        
        if not available_files:
            print("❌ No JSON files found.")
            return
        
        processor = FileProcessor()
        
        for file_path in available_files:
            preview = processor.preview_file(file_path)
            
            if 'error' in preview:
                print(f"\n❌ {preview['file_name']}: {preview['error']}")
                continue
            
            print(f"\n📁 {preview['file_name']}")
            print(f"   📊 Total articles: {preview['total_articles']}")
            print(f"   ✅ Valid articles: {preview['valid_articles']}")
            print(f"   📏 File size: {preview['file_size_kb']:.1f} KB")
            
            if preview['sample_articles']:
                print("   📝 Sample articles:")
                for sample in preview['sample_articles']:
                    status = "✅" if sample['is_valid'] else "❌"
                    title = sample['title'][:50] + "..." if len(sample['title']) > 50 else sample['title']
                    print(f"      {status} {sample['index']}: {title}")
    
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "preview":
            preview_files()
        elif sys.argv[1] == "help":
            print("Question Generator Tool Usage:")
            print("  python -m question_generator.main          # Interactive mode")
            print("  python -m question_generator.main preview  # Preview files only")
            print("  python -m question_generator.main help     # Show this help")
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use 'help' for usage information.")
    else:
        main()
