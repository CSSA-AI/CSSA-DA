#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块1：数据预处理与标准化
功能：读取原始Excel文件，清洗数据，转换为统一JSON格式
输入：生活专区.xlsx
输出：qa_dataset_cleaned.json
"""

import pandas as pd
import json
import re
from typing import List, Dict, Any
import uuid
import os

def inspect_excel_data(file_path: str):
    """
    检查Excel文件的内容和结构
    """
    print(f"正在检查文件: {file_path}")
    
    try:
        # 读取Excel文件
        df = pd.read_excel(file_path)
        
        print(f"数据形状: {df.shape}")
        print(f"列名: {list(df.columns)}")
        print("\n前5行数据:")
        print(df.head())
        
        print("\n数据类型:")
        print(df.dtypes)
        
        print("\n缺失值统计:")
        print(df.isnull().sum())
        
        return df
        
    except Exception as e:
        print(f"读取Excel文件时出错: {e}")
        return None

def clean_text(text: str) -> str:
    """
    清洗文本数据
    """
    if pd.isna(text) or text is None:
        return ""
    
    text = str(text).strip()
    # 移除多余空格
    text = re.sub(r'\s+', ' ', text)
    # 移除特殊字符（保留中文、英文、数字、常用标点）
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.\?\!\,\;\:\-\(\)\[\]\/\"\'\&\%\@\#]', '', text)
    
    return text.strip()

def extract_tags_from_text(question: str, answer: str) -> List[str]:
    """
    从问题和答案中提取标签
    """
    tags = []
    
    # 根据关键词判断分类
    keywords_mapping = {
        "交通": ["公交", "地铁", "出行", "车票", "道路", "停车", "驾照", "违章"],
        "政务": ["办证", "证件", "户口", "身份证", "护照", "签证", "税务", "工商"],
        "生活": ["水电", "物业", "垃圾", "快递", "购物", "医疗", "教育"],
        "金融": ["银行", "贷款", "信用卡", "支付", "转账", "理财"],
        "工作": ["就业", "招聘", "社保", "公积金", "劳动", "工资"]
    }
    
    text = (question + " " + answer).lower()
    
    for category, keywords in keywords_mapping.items():
        if any(keyword in text for keyword in keywords):
            tags.append(category)
    
    return tags

def standardize_data(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    将数据标准化为统一格式
    """
    standardized_data = []
    
    for index, row in df.iterrows():
        # 生成唯一ID
        item_id = f"{index:05d}"
        
        # 根据实际Excel列名提取数据
        question = ""
        answer = ""
        link = ""
        
        # 直接使用已知的列名
        if '标题/问题' in df.columns:
            question = clean_text(row['标题/问题'])
        
        if '内容' in df.columns:
            answer = clean_text(row['内容'])
        
        if '链接' in df.columns:
            link = clean_text(row['链接'])
        
        # 如果没有找到对应列，尝试智能匹配
        if not question:
            question_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['问题', 'question', '提问', '咨询', '标题'])]
            if question_cols:
                question = clean_text(row[question_cols[0]])
        
        if not answer:
            answer_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['答案', 'answer', '回答', '解答', '内容'])]
            if answer_cols:
                answer = clean_text(row[answer_cols[0]])
        
        if not link:
            link_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['链接', 'link', 'url', '网址'])]
            if link_cols:
                link = clean_text(row[link_cols[0]])
        
        # 生成标签
        tags = extract_tags_from_text(question, answer)
        
        # 只保留有效的问答对（降低长度要求）
        if question and answer and len(question) > 1 and len(answer) > 1:
            item = {
                "id": item_id,
                "question": question,
                "answer": answer,
                "link": link if link else "",
                "tags": tags
            }
            standardized_data.append(item)
        else:
            # 调试信息：显示被过滤的数据
            print(f"过滤数据 {index}: 问题='{question}' (长度:{len(question)}), 答案='{answer}' (长度:{len(answer)})")
    
    return standardized_data

def save_to_json(data: List[Dict[str, Any]], output_path: str):
    """
    保存数据到JSON文件
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"数据已保存到: {output_path}")
        print(f"共处理了 {len(data)} 条问答数据")
    except Exception as e:
        print(f"保存JSON文件时出错: {e}")

def main():
    """
    主函数
    """
    input_file = "生活专区.xlsx"
    output_file = "qa_dataset_cleaned.json"
    
    # 检查输入文件是否存在
    if not os.path.exists(input_file):
        print(f"错误：找不到输入文件 {input_file}")
        return
    
    print("=== 模块1：数据预处理与标准化 ===")
    
    # 1. 检查原始数据
    df = inspect_excel_data(input_file)
    if df is None:
        return
    
    # 2. 数据标准化
    print("\n正在进行数据标准化...")
    standardized_data = standardize_data(df)
    
    # 3. 保存结果
    save_to_json(standardized_data, output_file)
    
    # 4. 显示样例
    if standardized_data:
        print("\n标准化数据样例:")
        for i, item in enumerate(standardized_data[:3]):
            print(f"\n样例 {i+1}:")
            print(json.dumps(item, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main() 