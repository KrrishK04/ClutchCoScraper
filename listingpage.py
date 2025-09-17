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
OUTPUT_FILE = 'clutch_listings_data.jsonl'
# Set how many pages you want to scrape.
# Page 1 is the start, so 10 will scrape pages 1 through 10.
PAGES_TO_SCRAPE = 150

def main():
    """Main function to control the entire scraping process."""
    print("Setting up the Undetected Chrome WebDriver with Stealth...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options, use_subprocess=True)

    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    print("WebDriver is ready.")

    # Clear the output file before starting
    with open(OUTPUT_FILE, 'w') as f:
        pass

    total_scraped_companies = 0

    # Loop through the desired number of pages by constructing the URL
    # We start the loop from 0. Page 0 is the base URL, page 1 is ?page=1, etc.
    for page_num in range(PAGES_TO_SCRAPE):
        print("-" * 20)

        # Construct the URL based on the page number
        if page_num == 0:
            # The first page (page 0 in the loop) has no "?page=" parameter
            current_url = BASE_URL
        else:
            current_url = f"{BASE_URL}?page={page_num}"

        print(f"Scraping listings page #{page_num + 1}: {current_url}")
        driver.get(current_url)

        # Give the page a moment to load, especially the first one
        if page_num == 0:
            print("  - Waiting for initial Cloudflare challenge...")
            time.sleep(10)
        else:
            # Use a shorter, random wait for subsequent pages
            time.sleep(random.uniform(5, 8))

        try:
            # Wait for the list of companies to be present on the page
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.provider-list-item'))
            )
            print("  - Page content is loaded.")

            soup = BeautifulSoup(driver.page_source, 'lxml')
            companies_on_page = []
            companies = soup.select('li.provider-list-item')

            if not companies:
                print("  - No companies found. This might be the last page. Ending scrape.")
                break

            # Extract data from each company card on the page
            for company in companies:
                name_tag = company.select_one('h3.provider__title a')
                tagline_tag = company.select_one('.provider__tagline')
                location_tag = company.select_one('.locality')
                hourly_rate_tag = company.select_one('.hourly-rate')
                min_project_tag = company.select_one('.min-project-size')
                team_size_tag = company.select_one('.employees-count')
                website_tag = company.select_one('a.website-link__item')

                # Construct the full profile URL correctly
                profile_url = 'N/A'
                if name_tag and name_tag.has_attr('href'):
                    href = name_tag['href']
                    if href.startswith('/'):
                        profile_url = "https://clutch.co" + href
                    else:
                        profile_url = href

                company_data = {
                    'name': name_tag.text.strip() if name_tag else 'N/A',
                    'profile_url': profile_url,
                    'tagline': tagline_tag.text.strip() if tagline_tag else 'N/A',
                    'location': location_tag.text.strip() if location_tag else 'N/A',
                    'hourly_rate': hourly_rate_tag.text.strip() if hourly_rate_tag else 'N/A',
                    'min_project_size': min_project_tag.text.strip() if min_project_tag else 'N/A',
                    'team_size': team_size_tag.text.strip() if team_size_tag else 'N/A',
                    'website': website_tag['href'] if website_tag and website_tag.has_attr('href') else 'N/A'
                }
                companies_on_page.append(company_data)

            print(f"  - Scraped {len(companies_on_page)} companies from this page.")

            # Save data from the current page immediately
            if companies_on_page:
                with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                    for entry in companies_on_page:
                        json.dump(entry, f, ensure_ascii=False)
                        f.write('\n')
                total_scraped_companies += len(companies_on_page)
                print(f"  - Saved data. Total companies saved: {total_scraped_companies}")

        except TimeoutException:
            print("  - Page timed out or content not found. Ending scrape.")
            break
        except Exception as e:
            print(f"  - A critical error occurred, ending scrape: {e}")
            break

    driver.quit()
    print(f"\nScraping complete. Total companies saved to {OUTPUT_FILE}: {total_scraped_companies}")

if __name__ == '__main__':
    main()