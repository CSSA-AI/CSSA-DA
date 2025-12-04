import json
import uuid
from typing import List, Optional, Union
from datetime import date, datetime

class Article:
    def __init__(
        self, 
        text: str, 
        questions: List[str], 
        id: Optional[str] = None,
        source: Optional[str] = None, 
        author: Optional[str] = None, 
        post_date: Optional[Union[str, date]] = None, 
        language: Optional[str] = None, 
        created_at: Optional[Union[str, datetime]] = None, 
        tags: Optional[List[str]] = None, 
        link: Optional[str] = None
    ):
        # Auto-generate UUID if no ID provided
        self.id = id or str(uuid.uuid4())
        
        self.questions = questions or []
        self.text = text
        self.source = source
        self.author = author

        # Enforce type consistency for dates
        if isinstance(post_date, str):
            try:
                self.post_date = date.fromisoformat(post_date)
            except ValueError:
                raise ValueError(f"Invalid date string for post_date: {post_date}")
        else:
            self.post_date = post_date

        if isinstance(created_at, str):
            try:
                self.created_at = datetime.fromisoformat(created_at)
            except ValueError:
                raise ValueError(f"Invalid datetime string for created_at: {created_at}")
        else:
            self.created_at = created_at

        self.language = language
        self.tags = tags or []
        self.link = link

    # --- Utility methods ---
    def summary(self, length=100):
        """Return a short preview of the text."""
        return (self.text[:length] + "...") if len(self.text) > length else self.text

    def to_dict(self):
        """Convert Article object into a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "questions": self.questions,
            "text": self.text,
            "source": self.source,
            "author": self.author,
            "post_date": self.post_date.isoformat() if self.post_date else None,
            "language": self.language,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "tags": self.tags,
            "link": self.link,
        }
    
    def get_info(self):
        """Print out attribute : value pairs in a readable format"""
        for key, value in self.__dict__.items():
            print(f"{key}: {value}")

    def __repr__(self):
        """Pretty representation for debugging."""
        q_preview = self.questions[0][:20] + "..." if self.questions else "N/A"
        return f"<Article id={self.id}, question='{q_preview}'>"

    @classmethod
    def from_dict(cls, data: dict):
        """Build Article from dict, parsing date/datetime strings if needed."""
        return cls(**data)
    
    @classmethod
    def from_file_path(cls, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except FileNotFoundError:
            print("json file not found")
            return None
