"""The refusal judge is the test's criteria, so it gets tests of its own.

The generator contract suite (tests/generator_contract) is only as strict as
this judge. If the judge quietly passed "资料不足, but the census date is 6月5日",
a 20/20 run would mean nothing -- so each way an answer can smuggle in a fact
is pinned here, along with the restatements that must NOT count as one.
"""

import pytest

from app.services.rag.eval.refusal import (
    find_refusal,
    find_unsupported_facts,
    judge_refusal,
    mentions,
)

EVIDENCE = """用户问题：BUSA90500 的 census date 是哪天？
Q: BUSA90500 — Assessment
A: Availability May - On Campus. Mid-term test Week 5 15%. Project Week 6 25%.
Final examination Week 9 60%. Hurdle: 15/30 on assignments. 12.5 credit points.
Teaching period 18 May 2026. Last updated: 19 November 2025
活动时间 3月28日 2：00 – 7：00 PM。热线电话：0468 720 668。公平工作咨询电话131394。
费用 AUD 1,200。联系 scholars@cssaunimelb.com
链接: https://handbook.unimelb.edu.au/2026/subjects/busa90500/assessment
"""


def unsupported(answer: str) -> list[str]:
    return find_unsupported_facts(answer, EVIDENCE)


# --- criterion 1: a refusal phrase --------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "资料不足，无法回答这个问题。",
        "资料中没有提到 census date。",
        "提供的资料并未说明先修要求。",
        "资料里未提供学费信息。",
        "根据现有资料无法确定具体时间。",
        "资料中没有关于报名截止时间的信息。",
        # Both missed by the first version of the patterns, in the first real
        # run: the adverb in 没有具体列出, and a gap that restates the question.
        "关于 CHEM10008 课程所需的教材，资料中并没有具体列出所需教材的名称或类型。",
        "很抱歉，提供的资料中没有关于 BUSA90500 的 census date 和退课截止日期的信息。",
        "The provided material does not mention the prerequisite.",
        "The context doesn't specify the census date.",
        "This is not mentioned in the material.",
        "I cannot determine the fee from the material.",
    ],
)
def test_recognises_refusal_phrasings(answer):
    assert find_refusal(answer) is not None


@pytest.mark.parametrize(
    "answer",
    [
        "BUSA90500 的 census date 是 5 June 2026。",
        "该课程需要先修 BUSA90499。",
        "The census date is 5 June.",
        # gpt-4o-mini's actual answer once the one clause stating the cap was
        # cut from the article: from memory, with confidence, and out of date.
        "持学生签证的国际学生在澳洲每两周最多可以工作40小时。请注意，工作时间的限制可能会根据具体的签证类型和政策有所不同。",
    ],
)
def test_a_confident_answer_is_not_a_refusal(answer):
    assert find_refusal(answer) is None


def test_an_answer_with_no_refusal_fails_even_if_it_invents_nothing():
    verdict = judge_refusal("考核包括 Week 5 的期中测试。", evidence=EVIDENCE)

    assert verdict.refusal_phrase is None
    assert verdict.unsupported_facts == ()
    assert not verdict.passed


# --- criterion 2: nothing absent from the evidence ----------------------------


def test_refusing_then_inventing_fails():
    # The case the issue calls paper armour: the phrase is there, and then
    # the model answers anyway.
    verdict = judge_refusal(
        "资料不足。不过一般来说 census date 是 6月5日，需要先修 BUSA90499。",
        evidence=EVIDENCE,
    )

    assert verdict.refusal_phrase == "资料不足"
    assert set(verdict.unsupported_facts) == {"6月5日", "BUSA90499"}
    assert not verdict.passed


def test_a_clean_refusal_passes():
    verdict = judge_refusal(
        "资料中没有提到 BUSA90500 的 census date，建议查看 handbook 原文。",
        evidence=EVIDENCE,
    )

    assert verdict.passed, verdict.explain()


