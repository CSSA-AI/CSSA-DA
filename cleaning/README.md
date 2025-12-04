# 关键任务
## 数据清洗
处理原始表格（Excel/CSV），统一格式，去除无关信息、修正错别字、处理特殊字符。
## 结构化转换
将每一条问答知识，转换为标准的 JSON 格式。
## 脚本化
将整个过程编写为可重复执行的 Python 脚本，方便未来新增知识时自动处理。
# 输入
生活专区.xlsx 等原始表格文件。
# 输出 (Deliverable)
qa_dataset_cleaned.json：一个包含所有问答对的JSON文件。
# JSON条目格式标准
```json
{
  "id": "00123",
  "question": "如何申请公交卡？",
  "answer": "可通过公交公司官网或服务窗口直接办理。",
  "source": "ptv官网",
  "link": "https://city.gov/bus-card-application",
  "tags": ["交通"],
  "creator": "ruonan"(名字统一改为小写),
  "created_at": "2025-10-08"(datetime类型)
}
```
