from app.services.rag.doc_id import derive_doc_id


def test_wechat_link_uses_the_article_path_segment_with_a_wx_prefix():
    doc_id = derive_doc_id(
        link="https://mp.weixin.qq.com/s/vGqp2DXA34OE8iHxaSaUFg",
        text="irrelevant for this case",
    )

    assert doc_id == "wx_vGqp2DXA34OE8iHxaSaUFg"


def test_wechat_link_is_stable_across_calls():
    link = "https://mp.weixin.qq.com/s/vGqp2DXA34OE8iHxaSaUFg"

    first = derive_doc_id(link=link, text="content A")
    second = derive_doc_id(link=link, text="content B")

    assert first == second == "wx_vGqp2DXA34OE8iHxaSaUFg"


def test_different_wechat_links_get_different_ids():
    first = derive_doc_id(
        link="https://mp.weixin.qq.com/s/aaaaaaaaaaaaaaaaaaaa",
        text="same text",
    )
    second = derive_doc_id(
        link="https://mp.weixin.qq.com/s/bbbbbbbbbbbbbbbbbbbb",
        text="same text",
    )

    assert first != second


def test_non_wechat_link_falls_back_to_a_deterministic_hash():
    link = "https://example.com/handbook/comp90042"

    first = derive_doc_id(link=link, text="content A")
    second = derive_doc_id(link=link, text="content B")

    assert first == second
    assert first.startswith("kb_")
    assert first != "kb_"


def test_missing_link_falls_back_to_a_deterministic_hash_of_the_text():
    text = "Student visa application information."

    first = derive_doc_id(link=None, text=text)
    second = derive_doc_id(link=None, text=text)

    assert first == second
    assert first.startswith("kb_")


def test_missing_link_with_different_text_gets_a_different_id():
    first = derive_doc_id(link=None, text="Content A")
    second = derive_doc_id(link=None, text="Content B")

    assert first != second


def test_missing_link_does_not_raise():
    # A row with no link must still produce *some* stable id instead of
    # blowing up retrieval for the whole request.
    doc_id = derive_doc_id(link=None, text="fallback content")

    assert doc_id


def test_query_style_wechat_link_uses_the_sn_param():
    # WeChat's other URL shape has nothing usable in the path -- the last
    # segment is literally "s" -- so the per-article id has to come from
    # the `sn` query parameter instead.
    doc_id = derive_doc_id(
        link="http://mp.weixin.qq.com/s?__biz=abc&mid=1&sn=deadbeef123",
        text="irrelevant for this case",
    )

    assert doc_id == "wx_deadbeef123"


def test_query_style_wechat_links_do_not_collapse_to_a_single_id():
    # Regression test: taking the last path segment for this URL shape
    # gives "s" for every article, so distinct articles were silently
    # colliding onto the same wx_s id. See CSS-7 review.
    first = derive_doc_id(
        link="http://mp.weixin.qq.com/s?__biz=X&mid=1&sn=aaa",
        text="A",
    )
    second = derive_doc_id(
        link="http://mp.weixin.qq.com/s?__biz=Y&mid=2&sn=bbb",
        text="B",
    )

    assert first != second
    assert "wx_s" not in (first, second)


def test_empty_string_link_falls_back_to_the_text_hash():
    # The ingestion pipeline defaults a missing link to "" rather than
    # None (pipelines/transform/wechat_articles.py), so this path is
    # reachable in production, not just a defensive extra.
    doc_id = derive_doc_id(link="", text="content")

    assert doc_id.startswith("kb_")
