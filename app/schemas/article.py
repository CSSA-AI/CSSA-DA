import uuid
from typing import List, Optional
from datetime import date, datetime
from pydantic import AliasChoices, BaseModel, Field, field_validator

class Article(BaseModel):
    # --- 1. 声明字段 (Declarative Fields) ---
    # Pydantic 会自动读取这些来验证数据
    text: str
    questions: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("questions", "question"),
    )
    
    # default_factory 用于动态生成默认值，完美替代你的 manual UUID logic
    id: str = Field(default_factory=lambda: str(uuid.uuid4())) 
    
    source: Optional[str] = None
    author: Optional[str] = None
    
    # Pydantic 极其智能：如果你传了字符串 "2024-01-01"，它会自动帮你转成 date 对象！
    # 不需要你自己写 try-except 解析逻辑。
    post_date: Optional[date] = None 
    created_at: Optional[datetime] = None
    
    language: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    link: Optional[str] = None

    @field_validator("questions", mode="before")
    @classmethod
    def normalize_questions(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    # --- 2. 自定义逻辑 (如果有必要) ---
    # 如果你需要特殊的日期解析逻辑，可以用 @field_validator，但通常不需要
    
    # --- 3. 你的工具方法 (Utility Methods) ---
    def summary(self, length=100):
        """Return a short preview of the text."""
        return (self.text[:length] + "...") if len(self.text) > length else self.text
    
    # to_dict 和 from_dict 不需要了！
    # Pydantic 自带: article.model_dump() 和 Article(**dict_data)
    
    # 如果你非要保留 load from file 的功能：
    @classmethod
    def from_file_path(cls, file_path: str):
        import json
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data) # 直接解包字典，Pydantic 会自动验证
        except FileNotFoundError:
            print("json file not found")
            return None
