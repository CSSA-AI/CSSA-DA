import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pipelines.embedding.knowledge_base_text import build_embedding_text
from pipelines.orchestration.transform_wechat import run_local_transform
from pipelines.shared.storage import LocalStorage
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
    assert result.records[0]["content"] == (
        "This article explains how students apply for special "
        "consideration at university."
    )
    assert result.records[0]["created_at"] == "2026-07-04"
    assert "questions" not in result.records[0]
    assert "text" not in result.records[0]
    assert result.stats.input_count == 3
    assert result.stats.output_count == 1
    assert result.stats.dropped_count == 1
    assert result.stats.skipped_count == 1


# 30 个以上有效字符,过得了质量门槛。
BODY = "本次活动将在周六下午举行，地点在墨尔本大学主校区，欢迎所有在读同学报名参加，名额有限。"


def transform_one(title: str, content: str) -> wechat_articles.WechatTransformResult:
    return wechat_articles.transform_articles(
        [
            {
                "is_valid_for_rag": True,
                "title": title,
                "content": content,
                "date": "2026-04-10",
                "link": "https://example.com/article",
            }
        ],
        created_at=date(2026, 7, 4),
    )


# 抓取到的正文以标题开头,但那一份标题和 title 字段不一定逐字相同。
# 每一行都取自真实语料里出现过的形状。
@pytest.mark.parametrize(
    "title, opening",
    [
        ("【CSSA活动】沙滩排球活动预告", "【CSSA活动】沙滩排球活动预告"),
        # title 里有零宽字符和连续空格,清洗后的正文里没有
        ("【CSSA转发】\u200b\u200b 两只国宝的梦幻联动！", "【CSSA转发】 两只国宝的梦幻联动！"),
        ("【CSSA推荐】最高奖金五万元  全球短视频大赛", "【CSSA推荐】最高奖金五万元 全球短视频大赛"),
        # 正文里的方括号和下划线被 Markdown 转义
        ("[CSSA活动反馈] 电竞大赛：还想约电竞局？", "\\[CSSA活动反馈\\] 电竞大赛：还想约电竞局？"),
        ("【CSSA推荐】MelTown｜M_TAPE 原创音乐赛事", "【CSSA推荐】MelTown｜M\\_TAPE 原创音乐赛事"),
        # 星号在清洗时被整体删掉
        ("CSSA *迎新* 晚会报名开始", "CSSA *迎新* 晚会报名开始"),
    ],
    ids=[
        "verbatim",
        "zero-width",
        "double-space",
        "escaped-brackets",
        "escaped-underscore",
        "asterisks",
    ],
)
def test_title_opening_the_body_is_removed(title, opening):
    result = transform_one(title, opening + BODY)

    assert result.records[0]["question_text"] == title
    assert result.records[0]["content"] == BODY


def test_title_written_twice_is_removed_twice():
    title = "【CSSA活动回顾】王者荣耀S1电竞赛事圆满落幕！"

    result = transform_one(title, title + title + BODY)

    assert result.records[0]["content"] == BODY


def test_body_that_does_not_open_with_the_title_is_left_alone():
    title = "【CSSA活动】沙滩排球活动预告"
    body = "上周的" + title + "发出后，" + BODY

    result = transform_one(title, body)

    assert result.records[0]["content"] == body


def test_embedding_text_holds_the_title_once():
    # #117 的完成标准:没有任何一行的嵌入文本以「标题 + 同一标题」开头。
    title = "【CSSA活动】沙滩排球活动预告"

    record = transform_one(title, title + BODY).records[0]

    assert build_embedding_text(record) == f"{title}\n\n{BODY}"


@pytest.mark.parametrize(
    "leftover",
    [
        "",
        # 只有图片的转发,清洗后剩下的就是这些
        "携程 携程 [阅读原文](javascript:;)",
        "↓点击阅读原文，一键查阅全部岗位[阅读原文](javascript:;)",
    ],
    ids=["nothing", "repost-stub", "read-more-link"],
)
def test_article_with_little_besides_its_title_is_dropped(leftover):
    # 标题本身超过 30 个有效字符:门槛如果连标题一起数,这篇会过关。
    title = "【CSSA招聘】为青春，奔赴梦想之旅 | 携程集团2022海外秋季校园招聘正在进行时"

    result = transform_one(title, title + leftover)

    assert result.records == []
    assert result.stats.dropped_count == 1


def test_local_transform_reads_and_writes_json():
    temp_dir = Path(__file__).parent / ".tmp_wechat_process"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    input_file = temp_dir / "wechat_articles_all.json"
    output_file = temp_dir / "wechat_articles_processed.json"
    snapshot_file = (
        temp_dir
        / "processed"
        / "knowledge_base"
        / "wechat_articles_processed_20260710T010203Z.json"
    )

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
            LocalStorage(temp_dir),
            input_key="wechat_articles_all.json",
            output_key="wechat_articles_processed.json",
            created_at=date(2026, 7, 4),
            run_started_at=datetime(
                2026, 7, 10, 1, 2, 3, tzinfo=timezone.utc
            ),
        )
        processed = json.loads(output_file.read_text(encoding="utf-8"))
        snapshot = json.loads(
            snapshot_file.read_text(encoding="utf-8")
        )

        assert result.stats.output_count == 1
        assert processed == result.records
        assert snapshot == result.records
        assert not output_file.with_suffix(".json.tmp").exists()
    finally:
        shutil.rmtree(temp_dir)
