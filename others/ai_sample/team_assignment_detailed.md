# 🏗️ 墨尔本生活助手Chatbot - 6人小组分工方案

## 📋 项目分工一览表

| 角色 | 姓名 | 主要职责 | 核心模块 | 预计时间 |
|------|------|----------|----------|----------|
| **A - 数据工程师** | ___ | 数据收集、清洗、标准化 | 模块1 | 1-2周 |
| **B - AI模型工程师** | ___ | 模型集成、向量编码 | 模块2 | 2-3周 |
| **C - 检索算法工程师** | ___ | 语义检索、相似度计算 | 模块3 | 2-3周 |
| **D - 后端开发工程师** | ___ | 回答生成、API接口 | 模块4 | 2-3周 |
| **E - 前端开发工程师** | ___ | Web界面、用户交互 | 模块5 | 2-3周 |
| **F - 项目经理/测试工程师** | ___ | 项目管理、系统测试、集成 | 全流程 | 全程 |

---

## 👤 **人员A：数据工程师**

### 🎯 核心任务
负责数据收集、清洗、预处理和标准化，为整个系统提供高质量的问答数据基础。

### 📊 具体职责

#### 1. 数据收集 (第1周)
- **任务**: 从各渠道收集墨尔本生活相关问答数据
- **数据源建议**:
  - 墨尔本政府官网FAQ
  - 华人社区论坛问答
  - 移民局交通局官方资料
  - 留学生常见问题整理
- **目标**: 收集50-100条高质量问答对
- **格式要求**: Excel或CSV，包含问题、答案、来源链接

#### 2. 数据清洗与标准化 (第2周)
- **任务**: 开发数据预处理脚本
- **技术要求**:
  - Python + pandas
  - 文本清洗算法
  - 数据去重和质量检查
- **输出标准**:
```json
{
  "id": "00001",
  "question": "标准化的问题文本",
  "answer": "清洗后的答案内容", 
  "link": "参考链接URL",
  "tags": ["分类标签1", "标签2"]
}
```

#### 3. 数据质量控制
- **验证规则**:
  - 问题长度: 5-100字
  - 答案长度: 10-500字
  - 链接有效性检查
  - 重复内容过滤
- **质量指标**: 
  - 数据完整性 >95%
  - 文本清洗准确率 >90%

### 📦 交付物
1. `raw_data_collection.xlsx` - 原始数据收集
2. `data_preprocessing_script.py` - 数据处理脚本
3. `qa_dataset_cleaned.json` - 最终标准化数据
4. `data_quality_report.md` - 数据质量分析报告

---

## 🧠 **人员B：AI模型工程师**

### 🎯 核心任务
负责AI模型选择、集成和向量编码系统开发，构建语义理解的核心引擎。

### 🔧 具体职责

#### 1. 模型研究与选择 (第1周)
- **任务**: 调研并选择合适的中文预训练模型
- **候选模型**:
  - `bert-base-chinese`
  - `chinese-roberta-wwm`
  - `chinese-electra-base`
- **评估标准**:
  - 中文理解能力
  - 模型大小和速度
  - 在问答任务上的表现

#### 2. 向量编码系统开发 (第2-3周)
- **技术栈**:
  - PyTorch/TensorFlow
  - HuggingFace Transformers
  - CUDA优化(如有GPU)
- **核心功能**:
```python
class QuestionEncoder:
    def load_model(self) -> None
    def encode_questions(self, questions: List[str]) -> torch.Tensor
    def encode_single_question(self, question: str) -> torch.Tensor
    def save_embeddings(self, embeddings: torch.Tensor, path: str) -> None
```

#### 3. 性能优化
- **批处理**: 支持批量编码提高效率
- **缓存机制**: 避免重复计算
- **内存管理**: 大数据集的内存优化
- **性能指标**:
  - 单次编码时间 <100ms
  - 批量编码效率 >100 questions/second
  - 内存占用 <2GB

### 📦 交付物
1. `model_evaluation_report.md` - 模型选择和评估报告
2. `question_encoder.py` - 向量编码核心类
3. `qa_tensors.pt` - 编码后的问题向量
4. `model_performance_benchmark.py` - 性能测试脚本

---

## 🔍 **人员C：检索算法工程师**

### 🎯 核心任务
开发高效的语义检索系统，实现用户问题与知识库的智能匹配。

### ⚡ 具体职责

#### 1. 检索算法实现 (第1-2周)
- **相似度算法**:
  - 余弦相似度计算
  - 欧几里得距离
  - 内积相似度
- **索引结构**:
  - FAISS向量索引
  - Annoy近似最近邻
  - 原生NumPy实现(备选)

