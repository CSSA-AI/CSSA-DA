import requests
from bs4 import BeautifulSoup
import json
import time
import os


def scrape_subject_section(url, headers):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        content_div = soup.find(
            'div', class_='course__body') or soup.find('main')

        if content_div:
            return ' '.join(content_div.text.split())
        else:
            return "Content section not found."

    except requests.exceptions.RequestException as e:
        print(f"  [!] Failed to retrieve {url}: {e}")
        return None


def scrape_full_subject(subject_code, year="2026"):
    base_url = f"https://handbook.unimelb.edu.au/{year}/subjects/{subject_code.lower()}"
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

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
        "base_url": base_url
    }

    for section_name, url_suffix in sections.items():
        target_url = base_url + url_suffix
        print(f"  -> Scraping {section_name.replace('_', ' ').title()}...")

        section_text = scrape_subject_section(target_url, headers)
        subject_data[section_name] = section_text

        time.sleep(1.5)

    return subject_data


def load_existing_data(filename):
    """Load existing JSON data safely."""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_data(filename, data):
    """Save JSON data safely."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def main():
    subjects_to_scrape = ["MAST20005", "MAST30025"

                          ]

    output_filename = 'unimelb_full_subjects_test.json'

    print("Starting scraper...\n")

    # ✅ Load existing data
    existing_data = load_existing_data(output_filename)

    # ✅ Create a set of existing subject codes
    existing_codes = {item["subject_code"] for item in existing_data}

    for code in subjects_to_scrape:
        code_upper = code.upper()

        # ✅ Skip if already exists
        if code_upper in existing_codes:
            print(f"Skipping {code_upper} (already exists)\n")
            continue

        print(f"Processing {code_upper}:")
        data = scrape_full_subject(code)

        if data:
            existing_data.append(data)
            existing_codes.add(code_upper)

        print("-" * 30)

    # ✅ Save updated data (without overwriting old entries)
    save_data(output_filename, existing_data)

    print(f"Success! Data saved to {output_filename}")


# ✅ Proper entry check
if __name__ == "__main__":
    main()
