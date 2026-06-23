import requests
from bs4 import BeautifulSoup
import json
import time
import os
import re
from urllib.parse import urljoin


HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://handbook.unimelb.edu.au"


def get_html(url, headers=HEADERS, timeout=20):
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def scrape_subject_section(url, headers=HEADERS):
    try:
        html = get_html(url, headers=headers)
        soup = BeautifulSoup(html, "html.parser")

        content_div = soup.find(
            "div", class_="course__body") or soup.find("main")

        if content_div:
            return " ".join(content_div.get_text(" ", strip=True).split())
        else:
            return ""

    except requests.exceptions.RequestException as e:
        print(f"  [!] Failed to retrieve {url}: {e}")
        return None


def scrape_full_subject(subject_code, year="2026"):
    base_url = f"{BASE_URL}/{year}/subjects/{subject_code.lower()}"

    sections = {
        "overview": "",
        "eligibility_and_requirements": "/eligibility-and-requirements",
        "assessment": "/assessment",
        "dates_and_times": "/dates-times",
        "further_information": "/further-information"
    }

    subject_data = {
        "subject_code": subject_code.upper(),
        "year": year,
        "base_url": base_url,
        "overview": "",
        "eligibility_and_requirements": "",
        "assessment": "",
        "dates_and_times": "",
        "further_information": ""
    }

    for section_name, url_suffix in sections.items():
        target_url = base_url + url_suffix
        print(f"  -> Scraping {section_name.replace('_', ' ').title()}...")

        section_text = scrape_subject_section(target_url)

        if section_text is None:
            section_text = ""

        subject_data[section_name] = section_text

        time.sleep(1)

    return subject_data


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


def collect_all_subject_codes(year="2026", max_pages=400):
    """
    Automatically collect all subject codes from Handbook subject search pages.
    """
    all_codes = set()

    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/search?types%5B%5D=subject&page={page}"
        print(f"[Search Page {page}] {url}")

        try:
            html = get_html(url)
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

        except requests.exceptions.RequestException as e:
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


def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def main():
    year = "2026"
    output_filename = f"unimelb_subjects_{year}.json"

    print(f"Collecting all subject codes for {year}...\n")
    subject_codes = collect_all_subject_codes(year=year, max_pages=400)

    print(f"\nTotal discovered subject codes: {len(subject_codes)}")

    existing_data = load_existing_data(output_filename)
    existing_codes = {item["subject_code"] for item in existing_data}

    for i, code in enumerate(subject_codes, start=1):
        if code in existing_codes:
            print(f"[{i}/{len(subject_codes)}] Skipping {code} (already exists)\n")
            continue

        print(f"[{i}/{len(subject_codes)}] Processing {code}:")
        data = scrape_full_subject(code, year=year)

        if data:
            existing_data.append(data)
            existing_codes.add(code)

        save_data(output_filename, existing_data)
        print("-" * 50)

    print(f"Success! Data saved to {output_filename}")


if __name__ == "__main__":
    main()
