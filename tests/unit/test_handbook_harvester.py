import argparse
import json
from unittest.mock import MagicMock

import pytest
import requests

from scripts import handbook_harvester_all as harvester


def _response(text="<main>content</main>"):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = text
    return response


def test_has_content_true_when_any_section_non_empty():
    record = {name: "" for name in harvester.SECTIONS}
    record["assessment"] = "some text"

    assert harvester.has_content(record) is True


def test_has_content_false_when_all_sections_empty():
    record = {name: "" for name in harvester.SECTIONS}

    assert harvester.has_content(record) is False


def test_scrape_subject_section_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())
    calls = {"count": 0}

    def fake_get_html(url, headers=None, timeout=20, browser_context=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.ConnectionError("boom")
        return "<div class='course__body'>Real content</div>"

    monkeypatch.setattr(harvester, "get_html", fake_get_html)

    result = harvester.scrape_subject_section("http://example.test/section")

    assert result == "Real content"
    assert calls["count"] == 3


def test_scrape_subject_section_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())
    monkeypatch.setattr(
        harvester,
        "get_html",
        MagicMock(side_effect=requests.exceptions.Timeout("timed out")),
    )

    with pytest.raises(harvester.SectionFetchFailed):
        harvester.scrape_subject_section("http://example.test/section")

    assert harvester.get_html.call_count == harvester.MAX_ATTEMPTS


def test_scrape_subject_section_empty_content_div_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(harvester, "get_html", lambda *a, **k: "<html></html>")

    result = harvester.scrape_subject_section("http://example.test/section")

    assert result == ""


def test_scrape_full_subject_marks_failure_without_faking_empty_string(monkeypatch):
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())

    def fake_scrape_section(
        url, headers=None, max_attempts=harvester.MAX_ATTEMPTS, browser_context=None
    ):
        if "eligibility" in url:
            raise harvester.SectionFetchFailed("network dead")
        return "ok"

    monkeypatch.setattr(harvester, "scrape_subject_section", fake_scrape_section)

    data, ok = harvester.scrape_full_subject("COMP10001", year="2026")

    assert ok is False
    assert data["eligibility_and_requirements"] == ""
    assert data["overview"] == "ok"


def test_scrape_full_subject_succeeds_when_all_sections_fetch(monkeypatch):
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())
    monkeypatch.setattr(
        harvester, "scrape_subject_section", lambda *a, **k: "content"
    )

    data, ok = harvester.scrape_full_subject("COMP10001", year="2026")

    assert ok is True
    assert all(data[name] == "content" for name in harvester.SECTIONS)
    assert data["subject_code"] == "COMP10001"


def test_get_html_routes_to_browser_when_context_given(monkeypatch):
    monkeypatch.setattr(
        harvester, "get_html_via_browser", lambda ctx, url, timeout=20: "browser-html"
    )
    monkeypatch.setattr(
        requests, "get", MagicMock(side_effect=AssertionError("should not use requests"))
    )

    result = harvester.get_html("http://example.test", browser_context=object())

    assert result == "browser-html"


def test_get_html_via_browser_wraps_playwright_errors():
    class FakePage:
        def goto(self, url, timeout, wait_until):
            raise RuntimeError("navigation timeout")

        def close(self):
            pass

    class FakeContext:
        def new_page(self):
            return FakePage()

    with pytest.raises(harvester.FetchError):
        harvester.get_html_via_browser(FakeContext(), "http://example.test")


def test_get_html_via_browser_returns_page_content():
    class FakePage:
        def __init__(self):
            self.closed = False

        def goto(self, url, timeout, wait_until):
            pass

        def wait_for_timeout(self, ms):
            pass

        def content(self):
            return "<main>real content via browser</main>"

        def close(self):
            self.closed = True

    fake_page = FakePage()

    class FakeContext:
        def new_page(self):
            return fake_page

    html = harvester.get_html_via_browser(FakeContext(), "http://example.test")

    assert html == "<main>real content via browser</main>"
    assert fake_page.closed is True


