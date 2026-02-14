import trafilatura
import json
from langdetect import detect
import hanzidentifier
from urllib.parse import urlparse
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def extract_aoji_links():
    links = []
    # Start from the provided article ID and increment upwards
    start_id = 2745094
    max_pages = 1000  # Limit to prevent infinite loops
    consecutive_failures = 0  # Track consecutive failures to decide early stop
    
    for i in range(max_pages):
        article_id = start_id + i
        url = f"http://www.aoji.cn/news/{article_id}.html"
        print(f'accessing {url}')
        
        try:
            resp = requests.get(url, headers={"User-Agent": "MyBot/1.0"}, timeout=10)
            time.sleep(2)
            
            # Check if page exists (not 404)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                
                # Check if the page has actual content (not a 404 or error page)
                title = soup.find('title')
                if title and '404' not in title.text and 'error' not in title.text.lower():
                    links.append(url)
                    print(f'Found valid article: {url}')
                    # Reset failure counter on success
                    consecutive_failures = 0
                else:
                    print(f'Page {article_id} appears to be invalid or 404')
                    consecutive_failures += 1
            else:
                print(f'HTTP {resp.status_code} for {url}')
                consecutive_failures += 1
        except Exception as e:
            print(f'Error accessing {url}: {e}')
            consecutive_failures += 1

        # Stop after 10 consecutive failures of any kind
        if consecutive_failures >= 10:
            print('Stopping after 10 consecutive failures')
            break
    
    return links


def load_web(url):
    print(f'start fetch {url}')
    # Download HTML
    downloaded = trafilatura.fetch_url(url)
    # Extract with metadata
    data_json = trafilatura.extract(
        downloaded,
        output_format="json",   # structured output
        with_metadata=True,     # include title, author, date, etc.
        include_comments=False,
        include_images=False
    )
    if data_json:
        data = json.loads(data_json)

        # return none for 404 page
        if data.get('title') == 'undefined':
            return None
        
        return data
    else:
        return None


def check_language(text):
    # detect language
    try:
        language = detect(text)
    except:
        return None

    # check chinese script type
    if language.startswith('zh'):
        has_simp = hanzidentifier.is_simplified(text)
        has_trad = hanzidentifier.is_traditional(text)
        
        if has_simp and not has_trad:
            return "simplified-chinese"
        elif has_trad and not has_simp:
            return "traditional-chinese"
        elif has_simp and has_trad:
            return 'mixed-chinese'

    # English language
    elif language.startswith("en"):
        return 'english'
    else:
        return language


def extract_source(url):
    parsed = urlparse(url)
    domain = parsed.netloc
    return domain


def parse_json(data, url, id):
    # Parse JSON
    result_json = {
        'id': str(id).zfill(5),
        'question': None,
        'raw_text': data.get('raw_text'),
        'text': data.get('text'),
        'source': extract_source(url),
        'title': data.get('title'),
        'author': data.get('author'),
        'post_date': data.get('date'),
        'language': check_language(data.get('text')),
        'created_at': data.get('filedate'),
        'excerpt': data.get('excerpt'),
        'tags': [data.get('tags')],
        'link': url
    }
    return result_json


def main():
    id = 20000  # Start from 20000 to avoid conflicts with myoffer data
    json_list = []
    urls = extract_aoji_links()
    print(f'url collection succeed, collected {len(urls)} urls')
    
    for url in urls:
        data_json = load_web(url)
        time.sleep(2)
        if not data_json:
            print('No result fetched\n')
            continue

        id += 1
        result_json = parse_json(data_json, url, id)
        json_list.append(result_json)
        print('Successfully fetched\n')
    
    print('fetch finished')
    
    # Ensure the data directory exists
    import os
    data_dir = "../data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        print(f"Created directory: {data_dir}")
    
    # Write the JSON file
    output_file = os.path.join(data_dir, "aoji.json")
    try:
        # Load existing data if file exists
        existing_data = []
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            print(f"Loaded {len(existing_data)} existing articles")
        
        # Combine existing and new data
        all_data = existing_data + json_list
        
        # Write combined data
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"Successfully wrote {len(all_data)} total articles to {output_file} ({len(json_list)} new articles added)")
    except Exception as e:
        print(f"Error writing to {output_file}: {e}")
        # Try writing to current directory as fallback
        fallback_file = "aoji.json"
        with open(fallback_file, "w", encoding="utf-8") as f:
            json.dump(json_list, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(json_list)} articles to {fallback_file} in current directory")


if __name__ == '__main__':
    main()
