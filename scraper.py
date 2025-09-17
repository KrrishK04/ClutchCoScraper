import time
import json
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import re # Import the regular expressions library
import os # Import the os library to check for file existence

# --- Selenium Imports for Waiting and Interaction ---
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- Import Selenium-Stealth ---
from selenium_stealth import stealth

# --- Configuration ---
START_URL = "https://clutch.co/it-services/india"
URL_FILE = 'profile_urls.json'
OUTPUT_FILE = 'clutch_full_profiles_final.jsonl'
# Set a high limit to ensure all pages are scraped
LISTING_PAGES_TO_SCRAPE = 115 # Adjust if you know there are more pages

def scrape_company_profile(driver, profile_url):
    """
    Scrapes all detailed information (excluding reviews) from a single company profile page.
    """
    print(f"\n  -> Scraping profile: {profile_url}")
    driver.get(profile_url)
    company_data = {'profile_url': profile_url}

    try:
        print("    - Allowing page to settle for 10 seconds...")
        time.sleep(10) 
        
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.profile-header')))
        print("    - Profile header has loaded.")

        soup = BeautifulSoup(driver.page_source, 'lxml')
        
        header = soup.select_one('.profile-header')
        summary_section = soup.select_one('#profile-summary')
        
        # Correctly and safely get company name
        name_tag = soup.select_one('h1.profile-header__title')
        company_data['name'] = name_tag.get_text(strip=True) if name_tag else 'N/A'

        # Correctly and safely get summary description
        summary_tag = summary_section.select_one('.profile-summary__text') if summary_section else None
        company_data['summary_description'] = summary_tag.get_text(separator='\n', strip=True) if summary_tag else 'N/A'
        
        website_tag = header.select_one('a[data-link-type="visit-website"]') if header else None
        company_data['website'] = website_tag['href'] if website_tag and website_tag.has_attr('href') else 'N/A'

        # Safely get summary details
        summary_details = {}
        if summary_section:
            for detail in summary_section.select('.profile-summary__details li.profile-summary__detail'):
                label_tag = detail.select_one('.profile-summary__detail-label')
                title_tag = detail.select_one('.profile-summary__detail-title')
                if label_tag and title_tag:
                    label = label_tag.text.strip()
                    title = ' '.join(title_tag.text.split())
                    summary_details[label] = title
        company_data['summary_details'] = summary_details
        
        # Safely extract languages
        languages = []
        language_modal = soup.select_one('#profile-languages-modal')
        if language_modal:
            for lang_item in language_modal.select('.profile-modal--list li'):
                languages.append(lang_item.text.strip())
        company_data['languages'] = languages
        
        # Safely extract locations
        locations = []
        locations_modal = soup.select_one('#profile-locations-modal')
        if locations_modal:
            for loc_item in locations_modal.select('.profile-modal--list li'):
                locations.append(loc_item.text.strip())
        company_data['locations'] = locations

        # --- Extract Structured Chart Data ---
        service_lines, focus_areas, industries, clients = [], [], [], []
        
        script_tag = soup.find('script', string=lambda text: text and 'window.chartPie' in text)
        if script_tag:
            chart_json_match = re.search(r'window\.chartPie\s*=\s*({.*?});', script_tag.string, re.DOTALL)
            if chart_json_match:
                try:
                    chart_data = json.loads(chart_json_match.group(1))
                    
                    if 'service_provided' in chart_data and 'slices' in chart_data['service_provided']:
                        service_lines = [f"{s.get('name', '')}: {s.get('percent', 0)*100:.1f}%" for s in chart_data['service_provided']['slices']]
                    if 'industries' in chart_data and 'slices' in chart_data['industries']:
                        industries = [f"{s.get('name', '')}: {s.get('percent', 0)*100:.1f}%" for s in chart_data['industries']['slices']]
                    if 'clients' in chart_data and 'slices' in chart_data['clients']:
                        clients = [f"{s.get('name', '')}: {s.get('percent', 0)*100:.1f}%" for s in chart_data['clients']['slices']]
                    if 'focus' in chart_data and 'charts' in chart_data['focus']:
                        for focus_category, focus_data in chart_data['focus']['charts'].items():
                            if 'slices' in focus_data:
                                category_name = focus_data.get('legend_title', focus_category)
                                focus_details = [f"{s.get('name', '')}: {s.get('percent', 0)*100:.1f}%" for s in focus_data['slices']]
                                focus_areas.append({category_name: focus_details})
                except json.JSONDecodeError:
                    print("    - Could not parse chart data JSON.")
        
        company_data['service_lines'] = service_lines
        company_data['focus_breakdown'] = focus_areas
        company_data['industries_focus'] = industries
        company_data['client_focus'] = clients

        # --- Pricing Snapshot ---
        pricing_snapshot = {}
        pricing_section = soup.select_one('#pricing-snapshot')
        if pricing_section:
            common_size_tag = pricing_section.select_one('#common-project-size-value')
            pricing_snapshot['most_common_project_size'] = common_size_tag.text.strip() if common_size_tag else 'N/A'
            feedback_tag = pricing_section.select_one('.pricing-snapshot__clients-feedback-description')
            pricing_snapshot['client_feedback_summary'] = feedback_tag.text.strip() if feedback_tag else 'N/A'
        company_data['pricing_snapshot'] = pricing_snapshot

        return company_data

    except TimeoutException:
        print(f"  - Failed to load profile page {profile_url} in time.")
        return None
    except Exception as e:
        print(f"  - An unexpected error occurred on profile {profile_url}: {e}")
        return None

