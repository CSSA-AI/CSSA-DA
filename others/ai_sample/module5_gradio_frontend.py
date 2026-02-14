#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块5：Gradio交互前端原型
功能：构建用户友好的Web界面，整合所有模块功能
输入：用户问题（来自输入框）
输出：可交互的聊天界面原型
"""

import gradio as gr
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Tuple
from module4_answer_generation import AnswerGenerator

class ChatbotInterface:
    """
    聊天机器人界面类
    """
    
    def __init__(self):
        """
        初始化界面
        """
        self.generator = None
        self.chat_history = []
        self.initialized = False
        
    def initialize_system(self) -> str:
        """
        初始化后端系统
        """
        try:
            # 文件路径
            tensor_file = "qa_tensors.pt"
            id_map_file = "id_map.json"
            faiss_index_file = "qa_faiss_index.index"
            
            # 检查文件是否存在
            required_files = [tensor_file, id_map_file]
            for file_path in required_files:
                if not os.path.exists(file_path):
                    return f"❌ 错误：找不到文件 {file_path}\n请先运行模块1-4生成必要文件"
            
            # 初始化回答生成器
            self.generator = AnswerGenerator(use_openai=False)
            self.generator.initialize_searcher(tensor_file, id_map_file, faiss_index_file)
            
            self.initialized = True
            return "✅ 系统初始化成功！现在可以开始提问了。"
            
        except Exception as e:
            return f"❌ 系统初始化失败: {str(e)}"
    
    def process_question(self, question: str) -> Tuple[str, str]:
        """
        处理用户问题并生成回答
        Args:
            question: 用户问题
        Returns:
            (formatted_response, status_message)
        """
        if not self.initialized:
            return "请先点击'初始化系统'按钮", "系统未初始化"
        
        if not question.strip():
            return "请输入您的问题", "输入为空"
        
        try:
            # 生成回答
            result = self.generator.generate_answer(question.strip())
            
            # 格式化回答
            formatted_response = self.format_response(result)
            
            # 记录到历史
            self.chat_history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "question": question.strip(),
                "answer": result['answer'],
                "confidence": result['confidence'],
                "sources": result['sources']
            })
            
            return formatted_response, f"✅ 回答生成成功 (置信度: {result['confidence']:.4f})"
            
        except Exception as e:
            error_msg = f"❌ 生成回答时出错: {str(e)}"
            return error_msg, "处理失败"
    
    def format_response(self, result: Dict[str, Any]) -> str:
        """
        格式化回答显示
        """
        response = f"🤖 **墨尔本生活助手回答：**\n\n"
        response += f"{result['answer']}\n\n"
        
        if result['sources']:
            response += "📚 **参考链接：**\n"
            for i, source in enumerate(result['sources'][:3], 1):
                response += f"{i}. [{source}]({source})\n"
            response += "\n"
        
        response += f"🎯 **置信度：** {result['confidence']:.4f}\n"
        response += f"⏰ **回答时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return response
    
    def get_chat_history(self) -> str:
        """
        获取聊天历史记录
        """
        if not self.chat_history:
            return "暂无聊天记录"
        
        history_text = "## 📝 聊天历史记录\n\n"
        
        for i, record in enumerate(self.chat_history[-10:], 1):  # 显示最近10条
            history_text += f"### 第 {i} 次对话 ({record['timestamp']})\n"
            history_text += f"**问题：** {record['question']}\n"
            history_text += f"**回答：** {record['answer'][:200]}{'...' if len(record['answer']) > 200 else ''}\n"
            history_text += f"**置信度：** {record['confidence']:.4f}\n"
            if record['sources']:
                history_text += f"**参考链接数：** {len(record['sources'])}\n"
            history_text += "\n---\n\n"
        
        return history_text
    
    def clear_history(self) -> str:
        """
        清空聊天历史
        """
        self.chat_history = []
        return "✅ 聊天历史已清空"
    
    def export_history(self) -> str:
        """
        导出聊天历史到JSON文件
        """
        if not self.chat_history:
            return "暂无聊天记录可导出"
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_history_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, ensure_ascii=False, indent=2)
            
            return f"✅ 聊天历史已导出到: {filename}"
            
        except Exception as e:
            return f"❌ 导出失败: {str(e)}"

def create_interface():
    """
    创建Gradio界面
    """
    # 创建聊天机器人实例
    chatbot = ChatbotInterface()
    
    # 自定义CSS样式
    custom_css = """
    .gradio-container {
        max-width: 1200px;
        margin: auto;
        padding: 20px;
    }
    .header {
        text-align: center;
        padding: 20px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .question-box {
        border: 2px solid #e1e5e9;
        border-radius: 10px;
        padding: 10px;
    }
    .answer-box {
        background-color: #f8f9fa;
        border-left: 4px solid #007bff;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
    }
    """
    
    # 创建界面
    with gr.Blocks(css=custom_css, title="墨尔本生活助手 Chatbot") as demo:
        # 标题和说明
        gr.HTML("""
        <div class="header">
            <h1>🌆 墨尔本生活助手 Chatbot</h1>
            <p>基于 PyTorch + HuggingFace + FAISS 的中文问答系统</p>
            <p>专门回答墨尔本交通、生活相关问题</p>
        </div>
        """)
        
        # 系统状态和初始化
        with gr.Row():
            with gr.Column(scale=2):
                system_status = gr.Textbox(
                    label="📊 系统状态",
                    value="系统未初始化，请点击初始化按钮",
                    interactive=False
                )
            with gr.Column(scale=1):
                init_btn = gr.Button("🚀 初始化系统", variant="primary")
        
        # 主要聊天区域
        with gr.Row():
            with gr.Column(scale=2):
                # 问题输入区
                with gr.Group():
                    gr.Markdown("## 💬 提问区域")
                    question_input = gr.Textbox(
                        label="请输入您的问题",
                        placeholder="例如：墨尔本怎么坐公交车？",
                        lines=3,
                        elem_classes="question-box"
                    )
                    
                    with gr.Row():
                        submit_btn = gr.Button("🔍 提问", variant="primary")
                        clear_input_btn = gr.Button("🗑️ 清空输入")
                
                # 回答显示区
                with gr.Group():
                    gr.Markdown("## 🤖 助手回答")
                    answer_output = gr.Markdown(
                        value="等待您的提问...",
                        elem_classes="answer-box"
                    )
                    
                    # 状态信息
                    status_output = gr.Textbox(
                        label="处理状态",
                        interactive=False
                    )
            
            # 侧边栏 - 历史记录和功能
            with gr.Column(scale=1):
                with gr.Group():
                    gr.Markdown("## 📋 功能面板")
                    
                    # 历史记录相关
                    history_btn = gr.Button("📝 查看历史记录")
                    clear_history_btn = gr.Button("🗑️ 清空历史")
                    export_btn = gr.Button("💾 导出历史")
                    
                    # 系统信息
                    gr.Markdown("### 📊 系统信息")
                    system_info = gr.HTML("""
                    <div style="font-size: 12px; color: #666;">
                    <p><strong>数据集：</strong> 17条墨尔本生活问答</p>
                    <p><strong>编码模型：</strong> bert-base-chinese</p>
                    <p><strong>检索算法：</strong> FAISS + 余弦相似度</p>
                    <p><strong>回答生成：</strong> 模板式生成</p>
                    </div>
                    """)
        
        # 历史记录显示区（隐藏状态）
        with gr.Group(visible=False) as history_group:
            gr.Markdown("## 📚 聊天历史记录")
            history_output = gr.Markdown()
            close_history_btn = gr.Button("❌ 关闭历史记录")
        
        # 示例问题
        with gr.Group():
            gr.Markdown("## 💡 示例问题")
            examples = gr.Examples(
                examples=[
                    ["墨尔本怎么坐公交车？"],
                    ["如何使用Myki卡？"],
                    ["学生乘车有优惠吗？"],
                    ["从机场到市区怎么走？"],
                    ["墨尔本停车需要注意什么？"],
                    ["打车用什么软件最便宜？"],
                    ["墨尔本公共交通票价是多少？"]
                ],
                inputs=question_input
            )
        
        # 页脚信息
        gr.HTML("""
        <div style="text-align: center; padding: 20px; color: #666; border-top: 1px solid #eee; margin-top: 30px;">
            <p>🔧 开发团队：CSSA-DA AI项目组 | 🚀 技术栈：PyTorch + HuggingFace + FAISS + Gradio</p>
            <p>📅 版本：v1.0 | 📍 专注服务：墨尔本华人社区</p>
        </div>
        """)
        
        # 事件绑定
        def show_history():
            history_text = chatbot.get_chat_history()
            return {
                history_group: gr.update(visible=True),
                history_output: history_text
            }
        
        def hide_history():
            return {history_group: gr.update(visible=False)}
        
        def clear_input():
            return ""
        
        # 绑定事件
        init_btn.click(
            chatbot.initialize_system,
            outputs=system_status
        )
        
        submit_btn.click(
            chatbot.process_question,
            inputs=question_input,
            outputs=[answer_output, status_output]
        )
        
        question_input.submit(  # 支持回车提交
            chatbot.process_question,
            inputs=question_input,
            outputs=[answer_output, status_output]
        )
        
        clear_input_btn.click(
            clear_input,
            outputs=question_input
        )
        
        history_btn.click(
            show_history,
            outputs=[history_group, history_output]
        )
        
        close_history_btn.click(
            hide_history,
            outputs=[history_group]
        )
        
        clear_history_btn.click(
            chatbot.clear_history,
            outputs=system_status
        )
        
        export_btn.click(
            chatbot.export_history,
            outputs=system_status
        )
    
    return demo

def main():
    """
    主函数 - 启动Gradio界面
    """
    print("=== 模块5：Gradio前端原型 ===")
    print("正在启动Web界面...")
    
    # 创建界面
    demo = create_interface()
    
    # 启动服务
    demo.launch(
        server_name="0.0.0.0",  # 允许外部访问
        server_port=7860,       # 默认端口
        share=False,            # 不创建公网链接（可根据需要修改）
        debug=True,             # 开启调试模式
        show_api=False          # 不显示API文档
    )

if __name__ == "__main__":
    main() 