#### 2. 检索系统优化 (第2-3周)
- **核心类设计**:
```python
class SemanticSearcher:
    def build_index(self, embeddings: np.ndarray) -> None
    def search(self, query_embedding: np.ndarray, k: int) -> List[SearchResult]
    def batch_search(self, queries: List[np.ndarray], k: int) -> List[List[SearchResult]]
    def update_index(self, new_embeddings: np.ndarray) -> None
```

#### 3. 检索性能调优
- **算法优化**:
  - 索引构建策略
  - 查询时间复杂度优化
  - 结果排序和过滤
- **性能目标**:
  - 单次检索时间 <50ms
  - 检索准确率 >85%
  - 支持实时索引更新

### 📦 交付物
1. `semantic_searcher.py` - 语义检索核心类
2. `search_index.faiss` - 构建的向量索引文件
3. `retrieval_evaluation.py` - 检索效果评估脚本
4. `search_performance_report.md` - 检索性能分析

---

## ⚙️ **人员D：后端开发工程师**

### 🎯 核心任务
开发回答生成系统和API接口，整合前端检索结果生成用户友好的回答。

### 🔧 具体职责

#### 1. 回答生成系统 (第1-2周)
- **生成策略**:
  - 模板式回答生成
  - 上下文信息整合
  - OpenAI API集成(可选)
- **核心功能**:
```python
class AnswerGenerator:
    def generate_template_answer(self, question: str, context: List[Dict]) -> str
    def generate_with_llm(self, question: str, context: List[Dict]) -> str
    def format_response(self, answer: str, sources: List[str]) -> Dict
```

#### 2. API接口开发 (第2-3周)
- **技术栈**: FastAPI/Flask
- **接口设计**:
```python
POST /api/question
{
  "question": "用户问题",
  "top_k": 3
}

Response:
{
  "answer": "生成的回答",
  "confidence": 0.85,
  "sources": ["链接1", "链接2"],
  "search_results": [...]
}
```

#### 3. 系统集成
- **模块整合**: 集成检索和编码模块
- **错误处理**: 完善的异常处理机制
- **日志系统**: 操作日志和性能监控
- **配置管理**: 环境配置和参数管理

### 📦 交付物
1. `answer_generator.py` - 回答生成核心类
2. `api_server.py` - API服务器代码
3. `config.yaml` - 系统配置文件
4. `api_documentation.md` - API接口文档

---

## 🎨 **人员E：前端开发工程师**

### 🎯 核心任务
开发用户友好的Web界面，提供流畅的问答交互体验。

### 💻 具体职责

#### 1. 界面设计与开发 (第1-2周)
- **技术选择**:
  - Gradio (推荐) - 快速原型
  - 或 React + TypeScript - 自定义界面
  - 或 Vue.js + Element UI - 组件化开发
- **界面组件**:
  - 问题输入框
  - 实时回答显示
  - 历史记录管理
  - 系统状态显示

#### 2. 用户体验优化 (第2-3周)
- **交互功能**:
```javascript
// 核心功能模块
- QuestionInput: 问题输入和验证
- AnswerDisplay: 回答格式化显示  
- HistoryManager: 对话历史管理
- SettingsPanel: 系统设置面板
- LoadingIndicator: 加载状态提示
```

#### 3. 响应式设计
- **设备适配**: PC端 + 移动端
- **浏览器兼容**: Chrome, Firefox, Safari, Edge
- **性能优化**: 
  - 组件懒加载
  - 图片优化
  - 缓存策略

### 📦 交付物
1. `web_interface/` - 完整的Web界面代码
2. `ui_components.py/js` - 可复用UI组件
3. `static/css/style.css` - 样式文件
4. `user_manual.md` - 用户使用手册

---

## 👔 **人员F：项目经理/测试工程师**

### 🎯 核心任务
负责项目管理、质量控制、系统集成测试和项目交付。

### 📋 具体职责

#### 1. 项目管理 (全程)
- **进度跟踪**:
  - 周报制度
  - 里程碑检查
  - 风险管理
  - 资源协调
- **团队协作**:
  - 每日站会
  - 代码审查
  - 技术决策
  - 问题解决

#### 2. 测试体系建设 (第2-4周)
- **测试类型**:
```python
# 单元测试
test_data_processing()
test_vector_encoding()
test_semantic_search()
test_answer_generation()

# 集成测试  
test_end_to_end_pipeline()
test_api_integration()
test_web_interface()

# 性能测试
test_response_time()
test_concurrent_users()
test_memory_usage()
```

#### 3. 质量保证
- **代码质量**:
  - 代码规范检查
  - 单元测试覆盖率 >80%
  - 代码审查制度
- **系统质量**:
  - 功能测试用例
  - 性能基准测试
  - 用户体验测试

### 📦 交付物
1. `project_plan.md` - 详细项目计划
2. `test_suite/` - 完整测试套件
3. `deployment_guide.md` - 部署和运维指南
4. `final_report.md` - 项目总结报告

