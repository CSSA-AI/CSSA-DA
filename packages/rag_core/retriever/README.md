## 模块二：Retriever

**模块目标：**  
给定一个 query 提取 k 个可能的回答  

---

### 模块步骤：
1. 调用 hugging face 模型将 json 的问题 encode 成 vector  
2. 构建 FAISS 数据库  
3. 使用 FAISS 内置功能 retrieve k 个最相近的问题  
4. 找到对应的 json 并返还  

---

### 注意事项：
1. 现阶段使用 100 条手动收集的数据进行该模块  

