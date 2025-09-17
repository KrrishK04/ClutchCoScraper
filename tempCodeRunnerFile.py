import time
import json
import re
import random
import os
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from selenium_stealth import stealth

# --- Configuration ---
START_URL = "https://clutch.co/it-services/india"
OUTPUT_FILE = "clutch_full_profiles_final.jsonl"
PROFILE_URLS_FILE = "profile_urls.json"
LISTING_PAGES_TO_SCRAPE = 115
SETTLE_WAIT = 2   # seconds to wait after navigation


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def scrape_company_profile(driver, profile_url):
    print(f"\n  -> Scraping profile: {profile_url}")
    driver.get(profile_url)
    company_data = {"profile_url": profile_url}

    try:
        time.sleep(SETTLE_WAIT)

        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".profile-header")))
        soup = BeautifulSoup(driver.page_source, "lxml")

        # Name
        name_tag = soup.select_one("h1.profile-header__title")
        company_data["name"] = name_tag.get_text(strip=True) if name_tag else "N/A"

        # Summary
        summary_tag = soup.select_one(".profile-summary__text")
        company_data["summary_description"] = (
            summary_tag.get_text(separator="\n", strip=True) if summary_tag else "N/A"
        )

        # Website
        website_tag = soup.select_one("ul.profile-short-actions a[title='Visit website']")
        company_data["website"] = (
            website_tag["href"] if website_tag and website_tag.has_attr("href") else "N/A"
        )

        # Locations
        locations = []
        locations_modal = soup.select_one("#profile-locations-modal")
        if locations_modal:
            for loc_item in locations_modal.select(".profile-modal--list li"):
                locations.append(loc_item.text.strip())
        company_data["locations"] = locations

        # Languages
        languages = []
        language_modal = soup.select_one("#profile-languages-modal")
        if language_modal:
            for lang_item in language_modal.select(".profile-modal--list li"):
                languages.append(lang_item.text.strip())
        company_data["languages"] = languages

        # Chart Data
        service_lines, focus_areas, industries, clients = [], [], [], []
        script_tag = soup.find("script", string=lambda t: t and "window.chartPie" in t)
        if script_tag:
            chart_json_match = re.search(r"window\.chartPie\s*=\s*({.*?});", script_tag.string, re.DOTALL)
            if chart_json_match:
                try:
                    chart_data = json.loads(chart_json_match.group(1))
                    if "service_provided" in chart_data and "slices" in chart_data["service_provided"]:
                        service_lines = [
                            f"{s.get('name', '')}: {s.get('percent', 0) * 100:.1f}%"
                            for s in chart_data["service_provided"]["slices"]
                        ]
                    if "industries" in chart_data and "slices" in chart_data["industries"]:
                        industries = [
                            f"{s.get('name', '')}: {s.get('percent', 0) * 100:.1f}%"
                            for s in chart_data["industries"]["slices"]
                        ]
                    if "clients" in chart_data and "slices" in chart_data["clients"]:
                        clients = [
                            f"{s.get('name', '')}: {s.get('percent', 0) * 100:.1f}%"
                            for s in chart_data["clients"]["slices"]
                        ]
                    if "focus" in chart_data and "charts" in chart_data["focus"]:
                        for focus_category, focus_data in chart_data["focus"]["charts"].items():
                            if "slices" in focus_data:
                                category_name = focus_data.get("legend_title", focus_category)
                                focus_details = [
                                    f"{s.get('name', '')}: {s.get('percent', 0) * 100:.1f}%"
                                    for s in focus_data["slices"]
                                ]
                                focus_areas.append({category_name: focus_details})
                except json.JSONDecodeError:
                    print("    - Could not parse chart data JSON.")

        company_data["service_lines"] = service_lines
        company_data["focus_breakdown"] = focus_areas
        company_data["industries_focus"] = industries
        company_data["client_focus"] = clients

        # Pricing Snapshot
        pricing_snapshot = {}
        pricing_section = soup.select_one("#pricing-snapshot")
        if pricing_section:
            common_size_tag = pricing_section.select_one("#common-project-size-value")
            pricing_snapshot["most_common_project_size"] = (
                common_size_tag.text.strip() if common_size_tag else "N/A"
            )
            feedback_tag = pricing_section.select_one(".pricing-snapshot__clients-feedback-description")
            pricing_snapshot["client_feedback_summary"] = (
                feedback_tag.text.strip() if feedback_tag else "N/A"
            )
        company_data["pricing_snapshot"] = pricing_snapshot

        return company_data

    except Exception as e:
        print(f"  - Error on profile {profile_url}: {e}")
        return None


def collect_profile_urls(driver, existing_urls):
    print("Collecting profile URLs from listing pages...")
    profile_urls = list(existing_urls)
    page_count = len(existing_urls) // 20 + 1  # ~20 per page

    driver.get(START_URL)
    if page_count == 1:
        print("Solve captcha if shown... waiting 15s.")
        time.sleep(15)

    while page_count <= LISTING_PAGES_TO_SCRAPE:
        print(f"  -> Page {page_count}")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.provider-list-item h3.provider__title a"))
            )
            soup = BeautifulSoup(driver.page_source, "lxml")
            links = soup.select("li.provider-list-item h3.provider__title a")
            for link in links:
                if link.has_attr("href"):
                    href = link["href"]
                    full_url = "https://clutch.co" + href if href.startswith("/") else href
                    if full_url not in profile_urls:
                        profile_urls.append(full_url)

            # next page
            current_url = driver.current_url
            try:
                next_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Next"))
                )
                driver.execute_script("arguments[0].click();", next_button)
                WebDriverWait(driver, 10).until(EC.url_changes(current_url))
            except:
                print("  - No more pages.")
                break

            page_count += 1
            time.sleep(random.uniform(2, 4))

        except Exception as e:
            print(f"  - Error while collecting on page {page_count}: {e}")
            break

    save_json(PROFILE_URLS_FILE, profile_urls)
    print(f"Collected {len(profile_urls)} total profile URLs.")
    return profile_urls


def main():
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options, use_subprocess=True)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")

    # Load cached URLs
    profile_urls = load_json(PROFILE_URLS_FILE)
    if profile_urls:
        print(f"Using cached URLs from {PROFILE_URLS_FILE} ({len(profile_urls)} urls).")
    else:
        profile_urls = collect_profile_urls(driver, [])

    # Load already scraped data
    scraped_data = load_jsonl(OUTPUT_FILE)
    scraped_urls = {entry["profile_url"] for entry in scraped_data}
    print(f"Resuming: {len(scraped_urls)} already scraped.")

    # Scrape missing
    new_count = 0
    for url in profile_urls:
        if url in scraped_urls:
            continue
        data = scrape_company_profile(driver, url)
        if data:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.write("\n")
            scraped_urls.add(url)
            new_count += 1
            print(f"  --> Saved: {data.get('name')}")

    driver.quit()
    print(f"\nFinished scraping. New saved in this run: {new_count}")
    print("All done.")


if __name__ == "__main__":
    main()
