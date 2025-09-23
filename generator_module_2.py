import json
from typing import List, Dict
import random
import os

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain

from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found. Please set it in your .env file.")

class GeneratorModule:
    def __init__(self, model_name="gpt-5-nano", temperature=0.3):
        # LangChain封装
        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            temperature=temperature,
            streaming=True, # 开启流式输出
            callbacks=[StreamingStdOutCallbackHandler()] # 注册一个回调，用于在生成过程中直接把输出打印到控制台
        )

        # 构建提示词模板
        self.prompt_template = PromptTemplate(
            input_variables=["question", "context"],
            template=(
                "你是一名友好、知识丰富的CSSA智能助手，专门帮助在澳洲的留学生。\n"
                "请根据以下资料回答问题：\n"
                "{context}\n\n"
                "用户问题: {question}\n\n"
                "要求：\n"
                "1. 回答要简洁、礼貌，并用留学生容易理解的语言。\n"
                "2. 如果资料里有来源或链接，请引用。\n"
                "3. 如果资料中没有相关信息，请直接说“我没有找到相关信息”，不要编造。\n"
                "4. 语气可以稍微卖萌（适度）。"
            )
        )

        # 记录当前对话所有内容，按顺序累积
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            input_key="question",
            return_messages=True # 返回消息对象而非字符串
    )

        ##### 因为在 LangChain 里，要让 memory 生效，通常要配合 LLMChain
        self.chain = LLMChain(
            llm=self.llm,
            prompt=self.prompt_template,
            memory=self.memory
        )

        

    # 将检索结果转换为 Prompt 可用的上下文"
    def format_context(self, docs: List[Dict]) -> str:
        blocks = []
        for idx, item in enumerate(docs, start=1):
            block = (
                f"[资料{idx}]\n"   ##### 可以给上下文编号，便于引用 这样用户如果要追溯，也更清楚答案引用的是哪个资料。
                f"Q: {item.get('question', '')}\n"
                f"A: {item.get('answer', '')}\n"
                f"来源: {item.get('source', '')}\n"
                f"链接: {item.get('link', '')}\n"
                f"日期: {item.get('created_at', '')}"
            )
            blocks.append(block)
        return "\n\n".join(blocks) # 每条之间空一行，方便 LLM 阅读

    # 核心回答生成函数
    def generate_answer(self, query: str, context_docs: List[Dict]) -> str:
        context_str = self.format_context(context_docs)
        response = self.chain.invoke({
            "question": query,
            "context": context_str
    })
        return response["text"]  # LLMChain 返回 dict

    
    

if __name__ == "__main__":
    # 直接加载已清洗好的 JSON
    with open("qa_clean_data.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # 假设这里用前 5 条作为模拟的检索结果
    # mock_context = dataset[:2]
    mock_context = random.sample(dataset, min(5, len(dataset)))

    generator = GeneratorModule()
    user_query = "在墨尔本如何办理公交卡"
    print("\n=== 最终回答 ===")
    answer = generator.generate_answer(user_query, mock_context)
    # print("\n", answer)
