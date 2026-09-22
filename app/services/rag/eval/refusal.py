"""Executable criteria for the refusal contract (ROADMAP_rag.md Phase 3.1).

The system prompt tells the generator: if the material does not contain the
answer, say the material is insufficient and do not make one up. Nothing in the
code backs that sentence up -- the orchestrator hands the generator whatever
retrieval returned, relevant or not -- so this module is what turns it into
something a test can fail on.

An answer honours the contract only when BOTH hold:

1. it contains a refusal phrase (资料不足, 没有提到, does not mention, ...), and
2. every specific fact in it -- subject code, link, email, date, clock time,
   phone number, amount, count -- can be traced to the material the model was
   shown, or to the question it was asked.

The second half is the one that matters. A model can open with 资料不足 and
then write a confident paragraph anyway; checking only for the phrase would
pass that answer, which is paper armour. The refusal patterns are therefore
deliberately lenient and the fact check deliberately strict.

Facts are compared by value, not by spelling: the context says "31 March 2026",
the answer says "3月31日", and that is the same date. Dates and clock times are
compared as whole values rather than as loose numbers, because their parts are
small numbers that almost any context contains -- a fabricated "6月5日" would
otherwise hide behind a "Week 5" and a "Semester 6".

What this cannot see, so that nobody reads more into a green run than it
proves: facts with no digits in them (a made-up textbook title, the wrong
office), numbers written as Chinese numerals (十二学分), and a fact that is in
the context but attached to the wrong thing. A per-case `withheld` list covers
the first for the one answer each case was built without; the rest is what
reading the answers is for.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable

# ---------------------------------------------------------------------------
# Criterion 1: the answer says the material does not contain the answer
# ---------------------------------------------------------------------------

_REFUSAL = re.compile(
    "|".join(
        [
            # 资料不足 / 信息不够 / 资料有限
            r"(?:资料|材料|信息|内容)\s*(?:不足|不够|有限|不全|缺失)",
            # 没有提到 / 并未说明 / 未提供 / 没有具体列出
            r"(?:没有|没|未|并未|并没有|尚未)\s*(?:具体|明确|详细|直接|专门|清楚)?\s*"
            r"(?:提到|提及|包含|包括|涉及|说明|列出|给出|提供|写明|注明|载明|记载|明确"
            r"|显示|介绍|说到|列明|公布|透露|指出)",
            # 无法确定 / 不能回答
            r"(?:无法|不能|没法|难以|无从)\s*(?:确定|确认|回答|判断|提供|给出|得知|知道"
            r"|查到|找到|告知)",
            r"找不到|查不到|没有找到|未找到|未能找到",
            # 没有关于 BUSA90500 的 census date 和退课截止日期的信息 -- the
            # gap restates the question, so it has to be wide
            r"(?:没有|缺少|缺乏|暂无|并无)[^。！？\n]{0,60}?(?:信息|资料|说明|数据|记录|内容)",
            r"\binsufficient\b",
            r"\bnot enough (?:information|detail)",
            r"\bno (?:information|details?|mention)\b",
            r"\b(?:does|do|did)(?: not|n't|n’t) (?:mention|specify|state|provide"
            r"|include|contain|list|say|give|cover|indicate)",
            r"\bnot (?:mentioned|specified|stated|provided|included|listed|given"
            r"|covered|available|indicated)\b",
            r"\b(?:cannot|can't|can’t|unable to|could not|couldn't|couldn’t) "
            r"(?:determine|confirm|find|answer|provide|tell|say)",
        ]
    ),
    re.IGNORECASE,
)


def find_refusal(answer: str) -> str | None:
    """Return the refusal phrase the answer uses, or None if it has none."""
    match = _REFUSAL.search(_normalize(answer))
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# Criterion 2: every specific fact in the answer is traceable to the evidence
# ---------------------------------------------------------------------------

_MONTH_NUMBERS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?"
    r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_URL_CHARS = r"[A-Za-z0-9\-._~:/?#@!$&*+,;=%]"

# Word edges are spelled out as ASCII lookarounds throughout: Python's \b and
# \w count CJK characters as word characters, so "访问handbook.unimelb.edu.au"
# has no \b before the "h" and a \b-anchored pattern would never see the link.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL = re.compile(rf"(?:https?://|www\.){_URL_CHARS}+", re.IGNORECASE)
_DOMAIN = re.compile(
    rf"(?<![@A-Za-z0-9.-])(?:[A-Za-z0-9-]+\.)+(?:com|au|org|net|edu|gov|cn|io|co)"
    rf"(?![A-Za-z0-9-])(?:/{_URL_CHARS}*)?",
    re.IGNORECASE,
)
_SUBJECT_CODE = re.compile(r"(?<![A-Za-z])[A-Za-z]{4}\d{5}(?!\d)")

# Each date pattern yields (month, day) through a small adapter below.
_DATE_ZH = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_DATE_ISO = re.compile(r"(?<!\d)\d{4}\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_DATE_DAY_MONTH = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME})(?![A-Za-z])\.?",
    re.IGNORECASE,
)
_DATE_MONTH_DAY = re.compile(
    rf"(?<![A-Za-z])({_MONTH_NAME})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)",
    re.IGNORECASE,
)
# 28/3 or 3/28 -- Australian sources write day first, but the model may not.
_DATE_NUMERIC = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])")

_MONTH_ZH = re.compile(r"(?<!\d)(\d{1,2})\s*月")
# "May" is left out of the answer side: "May I..." is not a month. The
# evidence side keeps it, so a context saying "Availability May" still
# supports an answer saying "5月".
_MONTH_EN_STRICT = re.compile(
    r"(?<![A-Za-z])(January|February|March|April|June|July|August|September"
    r"|October|November|December|Jan|Feb|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
    r"(?![A-Za-z])"
)
_MONTH_EN_LENIENT = re.compile(rf"(?<![A-Za-z])({_MONTH_NAME})(?![A-Za-z])")

_PERIOD = r"(上午|早上|中午|下午|晚上|凌晨)?\s*"
_TIME_COLON = re.compile(
    _PERIOD + r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})(?!\d)\s*(am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)
_TIME_ZH = re.compile(_PERIOD + r"(?<![第\d])(\d{1,2})\s*[点时](?:\s*(\d{1,2})\s*分|\s*(半))?")
_TIME_AMPM = re.compile(r"(?<!\d)(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)(?![a-z])", re.IGNORECASE)

# Two or more digit groups: 0468 720 668, 13 13 94.
_PHONE = re.compile(r"(?<![\d.])\+?\d{2,4}(?:[ -]\d{2,4}){1,4}(?![\d.])")
_DIGIT_RUN = re.compile(r"\d{6,}")
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

# How an answer points at the material or numbers its own list. These are
# not facts, and "资料 3" must not count as a claim about the number 3.
_CITATIONS = re.compile(
    r"\[\s*(?:资料|材料)?\s*\d+\s*\]"
    r"|(?:资料|材料)\s*\d+"
    r"|第\s*\d+\s*(?:条|份|段|篇|个)?\s*(?:资料|材料|来源)"
    r"|(?<![A-Za-z])(?:source|document|material|item|context)\s*#?\s*\d+",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"(?m)^[ \t>*-]*\**(?:\d+[.)、](?!\d)|[(]\d+[)])")


@dataclass(frozen=True)
class _Evidence:
    text: str
    link_text: str
    codes: frozenset[str]
    dates: frozenset[tuple[int, int]]
    months: frozenset[int]
    times: frozenset[int]
    digit_strings: frozenset[str]
    numbers: frozenset[float]


def find_unsupported_facts(answer: str, evidence: str) -> list[str]:
    """Specific facts in `answer` that do not appear in `evidence`.

    `evidence` is everything the model was entitled to use: the context it
    was shown plus the question it was asked. Each fact is returned as it was
    written in the answer, so a failure message can quote it.
    """
    known = _index_evidence(evidence)
    text = _LIST_MARKER.sub(" ", _CITATIONS.sub(" ", _normalize(answer)))
    unsupported: list[str] = []

    def take(
        pattern: re.Pattern[str],
        is_known: Callable[[re.Match[str]], bool | None],
    ) -> None:
        """Judge every match of `pattern`, then blank it out of the answer.

        `is_known` returns None when a match only looks like this kind of
        fact -- "15/30" is a hurdle score, not the 30th of the 15th month --
        and that text is left in place for the later, looser passes.
        """
        nonlocal text

        def check(match: re.Match[str]) -> str:
            verdict = is_known(match)
            if verdict is None:
                return match.group(0)
            if not verdict:
                unsupported.append(match.group(0).strip())
            return " "

        text = pattern.sub(check, text)

    def within(candidates: frozenset[Any], known_values: frozenset[Any]) -> bool | None:
        return bool(candidates & known_values) if candidates else None

    # Order matters: each pass blanks what it consumed, so the digits of a
    # link, a code or a date are judged once, as that thing, and never again
    # as loose numbers.
    take(_EMAIL, lambda m: m.group(0).lower() in known.text)
    take(_URL, lambda m: _link_key(m.group(0)) in known.link_text)
    take(_DOMAIN, lambda m: _link_key(m.group(0)) in known.link_text)
    take(_SUBJECT_CODE, lambda m: m.group(0).upper() in known.codes)
    for pattern, to_dates in _DATE_PATTERNS:
        take(pattern, lambda m, to_dates=to_dates: within(to_dates(m), known.dates))
    take(_MONTH_ZH, lambda m: within(_months_of(m.group(1)), known.months))
    take(_MONTH_EN_STRICT, lambda m: _month_of(m.group(1)) in known.months)
    for pattern, to_minutes in _TIME_PATTERNS:
        take(pattern, lambda m, to_minutes=to_minutes: within(to_minutes(m), known.times))
    take(_PHONE, lambda m: within(_phone_digits(m.group(0)), known.digit_strings))
    take(_NUMBER, lambda m: _number(m.group(0)) in known.numbers)
    return unsupported


# ---------------------------------------------------------------------------
# Both criteria together
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefusalVerdict:
    refusal_phrase: str | None
    unsupported_facts: tuple[str, ...]
    withheld_leaks: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.refusal_phrase is not None
            and not self.unsupported_facts
            and not self.withheld_leaks
        )

    def explain(self) -> str:
        if self.passed:
            return f"refused ({self.refusal_phrase!r}) and invented nothing"
        problems = []
        if self.refusal_phrase is None:
            problems.append("no refusal phrase")
        if self.unsupported_facts:
            problems.append(f"facts not in the context: {list(self.unsupported_facts)}")
        if self.withheld_leaks:
            problems.append(f"supplied the withheld answer: {list(self.withheld_leaks)}")
        return "; ".join(problems)


def judge_refusal(
    answer: str,
    *,
    evidence: str,
    withheld: Iterable[str] = (),
) -> RefusalVerdict:
    """Judge one answer to a question whose context does not hold the answer.

    `withheld` names the answer the context was built without -- typically
    what the model might supply from its own knowledge. Any of it appearing
    in the answer is a failure even when it has no digits for
    `find_unsupported_facts` to catch.
    """
    return RefusalVerdict(
        refusal_phrase=find_refusal(answer),
        unsupported_facts=tuple(find_unsupported_facts(answer, evidence)),
        withheld_leaks=tuple(term for term in withheld if mentions(answer, term)),
    )


def mentions(text: str, term: str) -> bool:
    """Whether `text` mentions `term`, ignoring case and spacing.

    A purely numeric term is matched as a number, so "40" is found in
    "40 小时" but not in "2040" or "400".
    """
    text = _normalize(text)
    term = _normalize(term).strip()
    if _NUMBER.fullmatch(term):
        return _number(term) in {_number(n) for n in _NUMBER.findall(text)}
    return _squash(term) in _squash(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    # NFKC folds full-width digits and punctuation (１２：００) into ASCII, so
    # the same fact written in either width compares equal.
    return unicodedata.normalize("NFKC", text or "")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _link_key(link: str) -> str:
    key = link.lower().rstrip(".,;:!?/")
    key = re.sub(r"^https?://", "", key)
    return re.sub(r"^www\.", "", key)


def _number(token: str) -> float:
    return float(token.replace(",", ""))


def _months_of(value: str) -> frozenset[int]:
    month = int(value)
    return frozenset({month}) if 1 <= month <= 12 else frozenset()


def _phone_digits(value: str) -> frozenset[str]:
    # Fewer than six digits is a range or a pair of numbers ("10-12 周"), not
    # a phone number; those are left to be judged number by number.
    digits = re.sub(r"\D", "", value)
    return frozenset({digits}) if len(digits) >= 6 else frozenset()


def _valid(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _dates(pairs: Iterable[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    return frozenset(pair for pair in pairs if _valid(*pair))


def _month_of(name: str) -> int:
    return _MONTH_NUMBERS[name[:3].lower()]


_DATE_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], frozenset[tuple[int, int]]]]] = [
    (_DATE_ZH, lambda m: _dates([(int(m.group(1)), int(m.group(2)))])),
    (_DATE_ISO, lambda m: _dates([(int(m.group(1)), int(m.group(2)))])),
    (_DATE_DAY_MONTH, lambda m: _dates([(_month_of(m.group(2)), int(m.group(1)))])),
    (_DATE_MONTH_DAY, lambda m: _dates([(_month_of(m.group(1)), int(m.group(2)))])),
    (
        _DATE_NUMERIC,
        lambda m: _dates(
            [(int(m.group(2)), int(m.group(1))), (int(m.group(1)), int(m.group(2)))]
        ),
    ),
]


def _minutes(hour: int, minute: int, period: str | None) -> frozenset[int]:
    """Every minute-of-day a written time could mean.

    "7点" with no period could be morning or evening; both readings are kept,
    and the time is supported if either one is in the evidence.
    """
    if hour > 24 or minute > 59:
        return frozenset()
    period = (period or "").lower().replace(".", "")
    if hour in (0, 12, 24):
        hours = {0, 12}
    elif hour > 12:
        hours = {hour}
    elif period in ("pm", "下午", "晚上"):
        hours = {hour + 12}
    elif period in ("am", "上午", "早上", "凌晨"):
        hours = {hour}
    elif period == "中午":
        hours = {12, hour + 12}
    else:
        hours = {hour, hour + 12}
    return frozenset(h * 60 + minute for h in hours)


_TIME_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], frozenset[int]]]] = [
    (
        _TIME_COLON,
        lambda m: _minutes(int(m.group(2)), int(m.group(3)), m.group(4) or m.group(1)),
    ),
    (
        _TIME_ZH,
        lambda m: _minutes(
            int(m.group(2)), 30 if m.group(4) else int(m.group(3) or 0), m.group(1)
        ),
    ),
    (_TIME_AMPM, lambda m: _minutes(int(m.group(1)), 0, m.group(2))),
]


def _index_evidence(evidence: str) -> _Evidence:
    text = _normalize(evidence)
    dates: set[tuple[int, int]] = set()
    for pattern, to_dates in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            dates |= to_dates(match)
    months = {month for month, _ in dates}
    for value in _MONTH_ZH.findall(text):
        months |= _months_of(value)
    months |= {_month_of(name) for name in _MONTH_EN_LENIENT.findall(text)}
    times: set[int] = set()
    for pattern, to_minutes in _TIME_PATTERNS:
        for match in pattern.finditer(text):
            times |= to_minutes(match)
    digit_strings = set(_DIGIT_RUN.findall(text))
    for value in _PHONE.findall(text):
        digit_strings |= _phone_digits(value)
    lowered = text.lower()
    return _Evidence(
        text=lowered,
        link_text=re.sub(r"https?://|www\.", "", lowered),
        codes=frozenset(code.upper() for code in _SUBJECT_CODE.findall(text)),
        dates=frozenset(dates),
        months=frozenset(months),
        times=frozenset(times),
        digit_strings=frozenset(digit_strings),
        numbers=frozenset(_number(n) for n in _NUMBER.findall(text)),
    )
