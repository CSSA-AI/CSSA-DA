#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块4：回答生成模块
功能：使用检索到的上下文和用户问题，通过语言模型生成自然语言回答
输入：用户问题 + 检索上下文
输出：生成的回答文本（可包含参考链接）
"""

import json
import os
from typing import List, Dict, Any, Optional
import openai
from module3_semantic_search import SemanticSearcher

class AnswerGenerator:
    """
    回答生成器类
    """
    
    def __init__(self, use_openai: bool = False, api_key: Optional[str] = None):
        """
        初始化回答生成器
        Args:
            use_openai: 是否使用OpenAI API
            api_key: OpenAI API密钥
        """
        self.use_openai = use_openai
        self.searcher = None
        
        if use_openai:
            if api_key:
                openai.api_key = api_key
            else:
                # 尝试从环境变量获取API密钥
                openai.api_key = os.getenv("OPENAI_API_KEY")
            
            if not openai.api_key:
                print("警告：未找到OpenAI API密钥，将使用模板回答模式")
                self.use_openai = False
    
    def initialize_searcher(self, tensor_file: str, id_map_file: str, faiss_index_file: str = None):
        """
        初始化语义检索器
        """
        self.searcher = SemanticSearcher()
        self.searcher.initialize(tensor_file, id_map_file, faiss_index_file)
    
    def create_prompt(self, question: str, context_results: List[Dict[str, Any]]) -> str:
        """
        创建给语言模型的提示词
        """
        # 构建上下文信息
        context_text = ""
        for i, result in enumerate(context_results, 1):
            context_text += f"\n参考资料 {i}:\n"
            context_text += f"问题: {result['question']}\n"
            context_text += f"答案: {result['answer']}\n"
            if result['link']:
                context_text += f"链接: {result['link']}\n"
            if result['tags']:
                context_text += f"标签: {', '.join(result['tags'])}\n"
            context_text += "\n"
        
        # 创建提示词
        prompt = f"""你是一个专业的墨尔本生活助手，专门回答关于墨尔本交通、生活等方面的问题。

用户问题: {question}

参考资料:{context_text}

请根据上述参考资料，为用户提供准确、有用的中文回答。要求：
1. 回答要简洁明了，直接解决用户问题
2. 如果参考资料中有相关信息，请结合这些信息给出答案
3. 如果有有用的链接，请在回答末尾提供
4. 用友好、专业的语气回答
5. 如果参考资料不足以回答问题，请诚实说明并给出建议

回答:"""
        
        return prompt
    
    def generate_with_openai(self, prompt: str) -> str:
        """
        使用OpenAI API生成回答
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "你是一个专业的墨尔本生活助手。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"OpenAI API调用失败: {e}")
            return None
    
    def generate_template_answer(self, question: str, context_results: List[Dict[str, Any]]) -> str:
        """
        生成模板式回答（不使用OpenAI时的备选方案）
        """
        if not context_results:
            return f"抱歉，我没有找到关于'{question}'的相关信息。建议您查看墨尔本官方网站或咨询相关部门。"
        
        # 使用最相关的结果生成回答
        best_result = context_results[0]
        
        answer = f"根据我的知识库，关于您的问题'{question}'：\n\n"
        answer += f"{best_result['answer']}\n\n"
        
        # 添加更多上下文
        if len(context_results) > 1:
            answer += "相关信息：\n"
            for i, result in enumerate(context_results[1:3], 1):  # 最多显示2个额外结果
                answer += f"{i}. {result['question']} - {result['answer']}\n"
            answer += "\n"
        
        # 添加链接
        links = [r['link'] for r in context_results[:3] if r['link']]
        if links:
            answer += "详细信息请参考：\n"
            for i, link in enumerate(links, 1):
                answer += f"{i}. {link}\n"
        
        return answer
    
    def generate_answer(self, question: str, k: int = 3) -> Dict[str, Any]:
        """
        主要的回答生成函数
        """
        if self.searcher is None:
            raise ValueError("请先初始化语义检索器")
        
        print(f"正在为问题生成回答: '{question}'")
        
        # 1. 检索相关上下文
        context_results = self.searcher.search(question, k=k)
        
        # 2. 生成回答
        if self.use_openai:
            prompt = self.create_prompt(question, context_results)
            generated_answer = self.generate_with_openai(prompt)
            
            if generated_answer is None:
                print("OpenAI生成失败，使用模板回答")
                generated_answer = self.generate_template_answer(question, context_results)
        else:
            generated_answer = self.generate_template_answer(question, context_results)
        
        # 3. 构建最终结果
        result = {
            "question": question,
            "answer": generated_answer,
            "search_results": context_results,
            "sources": [r['link'] for r in context_results if r['link']],
            "confidence": context_results[0]['score'] if context_results else 0.0
        }
        
        return result
    
    def batch_generate_answers(self, questions: List[str], k: int = 3) -> List[Dict[str, Any]]:
        """
        批量生成回答
        """
        results = []
        for question in questions:
            try:
                result = self.generate_answer(question, k)
                results.append(result)
            except Exception as e:
                print(f"生成回答失败 '{question}': {e}")
                results.append({
                    "question": question,
                    "answer": "抱歉，生成回答时出现错误。",
                    "search_results": [],
                    "sources": [],
                    "confidence": 0.0
                })
        return results

