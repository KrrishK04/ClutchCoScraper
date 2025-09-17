import time
import json
import re
import os
import random
import urllib.parse
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from selenium_stealth import stealth

# ---------- CONFIG ----------
START_URL = "https://clutch.co/it-services/india"
URL_FILE = "profile_urls.json"
OUTPUT_FILE = "clutch_full_profiles_final.jsonl"
LISTING_PAGES_TO_SCRAPE = 115

# Captcha/wait tuning
INITIAL_LONG_WAIT = 20   # seconds — used for first few interactions (captcha)
SHORT_WAIT = 2           # seconds — used after initial interactions
CAPTCHA_PHASE_PAGES = 5  # how many first profile loads use long wait
# --------------------------------

interaction_count = 0

def extract_target_url_from_redirect(href):
    """Return the actual vendor URL from a Clutch redirect href (u=... or provider_website=...)."""
    if not href or not href.startswith("http"):
        return None
    try:
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        # Prefer 'u'
        for key in ("u", "provider_website", "provider_website_encoded"):
            if key in qs and qs[key]:
                return urllib.parse.unquote(qs[key][0])
    except Exception:
        pass
    return None

def smart_settle():
    """Adaptive wait: long for the first few interactions (captcha), then short."""
    global interaction_count
    interaction_count += 1
    if interaction_count <= CAPTCHA_PHASE_PAGES:
        time.sleep(INITIAL_LONG_WAIT)
    else:
        time.sleep(SHORT_WAIT)

