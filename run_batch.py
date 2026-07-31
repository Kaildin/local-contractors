import argparse
import logging
import csv
import time
import random
import signal
import threading
import os
import sys
from math import ceil
from pathlib import Path

from src.scraper import search_contractors, get_max_results
from src.niches import NICHES


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

stop_event = threading.Event()


def _handle_stop(signum, frame):
    """Handler per SIGINT (Ctrl+C) e SIGTERM (kill)."""
    logger.warning("Segnale ricevuto (%s): stop richiesto, attendi chiusura pulita...", signum)
    stop_event.set()


# Registra handler per i segnali
signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)


def build_keywords(selected_labels):
    niche_map = {label: keywords for label, keywords in NICHES}
    keywords = []
    for label in selected_labels:
        kw = niche_map.get(label)
        if kw:
            keywords.extend(kw)
        else:
            logger.warning(f"Nicchia non trovata: '{label}'")
    return keywords


def load_cities(csv_path: str, state_filter: str = None, lang: str = "en"):
    """
    Legge il CSV delle citta'.

    Modalita' US  -> colonne attese: city, state, population
    Modalita' IT  -> colonne attese: comune, provincia, popolazione
    """
    cities = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if lang == "en":
                city = (row.get("city") or "").strip()
                state = (row.get("state") or "").strip()
                try:
                    pop = int(
                        (row.get("population") or "0")
                        .replace(".", "").replace(",", "")
                    )
                except ValueError:
                    pop = 0
            else:
                city = (row.get("comune") or "").strip()
                state = (row.get("provincia") or "").strip()
                try:
                    pop = int(
                        (row.get("popolazione") or "0")
                        .replace(".", "").replace(",", "")
                    )
                except ValueError:
                    pop = 0

            if not city:
                continue
            if state_filter and state.lower() != state_filter.lower():
                continue

            cities.append({
                "city": city,
                "state": state,
                "population": pop,
            })
    return cities


def get_already_completed(output_csv: str) -> set:
    """
    Legge il CSV output esistente e restituisce il set di
    (city.lower, keyword.lower) gia' completati (resume).
    """
    done = set()
    path = Path(output_csv)
    if not path.exists():
        return done
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                city = (
                    row.get("city") or row.get("comune") or ""
                ).strip().lower()
                keyword = (row.get("keyword") or "").strip().lower()
                if city and keyword:
                    done.add((city, keyword))
        logger.info(f"[Resume] {len(done)} (city, keyword) gia' presenti nel CSV.")
    except Exception as e:
        logger.warning(f"[Resume] Errore lettura CSV esistente: {e}")
    return done


def chunk_list(items, n_chunks):
    """Split items into n_chunks roughly equal parts."""
    if n_chunks <= 1:
        return [items]
    size = ceil(len(items) / n_chunks)
    return [items[i: i + size] for i in range(0, len(items), size)]


