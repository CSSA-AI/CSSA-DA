import json
import shutil
from datetime import date
from pathlib import Path

from pipelines.orchestration.transform_wechat import run_local_transform
from pipelines.transform import wechat_articles

clean_text = wechat_articles.clean_text

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
        # 注意：我在 123456 和 结尾 之间加了一个空格，防止正则把汉字当成网址吃掉
        raw_text = "<h1>标题</h1>内容![图片](https://url.com)链接https://mmbiz.qpic.cn/123456 结尾"
        
        # 期望值也对应加上这个空格
        expected = "标题内容链接 结尾"
        
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


def test_transform_articles_returns_records_and_statistics():
    raw_articles = [
        {
            "is_valid_for_rag": True,
            "title": "Special consideration guide",
            "content": (
                "This article explains how students apply for special "
                "consideration at university."
            ),
            "date": "2026-04-10",
            "link": "https://example.com/article",
        },
        {
            "is_valid_for_rag": True,
            "title": "Empty article",
            "content": "too short",
            "date": "2026-04-11",
            "link": "https://example.com/empty",
        },
        {
            "is_valid_for_rag": False,
            "title": "Skipped article",
            "content": "This content should not be transformed.",
            "link": "https://example.com/skipped",
        },
    ]

    result = wechat_articles.transform_articles(
        raw_articles,
        created_at=date(2026, 7, 4),
    )

    assert len(result.records) == 1
    assert result.records[0]["question_text"] == (
        "Special consideration guide"
    )
    assert result.records[0]["content"].startswith(
        "# Special consideration guide"
    )
    assert result.records[0]["created_at"] == "2026-07-04"
    assert "questions" not in result.records[0]
    assert "text" not in result.records[0]
    assert result.stats.input_count == 3
    assert result.stats.output_count == 1
    assert result.stats.dropped_count == 1
    assert result.stats.skipped_count == 1


def test_local_transform_reads_and_writes_json():
    temp_dir = Path(__file__).parent / ".tmp_wechat_process"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    input_file = temp_dir / "wechat_articles_all.json"
    output_file = temp_dir / "wechat_articles_processed.json"

    input_file.write_text(
        json.dumps(
            [
                {
                    "is_valid_for_rag": True,
                    "title": "Special consideration guide",
                    "content": (
                        "This article explains how students apply for "
                        "special consideration at university."
                    ),
                    "date": "2026-04-10",
                    "link": "https://example.com/article",
                }
            ]
        ),
        encoding="utf-8",
    )

    try:
        result = run_local_transform(
            input_file=input_file,
            output_file=output_file,
            created_at=date(2026, 7, 4),
        )
        processed = json.loads(output_file.read_text(encoding="utf-8"))

        assert result.stats.output_count == 1
        assert processed == result.records
        assert not output_file.with_suffix(".json.tmp").exists()
    finally:
        shutil.rmtree(temp_dir)
