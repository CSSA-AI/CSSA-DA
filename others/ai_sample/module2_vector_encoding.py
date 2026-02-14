#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块2：向量编码与索引构建（HuggingFace）
功能：使用bert-base-chinese对所有问题编码，生成PyTorch张量和索引
输入：qa_dataset_cleaned.json
输出：qa_tensors.pt, id_map.json, 向量索引结构
"""

import json
import torch
import numpy as np
from transformers import BertTokenizer, BertModel
from typing import List, Dict, Any, Tuple
import os
import pickle
from tqdm import tqdm

# 检查是否有CUDA可用
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"使用设备: {device}")

class QuestionEncoder:
    """
    问题编码器类，使用BERT模型对中文问题进行编码
    """
    
    def __init__(self, model_name: str = "bert-base-chinese"):
        """
        初始化编码器
        Args:
            model_name: 使用的BERT模型名称
        """
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self.max_length = 128  # 最大序列长度
        
    def load_model(self):
        """
        加载预训练的BERT模型和分词器
        """
        print(f"正在加载模型: {self.model_name}")
        try:
            self.tokenizer = BertTokenizer.from_pretrained(self.model_name)
            self.model = BertModel.from_pretrained(self.model_name)
            self.model.to(device)
            self.model.eval()  # 设置为评估模式
            print("模型加载成功")
        except Exception as e:
            print(f"模型加载失败: {e}")
            print("尝试使用本地模型或检查网络连接")
            raise
    
    def encode_questions(self, questions: List[str]) -> torch.Tensor:
        """
        对问题列表进行批量编码
        Args:
            questions: 问题字符串列表
        Returns:
            torch.Tensor: 编码后的张量，形状为 (N, hidden_size)
        """
        if self.model is None:
            self.load_model()
        
        all_embeddings = []
        batch_size = 8  # 批处理大小
        
        print(f"正在编码 {len(questions)} 个问题...")
        
        with torch.no_grad():
            for i in tqdm(range(0, len(questions), batch_size)):
                batch_questions = questions[i:i + batch_size]
                
                # 分词和编码
                inputs = self.tokenizer(
                    batch_questions,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt"
                ).to(device)
                
                # 获取BERT输出
                outputs = self.model(**inputs)
                
                # 使用[CLS]标记的输出作为句子表示
                # 或者可以使用平均池化：torch.mean(outputs.last_hidden_state, dim=1)
                cls_embeddings = outputs.last_hidden_state[:, 0, :]
                
                all_embeddings.append(cls_embeddings.cpu())
        
        # 拼接所有批次的结果
        final_embeddings = torch.cat(all_embeddings, dim=0)
        print(f"编码完成，张量形状: {final_embeddings.shape}")
        
        return final_embeddings

def load_qa_data(file_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    加载问答数据
    Args:
        file_path: JSON文件路径
    Returns:
        qa_data: 完整的问答数据列表
        questions: 问题字符串列表
    """
    print(f"正在加载问答数据: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        qa_data = json.load(f)
    
    questions = [item['question'] for item in qa_data]
    
    print(f"加载了 {len(qa_data)} 条问答数据")
    return qa_data, questions

def save_tensors(tensors: torch.Tensor, file_path: str):
    """
    保存张量到文件
    """
    torch.save(tensors, file_path)
    print(f"张量已保存到: {file_path}")

def save_id_mapping(qa_data: List[Dict[str, Any]], file_path: str):
    """
    保存ID映射关系到JSON文件
    """
    id_map = {}
    for i, item in enumerate(qa_data):
        id_map[str(i)] = {
            "original_id": item["id"],
            "question": item["question"],
            "answer": item["answer"],
            "link": item["link"],
            "tags": item["tags"]
        }
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(id_map, f, ensure_ascii=False, indent=2)
    
    print(f"ID映射已保存到: {file_path}")

def build_faiss_index(embeddings: torch.Tensor) -> object:
    """
    构建FAISS向量索引
    Args:
        embeddings: 问题向量张量
    Returns:
        FAISS索引对象
    """
    try:
        import faiss
        
        # 转换为numpy数组
        embeddings_np = embeddings.numpy().astype('float32')
        
        # 建立索引
        dimension = embeddings_np.shape[1]
        print(f"构建FAISS索引，维度: {dimension}")
        
        # 使用L2距离的暴力搜索索引（适合小数据集）
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings_np)
        
        print(f"FAISS索引构建完成，包含 {index.ntotal} 个向量")
        return index
        
    except ImportError:
        print("FAISS未安装，跳过索引构建")
        print("可以使用: pip install faiss-cpu  或  pip install faiss-gpu")
        return None

def save_faiss_index(index, file_path: str):
    """
    保存FAISS索引到文件
    """
    if index is not None:
        import faiss
        faiss.write_index(index, file_path)
        print(f"FAISS索引已保存到: {file_path}")

def main():
    """
    主函数
    """
    print("=== 模块2：向量编码与索引构建 ===")
    
    # 文件路径
    input_file = "qa_dataset_cleaned.json"
    output_tensor_file = "qa_tensors.pt"
    output_id_map_file = "id_map.json"
    output_faiss_index_file = "qa_faiss_index.index"
    
    # 检查输入文件
    if not os.path.exists(input_file):
        print(f"错误：找不到输入文件 {input_file}")
        print("请先运行模块1生成数据文件")
        return
    
    # 1. 加载问答数据
    qa_data, questions = load_qa_data(input_file)
    
    if not questions:
        print("错误：没有找到问题数据")
        return
    
    # 2. 初始化编码器并编码问题
    encoder = QuestionEncoder()
    embeddings = encoder.encode_questions(questions)
    
    # 3. 保存张量文件
    save_tensors(embeddings, output_tensor_file)
    
    # 4. 保存ID映射文件
    save_id_mapping(qa_data, output_id_map_file)
    
    # 5. 构建并保存FAISS索引
    faiss_index = build_faiss_index(embeddings)
    if faiss_index is not None:
        save_faiss_index(faiss_index, output_faiss_index_file)
    
    # 6. 输出统计信息
    print("\n=== 编码统计信息 ===")
    print(f"总问题数量: {len(questions)}")
    print(f"向量维度: {embeddings.shape[1]}")
    print(f"张量形状: {embeddings.shape}")
    print(f"张量大小: {embeddings.element_size() * embeddings.nelement() / 1024:.2f} KB")
    
    # 7. 简单验证
    print("\n=== 验证测试 ===")
    print("前3个问题的向量范数:")
    for i in range(min(3, len(questions))):
        norm = torch.norm(embeddings[i]).item()
        print(f"问题 {i}: '{questions[i][:30]}...' -> 向量范数: {norm:.4f}")

if __name__ == "__main__":
    main() 