def test_save_data_writes_atomically_and_leaves_no_tmp_file(tmp_path):
    output_file = tmp_path / "nested" / "out.json"

    harvester.save_data(str(output_file), [{"a": 1}])

    assert json.loads(output_file.read_text(encoding="utf-8")) == [{"a": 1}]
    assert not output_file.with_suffix(".json.tmp").exists()
    assert list(tmp_path.rglob("*.tmp")) == []


def test_main_resumes_by_content_not_by_presence_and_writes_failed_list(
    monkeypatch, tmp_path
):
    output_file = tmp_path / "data" / "unimelb_subjects_2026.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    existing = [
        {
            "subject_code": "AAAA10001",
            "year": "2026",
            "base_url": "x",
            **{name: "" for name in harvester.SECTIONS},
        },
        {
            "subject_code": "BBBB10001",
            "year": "2026",
            "base_url": "x",
            **{name: "already has content" for name in harvester.SECTIONS},
        },
    ]
    output_file.write_text(json.dumps(existing), encoding="utf-8")

    monkeypatch.setattr(
        harvester, "collect_all_subject_codes", lambda **kwargs: [
            "AAAA10001", "BBBB10001", "CCCC10001",
        ]
    )
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())

    def fake_scrape_full_subject(code, year="2026", browser_context=None):
        if code == "CCCC10001":
            return (
                {
                    "subject_code": code,
                    "year": year,
                    "base_url": "x",
                    **{name: "" for name in harvester.SECTIONS},
                },
                False,
            )
        return (
            {
                "subject_code": code,
                "year": year,
                "base_url": "x",
                **{name: "re-scraped" for name in harvester.SECTIONS},
            },
            True,
        )

    monkeypatch.setattr(harvester, "scrape_full_subject", fake_scrape_full_subject)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        harvester,
        "parse_args",
        lambda: argparse.Namespace(
            year="2026", output=None, limit=None, use_browser=False
        ),
    )

    harvester.main()

    saved = json.loads((tmp_path / "data" / "unimelb_subjects_2026.json").read_text(
        encoding="utf-8"
    ))
    saved_by_code = {item["subject_code"]: item for item in saved}

    # BBBB10001 already had content -> not re-scraped, left untouched.
    assert saved_by_code["BBBB10001"]["overview"] == "already has content"
    # AAAA10001 was all-empty -> re-scraped even though it was already "in the file".
    assert saved_by_code["AAAA10001"]["overview"] == "re-scraped"
    assert "CCCC10001" not in saved_by_code

    failed = json.loads((tmp_path / "data" / "unimelb_subjects_2026_failed.json").read_text(
        encoding="utf-8"
    ))
    assert failed == ["CCCC10001"]


def test_main_respects_limit_for_a_quick_smoke_test(monkeypatch, tmp_path):
    output_file = tmp_path / "smoke_test.json"

    monkeypatch.setattr(
        harvester, "collect_all_subject_codes", lambda **kwargs: [
            "AAAA10001", "BBBB10001", "CCCC10001", "DDDD10001",
        ]
    )
    monkeypatch.setattr(harvester.time, "sleep", MagicMock())

    scraped_codes = []

    def fake_scrape_full_subject(code, year="2026", browser_context=None):
        scraped_codes.append(code)
        return (
            {
                "subject_code": code,
                "year": year,
                "base_url": "x",
                **{name: "content" for name in harvester.SECTIONS},
            },
            True,
        )

    monkeypatch.setattr(harvester, "scrape_full_subject", fake_scrape_full_subject)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        harvester,
        "parse_args",
        lambda: argparse.Namespace(
            year="2026", output=str(output_file), limit=2, use_browser=False
        ),
    )

    harvester.main()

    assert scraped_codes == ["AAAA10001", "BBBB10001"]
    saved = json.loads(output_file.read_text(encoding="utf-8"))
    assert {item["subject_code"] for item in saved} == {"AAAA10001", "BBBB10001"}