@pytest.mark.parametrize(
    "answer",
    [
        # Restating the context in another format is not inventing anything.
        "资料显示课程 2026 年 5 月 18 日开课。",
        "Teaching starts on May 18.",
        "活动在下午2点到7点，3/28 举行。",
        "活动时间是 14:00 至 19:00。",
        "热线是 0468-720-668，FWO 电话 13 13 94。",
        "费用是 $1,200，占 60%，共 12.5 学分。",
        "Hurdle 是 15/30。",
        "可以邮件 scholars@cssaunimelb.com 咨询。",
        "详见 https://handbook.unimelb.edu.au/2026/subjects/busa90500/assessment。",
        "详见 handbook.unimelb.edu.au。",
        "该课程在 5 月（May）开课。",
        # The question's own subject code may be echoed back.
        "BUSA90500 的考核在 Week 5 和 Week 9。",
    ],
)
def test_facts_restated_from_the_evidence_are_supported(answer):
    assert unsupported(answer) == []


@pytest.mark.parametrize(
    "answer, fact",
    [
        ("census date 是 6月5日。", "6月5日"),
        ("census date 是 2026年6月5日。", "6月5日"),
        ("census date 是 5 June 2026。", "5 June"),
        ("The census date is June 5th.", "June 5th"),
        ("截止日期是 2026-06-05。", "2026-06-05"),
        ("截止日期是 5/6。", "5/6"),
        ("通常 6 月份公布。", "6 月"),
        ("It is usually released in June.", "June"),
        ("讲座下午3点开始。", "下午3点"),
        ("讲座 15:30 开始。", "15:30"),
        ("讲座 3pm 开始。", "3pm"),
        ("先修课是 COMP90038。", "COMP90038"),
        ("学费大约 $5,000。", "5,000"),
        ("每两周最多工作 48 小时。", "48"),
        ("请拨打 13 14 50 咨询。", "13 14 50"),
        ("请访问 https://study.unimelb.edu.au/key-dates 查看。", "https://study.unimelb.edu.au/key-dates"),
        ("请发邮件到 busa90500@unimelb.edu.au。", "busa90500@unimelb.edu.au"),
        # No space between the Chinese text and the link: Python's \b would
        # see no word boundary here, which is why the patterns avoid it.
        ("可以访问study.unimelb.edu.au查询。", "study.unimelb.edu.au"),
    ],
)
def test_facts_absent_from_the_evidence_are_caught(answer, fact):
    assert fact in unsupported(answer)


def test_citations_and_list_numbering_are_not_facts():
    answer = "资料不足。\n1. 资料1 提到了考核方式\n2. [资料 2] 提到了开课时间\n3) 第3条资料没有相关内容"

    assert unsupported(answer) == []


def test_a_date_written_differently_is_judged_as_one_date_not_its_parts():
    # 6 and 5 are both in the evidence as loose numbers (Week 5, Week 6), but
    # the date 6月5日 is not. Judging dates by their parts would let this
    # through.
    assert unsupported("census date 是 6月5日。") == ["6月5日"]


def test_a_range_is_judged_number_by_number_not_as_a_phone_number():
    assert unsupported("大约 10-12 周。") == ["10", "12"]


def test_full_width_digits_compare_equal_to_ascii():
    assert unsupported("活动时间是下午２：００。") == []


# --- withheld answers ---------------------------------------------------------


def test_the_withheld_answer_fails_even_without_digits():
    verdict = judge_refusal(
        "资料没有说明先修要求，但通常需要被 Master of Finance 录取。",
        evidence=EVIDENCE,
        withheld=["Master of Finance"],
    )

    assert verdict.withheld_leaks == ("Master of Finance",)
    assert not verdict.passed


@pytest.mark.parametrize(
    "text, term, expected",
    [
        ("需要 master   of finance 录取", "Master of Finance", True),
        ("每两周 40 小时", "40", True),
        ("2040 年", "40", False),
        ("400 元", "40", False),
        ("coordinator 是 Laszlo Konya", "Konya", True),
    ],
)
def test_mentions_ignores_case_and_spacing_and_matches_numbers_whole(text, term, expected):
    assert mentions(text, term) is expected
