"""
Configuration module for the Question Generator Tool.
Handles environment variables, API configuration, and settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class for the question generator tool."""
    
    # API Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL = "gpt-4.1-nano"
    
    # File paths
    DATA_DIR = Path("data")
    
    # Question generation settings
    QUESTIONS_PER_ARTICLE = 10  # Number of questions to generate per article
    MAX_TOKENS = 1000  # Maximum tokens for question generation
    TEMPERATURE = 0.7  # Creativity level for question generation
    
    # Supported file types
    SUPPORTED_EXTENSIONS = ['.json']
    
    @classmethod
    def validate_config(cls):
        """Validate that all required configuration is present."""
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")
        
        if not cls.DATA_DIR.exists():
            raise ValueError(f"Data directory {cls.DATA_DIR} does not exist.")
        
        return True
    
    @classmethod
    def get_available_files(cls):
        """Get list of available JSON files in the data directory."""
        files = []
        for file_path in cls.DATA_DIR.glob("*.json"):
            if file_path.is_file():
                files.append(file_path)
        return sorted(files)
