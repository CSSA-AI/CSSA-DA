#!/usr/bin/env python3
"""
Launcher script for the Question Generator Tool.
This script makes it easy to run the tool from the project root.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the main module
from question_generator.main import main, preview_files

if __name__ == "__main__":
    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "preview":
            preview_files()
        elif sys.argv[1] == "help":
            print("Question Generator Tool Usage:")
            print("  python run_question_generator.py          # Interactive mode")
            print("  python run_question_generator.py preview  # Preview files only")
            print("  python run_question_generator.py help     # Show this help")
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use 'help' for usage information.")
    else:
        main()
