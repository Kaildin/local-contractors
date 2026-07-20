# local-contractors — US Market

Google Maps scraper for collecting local contractor leads in the **US market**.

This branch is focused only on United States searches and debugging for Google Maps result pages. It is designed to scrape business listings from Google Maps search result pages, open place pages, and extract core lead data such as business name, address, phone number, website, review count, and Maps URL.

## Scope

This branch is dedicated to:

- US-market Google Maps searches
- Result-list scraping for local contractor niches
- SERP screenshot logging during scrolling
- Business detail extraction from Google Maps place pages

Everything outside the US-market workflow is intentionally out of scope for this branch.

## Current behavior

The scraper:

1. Opens a Google Maps search URL for a keyword + location
2. Scrolls the results panel multiple times to load more businesses
3. Saves a screenshot of the Google Maps SERP after each scroll step
4. Collects result candidates from the loaded list
5. Opens each place page
6. Extracts the main business fields
7. Returns structured lead data

## Screenshot behavior

This branch keeps **only SERP screenshots**.

### What is saved

Screenshots are saved for the initial Google Maps results page, for example:

- `landscaper minnesota`
- `roofing contractor texas`
- `plumber miami`

A screenshot is saved after **every scroll step** in the results-loading phase.

### What is not saved

This branch no longer saves:

- debug screenshots from `_navigate_to_place()`
- screenshots of individual business place pages
- screenshots inside `debug/maps_screenshots/`

### Screenshot output path

All screenshots are saved inside:

```bash
debug/
```

### Screenshot filename format

Example format:

```bash
serp_YYYYMMDD_HHMMSS_03_city_keyword.png
```

The filename includes:

- timestamp
- scroll number
- comune / city
- keyword

## Extracted fields

Each scraped business may include:

- `comune`
- `keyword`
- `nome`
- `indirizzo`
- `telefono`
- `sito_web`
- `num_recensioni`
- `maps_url`

## Main scraper flow

The main Selenium flow is centered around:

- `scrape_with_selenium(...)`
- `_scroll_results_panel(...)`
- `_navigate_to_place(...)`
- `_wait_for_place_page(...)`
- `_extract_num_recensioni(...)`

## Key branch-specific changes

US-market branch changes include:

- removal of business-page screenshot saving
- removal of debug screenshots inside `_navigate_to_place()`
- introduction of SERP-only screenshot capture
- screenshot capture after every scroll step
- screenshot output unified under `debug/`

## Usage

Example high-level flow:

```python
results, driver = scrape_with_selenium(
    search_urls=search_urls,
    max_results=20,
    scroll_times=10
)
```

Where each search item typically contains:

```python
{
    "comune": "minnesota",
    "keyword": "landscaper",
    "url": "https://www.google.com/maps/..."
}
```

## Notes

- This branch is optimized for the US-market workflow only.
- If you are working on non-US scraping logic, use another branch.
- Debugging of result loading should be done through the SERP screenshots in `debug/`.

## Repository intent

This branch is meant for:

- local contractor lead generation
- Google Maps result capture
- US-focused scraping tests
- debugging result loading through scroll snapshots