def run_parallel(
    cities_list,
    keywords,
    n_workers,
    *,
    lang,
    headless,
    scroll_times,
    min_reviews,
    max_reviews,
    check_website_alive,
    debug_screenshot,
    output_csv,
):
    """
    Dispatch city chunks to N separate processes, each owning its Chrome.
    Returns a flat list of all lead dicts.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from src.parallel_worker import worker_scrape_cities

    chunks = chunk_list(cities_list, n_workers)
    actual_workers = len(chunks)          # may be < n_workers if few cities

    logger.info(
        f"[Parallel] Avvio {actual_workers} worker(s) su {len(cities_list)} citta' "
        f"(chunk sizes: {[len(c) for c in chunks]})"
    )
    print(
        f"\n[Parallel] {actual_workers} worker(s) | "
        f"{len(cities_list)} citta' | chunk sizes: {[len(c) for c in chunks]}"
    )

    all_results = []
    worker_processes = []
    executor = None
    
    try:
        with ProcessPoolExecutor(max_workers=actual_workers) as executor:
            futures = {
                executor.submit(
                    worker_scrape_cities,
                    chunk,
                    keywords,
                    lang=lang,
                    headless=headless,
                    scroll_times=scroll_times,
                    min_reviews=min_reviews,
                    max_reviews=max_reviews,
                    check_website_alive=check_website_alive,
                    debug_screenshot=debug_screenshot,
                    output_csv=output_csv,
                    worker_id=idx,
                ): idx
                for idx, chunk in enumerate(chunks)
            }
            
            # Store process PIDs for emergency cleanup
            if hasattr(executor, '_processes'):
                for proc in executor._processes.values():
                    worker_processes.append(proc.pid)
            
            for future in as_completed(futures):
                # Check if stop was requested
                if stop_event.is_set():
                    logger.warning("[Parallel] Stop richiesto, interrompo attesa risultati...")
                    # Cancel all pending futures
                    for f in futures:
                        f.cancel()
                    # Send SIGTERM to all worker processes
                    _send_sigterm_to_workers(worker_processes)
                    break
                    
                wid = futures[future]
                try:
                    chunk_results = future.result()
                    logger.info(f"[Parallel] Worker {wid} completato: {len(chunk_results)} lead")
                    print(f"  [W{wid}] completato -> {len(chunk_results)} lead")
                    all_results.extend(chunk_results)
                except Exception as exc:
                    logger.error(f"[Parallel] Worker {wid} fallito: {exc}")
                    print(f"  [W{wid}] ERRORE: {exc}")
    
    finally:
        # Cleanup: kill any remaining worker processes
        if stop_event.is_set():
            _kill_worker_processes(worker_processes)


def _send_sigterm_to_workers(process_pids):
    """Send SIGTERM to worker processes to request graceful shutdown."""
    for pid in process_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"[Cleanup] Inviato SIGTERM a worker PID={pid}")
        except ProcessLookupError:
            pass  # Process already dead
        except Exception as e:
            logger.warning(f"[Cleanup] Errore invio SIGTERM a {pid}: {e}")


def _kill_worker_processes(process_pids):
    """Kill worker processes and their Chrome children."""
    try:
        import psutil
        for pid in process_pids:
            try:
                proc = psutil.Process(pid)
                # Kill all children first (Chrome processes)
                for child in proc.children(recursive=True):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                # Then kill the worker process
                proc.terminate()
                # Give it a moment to terminate gracefully
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                logger.warning(f"[Cleanup] Errore kill processo {pid}: {e}")
    except ImportError:
        logger.warning("[Cleanup] psutil non disponibile, impossibile killare processi worker")


def _cleanup_chrome_processes():
    """Kill all orphan Chrome/Chromium processes."""
    try:
        import psutil
        chrome_keywords = ['chrome', 'chromium', 'chromedriver']
        killed = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info['name'] or ''
                cmdline = proc.info['cmdline'] or []
                if any(kw in name.lower() for kw in chrome_keywords):
                    # Skip if it's our own process or parent
                    if proc.pid == os.getpid():
                        continue
                    # Check if it's a Chrome process
                    if 'chrome' in name.lower() or 'chromium' in name.lower():
                        try:
                            proc.terminate()
                            killed += 1
                            logger.info(f"[Cleanup] Killato Chrome processo PID={proc.pid}")
                        except psutil.NoSuchProcess:
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed > 0:
            logger.info(f"[Cleanup] Killati {killed} processi Chrome orfani")
    except ImportError:
        logger.debug("[Cleanup] psutil non disponibile per cleanup Chrome")
    except Exception as e:
        logger.warning(f"[Cleanup] Errore durante pulizia Chrome: {e}")


# Register cleanup on exit
def _exit_handler():
    """Cleanup handler called on script exit."""
    if stop_event.is_set():
        logger.warning("Esecuzione interrotta, pulizia processi in corso...")
        _cleanup_chrome_processes()


import atexit
atexit.register(_exit_handler)

import atexit
atexit.register(_exit_handler)


def main():
    parser = argparse.ArgumentParser(
        description="Batch scraper: itera su tutte le citta' di un CSV input."
    )
    parser.add_argument(
        "--input", required=True,
        help=(
            "Path al CSV. "
            "US: colonne city, state, population | "
            "IT: colonne comune, provincia, popolazione"
        )
    )
    parser.add_argument(
        "--nicchie", nargs="+", required=True,
        help="Una o piu' nicchie (es. \"Plumber\" \"Dog Groomer\")"
    )
    parser.add_argument(
        "--lang", default="en", choices=["en", "it"],
        help="Lingua/mercato: en = US (default), it = Italia"
    )
    parser.add_argument(
        "--state", default=None,
        help="Filtra per stato/provincia (es. TX, California). Se omesso scrapa tutto il CSV."
    )
    parser.add_argument("--min-reviews", type=int, default=1)
    parser.add_argument("--max-reviews", type=int, default=100)
    parser.add_argument("--scroll-times", type=int, default=30)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-http-check", action="store_true")
    parser.add_argument(
        "--output", default="output/batch_results.csv",
        help="CSV output (salvataggio incrementale, supporta resume)"
    )
    parser.add_argument(
        "--pause-min", type=float, default=5.0,
        help="Pausa minima in secondi tra citta' (solo modalita' seriale)"
    )
    parser.add_argument(
        "--pause-max", type=float, default=15.0,
        help="Pausa massima in secondi tra citta' (solo modalita' seriale)"
    )
    parser.add_argument(
        "--max-results", type=int, default=None,
        help=(
            "Numero massimo di risultati per citta' (override fisso). "
            "Se omesso, il valore viene calcolato automaticamente "
            "in base alla popolazione della citta' (10-50 a seconda della taglia)."
        )
    )
    parser.add_argument("--debug-screenshot", action="store_true", default=False,
                        help="Salva screenshot SERP per debug")
    parser.add_argument(
        "--workers", type=int, default=1,
        help=(
            "Numero di processi paralleli (default: 1 = seriale). "
            "Ogni worker ha il suo Chrome separato. "
            "Consigliato: 2-3. Ogni istanza Chrome usa ~300-500 MB di RAM."
        )
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    keywords = build_keywords(args.nicchie)
    if not keywords:
        raise SystemExit(
            "Nessuna keyword trovata. Nicchie disponibili:\n"
            + "\n".join(f"  - {n[0]}" for n in NICHES)
        )

    cities_list = load_cities(args.input, state_filter=args.state, lang=args.lang)
    if not cities_list:
        raise SystemExit("Nessuna citta' trovata nel CSV con i filtri specificati.")

    out_path = args.output
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    done_pairs = get_already_completed(out_path)

    # Filter out already-completed cities (resume logic)
    cities_todo = []
    for entry in cities_list:
        city = entry["city"]
        keywords_da_fare = [
            kw for kw in keywords
            if (city.lower(), kw.lower()) not in done_pairs
        ]
        if keywords_da_fare:
            cities_todo.append(entry)
        else:
            logger.info(f"[Resume] '{city}' gia' completato, saltato.")

    total = len(cities_list)
    todo  = len(cities_todo)
    mode  = f"PARALLEL ({args.workers} workers)" if args.workers > 1 else "SERIALE"
    max_results_display = (
        str(args.max_results) if args.max_results is not None
        else "auto (basato su popolazione)"
    )

    print(f"\n{'='*60}")
    print(f"BATCH SCRAPING  [{mode}]")
    print(f"  Citta' totali          : {total}")
    print(f"  Citta' da processare   : {todo}  (saltate: {total - todo})")
    print(f"  Nicchie                : {args.nicchie}")
    print(f"  Keywords               : {keywords}")
    print(f"  Lingua/mercato         : {args.lang.upper()}")
    print(f"  Filtro stato/prov.     : {args.state or 'tutti'}")
    print(f"  Max risultati/citta'   : {max_results_display}")
    print(f"  Recensioni accettate   : {args.min_reviews} - {args.max_reviews}")
    print(f"  Output CSV             : {out_path}")
    print(f"  Headless               : {args.headless}")
    if args.workers <= 1:
        print(f"  Pausa tra citta'       : {args.pause_min}-{args.pause_max}s")
    else:
        print(f"  Workers                : {args.workers}")
    print(f"{'='*60}\n")

    if not cities_todo:
        print("Nessuna citta' da processare (tutte gia' nel CSV). Uscita.")
        return

    # ------------------------------------------------------------------ #
    # PARALLEL MODE                                                        #
    # ------------------------------------------------------------------ #
    if args.workers > 1:
        all_results = run_parallel(
            cities_todo,
            keywords,
            args.workers,
            lang=args.lang,
            headless=args.headless,
            scroll_times=args.scroll_times,
            min_reviews=args.min_reviews,
            max_reviews=args.max_reviews,
            check_website_alive=not args.no_http_check,
            debug_screenshot=args.debug_screenshot,
            output_csv=out_path,
        )
        print(f"\n{'='*60}")
        print(f"COMPLETATO (parallel) — {len(all_results)} lead totali salvati in: {out_path}")
        print(f"{'='*60}\n")
        return

    # ------------------------------------------------------------------ #
    # SERIAL MODE (default, backward-compatible)                           #
    # ------------------------------------------------------------------ #
    total_leads = 0

    for idx, entry in enumerate(cities_todo, 1):
        # --- STOP CHECK ---
        if stop_event.is_set():
            logger.warning("[Serial] Stop richiesto, interrompo dopo questa citta'")
            break
            
        city       = entry["city"]
        state      = entry["state"]
        population = entry["population"]

        if args.max_results is not None:
            max_results = args.max_results
        else:
            max_results = get_max_results(population, lang=args.lang)

        print(f"[{idx}/{todo}] {city}, {state} (pop. {population:,} | max_results={max_results})")

        try:
            results = search_contractors(
                comune=city,
                keywords=keywords,
                min_reviews=args.min_reviews,
                max_reviews=args.max_reviews,
                check_website_alive=not args.no_http_check,
                headless=args.headless,
                scroll_times=args.scroll_times,
                max_results=max_results,
                output_csv=out_path,
                lang=args.lang,
                state=state,
                debug_screenshot=args.debug_screenshot,
            )
            n = len(results)
            total_leads += n
            print(f"  -> {n} lead trovati (totale cumulativo: {total_leads})")

            for kw in keywords:
                done_pairs.add((city.lower(), kw.lower()))

        except Exception as e:
            logger.error(f"[{idx}/{todo}] Errore su {city}: {e}")
            print(f"  -> ERRORE: {e} — continuo con la prossima citta'")

        if idx < todo:
            pause = random.uniform(args.pause_min, args.pause_max)
            logger.info(f"Pausa {pause:.1f}s prima della prossima citta'...")
            time.sleep(pause)

    print(f"\n{'='*60}")
    print(f"COMPLETATO (seriale) — {total_leads} lead totali salvati in: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
