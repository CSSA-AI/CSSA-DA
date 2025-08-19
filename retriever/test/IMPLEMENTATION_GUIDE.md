# 🎯 模块二：Retriever 详细实施指南

## 📋 任务目标
构建一个语义检索系统，给定用户查询(query)，能够从知识库中检索出k个最相关的问答对。

## 🏗️ 实施步骤详解

### 第一阶段：环境准备和测试 (30分钟)

#### 步骤1：检查Python环境
```bash
# 确保在项目目录下
cd "c:\Users\14284\Desktop\CSSA\CSSA-DA"

# 激活conda环境
conda activate cssa-ai

# 检查Python版本
python --version
```

#### 步骤2：运行测试脚本
```bash
# 运行Retriever测试
python retriever/test_retriever.py
```

#### 步骤3：安装必要的包
```bash
# 安装jieba分词库
pip install jieba

# 如果需要更高精度，安装sentence-transformers（可选）
pip install sentence-transformers
```

### 第二阶段：实现基础版检索器 (1小时)

#### 步骤4：运行简化版检索器
```bash
# 运行TF-IDF版本的检索器
python retriever/simple_retriever.py
```

这个版本使用：
- TF-IDF向量化
- 余弦相似度计算
- jieba中文分词
- scikit-learn库

#### 步骤5：测试检索效果
检索器会自动测试以下查询：
- "墨尔本怎么坐公交车？"
- "如何使用Myki卡？"
- "学生乘车有优惠吗？"
- "墨尔本的交通工具有哪些？"

### 第三阶段：高级版检索器（可选，2小时）

#### 步骤6：BERT版本检索器
如果环境允许，可以运行基于BERT的版本：
```bash
python retriever/retriever.py
```

这个版本使用：
- bert-base-chinese模型
- FAISS向量索引
- 更高精度的语义理解

## 📊 核心技术实现

### 1. 数据预处理
```python
def preprocess_text(text):
    # 去除特殊字符
    # 中文分词
    # 过滤停用词
    return processed_text
```

### 2. 向量编码
```python
# TF-IDF方法
vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1,2))
question_vectors = vectorizer.fit_transform(questions)

# 或BERT方法
model = AutoModel.from_pretrained('bert-base-chinese')
embeddings = model(inputs).last_hidden_state[:, 0, :]
```

### 3. 相似度计算
```python
# 余弦相似度
similarities = cosine_similarity(query_vector, question_vectors)

# 或FAISS检索
similarities, indices = faiss_index.search(query_embedding, k)
```

### 4. 结果返回
```python
@dataclass
class RetrievalResult:
    question_id: str
    question: str
    answer: str
    similarity_score: float
```

## 🎯 性能指标

### 评估标准
1. **检索速度**: < 1秒
2. **相关性**: Top-3命中率 > 80%
3. **覆盖度**: 能找到相关答案的查询比例

### 测试用例
创建测试集包含：
- 直接匹配查询（如"Myki卡"）
- 同义词查询（如"公交卡"vs"Myki卡"）
- 长句查询（如"我想知道在墨尔本如何乘坐公共交通"）

## 📁 文件结构

```
retriever/
├── test_retriever.py          # 测试脚本
├── simple_retriever.py        # TF-IDF版本
├── retriever.py              # BERT版本
├── tfidf_vectorizer.pkl      # 保存的向量化器
├── question_vectors.pkl      # 保存的问题向量
├── id_mapping.json          # ID映射文件
└── README.md                # 说明文档
```

## 🔧 调试和优化

### 常见问题
1. **分词效果差**: 调整jieba分词，添加自定义词典
2. **检索不准确**: 调整TF-IDF参数，增加n-gram
3. **速度太慢**: 优化向量维度，使用稀疏矩阵

### 参数调优
```python
# TF-IDF参数
TfidfVectorizer(
    max_features=5000,     # 特征数量
    ngram_range=(1, 2),    # n-gram范围
    min_df=1,              # 最小文档频率
    max_df=0.8             # 最大文档频率
)
```

## 📈 扩展方向

### 短期优化
1. 添加查询扩展（同义词）
2. 实现查询纠错
3. 支持多轮对话

### 长期规划
1. 集成更大的预训练模型
2. 实现混合检索（稠密+稀疏）
3. 添加重排序模块

## ✅ 验收标准

完成以下任务即可通过验收：

1. ✅ 成功加载221条问答数据
2. ✅ 构建问题向量索引
3. ✅ 实现search(query, k)函数
4. ✅ 返回RetrievalResult格式的结果
5. ✅ 测试用例通过率 > 80%
6. ✅ 平均检索时间 < 1秒
7. ✅ 代码结构清晰，有注释
8. ✅ 提供使用示例和测试脚本

## 🚀 开始执行

现在可以按照以下顺序执行：

1. **立即执行**: `python retriever/test_retriever.py`
2. **安装依赖**: `pip install jieba`
3. **测试检索**: `python retriever/simple_retriever.py`
4. **验证结果**: 检查输出的检索结果是否合理
5. **优化调整**: 根据结果调整参数
6. **文档完善**: 更新README和注释

开始吧！🎯
