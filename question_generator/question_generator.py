"""
Question Generator module using OpenAI API.
Generates relevant Chinese questions for articles.
"""

from openai import OpenAI
from typing import List, Dict, Any
from .config import Config
from .utils import extract_article_content, validate_article_structure

class QuestionGenerator:
    """Handles question generation using OpenAI API."""
    
    def __init__(self):
        """Initialize the question generator with OpenAI API key."""
        if not Config.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured")
        
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.model = Config.OPENAI_MODEL
        self.max_tokens = Config.MAX_TOKENS
        self.temperature = Config.TEMPERATURE
    
    def generate_questions_for_article(self, article: Dict[str, Any]) -> List[str]:
        """Generate questions for a single article."""
        if not validate_article_structure(article):
            return []
        
        content = extract_article_content(article)
        if not content:
            return []
        
        title = article.get('title', '')
        
        # Create the prompt for question generation
        prompt = self._create_question_prompt(title, content)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的教育内容分析师，专门为留学相关的文章生成高质量的中文问题。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                n=1
            )
            
            # Extract and parse the generated questions
            questions_text = response.choices[0].message.content.strip()
            questions = self._parse_questions(questions_text)
            
            return questions[:Config.QUESTIONS_PER_ARTICLE]
            
        except Exception as e:
            print(f"❌ Error generating questions: {e}")
            return []
    
    def _create_question_prompt(self, title: str, content: str) -> str:
        """Create a universal prompt for question generation (any content type)."""
        content_patterns = self._detect_content_patterns(content)
        return f"""
请基于下面这篇文章，为真实读者写出{Config.QUESTIONS_PER_ARTICLE}个"自然、口语化、可由本文回答"的问题。

文章标题：{title}

文章内容：
{content}

写作指引（重要）：
1) 语气与风格：
   - 像人在咨询时会问的自然问题，不要机械或模板化。
   - 用简洁口语表达。
2) 泛化但可回答：
   - 问题应适用于类似场景（便于后续RAG检索），尽量避免直接写出文章中的专有名词。
   - 问题应独立完整，不依赖"这篇文章/这个产品"等指代，但保证问题仍能由本文内容作答。
3) 信息取材：
   - 紧扣文章中可落地的信息：流程/材料/条件/分数/费用构成/时限/差异点/注意事项/常见误区/操作步骤等。
   - 问题中应包含文章的主要主体（如大学名称、专业名称、地区名称等），但避免过于具体的细节。
4) 形式要求：
   - 每个问题一行，不要编号，不要解释或前后缀。
   - 每个问题尽量不超过30个字，直截了当。
   - 严禁复述标题，也不要出现"这篇文章/本文/核心要点是什么"之类句式。

仅输出问题列表，每行一个问题，不要其他内容。
"""
    
    def _parse_questions(self, questions_text: str) -> List[str]:
        """Parse the generated questions from the API response."""
        questions = []
        lines = questions_text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            # Remove common prefixes like numbers, dashes, etc.
            line = line.lstrip('0123456789.-•* ')
            
            if line and len(line) > 5:  # Minimum question length
                questions.append(line)
        
        return questions
    
    def _detect_content_patterns(self, content: str) -> List[str]:
        """Detect broad content patterns for universal question generation."""
        content_lower = content.lower()
        patterns = []
        
        # Informational patterns
        if any(word in content_lower for word in ['介绍', '说明', '指南', '教程', '如何', '怎么']):
            patterns.append('informational')
        
        # Comparative patterns
        if any(word in content_lower for word in ['对比', '比较', '选择', '差异', '优势', '劣势']):
            patterns.append('comparative')
        
        # Process patterns
        if any(word in content_lower for word in ['步骤', '流程', '方法', '操作', '申请', '办理']):
            patterns.append('process')
        
        # Cost patterns
        if any(word in content_lower for word in ['价格', '费用', '成本', '花费', '学费', '生活费']):
            patterns.append('cost')
        
        # Requirements patterns
        if any(word in content_lower for word in ['条件', '要求', '资格', '标准', '门槛', '限制']):
            patterns.append('requirements')
        
        # Features patterns
        if any(word in content_lower for word in ['特点', '功能', '优势', '特色', '亮点', '卖点']):
            patterns.append('features')
        
        # Lifestyle patterns
        if any(word in content_lower for word in ['生活', '娱乐', '美食', '旅游', '购物', '体验']):
            patterns.append('lifestyle')
        
        # Personal patterns
        if any(word in content_lower for word in ['感受', '建议', '推荐', '评价', '体验', '心得']):
            patterns.append('personal')
        
        return patterns
    
    def generate_questions_for_articles(self, articles: List[Dict[str, Any]]) -> Dict[int, List[str]]:
        """Generate questions for multiple articles."""
        results = {}
        
        for i, article in enumerate(articles):
            questions = self.generate_questions_for_article(article)
            if questions:
                results[i] = questions
        
        return results
