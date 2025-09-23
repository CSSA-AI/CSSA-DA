import json
from typing import List, Dict
import random

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.memory import ConversationBufferMemory

from dotenv import load_dotenv
load_dotenv()

class GeneratorModule:
    def __init__(self, model_name="gpt-5-nano", temperature=0.3):
        # LangChain封装
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            streaming=True, # 开启流式输出
            callbacks=[StreamingStdOutCallbackHandler()] # 注册一个回调，用于在生成过程中直接把输出打印到控制台
        )

        # 记录当前对话所有内容，按顺序累积
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            input_key="question",
            return_messages=True # 返回消息对象而非字符串
        )

        # 构建提示词模板
        self.prompt_template = PromptTemplate(
            input_variables=["question", "context"],
            template=(
                "你是一名友好、知识丰富的CSSA智能助手, 专门为在澳洲的留学生提供建议。\n"
                "请根据以下资料，结合你的知识，准确回答用户问题，并保持简洁、清晰、有礼貌。\n"
                "如涉及实用信息, 请尽量引用来源(source)和链接(link)。\n"
                "\n"
                "用户问题: {question}\n"
                "资料:\n"
                "{context}\n"
                "\n"
                "请用留学生能理解的卖萌语气回答，不要编造信息。"
            )
        )

    # 将检索结果转换为 Prompt 可用的上下文"
    def format_context(self, docs: List[Dict]) -> str:
        blocks = []
        for item in docs:
            block = (
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
        prompt = self.prompt_template.format(
            question=query,
            context=context_str
        )
        return self.llm.predict(prompt)

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
