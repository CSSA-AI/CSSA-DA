#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键启动墨尔本生活助手Chatbot
自动检查依赖、运行必要模块并启动Web界面
"""

import os
import sys
import subprocess
import importlib.util

def check_package(package_name):
    """检查包是否已安装"""
    spec = importlib.util.find_spec(package_name)
    return spec is not None

def install_package(package_name):
    """安装包"""
    subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

def check_dependencies():
    """检查并安装依赖包"""
    required_packages = [
        "torch", "transformers", "tqdm", "faiss-cpu", 
        "scikit-learn", "openai", "gradio", "pandas", "numpy"
    ]
    
    missing_packages = []
    for package in required_packages:
        if not check_package(package):
            missing_packages.append(package)
    
    if missing_packages:
        print(f"检测到缺少以下依赖包: {', '.join(missing_packages)}")
        print("正在安装...")
        
        for package in missing_packages:
            try:
                install_package(package)
                print(f"✅ {package} 安装成功")
            except Exception as e:
                print(f"❌ {package} 安装失败: {e}")
                return False
    
    print("✅ 所有依赖包检查完成")
    return True

def check_data_files():
    """检查必要的数据文件"""
    required_files = [
        "qa_dataset_cleaned.json",
        "qa_tensors.pt", 
        "id_map.json"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    return missing_files

def run_preprocessing():
    """运行数据预处理步骤"""
    print("\n=== 开始数据预处理 ===")
    
    # 检查原始数据文件
    if not os.path.exists("生活专区.xlsx"):
        print("❌ 错误：找不到原始数据文件 '生活专区.xlsx'")
        return False
    
    try:
        # 步骤1：数据预处理
        print("步骤1/2: 数据预处理...")
        subprocess.run([sys.executable, "module1_data_preprocessing.py"], check=True)
        
        # 步骤2：向量编码
        print("步骤2/2: 向量编码...")
        subprocess.run([sys.executable, "module2_vector_encoding.py"], check=True)
        
        print("✅ 数据预处理完成")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ 预处理失败: {e}")
        return False

def start_web_interface():
    """启动Web界面"""
    print("\n=== 启动Web界面 ===")
    try:
        subprocess.run([sys.executable, "module5_gradio_frontend.py"])
    except KeyboardInterrupt:
        print("\n👋 感谢使用墨尔本生活助手Chatbot！")
    except Exception as e:
        print(f"❌ 启动界面失败: {e}")

def main():
    """主函数"""
    print("🌆 墨尔本生活助手Chatbot - 一键启动脚本")
    print("="*50)
    
    # 1. 检查依赖
    print("\n📦 检查依赖包...")
    if not check_dependencies():
        print("❌ 依赖包安装失败，程序退出")
        return
    
    # 2. 检查数据文件
    print("\n📁 检查数据文件...")
    missing_files = check_data_files()
    
    if missing_files:
        print(f"检测到缺少以下文件: {', '.join(missing_files)}")
        print("开始数据预处理...")
        
        if not run_preprocessing():
            print("❌ 数据预处理失败，程序退出")
            return
    else:
        print("✅ 所有数据文件已就绪")
    
    # 3. 启动Web界面
    print("\n🚀 启动Web界面...")
    print("界面将在 http://localhost:7860 开启")
    print("按 Ctrl+C 退出程序")
    
    start_web_interface()

if __name__ == "__main__":
    main() 