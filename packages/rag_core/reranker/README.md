# 🤬模块五：Reranker （wcy，sly)

## 模块目标
给定一个query和k个相关的答案，判断哪几个答案能够用来回答这个query

## 模块思路：
1. 调用huggingface text reranking部署基础款reranker ddl: week8 Tuesday 后续步骤之后做
2. 用现有的预训练模型去判断query和某个答案是否存在逻辑关系：问题-答案 pair
3. 尝试用LoRA对于训练模型进行微调
4. 微调数据需要用现有的数据进行cross-encoder（就是我在开会的时候说的问题答案做pair，class是0/1）(question, candidate_answer) 句对

## 数据示例：
<img width="809" height="262" alt="image" src="https://github.com/user-attachments/assets/cc376b02-9d7e-4a82-b5b1-cd3ee383706f" />
