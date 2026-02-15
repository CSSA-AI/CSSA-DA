import streamlit as st
import time
import json
import os
import sys

# 把当前脚本的上一级目录（即项目根目录）加到 Python 的搜索路径里
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 确保引入了 Article
from app.schemas.article import Article

# 引入你的后端组件
from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.retriever.faiss_retriever import FAISSRetriever
from app.services.rag.reranker.cross_encoder import CrossEncoderReranker
from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator

# 设置页面配置
st.set_page_config(page_title="墨大留学助手 (RAG Demo)", page_icon="🎓")

st.title("CSSA RAG Chatbot")
st.caption("Powered by: FAISS + CrossEncoder + ChatGPT")

# --- 1. 初始化核心系统 (使用缓存，防止每次刷新都重载模型) ---
@st.cache_resource
def init_rag_system():
    print("🔄 正在初始化 RAG 系统...")
    
    # 1. 定义数据路径 (对应你 merge_json.py 里的 OUTPUT_FILE)
    DATA_PATH = "data/demo_data.json"
    
    # 2. 读取合并后的 JSON
    if not os.path.exists(DATA_PATH):
        st.error(f"❌ 找不到数据文件: {DATA_PATH}，请先运行 merge_json.py")
        return None
        
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    
    # 一行代码把 list[dict] 转成 list[Article]
    all_articles = [Article(**item) for item in raw_data]
    print(f"✅ 已加载 {len(all_articles)} 篇文章")

    # 3. 初始化组件
    # A. Retriever
    retriever = FAISSRetriever(input_list=all_articles, model_name="paraphrase-multilingual-MiniLM-L12-v2")
    
    # B. Reranker
    reranker = CrossEncoderReranker(model_name="cross-encoder/ms-marco-MiniLM-L12-v2")
    
    # C. Generator
    generator = ChatGPTGenerator(model_name="gpt-4o-mini") 
    
    # D. Orchestrator
    orchestrator = RAGOrchestrator(retriever, reranker, generator)
    
    return orchestrator

try:
    rag_orchestrator = init_rag_system()
    st.success("✅ 系统加载完成！", icon="🚀")
except Exception as e:
    st.error(f"❌ 系统加载失败: {e}")
    st.stop()

# --- 2. 管理会话历史 (Session State) ---
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "你好！我是墨大留学助手，有什么可以帮你？"}
    ]

# --- 3. 渲染聊天界面 ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # 如果历史消息里有来源信息，也渲染出来
        if "sources" in msg:
            with st.expander("📚 参考来源 (History)"):
                for idx, src in enumerate(msg["sources"]):
                    st.markdown(f"**{idx+1}. {src['title']}** (Score: {src['score']:.4f})")
                    st.markdown(f"URL: {src['url']}")
                    st.divider()

# --- 4. 处理用户输入 ---
if prompt := st.chat_input("请输入你的问题 (例如: 墨大CS硕士雅思要求多少?)"):
    # A. 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # B. 调用后端 (Orchestrator)
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("🤔 正在思考并检索知识库...")
        
        start_time = time.time()
        
        # === 核心调用 ===
        # 使用 session_id 区分不同用户，这里 Demo 简单用 default
        answer, sources = rag_orchestrator.run(query=prompt, session_id="demo_user")
        
        duration = time.time() - start_time
        
        # C. 显示 AI 回答
        message_placeholder.markdown(answer)
        
        # D. 显示参考来源 (这是 RAG 的灵魂)
        if sources:
            with st.expander(f"📚 参考来源 ({len(sources)} 篇 - 耗时 {duration:.2f}s)"):
                for idx, res in enumerate(sources):
                    # res 是 SearchResult 对象
                    score_emoji = "🟢" if res.score > 0.7 else "🟡"
                    st.markdown(f"{score_emoji} **No.{idx+1} {res.article.questions[0]}**")
                    st.caption(f"Score: {res.score:.4f} | URL: {res.article.link}")
                    st.text(res.article.text[:100] + "...") # 只展示前100字预览
                    st.divider()
        else:
            with st.expander("⚠️ 未找到相关来源"):
                st.write("直接由大模型生成，未参考知识库。")

    # E. 保存 AI 回答到历史
    # 我们把 sources 转成简单的 dict 存进去，方便上面渲染历史
    saved_sources = [
        {"title": res.article.questions[0], "url": res.article.link, "score": res.score} 
        for res in sources
    ]
    st.session_state.messages.append({
        "role": "assistant", 
        "content": answer,
        "sources": saved_sources
    })