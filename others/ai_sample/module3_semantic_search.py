#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块3：语义检索系统
功能：接收用户问题，编码后检索最相似的k个问答对
输入：用户问题字符串、编码模型、索引张量
输出：top-k相关问答条目（含相似度）
"""

import json
import torch
import numpy as np
from transformers import BertTokenizer, BertModel
from typing import List, Dict, Any, Tuple
import os
from sklearn.metrics.pairwise import cosine_similarity

# 检查是否有CUDA可用
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

class SemanticSearcher:
    """
    语义检索器类
    """
    
    def __init__(self, model_name: str = "bert-base-chinese"):
        """
        初始化检索器
        """
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self.qa_embeddings = None
        self.id_mapping = None
        self.faiss_index = None
        self.max_length = 128
        
    def load_model(self):
        """
        加载BERT模型和分词器
        """
        print(f"正在加载模型: {self.model_name}")
        try:
            self.tokenizer = BertTokenizer.from_pretrained(self.model_name)
            self.model = BertModel.from_pretrained(self.model_name)
            self.model.to(device)
            self.model.eval()
            print("模型加载成功")
        except Exception as e:
            print(f"模型加载失败: {e}")
            raise
    
    def load_embeddings(self, tensor_file: str):
        """
        加载预计算的问题向量
        """
        print(f"正在加载向量文件: {tensor_file}")
        self.qa_embeddings = torch.load(tensor_file, map_location='cpu')
        print(f"向量加载成功，形状: {self.qa_embeddings.shape}")
    
    def load_id_mapping(self, id_map_file: str):
        """
        加载ID映射文件
        """
        print(f"正在加载ID映射: {id_map_file}")
        with open(id_map_file, 'r', encoding='utf-8') as f:
            self.id_mapping = json.load(f)
        print(f"ID映射加载成功，包含 {len(self.id_mapping)} 条记录")
    
    def load_faiss_index(self, index_file: str):
        """
        加载FAISS索引
        """
        try:
            import faiss
            print(f"正在加载FAISS索引: {index_file}")
            self.faiss_index = faiss.read_index(index_file)
            print(f"FAISS索引加载成功，包含 {self.faiss_index.ntotal} 个向量")
        except ImportError:
            print("FAISS未安装，将使用余弦相似度进行检索")
            self.faiss_index = None
        except Exception as e:
            print(f"FAISS索引加载失败: {e}")
            self.faiss_index = None
    
    def encode_question(self, question: str) -> torch.Tensor:
        """
        对单个问题进行编码
        """
        if self.model is None:
            self.load_model()
        
        with torch.no_grad():
            inputs = self.tokenizer(
                question,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt"
            ).to(device)
            
            outputs = self.model(**inputs)
            # 使用[CLS]标记的输出作为句子表示
            embedding = outputs.last_hidden_state[:, 0, :].cpu()
            
        return embedding.squeeze(0)  # 移除批次维度
    
    def search_with_faiss(self, query_embedding: torch.Tensor, k: int = 5) -> Tuple[List[float], List[int]]:
        """
        使用FAISS进行快速检索
        """
        query_np = query_embedding.numpy().astype('float32').reshape(1, -1)
        
        # FAISS返回距离（L2距离）和索引
        distances, indices = self.faiss_index.search(query_np, k)
        
        # 转换L2距离为相似度分数（越小距离越相似）
        scores = [1.0 / (1.0 + dist) for dist in distances[0]]
        
        return scores, indices[0].tolist()
    
    def search_with_cosine_similarity(self, query_embedding: torch.Tensor, k: int = 5) -> Tuple[List[float], List[int]]:
        """
        使用余弦相似度进行检索
        """
        query_np = query_embedding.numpy().reshape(1, -1)
        qa_embeddings_np = self.qa_embeddings.numpy()
        
        # 计算余弦相似度
        similarities = cosine_similarity(query_np, qa_embeddings_np)[0]
        
        # 获取top-k结果
        top_k_indices = np.argsort(similarities)[::-1][:k]
        top_k_scores = similarities[top_k_indices]
        
        return top_k_scores.tolist(), top_k_indices.tolist()
    
    def search(self, question: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        主检索函数
        """
        # 检查必要组件是否已加载
        if self.qa_embeddings is None:
            raise ValueError("请先加载向量文件")
        if self.id_mapping is None:
            raise ValueError("请先加载ID映射文件")
        
        print(f"检索问题: '{question}'")
        
        # 1. 编码查询问题
        query_embedding = self.encode_question(question)
        
        # 2. 进行相似度检索
        if self.faiss_index is not None:
            scores, indices = self.search_with_faiss(query_embedding, k)
            print("使用FAISS索引进行检索")
        else:
            scores, indices = self.search_with_cosine_similarity(query_embedding, k)
            print("使用余弦相似度进行检索")
        
        # 3. 构建结果
        results = []
        for i, (score, idx) in enumerate(zip(scores, indices)):
            qa_data = self.id_mapping[str(idx)]
            result = {
                "rank": i + 1,
                "id": qa_data["original_id"],
                "score": float(score),
                "question": qa_data["question"],
                "answer": qa_data["answer"],
                "link": qa_data["link"],
                "tags": qa_data["tags"]
            }
            results.append(result)
        
        print(f"检索完成，返回 {len(results)} 个结果")
        return results
    
    def initialize(self, tensor_file: str, id_map_file: str, faiss_index_file: str = None):
        """
        初始化所有组件
        """
        self.load_model()
        self.load_embeddings(tensor_file)
        self.load_id_mapping(id_map_file)
        
        if faiss_index_file and os.path.exists(faiss_index_file):
            self.load_faiss_index(faiss_index_file)
        
        print("语义检索器初始化完成")

