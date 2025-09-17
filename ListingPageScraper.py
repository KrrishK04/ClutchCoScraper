import time
import json
import random
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

# --- Selenium Imports for Waiting and Interaction ---
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# --- Import Selenium-Stealth ---
from selenium_stealth import stealth

# --- Configuration ---
BASE_URL = "https://clutch.co/it-services/india"
OUTPUT_FILE = 'clutch_listings_data_raw.jsonl' # Saving to a new file for raw data
PAGES_TO_SCRAPE = 115 # Set how many pages you want to scrape

def parse_company_card(card_soup):
    """
    Parses a single company card (either a featured provider-list-item or a regular provider-list-item)
    and returns a dictionary of its data. This function is designed to handle both card types.
    """
    # This selector works for both featured and regular company titles
    name_tag = card_soup.select_one('h3.provider__title a')
    
    profile_url = 'N/A'
    if name_tag and name_tag.has_attr('href'):
        href = name_tag['href']
        # Construct the full URL correctly
        if href.startswith('/'):
            profile_url = "https://clutch.co" + href
        else:
            # Handle cases where the link might already be absolute (less common but safe to check)
            profile_url = href
            
    # These selectors are designed to be found within the broader 'provider' div
    tagline_tag = card_soup.select_one('.provider__tagline')
    description_tag = card_soup.select_one('.provider__description p') # More specific selector for the description text
    location_tag = card_soup.select_one('.locality')
    hourly_rate_tag = card_soup.select_one('.hourly-rate')
    min_project_tag = card_soup.select_one('.min-project-size')
    team_size_tag = card_soup.select_one('.employees-count')
    website_tag = card_soup.select_one('a.website-link__item')

    company_data = {
        'name': name_tag.text.strip() if name_tag else 'N/A',
        'profile_url': profile_url,
        'tagline': tagline_tag.text.strip() if tagline_tag else 'N/A',
        'description': description_tag.text.strip() if description_tag else 'N/A',
        'location': location_tag.text.strip() if location_tag else 'N/A',
        'hourly_rate': hourly_rate_tag.text.strip() if hourly_rate_tag else 'N/A',
        'min_project_size': min_project_tag.text.strip() if min_project_tag else 'N/A',
        'team_size': team_size_tag.text.strip() if team_size_tag else 'N/A',
        'website': website_tag['href'] if website_tag and website_tag.has_attr('href') else 'N/A'
    }
    return company_data

def main():
    """Main function to control the entire scraping process."""
    print("Setting up the Undetected Chrome WebDriver with Stealth...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options, use_subprocess=True)

    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")
    print("WebDriver is ready.")

    # Clear the output file before starting
    with open(OUTPUT_FILE, 'w') as f:
        pass
        
    total_scraped_companies = 0
    
    for page_num in range(PAGES_TO_SCRAPE):
        print("-" * 20)
        current_url = BASE_URL if page_num == 0 else f"{BASE_URL}?page={page_num}"
        print(f"Scraping listings page #{page_num + 1}: {current_url}")
        driver.get(current_url)

        if page_num == 0:
            print("  - Waiting for initial page load...")
            time.sleep(10)
        else:
            time.sleep(random.uniform(5, 8))

        try:
            # Wait for any provider card to be present, featured or regular
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'li.provider-list-item'))
            )
            print("  - Page content is loaded.")
            soup = BeautifulSoup(driver.page_source, 'lxml')
            
            companies_on_page = []

            # Scrape all providers, which includes both featured and regular listings
            all_providers = soup.select('li.provider-list-item')
            print(f"  - Found {len(all_providers)} total provider entries on the page.")
            for card in all_providers:
                companies_on_page.append(parse_company_card(card))
            
            # --- PERIODIC SAVE (NO DE-DUPLICATION) ---
            if companies_on_page:
                with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                    for entry in companies_on_page:
                        json.dump(entry, f, ensure_ascii=False)
                        f.write('\n')
                total_scraped_companies += len(companies_on_page)
                print(f"  - Saved {len(companies_on_page)} entries. Total saved so far: {total_scraped_companies}")

        except TimeoutException:
            print("  - Page timed out or no providers found. Ending scrape.")
            break
        except Exception as e:
            print(f"  - A critical error occurred, ending collection: {e}")
            break

    driver.quit()
    print("\nBrowser closed.")
    print(f"\nScraping complete. Total entries (including duplicates) saved to {OUTPUT_FILE}: {total_scraped_companies}")

if __name__ == '__main__':
    main()