def test_answer_generation():
    """
    测试回答生成系统
    """
    print("=== 模块4：回答生成模块测试 ===")
    
    # 文件路径
    tensor_file = "qa_tensors.pt"
    id_map_file = "id_map.json"
    faiss_index_file = "qa_faiss_index.index"
    
    # 检查文件是否存在
    required_files = [tensor_file, id_map_file]
    for file_path in required_files:
        if not os.path.exists(file_path):
            print(f"错误：找不到文件 {file_path}")
            print("请先运行模块2和模块3生成必要文件")
            return
    
    # 初始化回答生成器（使用模板模式，不需要OpenAI API）
    generator = AnswerGenerator(use_openai=False)
    generator.initialize_searcher(tensor_file, id_map_file, faiss_index_file)
    
    # 测试问题列表
    test_questions = [
        "墨尔本怎么坐公交车？",
        "如何使用Myki卡？",
        "学生乘车有优惠吗？",
        "从机场到市区怎么走？",
        "墨尔本停车需要注意什么？"
    ]
    
    print("\n=== 开始测试回答生成 ===")
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*60}")
        print(f"测试 {i}: {question}")
        print('='*60)
        
        try:
            result = generator.generate_answer(question)
            
            print(f"生成的回答:")
            print(result['answer'])
            print(f"\n置信度: {result['confidence']:.4f}")
            
            if result['sources']:
                print(f"\n参考链接:")
                for j, source in enumerate(result['sources'][:3], 1):
                    print(f"{j}. {source}")
                    
        except Exception as e:
            print(f"回答生成失败: {e}")

def interactive_qa():
    """
    交互式问答测试
    """
    print("=== 交互式问答系统测试 ===")
    
    # 文件路径
    tensor_file = "qa_tensors.pt"
    id_map_file = "id_map.json"
    faiss_index_file = "qa_faiss_index.index"
    
    # 初始化回答生成器
    generator = AnswerGenerator(use_openai=False)
    generator.initialize_searcher(tensor_file, id_map_file, faiss_index_file)
    
    print("\n欢迎使用墨尔本生活助手！")
    print("输入问题获取答案（输入'quit'退出）:")
    
    while True:
        question = input("\n请输入问题: ").strip()
        
        if question.lower() == 'quit':
            break
        
        if not question:
            continue
        
        try:
            result = generator.generate_answer(question)
            
            print(f"\n🤖 助手回答:")
            print(result['answer'])
            
            if result['sources']:
                print(f"\n📚 参考链接:")
                for i, source in enumerate(result['sources'][:2], 1):
                    print(f"{i}. {source}")
                    
        except Exception as e:
            print(f"❌ 回答生成出错: {e}")
    
    print("\n感谢使用墨尔本生活助手！")

def main():
    """
    主函数
    """
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        interactive_qa()
    else:
        test_answer_generation()

if __name__ == "__main__":
    main() 