def collect_profile_urls(driver):
    """
    Collects all unique profile URLs from the listing pages.
    Skips if the URL file already exists.
    """
    if os.path.exists(URL_FILE):
        print(f"Found existing URL file '{URL_FILE}'. Loading URLs and skipping collection.")
        with open(URL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    print("Starting Phase 1: Collecting all profile URLs...")
    page_count = 1
    profile_urls = []
    
    while page_count <= LISTING_PAGES_TO_SCRAPE:
        print("-" * 20)
        print(f"Collecting URLs from listings page #{page_count}")
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.provider-list-item h3.provider__title a')))
            soup = BeautifulSoup(driver.page_source, 'lxml')
            
            links = soup.select('li.provider-list-item h3.provider__title a')
            new_urls_found = 0
            for link in links:
                if link.has_attr('href'):
                    href = link['href']
                    full_url = "https://clutch.co" + href if href.startswith('/') else href
                    if full_url not in profile_urls:
                        profile_urls.append(full_url)
                        new_urls_found += 1
            
            print(f"  Found {new_urls_found} new URLs. Total unique URLs: {len(profile_urls)}")
            
            page_count += 1
            if page_count > LISTING_PAGES_TO_SCRAPE:
                print("Reached page limit for collecting URLs.")
                break
                
            print("  Looking for the 'Next' button...")
            current_page_url = driver.current_url
            wait = WebDriverWait(driver, 10)
            next_button = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, 'Next')))
            driver.execute_script("arguments[0].click();", next_button)
            wait.until(EC.not_(EC.url_to_be(current_page_url)))
            print(f"  Successfully navigated to page {page_count}.")
            time.sleep(3)
        except Exception as e:
            print(f"  Could not proceed to the next page. Ending URL collection. Error: {e}")
            break
            
    # Save the collected URLs to a file for future runs
    with open(URL_FILE, 'w', encoding='utf-8') as f:
        json.dump(profile_urls, f)
    print(f"\nURL collection complete. Saved {len(profile_urls)} URLs to '{URL_FILE}'.")
    return profile_urls

def scrape_all_profiles(driver, profile_urls):
    """
    Scrapes all profiles from a list of URLs, skipping those already scraped.
    """
    print("\nStarting Phase 2: Scraping individual company profiles...")
    
    # --- RESUMABLE LOGIC ---
    scraped_urls = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line)
                    scraped_urls.add(data['profile_url'])
            print(f"Found {len(scraped_urls)} previously scraped companies. They will be skipped.")
        except (json.JSONDecodeError, IOError):
            print(f"Warning: Could not read existing output file '{OUTPUT_FILE}'. Starting fresh.")
            scraped_urls = set()

    scraped_count = 0
    for url in profile_urls:
        if url in scraped_urls:
            print(f"  -> Skipping already scraped URL: {url}")
            continue
        
        company_details = scrape_company_profile(driver, url)
        if company_details:
            with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                json.dump(company_details, f, ensure_ascii=False)
                f.write('\n')
            print(f"  --> Successfully scraped and saved data for: {company_details.get('name', 'N/A')}")
            scraped_count += 1

    print(f"\nScraping phase complete. Scraped {scraped_count} new profiles.")

def main():
    """Main function to control the entire scraping process."""
    print("Setting up the Undetected Chrome WebDriver with Stealth...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options, use_subprocess=True)

    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")
    print("WebDriver is ready.")

    driver.get(START_URL)
    print("Waiting for initial Cloudflare challenge...")
    time.sleep(10)

    # --- Run the two phases ---
    all_urls = collect_profile_urls(driver)
    scrape_all_profiles(driver, all_urls)

    driver.quit()
    print("\nScraping complete.")

if __name__ == '__main__':
    main()