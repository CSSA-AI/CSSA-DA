import sys
import os
import pytest

# 动态将 scripts 目录加入环境变量，方便导入我们的处理脚本
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

# 导入我们要测试的核心函数
from wechat_article_process import clean_text

class TestWechatDataPurify:
    """测试微信公众号数据清洗的各个阶段"""

    def test_footer_truncation(self):
        """测试阶段 1: 底部冗余模板截断"""
        raw_text = "这是一篇非常好的干货文章。\n**联系我们**\n大家有任何关于CSSA的疑问\n扫码进群！"
        expected = "这是一篇非常好的干货文章。"
        assert clean_text(raw_text) == expected

        raw_text2 = "正文内容结束。\n-END-\n文案 / William\n排版 / William"
        expected2 = "正文内容结束。"
        assert clean_text(raw_text2) == expected2

    def test_wechat_noise_removal(self):
        """测试阶段 2: 微信专有噪音 (CSS, 占位符等)"""
        raw_text = """
        #js_row_immersive { max-width: 667px; }
        .sns_opr_btn::before { width: 16px; }
        墨大中国学生会 墨大中国学生会 [墨尔本大学中国学生会](javascript:void(0);)
        在小说阅读器读本章 去阅读 在小说阅读器中沉浸阅读
        真正的正文开始。
        """
        expected = "真正的正文开始。"
        assert clean_text(raw_text) == expected

    def test_markdown_and_html_removal(self):
        """测试阶段 3: 图片与 HTML 标签清洗"""
        raw_text = """
        <h1>欢迎</h1>
        这是一张图 ![海报](https://example.com/img.png)
        游离链接 https://mmbiz.qpic.cn/123456
        这是结尾
        """
        expected = "欢迎\n这是一张图 \n游离链接 \n这是结尾"
        assert clean_text(raw_text) == expected

    def test_formatting_and_compression(self):
        """测试阶段 4: 排版整理与幽灵字符压缩"""
        # 包含零宽字符 \u200b，多个连续空格，以及 4 个连续换行
        raw_text = "Hello\u200bWorld!    This  is   a test.\n\n\n\nNext paragraph."
        expected = "HelloWorld! This is a test.\n\nNext paragraph."
        assert clean_text(raw_text) == expected
        
    def test_long_dividers(self):
        """测试长条分割线的清除"""
        raw_text = "段落一\n=========================\n段落二\n------------\n段落三"
        expected = "段落一\n段落二\n段落三"
        assert clean_text(raw_text) == expected

    def test_empty_input(self):
        """测试边界情况: 输入为空或 None"""
        assert clean_text("") == ""
        assert clean_text(None) == ""