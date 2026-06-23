import requests
from bs4 import BeautifulSoup
import json
import time
import os
from datetime import datetime


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


def scrape_full_subject(subject_code, year=None):
    if year is None:
        year = datetime.now().year
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


def search_subject_by_keyword(keyword, year=None):
    """
    Search for subjects by keyword and return possible matches.
    This function makes a search request to the handbook.
    """
    if year is None:
        year = datetime.now().year
    search_url = f"https://handbook.unimelb.edu.au/{year}/search"
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    
    try:
        params = {'q': keyword, 'types[]': 'subject'}
        response = requests.get(search_url, headers=headers, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        results = []
        result_items = soup.find_all('div', class_='search-result-item')
        
        for item in result_items[:5]:
            title_elem = item.find('h3') or item.find('a')
            if title_elem:
                title_text = title_elem.text.strip()
                link = title_elem.find('a')['href'] if title_elem.find('a') else None
                
                if link and '/subjects/' in link:
                    subject_code = link.split('/subjects/')[-1].split('/')[0].upper()
                    results.append({
                        'code': subject_code,
                        'title': title_text,
                        'link': link
                    })
        
        return results
    except Exception as e:
        print(f"Search failed: {e}")
        return []


def is_valid_subject_code(code):
    """
    Check if the input looks like a valid subject code.
    Format: typically 4 letters followed by 5 digits (e.g., MAST20005)
    """
    import re
    pattern = r'^[A-Z]{4}\d{5}$'
    return bool(re.match(pattern, code.upper()))


def interactive_mode():
    """
    Interactive mode: allows users to input course codes or search keywords.
    """
    output_filename = 'unimelb_subjects_data.json'
    
    print("=" * 60)
    print("  UniMelb Course Handbook Scraper")
    print("=" * 60)
    print("Enter course codes (e.g., MAST20005) or keywords to search.")
    print("You can enter multiple codes separated by commas.")
    print("Type 'quit' or 'exit' to stop.\n")
    
    existing_data = load_existing_data(output_filename)
    existing_codes = {item["subject_code"] for item in existing_data}
    
    while True:
        user_input = input("\nEnter course code(s) or search keyword: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nExiting scraper. Data has been saved.")
            break
        
        if not user_input:
            print("Please enter a valid input.")
            continue
        
        codes_to_process = []
        
        if ',' in user_input:
            codes_to_process = [code.strip().upper() for code in user_input.split(',')]
        elif is_valid_subject_code(user_input):
            codes_to_process = [user_input.upper()]
        else:
            print(f"\n🔍 Searching for: '{user_input}'...")
            search_results = search_subject_by_keyword(user_input)
            
            if not search_results:
                print("No subjects found. Try a different keyword or enter a specific course code.")
                continue
            
            print(f"\n📚 Found {len(search_results)} subject(s):")
            for idx, result in enumerate(search_results, 1):
                print(f"  {idx}. {result['code']} - {result['title']}")
            
            choice = input("\nEnter the number(s) to scrape (comma-separated) or 'all': ").strip()
            
            if choice.lower() == 'all':
                codes_to_process = [r['code'] for r in search_results]
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in choice.split(',')]
                    codes_to_process = [search_results[i]['code'] for i in indices if 0 <= i < len(search_results)]
                except (ValueError, IndexError):
                    print("Invalid selection. Please try again.")
                    continue
        
        if not codes_to_process:
            print("No valid course codes to process.")
            continue
        
        print(f"\n{'=' * 60}")
        print(f"Processing {len(codes_to_process)} course(s)...")
        print(f"{'=' * 60}\n")
        
        for code in codes_to_process:
            code_upper = code.upper()
            
            if code_upper in existing_codes:
                print(f"⏭️  Skipping {code_upper} (already exists in database)\n")
                continue
            
            print(f"📥 Processing {code_upper}:")
            data = scrape_full_subject(code)
            
            if data and data.get('overview'):
                existing_data.append(data)
                existing_codes.add(code_upper)
                save_data(output_filename, existing_data)
                print(f"✅ Successfully scraped and saved {code_upper}")
            else:
                print(f"❌ Failed to scrape {code_upper} or no data found")
            
            print("-" * 60)
        
        print(f"\n💾 Data saved to {output_filename}")


def batch_mode(subject_codes):
    """
    Batch mode: process a list of subject codes provided as argument.
    """
    output_filename = 'unimelb_subjects_data.json'
    
    print("=" * 60)
    print("  Batch Mode: Scraping Subjects")
    print("=" * 60)
    
    existing_data = load_existing_data(output_filename)
    existing_codes = {item["subject_code"] for item in existing_data}
    
    for code in subject_codes:
        code_upper = code.upper()
        
        if code_upper in existing_codes:
            print(f"Skipping {code_upper} (already exists)\n")
            continue
        
        print(f"Processing {code_upper}:")
        data = scrape_full_subject(code)
        
        if data:
            existing_data.append(data)
            existing_codes.add(code_upper)
        
        print("-" * 30)
    
    save_data(output_filename, existing_data)
    print(f"Success! Data saved to {output_filename}")


def main():
    """
    Main entry point: supports both interactive and batch modes.
    """
    import sys
    
    if len(sys.argv) > 1:
        subject_codes = sys.argv[1:]
        batch_mode(subject_codes)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