def pick_text_multi(soup, selectors):
    """Return first non-empty text from a list of selectors."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            # if contains anchor, prefer anchor text
            a = el.select_one("a")
            return a.get_text(strip=True) if a else el.get_text(strip=True)
    return None

def scrape_company_profile(driver, profile_url, profile_index=None):
    """Scrape a single company profile; returns dict or None."""
    print(f"\n-> [{profile_index}] Scraping: {profile_url}" if profile_index else f"\n-> Scraping: {profile_url}")
    try:
        driver.get(profile_url)
    except Exception as e:
        print("  driver.get() failed:", e)
        return None

    smart_settle()

    try:
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".profile-header, h1.profile-header__title, h1.header-company--title")))

        soup = BeautifulSoup(driver.page_source, "lxml")

        data = {"profile_url": profile_url}

        # Name — multiple fallbacks
        name = pick_text_multi(soup, [
            "h1.profile-header__title",
            "h1.header-company--title",
            "h1[itemprop='name']",
            ".profile-header__title",
            ".profile-header h1"
        ])
        data["name"] = name or "N/A"

        # Summary description
        summary_el = soup.select_one(".profile-summary__text") or soup.select_one("#profile-summary-text")
        if summary_el:
            # combine paragraphs
            paragraphs = [p.get_text(" ", strip=True) for p in summary_el.find_all("p")] or [summary_el.get_text(" ", strip=True)]
            data["summary_description"] = "\n".join([p for p in paragraphs if p]).strip()
        else:
            data["summary_description"] = "N/A"

        # WEBSITE — robust extraction
        website = None

        # 1) Common anchor (visit website)
        # Check in header or quick actions
        a_candidates = []
        header = soup.select_one(".profile-header") or soup.select_one("#profile_header")
        if header:
            a_candidates.extend(header.select("a"))
        # additional candidates across page
        a_candidates.extend(soup.select("a.website-link__item, li.profile-short-actions__item--visit-website a, a[title*='Visit website'], a[aria-label*='website']"))

        # iterate candidates to find a redirect or direct link
        for a in a_candidates:
            href = a.get("href")
            if not href:
                continue
            # If it's a Clutch redirect, parse 'u' or provider_website
            target = extract_target_url_from_redirect(href)
            if target:
                website = target
                break
            # sometimes data-link holds the redirect
            for attr in ("data-link", "data-href", "data-url"):
                if a.has_attr(attr):
                    target = extract_target_url_from_redirect(a[attr])
                    if target:
                        website = target
                        break
            if website:
                break
            # if href looks like a direct site (not clutch redirect), accept it
            parsed = urllib.parse.urlparse(href)
            if parsed.scheme in ("http", "https") and "r.clutch.co" not in parsed.netloc and "clutch.co" not in parsed.netloc:
                website = href
                break

        # 2) fallback: meta[itemprop="sameAs"]
        if not website:
            m = soup.select_one('meta[itemprop="sameAs"]')
            if m and m.get("content"):
                website = m["content"]

        # 3) fallback: meta[itemprop="url"]
        if not website:
            m = soup.select_one('meta[itemprop="url"]')
            if m and m.get("content"):
                website = m["content"]

        # 4) fallback: try regex for u= in page source
        if not website:
            m = re.search(r"[?&]u=([^&\"'>\s]+)", driver.page_source)
            if m:
                website = urllib.parse.unquote(m.group(1))

        data["website"] = website or "N/A"

        # Summary details (min project size, hourly rate, employees, locations)
        summary_details = {}
        summary_section = soup.select_one("#profile-summary")
        if summary_section:
            for li in summary_section.select(".profile-summary__detail"):
                label = li.select_one(".profile-summary__detail-label")
                val = li.select_one(".profile-summary__detail-title")
                if label and val:
                    summary_details[label.get_text(strip=True)] = " ".join(val.get_text(" ", strip=True).split())
        data["summary_details"] = summary_details

        # Languages from modal fallback
        langs = []
        lang_modal = soup.select_one("#profile-languages-modal")
        if lang_modal:
            langs = [li.get_text(strip=True) for li in lang_modal.select(".profile-modal--list li")]
        data["languages"] = langs

        # Locations
        locs = []
        loc_modal = soup.select_one("#profile-locations-modal")
        if loc_modal:
            locs = [li.get_text(strip=True) for li in loc_modal.select(".profile-modal--list li")]
        # Also fallback to summary_details "Locations"
        if not locs and "Locations" in summary_details:
            locs = [summary_details.get("Locations")]
        data["locations"] = locs

        # Chart data: robust parse of window.chartPie or data-chart
        chart_data = None
        script_tag = soup.find("script", string=lambda t: t and "window.chartPie" in t)
        if script_tag and getattr(script_tag, "string", None):
            m = re.search(r"window\.chartPie\s*=\s*(\{.*?\})\s*;", script_tag.string, re.DOTALL)
            if m:
                try:
                    chart_data = json.loads(m.group(1))
                except Exception:
                    chart_data = None

        if not chart_data:
            div = soup.select_one("div[data-chart]")
            if div and div.has_attr("data-chart"):
                try:
                    chart_data = json.loads(div["data-chart"])
                except Exception:
                    chart_data = None

        service_lines, focus_breakdown, industries, clients = [], [], [], []
        if chart_data:
            if chart_data.get("service_provided", {}).get("slices"):
                service_lines = [f"{s.get('name','')}: {s.get('percent',0)*100:.1f}%" for s in chart_data["service_provided"]["slices"]]
            if chart_data.get("industries", {}).get("slices"):
                industries = [f"{s.get('name','')}: {s.get('percent',0)*100:.1f}%" for s in chart_data["industries"]["slices"]]
            if chart_data.get("clients", {}).get("slices"):
                clients = [f"{s.get('name','')}: {s.get('percent',0)*100:.1f}%" for s in chart_data["clients"]["slices"]]
            if chart_data.get("focus", {}).get("charts"):
                for k,v in chart_data["focus"]["charts"].items():
                    if v.get("slices"):
                        title = v.get("legend_title", k)
                        focus_breakdown.append({title: [f"{s.get('name','')}: {s.get('percent',0)*100:.1f}%" for s in v["slices"]]})

        data["service_lines"] = service_lines
        data["focus_breakdown"] = focus_breakdown
        data["industries_focus"] = industries
        data["client_focus"] = clients

        # Pricing snapshot fallback
        pricing_snapshot = {}
        pricing_section = soup.select_one("#pricing-snapshot")
        if pricing_section:
            common_tag = pricing_section.select_one("#common-project-size-value")
            fb_tag = pricing_section.select_one(".pricing-snapshot__clients-feedback-description")
            pricing_snapshot["most_common_project_size"] = common_tag.get_text(strip=True) if common_tag else "N/A"
            pricing_snapshot["client_feedback_summary"] = fb_tag.get_text(strip=True) if fb_tag else "N/A"
        data["pricing_snapshot"] = pricing_snapshot

        print(f"  -> Scraped: name='{data['name']}', website='{data['website']}'")
        return data

    except TimeoutException:
        print("  Timeout waiting for profile DOM. Skipping.")
        return None
    except Exception as e:
        print("  Unexpected error:", e)
        return None

def collect_profile_urls(driver):
    """Collect and cache profile URLs across listing pages; resumable via URL_FILE."""
    if os.path.exists(URL_FILE):
        try:
            with open(URL_FILE, "r", encoding="utf-8") as f:
                urls = json.load(f)
            if isinstance(urls, list) and urls:
                print(f"Using cached URLs from {URL_FILE} ({len(urls)} urls).")
                return urls
        except Exception:
            pass

    print("Collecting listing pages...")
    profile_urls = []
    driver.get(START_URL)
    smart_wait = smart_settle  # alias
    smart_wait()

    page = 1
    while page <= LISTING_PAGES_TO_SCRAPE:
        print(f"  Listing page {page} ...")
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.provider-list-item h3.provider__title a")))
            soup = BeautifulSoup(driver.page_source, "lxml")
            links = soup.select("li.provider-list-item h3.provider__title a")
            added = 0
            for a in links:
                href = a.get("href")
                if href:
                    full = "https://clutch.co" + href if href.startswith("/") else href
                    if full not in profile_urls:
                        profile_urls.append(full)
                        added += 1
            print(f"    found {added} new, total {len(profile_urls)}")
            page += 1
            if page > LISTING_PAGES_TO_SCRAPE:
                break
            # click Next
            try:
                curr = driver.current_url
                nxt = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Next")))
                driver.execute_script("arguments[0].click();", nxt)
                WebDriverWait(driver, 10).until(EC.not_(EC.url_to_be(curr)))
            except Exception as e:
                print("    couldn't click Next:", e)
                break
            smart_wait()
        except Exception as e:
            print("  Error collecting page:", e)
            break

    # save
    with open(URL_FILE, "w", encoding="utf-8") as f:
        json.dump(profile_urls, f, indent=2)
    print(f"Saved {len(profile_urls)} URLs to {URL_FILE}")
    return profile_urls

def scrape_all_profiles(driver, urls):
    """Iterate through urls, skip already-scraped ones (resumable)."""
    existing = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        existing.add(obj.get("profile_url"))
                    except Exception:
                        pass
            print(f"Resuming: {len(existing)} already scraped.")
        except Exception:
            pass

    count = 0
    total = len(urls)
    for idx, url in enumerate(urls, start=1):
        if url in existing:
            continue
        data = scrape_company_profile(driver, url, profile_index=idx)
        if data:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.write("\n")
                f.flush()
            existing.add(url)
            count += 1
        # polite random delay small
        time.sleep(random.uniform(0.8, 1.6))
        # print progress
        if idx % 20 == 0:
            print(f"Progress: {idx}/{total}, saved {count} in this run.")

    print(f"\nFinished scraping. New saved in this run: {count}")

def main():
    print("Launching undetected Chrome (visible). Solve captcha if shown in the first page.")
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    # NOTE: keep visible so you can solve captcha manually:
    # opts.add_argument("--headless=new")  # <-- do NOT enable headless if you need to solve captcha
    driver = uc.Chrome(options=opts, use_subprocess=True)

    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")

    # warm start at listings
    driver.get(START_URL)
    print("Please solve any captcha in the opened browser if present; script will continue after initial wait.")
    time.sleep(5)  # give you a moment; smart_settle will apply longer for first pages

    urls = collect_profile_urls(driver)
    if not urls:
        print("No profile URLs found. Exiting.")
        driver.quit()
        return

    scrape_all_profiles(driver, urls)
    driver.quit()
    print("All done.")

if __name__ == "__main__":
    main()
