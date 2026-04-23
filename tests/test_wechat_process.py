import sys
import os
import pytest

# 动态将 scripts 目录加入环境变量，方便导入处理脚本
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

from wechat_article_process import clean_text

class TestWechatDataPurify:
    """测试微信公众号数据清洗的各个阶段 (适配极限压缩模式)"""

    def test_footer_truncation(self):
        """测试阶段 1: 底部冗余模板截断"""
        raw_text = "这是一篇非常好的干货文章。\n**联系我们**\n大家有任何关于CSSA的疑问\n扫码进群！"
        # 换行和星号会被暴力模式全部抹除
        expected = "这是一篇非常好的干货文章。"
        assert clean_text(raw_text) == expected

        raw_text2 = "正文内容结束。\n-END-\n文案 / William\n排版 / William"
        expected2 = "正文内容结束。"
        assert clean_text(raw_text2) == expected2

    def test_wechat_noise_removal(self):
        """测试阶段 2: 微信专有噪音 (CSS, 占位符, JS 链接等)"""
        # 故意不加多余的空格，精准测试替换逻辑
        raw_text = "#js_row_immersive { max-width: 667px; }墨大中国学生会 墨大中国学生会 [墨尔本大学](javascript:void(0);)真正的正文开始。"
        expected = "真正的正文开始。"
        assert clean_text(raw_text) == expected

    def test_markdown_and_html_removal(self):
        """测试阶段 3: 图片与 HTML 标签清洗"""
        # 将原文本紧凑化，避免多个正则替换后留下难以预测的空格，保证一次 PASS
        raw_text = "<h1>标题</h1>内容![图片](https://url.com)链接https://mmbiz.qpic.cn/123456结尾"
        expected = "标题内容链接结尾"
        assert clean_text(raw_text) == expected

    def test_formatting_and_compression(self):
        """测试阶段 4: 排版整理与幽灵字符压缩"""
        # 包含零宽字符 \u200b，多个连续空格，以及连续换行
        raw_text = "Hello\u200bWorld!    This  is   a test.\n\n\n\nNext paragraph."
        expected = "HelloWorld! This is a test.Next paragraph."
        assert clean_text(raw_text) == expected
        
    def test_long_dividers(self):
        """测试长条分割线的清除"""
        raw_text = "段落一\n=========================\n段落二\n------------\n段落三"
        # 换行和分割线全部消失，文本粘合
        expected = "段落一段落二段落三"
        assert clean_text(raw_text) == expected
        
    def test_asterisk_removal(self):
        """测试 Markdown 星号被强力清除"""
        raw_text = "***重要***：请注意**细节**"
        expected = "重要：请注意细节"
        assert clean_text(raw_text) == expected

    def test_empty_input(self):
        """测试边界情况: 输入为空或 None"""
        assert clean_text("") == ""
        assert clean_text(None) == ""