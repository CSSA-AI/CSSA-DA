from datetime import date

from pipelines.transform.wechat_articles import transform_articles

BODY_A = (
    "墨大的校招求职群欢迎各位同学加入,群内会定期分享校招信息、"
    "内推机会和面试经验,请添加小助手微信并备注专业和年级。"
)
BODY_B = (
    "本周六下午两点在校园咖啡厅举办新生交流活动,现场有茶点和小游戏,"
    "欢迎刚到墨尔本的同学前来认识新朋友,名额有限先到先得。"
)


def make_raw(*, title, content, link, post_date):
    return {
        "title": title,
        "content": content,
        "link": link,
        "date": post_date,
        "is_valid_for_rag": True,
    }


def run(raw):
    return transform_articles(raw, created_at=date(2026, 7, 1))


def test_same_body_collapses_to_earliest_post_date():
    raw = [
        make_raw(title="求职群", content=BODY_A,
                 link="https://x/2", post_date="2014-04-12"),
        make_raw(title="求职群", content=BODY_A, link="https://x/1",
                 post_date="2014-04-11"),  # 最早,故意放中间
        make_raw(title="求职群", content=BODY_A,
                 link="https://x/3", post_date="2014-04-13"),
    ]

    result = run(raw)

    assert len(result.records) == 1
    kept = result.records[0]
    assert kept["post_date"] == "2014-04-11"
    assert kept["link"] == "https://x/1"
    assert result.stats.output_count == 1


def test_same_title_different_body_is_not_deduped():
    raw = [
        make_raw(title="每周活动", content=BODY_A,
                 link="https://x/1", post_date="2014-04-11"),
        make_raw(title="每周活动", content=BODY_B,
                 link="https://x/2", post_date="2014-04-18"),
    ]

    result = run(raw)

    assert len(result.records) == 2