---

## 📅 项目时间计划

### 第1周：项目启动
- **所有人**: 需求分析、技术选型、环境搭建
- **A**: 开始数据收集
- **F**: 制定详细项目计划

### 第2周：核心开发
- **A**: 数据清洗脚本开发
- **B**: 模型研究和集成
- **C**: 检索算法实现
- **D**: 回答生成系统设计
- **E**: 界面原型设计
- **F**: 测试框架搭建

### 第3周：功能实现
- **A**: 数据标准化完成
- **B**: 向量编码系统完成
- **C**: 检索系统优化
- **D**: API接口开发
- **E**: Web界面开发
- **F**: 单元测试执行

### 第4周：集成测试
- **所有人**: 模块集成和联调
- **F**: 集成测试和性能优化

### 第5周：优化部署
- **所有人**: Bug修复和功能优化
- **F**: 部署和用户测试

### 第6周：项目交付
- **所有人**: 文档完善和项目总结
- **F**: 最终演示和交付

---

## 🔧 技术要求和工具

### 开发环境
- **Python**: 3.8+
- **包管理**: pip/conda
- **版本控制**: Git
- **协作平台**: GitHub/GitLab

### 必需依赖
```bash
torch>=1.9.0
transformers>=4.0.0
faiss-cpu>=1.7.0
gradio>=3.0.0
fastapi>=0.70.0
pandas>=1.3.0
numpy>=1.21.0
scikit-learn>=1.0.0
```

### 开发工具建议
- **IDE**: VSCode, PyCharm
- **API测试**: Postman
- **文档**: Markdown + GitBook
- **项目管理**: Trello, Notion

---

## 📊 成功标准

### 技术指标
- [ ] 问答准确率 >80%
- [ ] 平均响应时间 <2秒
- [ ] 系统可用性 >99%
- [ ] 单元测试覆盖率 >80%

### 功能指标
- [ ] 支持中文问答
- [ ] Web界面友好
- [ ] 历史记录功能
- [ ] 数据导出功能

### 项目指标
- [ ] 按时交付
- [ ] 代码质量达标
- [ ] 文档完整
- [ ] 演示成功

---

## 🤝 协作规范

### 代码规范
- 使用Python PEP8标准
- 函数和类添加详细注释
- 变量命名采用英文
- 提交信息规范化

### 沟通机制
- **每日站会**: 15分钟进度同步
- **周报制度**: 每周五提交进度报告
- **技术讨论**: 遇到问题及时沟通
- **代码审查**: 重要功能需要peer review

### Git工作流
```bash
# 1. 克隆项目
git clone [项目地址]

# 2. 创建个人分支
git checkout -b feature/[姓名]-[功能]

# 3. 开发完成后提交
git add .
git commit -m "feat: [功能描述]"
git push origin feature/[姓名]-[功能]

# 4. 创建Pull Request
# 等待代码审查后合并到main分支
```

---

## 📝 个人任务检查清单

### 人员A - 数据工程师
- [ ] 完成数据收集计划
- [ ] 收集50+条高质量问答数据
- [ ] 开发数据清洗脚本
- [ ] 生成标准化JSON数据
- [ ] 撰写数据质量报告

### 人员B - AI模型工程师
- [ ] 完成模型选型调研
- [ ] 实现向量编码系统
- [ ] 优化模型性能
- [ ] 生成问题向量文件
- [ ] 撰写模型评估报告

### 人员C - 检索算法工程师
- [ ] 实现语义检索算法
- [ ] 构建FAISS索引
- [ ] 优化检索性能
- [ ] 完成检索效果评估
- [ ] 撰写性能分析报告

### 人员D - 后端开发工程师
- [ ] 开发回答生成系统
- [ ] 实现API接口
- [ ] 完成系统集成
- [ ] 撰写API文档
- [ ] 配置系统环境

### 人员E - 前端开发工程师
- [ ] 设计用户界面
- [ ] 实现Web交互功能
- [ ] 优化用户体验
- [ ] 适配不同设备
- [ ] 撰写用户手册

### 人员F - 项目经理/测试工程师
- [ ] 制定项目计划
- [ ] 建立测试体系
- [ ] 执行集成测试
- [ ] 协调团队合作
- [ ] 撰写项目总结

---

## 🎯 最终交付清单

### 技术交付物
- [ ] 完整的源代码仓库
- [ ] 可运行的Demo系统
- [ ] 完整的技术文档
- [ ] 测试用例和报告
- [ ] 部署和运维指南

### 演示材料
- [ ] 项目演示PPT
- [ ] 技术架构图
- [ ] 功能演示视频
- [ ] 性能测试报告
- [ ] 用户使用手册

---

**📞 如有问题，请及时在团队群里沟通！**

*项目成功的关键在于团队协作和持续沟通* 🚀