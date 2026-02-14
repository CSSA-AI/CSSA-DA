# 🌆 墨尔本生活助手 Chatbot

基于 PyTorch + HuggingFace + FAISS + Gradio 的中文问答系统

## 📋 项目概述

本项目是一个专门为墨尔本华人社区打造的智能问答系统，采用先进的语义检索技术，能够准确回答关于墨尔本交通、生活等方面的问题。

### 🎯 核心功能

- **智能问答**：支持中文自然语言问题输入
- **语义检索**：基于BERT的语义相似度匹配
- **知识库**：涵盖墨尔本交通、生活等17个主要问题领域
- **Web界面**：友好的Gradio前端界面
- **历史记录**：支持聊天历史查看和导出

### 🛠️ 技术架构

```
用户问题 → BERT编码 → FAISS检索 → 模板生成 → 回答输出
     ↓         ↓         ↓         ↓         ↓
  Gradio    PyTorch   向量索引   上下文拼接   Web显示
```

## 🧩 模块架构

### 模块1：数据预处理与标准化
- **文件**：`module1_data_preprocessing.py`
- **功能**：读取Excel数据，清洗并转换为标准JSON格式
- **输入**：`生活专区.xlsx`
- **输出**：`qa_dataset_cleaned.json`

### 模块2：向量编码与索引构建
- **文件**：`module2_vector_encoding.py`
- **功能**：使用bert-base-chinese对问题进行编码
- **输入**：`qa_dataset_cleaned.json`
- **输出**：
  - `qa_tensors.pt`：问题向量张量
  - `id_map.json`：ID映射文件
  - `qa_faiss_index.index`：FAISS索引文件

### 模块3：语义检索系统
- **文件**：`module3_semantic_search.py`
- **功能**：对用户问题进行语义检索，返回最相关的k个结果
- **支持**：FAISS快速检索 + 余弦相似度备选

### 模块4：回答生成模块
- **文件**：`module4_answer_generation.py`
- **功能**：基于检索结果生成自然语言回答
- **支持**：模板式生成 + OpenAI API接口（可选）

### 模块5：Gradio前端界面
- **文件**：`module5_gradio_frontend.py`
- **功能**：提供用户友好的Web交互界面
- **特性**：实时问答、历史记录、示例问题

## 🚀 快速开始

### 1. 环境准备

```bash
# 安装依赖包
pip install torch torchvision transformers tqdm faiss-cpu scikit-learn openai gradio pandas
```

### 2. 运行步骤

```bash
# 步骤1：数据预处理
python module1_data_preprocessing.py

# 步骤2：向量编码
python module2_vector_encoding.py

# 步骤3：测试检索（可选）
python module3_semantic_search.py

# 步骤4：测试回答生成（可选）
python module4_answer_generation.py

# 步骤5：启动Web界面
python module5_gradio_frontend.py
```

### 3. 访问界面

启动后访问：`http://localhost:7860`

## 📊 项目数据

### 数据统计
- **问答对数量**：17条
- **覆盖领域**：墨尔本交通、生活指南
- **向量维度**：768维（BERT-base-chinese）
- **检索方式**：FAISS + 余弦相似度

### 示例问题
- 墨尔本怎么坐公交车？
- 如何使用Myki卡？
- 学生乘车有优惠吗？
- 从机场到市区怎么走？
- 墨尔本停车需要注意什么？

## 🎨 界面预览

### 主要功能区域
- **提问区域**：输入问题的地方
- **回答显示**：AI助手的回答
- **功能面板**：历史记录、系统信息
- **示例问题**：快速体验

### 界面特色
- 🎨 现代化设计，响应式布局
- 📱 支持移动端访问
- 🔍 实时搜索和回答
- 📝 完整的交互历史记录
- 💾 支持历史记录导出

## 📁 文件结构

```
AI chatbot/
├── 生活专区.xlsx                    # 原始数据文件
├── qa_dataset_cleaned.json          # 清洗后的问答数据
├── qa_tensors.pt                    # 问题向量张量
├── id_map.json                      # ID映射文件
├── qa_faiss_index.index             # FAISS索引
├── module1_data_preprocessing.py    # 模块1：数据预处理
├── module2_vector_encoding.py       # 模块2：向量编码
├── module3_semantic_search.py       # 模块3：语义检索
├── module4_answer_generation.py     # 模块4：回答生成
├── module5_gradio_frontend.py       # 模块5：Web界面
├── qa_chatbot_project_plan_torch.md # 项目计划文档
└── README.md                        # 项目说明文档
```

## 🔧 技术细节

### 核心技术栈
- **深度学习框架**：PyTorch 2.7.1
- **预训练模型**：bert-base-chinese (HuggingFace)
- **向量检索**：FAISS (Facebook AI)
- **Web框架**：Gradio 5.39.0
- **数据处理**：pandas, numpy

### 性能指标
- **模型加载时间**：~10秒
- **单次检索时间**：<1秒
- **回答生成时间**：<2秒
- **内存占用**：~2GB（包含模型）

## 🚦 使用说明

### 1. 初始化系统
- 启动界面后，点击"🚀 初始化系统"按钮
- 等待模型和数据加载完成

### 2. 开始提问
- 在输入框中输入问题
- 点击"🔍 提问"按钮或按回车键
- 查看AI助手的回答和参考链接

### 3. 查看历史
- 点击"📝 查看历史记录"查看聊天记录
- 点击"💾 导出历史"保存聊天记录到本地

### 4. 使用示例
- 点击"💡 示例问题"区域的预设问题快速体验

## 🔄 扩展说明

### 添加新数据
1. 在Excel文件中添加新的问答对
2. 重新运行模块1-2进行数据预处理和编码
3. 重启Web界面

### API集成
```python
from module4_answer_generation import AnswerGenerator

# 初始化生成器
generator = AnswerGenerator()
generator.initialize_searcher("qa_tensors.pt", "id_map.json", "qa_faiss_index.index")

# 生成回答
result = generator.generate_answer("你的问题")
print(result['answer'])
```

### OpenAI集成（可选）
```python
# 设置环境变量
export OPENAI_API_KEY="your-api-key"

# 或在代码中配置
generator = AnswerGenerator(use_openai=True, api_key="your-api-key")
```

## 🐛 常见问题

### Q1: 模型加载失败
**A**: 检查网络连接，确保能够下载HuggingFace模型

### Q2: FAISS索引错误
**A**: 重新运行模块2生成索引文件

### Q3: 界面无法访问
**A**: 检查防火墙设置，确保7860端口未被占用

### Q4: 回答不准确
**A**: 这是由于数据集较小，可以通过添加更多高质量问答数据来改善

## 👥 开发团队

- **项目组织**：CSSA-DA AI项目组
- **技术架构**：PyTorch + HuggingFace + FAISS + Gradio
- **目标用户**：墨尔本华人社区

## 📄 许可证

本项目采用MIT许可证，详见LICENSE文件。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进项目！

### 贡献方式
1. Fork本项目
2. 创建feature分支
3. 提交更改
4. 发起Pull Request

## 📞 联系我们

如有问题或建议，请联系项目团队。

---

**🎉 感谢使用墨尔本生活助手Chatbot！** 