"""
src/parallel_worker.py

Worker function designed to run inside a *separate OS process*.
Each worker owns its own Chrome / WebDriver instance, which is the
only safe way to parallelise Selenium (no shared driver, no threads
talking to the same browser, no GIL contention).

Usage: called internally by run_batch.py when --workers > 1.
Do NOT import this module at the top level of run_batch.py;
the import happens inside the worker function to avoid forking
already-initialised Chrome handles.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def worker_scrape_cities(
    city_entries: List[Dict[str, Any]],
    keywords: List[str],
    *,
    lang: str = "en",
    headless: bool = True,
    scroll_times: int = 30,
    min_reviews: int = 1,
    max_reviews: int = 100,
    check_website_alive: bool = True,
    debug_screenshot: bool = False,
    output_csv: Optional[str] = None,
    worker_id: int = 0,
) -> List[Dict[str, Any]]:
    """
    Process a list of city entries serially, each with its own fresh driver.

    Parameters
    ----------
    city_entries : list of dicts with keys 'city', 'state', 'population'
    keywords     : list of keyword strings
    worker_id    : integer label used only in log messages

    Returns
    -------
    Flat list of lead dicts collected across all cities in this chunk.
    """
    # Local imports so that Chrome is only initialised inside the spawned
    # process, never in the parent that calls ProcessPoolExecutor.
    from src.scraper import search_contractors, get_max_results  # noqa: PLC0415
    from src.driver_utils import cleanup_chrome_tmp              # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [W{worker_id}][%(levelname)s] %(name)s: %(message)s",
    )

    all_results: List[Dict[str, Any]] = []

    for entry in city_entries:
        city       = entry["city"]
        state      = entry["state"]
        population = entry["population"]
        max_results = get_max_results(population, lang=lang)

        logger.info(f"[W{worker_id}] Scraping '{city}' ({state}) – max_results={max_results}")
        try:
            results = search_contractors(
                comune=city,
                keywords=keywords,
                min_reviews=min_reviews,
                max_reviews=max_reviews,
                check_website_alive=check_website_alive,
                headless=headless,
                scroll_times=scroll_times,
                max_results=max_results,
                output_csv=output_csv,
                lang=lang,
                state=state,
                debug_screenshot=debug_screenshot,
            )
            logger.info(f"[W{worker_id}] '{city}' -> {len(results)} lead")
            all_results.extend(results)
        except Exception:
            logger.error(
                f"[W{worker_id}] Errore su '{city}': {traceback.format_exc()}"
            )

    # Final Chrome temp cleanup for this process
    try:
        cleanup_chrome_tmp()
    except Exception:
        pass

    return all_results
