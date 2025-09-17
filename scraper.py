import time
import json
import re
import os
import random
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium_stealth import stealth

# --- Configuration ---
START_URL = "https://clutch.co/it-services/india"
URL_FILE = 'profile_urls.json'
OUTPUT_FILE = 'clutch_full_profiles_final.jsonl'
LISTING_PAGES_TO_SCRAPE = 115
SETTLE_WAIT = 2   # seconds to let a profile page settle


def scrape_company_profile(driver, profile_url):
    print(f"\n  -> Scraping profile: {profile_url}")
    company_data = {'profile_url': profile_url}

    try:
        driver.get(profile_url)
        time.sleep(SETTLE_WAIT)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.profile-header'))
        )
        soup = BeautifulSoup(driver.page_source, 'lxml')

        # --- Core fields ---
        header = soup.select_one('.profile-header')
        summary_section = soup.select_one('#profile-summary')

        # Name
        name_tag = soup.select_one('h1.profile-header__title')
        company_data['name'] = name_tag.get_text(strip=True) if name_tag else 'N/A'

        # Summary
        # Try normal extraction
        summary_tag = soup.select_one(".profile-summary__text")
        if summary_tag:
            company_data["summary_description"] = summary_tag.get_text(separator="\n", strip=True)
        else:
            # Fallback: Check JSON-LD
            json_ld_tag = soup.find("script", type="application/ld+json")
            if json_ld_tag:
                try:
                    data = json.loads(json_ld_tag.string.strip())
                    company_data["summary_description"] = data.get("description", "N/A")
                except Exception:
                    company_data["summary_description"] = "N/A"
            else:
                company_data["summary_description"] = "N/A"


        # Website
        website_tag = soup.select_one("ul.profile-short-actions a[title='Visit website']")
        if website_tag and website_tag.has_attr("href"):
            href = website_tag["href"]
            # Try to get the real website from the `u` parameter
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            real_website = query.get("u", [None])[0] or query.get("provider_website", [None])[0]
            company_data["website"] = real_website if real_website else href
        else:
            company_data["website"] = "N/A"


        # Summary details
        summary_details = {}
        details_section = soup.select('ul.profile-summary__details li.profile-summary__detail, ul.profile-summary__details li.profile-summary__detail-clickable')
        for detail in details_section:
            label_tag = detail.select_one('.profile-summary__detail-label')
            title_tag = detail.select_one('.profile-summary__detail-title')
            if label_tag and title_tag:
                label = label_tag.get_text(strip=True)
                title = " ".join(title_tag.get_text(strip=True).split())
                summary_details[label] = title

        company_data['summary_details'] = summary_details


        # Languages
        languages = []
        lang_modal = soup.select_one('#profile-languages-modal')
        if lang_modal:
            languages = [li.text.strip() for li in lang_modal.select('.profile-modal--list li')]
        company_data['languages'] = languages

        # Locations
        locations = []
        loc_modal = soup.select_one('#profile-locations-modal')
        if loc_modal:
            locations = [li.text.strip() for li in loc_modal.select('.profile-modal--list li')]
        company_data['locations'] = locations

        # Chart data
        service_lines, focus_areas, industries, clients = [], [], [], []
        script_tag = soup.find('script', string=lambda t: t and 'window.chartPie' in t)
        if script_tag:
            m = re.search(r'window\.chartPie\s*=\s*({.*?});', script_tag.string, re.DOTALL)
            if m:
                try:
                    chart_data = json.loads(m.group(1))
                    if 'service_provided' in chart_data:
                        service_lines = [f"{s['name']}: {s['percent']*100:.1f}%" for s in chart_data['service_provided']['slices']]
                    if 'industries' in chart_data:
                        industries = [f"{s['name']}: {s['percent']*100:.1f}%" for s in chart_data['industries']['slices']]
                    if 'clients' in chart_data:
                        clients = [f"{s['name']}: {s['percent']*100:.1f}%" for s in chart_data['clients']['slices']]
                    if 'focus' in chart_data:
                        for cat, data in chart_data['focus']['charts'].items():
                            focus_areas.append({data.get('legend_title', cat): [f"{s['name']}: {s['percent']*100:.1f}%" for s in data['slices']]})
                except Exception:
                    pass
        company_data.update({
            'service_lines': service_lines,
            'focus_breakdown': focus_areas,
            'industries_focus': industries,
            'client_focus': clients
        })

        # Pricing
        pricing_snapshot = {}
        pricing = soup.select_one('#pricing-snapshot')
        if pricing:
            size = pricing.select_one('#common-project-size-value')
            fb = pricing.select_one('.pricing-snapshot__clients-feedback-description')
            pricing_snapshot['most_common_project_size'] = size.text.strip() if size else 'N/A'
            pricing_snapshot['client_feedback_summary'] = fb.text.strip() if fb else 'N/A'
        company_data['pricing_snapshot'] = pricing_snapshot

        return company_data

    except Exception as e:
        print(f"  - Error scraping {profile_url}: {e}")
        return None


def collect_profile_urls(driver):
    if os.path.exists(URL_FILE):
        print(f"Found existing {URL_FILE}, loading cached URLs...")
        with open(URL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    print("Collecting profile URLs from listing pages...")
    profile_urls = []

    for page_num in range(1, LISTING_PAGES_TO_SCRAPE + 1):
        url = START_URL if page_num == 1 else f"{START_URL}?page={page_num}"
        print(f"  - Visiting listing page {page_num}: {url}")
        driver.get(url)
        time.sleep(random.uniform(4, 6))

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.provider-list-item h3.provider__title a'))
            )
            soup = BeautifulSoup(driver.page_source, 'lxml')
            links = soup.select('li.provider-list-item h3.provider__title a')
            new_urls = 0
            for link in links:
                if link.has_attr('href'):
                    full = "https://clutch.co" + link['href'] if link['href'].startswith('/') else link['href']
                    if full not in profile_urls:
                        profile_urls.append(full)
                        new_urls += 1
            print(f"    Found {new_urls} new URLs. Total: {len(profile_urls)}")

        except TimeoutException:
            print("    Timeout on this page, skipping further collection.")
            break

    with open(URL_FILE, 'w', encoding='utf-8') as f:
        json.dump(profile_urls, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(profile_urls)} profile URLs to {URL_FILE}")
    return profile_urls


def scrape_all_profiles(driver, profile_urls):
    print("\nScraping company profiles...")
    scraped_urls = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    scraped_urls.add(json.loads(line)['profile_url'])
                except:
                    pass
        print(f"Already scraped {len(scraped_urls)} profiles, will skip them.")

    new_count = 0
    for url in profile_urls:
        if url in scraped_urls:
            continue
        data = scrape_company_profile(driver, url)
        if data:
            with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.write("\n")
            scraped_urls.add(url)
            new_count += 1
            print(f"  --> Saved {data.get('name')}")
    print(f"Scraping complete. Added {new_count} new profiles.")


def main():
    print("Launching undetected Chrome...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options, use_subprocess=True)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")

    urls = collect_profile_urls(driver)
    scrape_all_profiles(driver, urls)

    driver.quit()


if __name__ == "__main__":
    main()