def test_search_system():
    """
    测试检索系统
    """
    print("=== 模块3：语义检索系统测试 ===")
    
    # 文件路径
    tensor_file = "qa_tensors.pt"
    id_map_file = "id_map.json"
    faiss_index_file = "qa_faiss_index.index"
    
    # 检查文件是否存在
    required_files = [tensor_file, id_map_file]
    for file_path in required_files:
        if not os.path.exists(file_path):
            print(f"错误：找不到文件 {file_path}")
            print("请先运行模块2生成必要文件")
            return
    
    # 初始化检索器
    searcher = SemanticSearcher()
    searcher.initialize(tensor_file, id_map_file, faiss_index_file)
    
    # 测试问题列表
    test_questions = [
        "墨尔本怎么坐公交车？",
        "如何使用Myki卡？",
        "学生乘车有优惠吗？",
        "从机场到市区怎么走？",
        "墨尔本停车需要注意什么？"
    ]
    
    print("\n=== 开始测试检索 ===")
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n--- 测试 {i}: {question} ---")
        
        try:
            results = searcher.search(question, k=3)
            
            for result in results:
                print(f"排名 {result['rank']}: (相似度: {result['score']:.4f})")
                print(f"  问题: {result['question']}")
                print(f"  答案: {result['answer']}")
                print(f"  链接: {result['link']}")
                print(f"  标签: {result['tags']}")
                print()
                
        except Exception as e:
            print(f"检索失败: {e}")

def interactive_search():
    """
    交互式检索测试
    """
    print("=== 交互式语义检索测试 ===")
    
    # 文件路径
    tensor_file = "qa_tensors.pt"
    id_map_file = "id_map.json"
    faiss_index_file = "qa_faiss_index.index"
    
    # 初始化检索器
    searcher = SemanticSearcher()
    searcher.initialize(tensor_file, id_map_file, faiss_index_file)
    
    print("\n输入问题进行检索（输入'quit'退出）:")
    
    while True:
        question = input("\n请输入问题: ").strip()
        
        if question.lower() == 'quit':
            break
        
        if not question:
            continue
        
        try:
            results = searcher.search(question, k=3)
            
            print(f"\n检索结果 (共{len(results)}条):")
            for result in results:
                print(f"\n{result['rank']}. 相似度: {result['score']:.4f}")
                print(f"   问题: {result['question']}")
                print(f"   答案: {result['answer']}")
                if result['link']:
                    print(f"   链接: {result['link']}")
                if result['tags']:
                    print(f"   标签: {', '.join(result['tags'])}")
                    
        except Exception as e:
            print(f"检索出错: {e}")
    
    print("感谢使用！")

def main():
    """
    主函数
    """
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        interactive_search()
    else:
        test_search_system()

if __name__ == "__main__":
    main() 