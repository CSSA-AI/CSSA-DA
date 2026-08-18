import argparse
import contextlib
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://handbook.unimelb.edu.au"

# A section fetch gets this many total attempts (1 initial + retries) before
# it is treated as a hard failure, with exponential backoff between attempts.
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 2

# Rewrite the output file every N subjects instead of after every single one,
# so a ~9MB file isn't rewritten O(n) times over a multi-thousand-subject run.
SAVE_EVERY = 20

SECTIONS = {
    "overview": "",
    "eligibility_and_requirements": "/eligibility-and-requirements",
    "assessment": "/assessment",
    "dates_and_times": "/dates-times",
    "further_information": "/further-information",
}


class SectionFetchFailed(Exception):
    """A section could not be retrieved after all retries.

    This is intentionally distinct from "the school published an empty
    section" -- callers must never fall back to an empty string here, since
    that would make a dropped request look identical to genuinely missing
    handbook content.
    """


class FetchError(Exception):
    """A page could not be fetched, regardless of which fetch backend
    (plain HTTP vs. browser) was used. ``scrape_subject_section`` only
    needs to know about this one exception type to retry/give up.
    """


class BrowserSession:
    """Owns a single headless Chromium browser + context for a whole run.

    The handbook site is protected by Incapsula-style bot mitigation: a
    plain HTTP client gets served a JS-challenge page as a normal ``200``
    response, so ``requests`` never sees an error -- the challenge page
    just silently parses as "no content". A real browser executes that
    challenge JS and gets redirected to the actual page.

    One browser/context is reused across every fetch in the run rather
    than launched per page: browser startup takes ~1-2s, which would
    dominate a multi-thousand-page run otherwise.
    """

    def __init__(self, headers=None, headless=True):
        self.headers = headers or HEADERS
        self.headless = headless
        self._playwright = None
        self._browser = None
        self.context = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self.context = self._browser.new_context(
            user_agent=self.headers.get("User-Agent")
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.context is not None:
            self.context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        return False


def get_html_via_browser(context, url, timeout=20, challenge_wait_ms=3000):
    """Fetch a page's HTML through a real browser page.

    ``wait_until="networkidle"`` gets past the initial challenge redirect;
    the extra fixed wait covers the JS challenge's own follow-up requests,
    which happen after the network otherwise looks idle.
    """
    page = context.new_page()
    try:
        page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
        page.wait_for_timeout(challenge_wait_ms)
        return page.content()
    except Exception as e:
        raise FetchError(str(e)) from e
    finally:
        page.close()


def get_html(url, headers=HEADERS, timeout=20, browser_context=None):
    if browser_context is not None:
        return get_html_via_browser(browser_context, url, timeout=timeout)

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        raise FetchError(str(e)) from e


def scrape_subject_section(
    url, headers=HEADERS, max_attempts=MAX_ATTEMPTS, browser_context=None
):
    """Fetch and extract the text content of one handbook section.

    Retries transient failures (network errors, or a browser fetch that
    raised) with exponential backoff. Raises ``SectionFetchFailed`` if
    every attempt fails -- the caller must not substitute an empty string
    in that case.
    """
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            html = get_html(url, headers=headers, browser_context=browser_context)
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.find(
                "div", class_="course__body") or soup.find("main")

            if content_div:
                return " ".join(content_div.get_text(" ", strip=True).split())
            return ""

        except (requests.exceptions.RequestException, FetchError) as e:
            last_error = e
            if attempt < max_attempts:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(
                    f"  [!] Attempt {attempt}/{max_attempts} failed for "
                    f"{url}: {e}. Retrying in {backoff}s..."
                )
                time.sleep(backoff)
            else:
                print(f"  [x] Giving up on {url} after {max_attempts} attempts: {e}")

    raise SectionFetchFailed(f"{url}: {last_error}")


def scrape_full_subject(subject_code, year="2026", browser_context=None):
    """Scrape all sections for one subject.

    Returns ``(subject_data, ok)``. ``ok`` is False if any section hit a
    hard failure after retries; callers must not persist ``subject_data`` in
    that case, since it would contain empty strings that look like real
    (but missing) content.
    """
    base_url = f"{BASE_URL}/{year}/subjects/{subject_code.lower()}"

    subject_data = {
        "subject_code": subject_code.upper(),
        "year": year,
        "base_url": base_url,
        **{name: "" for name in SECTIONS},
    }

    ok = True

    for section_name, url_suffix in SECTIONS.items():
        target_url = base_url + url_suffix
        print(f"  -> Scraping {section_name.replace('_', ' ').title()}...")

        try:
            subject_data[section_name] = scrape_subject_section(
                target_url, browser_context=browser_context
            )
        except SectionFetchFailed as e:
            print(f"  [x] {subject_code}: {section_name} failed permanently: {e}")
            ok = False

        time.sleep(1)

    return subject_data, ok


def extract_subject_codes_from_search_page(html, year="2026"):
    """
    Extract subject codes from subject result links like:
    /2026/subjects/comp10001
    """
    soup = BeautifulSoup(html, "html.parser")
    subject_codes = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        match = re.search(
            rf"/{year}/subjects/([a-z]{{4}}\d{{5}})/?$", href, re.IGNORECASE)
        if match:
            subject_codes.add(match.group(1).upper())

    return sorted(subject_codes)


def collect_all_subject_codes(year="2026", max_pages=400, browser_context=None):
    """
    Automatically collect all subject codes from Handbook subject search pages.
    """
    all_codes = set()

    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/search?types%5B%5D=subject&page={page}"
        print(f"[Search Page {page}] {url}")

        try:
            html = get_html(url, browser_context=browser_context)
            page_codes = extract_subject_codes_from_search_page(
                html, year=year)

            if not page_codes:
                print("  No subject codes found on this page. Stopping.")
                break

            before = len(all_codes)
            all_codes.update(page_codes)
            added = len(all_codes) - before

            print(f"  Found {len(page_codes)} codes, added {added} new")

            if added == 0:
                print("  No new subject codes added. Stopping.")
                break

            time.sleep(1)

        except (requests.exceptions.RequestException, FetchError) as e:
            print(f"  [!] Failed to retrieve search page {page}: {e}")

    return sorted(all_codes)


def load_existing_data(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def has_content(subject_record):
    """A subject counts as already scraped only if at least one of its
    five sections is non-empty. A record where every section is "" looks
    identical to a subject the school genuinely left blank, so this is the
    same bar the re-scrape needs to clear before skipping a subject.
    """
    return any(subject_record.get(name) for name in SECTIONS)


def save_data(filename, data):
    """Write ``data`` to ``filename`` atomically.

    Writes go through a temporary file and ``os.replace`` so a crash
    mid-write never leaves a truncated/corrupt JSON file behind.
    """
    directory = os.path.dirname(filename)
    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_filename = f"{filename}.tmp"
    with open(temp_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(temp_filename, filename)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Re-scrape UniMelb handbook subject content."
    )
    parser.add_argument(
        "--year", default="2026", help="Handbook year to scrape (default: 2026)."
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output JSON path. Defaults to "
            "data/unimelb_subjects_<year>.json. Use a throwaway path here "
            "for smoke-testing a small --limit run so the real dataset "
            "isn't touched."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Only scrape the first N subjects that still need (re)scraping. "
            "Useful for a quick smoke test before committing to the full "
            "multi-hour run."
        ),
    )
    parser.add_argument(
        "--use-browser",
        action="store_true",
        help=(
            "Fetch pages through a real headless Chromium browser (via "
            "Playwright) instead of plain requests. Needed when the site's "
            "bot mitigation (Incapsula) is serving a JS-challenge page to "
            "plain HTTP clients -- that comes back as an ordinary 200 "
            "response with no course content, so requests never sees it as "
            "a failure. Requires `uv run playwright install chromium` once."
        ),
    )
    return parser.parse_args()


def _run(codes_to_scrape, by_code, year, output_filename, failed_filename, browser_context):
    failed_codes = []
    start_time = time.monotonic()
    total = len(codes_to_scrape)

    for i, code in enumerate(codes_to_scrape, start=1):
        print(f"[{i}/{total}] Processing {code}:")
        data, ok = scrape_full_subject(
            code, year=year, browser_context=browser_context
        )

        if ok:
            by_code[code] = data
        else:
            failed_codes.append(code)
            print(f"  [!] {code} had a permanently failed section; not saved this run.")

        if i % SAVE_EVERY == 0 or i == total:
            save_data(output_filename, sorted(
                by_code.values(), key=lambda d: d["subject_code"]))
            print(f"  [saved progress: {len(by_code)} subjects with data so far]")

        print("-" * 50)

    save_data(output_filename, sorted(
        by_code.values(), key=lambda d: d["subject_code"]))

    if failed_codes:
        save_data(failed_filename, failed_codes)

    elapsed_minutes = (time.monotonic() - start_time) / 60
    failure_rate = (len(failed_codes) / total * 100) if total else 0.0

    print(f"\nDone in {elapsed_minutes:.1f} minutes.")
    print(f"Attempted: {total}, failed: {len(failed_codes)} ({failure_rate:.1f}%)")
    if failed_codes:
        print(f"Failed subject codes written to {failed_filename}: {failed_codes}")
    print(f"Success! Data saved to {output_filename}")


def main():
    args = parse_args()
    year = args.year
    # Must match where the data actually lives -- a bare relative filename
    # here previously wrote a second, disconnected copy in the repo root.
    output_filename = args.output or os.path.join(
        "data", f"unimelb_subjects_{year}.json")
    failed_filename = f"{os.path.splitext(output_filename)[0]}_failed.json"

    session_cm = BrowserSession() if args.use_browser else contextlib.nullcontext()

    with session_cm as session:
        browser_context = session.context if args.use_browser else None

        print(
            f"Collecting all subject codes for {year}"
            f"{' (via browser)' if args.use_browser else ''}...\n"
        )
        subject_codes = collect_all_subject_codes(
            year=year, browser_context=browser_context)
        print(f"\nTotal discovered subject codes: {len(subject_codes)}")

        existing_data = load_existing_data(output_filename)
        by_code = {item["subject_code"]: item for item in existing_data}
        completed_codes = {
            code for code, item in by_code.items() if has_content(item)
        }
        codes_to_scrape = [
            code for code in subject_codes if code not in completed_codes
        ]
        if args.limit is not None:
            codes_to_scrape = codes_to_scrape[: args.limit]
            print(f"--limit {args.limit} set: only scraping this many subjects this run.")

        print(
            f"{len(completed_codes)} subjects already have content, "
            f"{len(codes_to_scrape)} to (re)scrape this run\n"
        )

        _run(codes_to_scrape, by_code, year, output_filename,
             failed_filename, browser_context)


if __name__ == "__main__":
    main()
