模块一：Chunking
模块目标：生成干净可以使用的数据
模块步骤：
1. 使用langchain爬取网页数据并存成json类型
2. 调用hugging face模型将整篇的文章分成多个sematic chunk
	两种做法：
        a. 直接拆分：极大可能会拆分的过细，将一个内容的句子拆成好几块
        b. 先拆分，后拼接
3. 对于每个sematic chunk，生成该chunk能回答的问题（hugging face pretrain或者llm）
4. 将问题塞进json返还json
