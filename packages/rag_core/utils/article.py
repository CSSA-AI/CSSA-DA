import json

class Article:
    def __init__(self, title, raw_text, id = None, questions = None, 
                 text = None, source = None, author = None, post_date = None, 
                 language = None, created_at = None, tags = None, link = None):
        self.id = id
        self.questions = questions
        self.raw_text = raw_text
        self.text = text
        self.source = source
        self.title = title
        self.author = author
        self.post_date = post_date
        self.language = language
        self.created_at = created_at
        self.tags = tags
        self.link = link

    # --- Utility methods ---
    def summary(self, length=100):
        """Return a short preview of the text."""
        return (self.text[:length] + "...") if len(self.text) > length else self.text

    def to_dict(self):
        """Convert Article object back into a dictionary."""
        return {
            "id": self.id,
            "questions": self.questions,
            "raw_text": self.raw_text,
            "text": self.text,
            "source": self.source,
            "title": self.title,
            "author": self.author,
            "post_date": self.post_date,
            "language": self.language,
            "created_at": self.created_at,
            "tags": self.tags,
            "link": self.link,
        }
    
    def get_info(self):
        """Print out attribute : value pairs in a readable format"""
        for key, value in self.__dict__.items():
            print(f"{key}: {value}")

    def __repr__(self):
        """Pretty representation for debugging."""
        return f"<Article id={self.id}, title={self.title[:20]}...>"

    @classmethod
    def from_dict(cls, data:dict):
        return cls(**data)
    
    @classmethod
    def from_file_path(cls, file_path:str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            print("json file not found")