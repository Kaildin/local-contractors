import argparse
import logging
import csv
import time
import random
from pathlib import Path

from src.scraper import search_contractors
from src.niches import NICHES


logger = logging.getLogger(__name__)


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


def get_max_results(popolazione: int, lang: str = "en") -> int:
    """
    Adatta max_results alla dimensione della citta'.
    Per il mercato US le soglie di popolazione sono piu' alte.
    Google Maps non mostra piu' di ~20 risultati per query nella
    lista laterale, quindi 50 e' il massimo utile in ogni caso.
    """
    if lang == "en":  # US
        if popolazione < 50_000:
            return 20
        elif popolazione < 250_000:
            return 30
        elif popolazione < 1_000_000:
            return 40
        else:
            return 50
    else:  # IT
        if popolazione < 5_000:
            return 10
        elif popolazione < 20_000:
            return 20
        elif popolazione < 100_000:
            return 30
        else:
            return 50


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
    parser.add_argument("--scroll-times", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-http-check", action="store_true")
    parser.add_argument(
        "--output", default="output/batch_results.csv",
        help="CSV output (salvataggio incrementale, supporta resume)"
    )
    parser.add_argument(
        "--pause-min", type=float, default=5.0,
        help="Pausa minima in secondi tra una citta' e l'altra (anti-ban)"
    )
    parser.add_argument(
        "--pause-max", type=float, default=15.0,
        help="Pausa massima in secondi tra una citta' e l'altra (anti-ban)"
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

    # Validazione nicchie
    keywords = build_keywords(args.nicchie)
    if not keywords:
        raise SystemExit(
            "Nessuna keyword trovata. Nicchie disponibili:\n"
            + "\n".join(f"  - {n[0]}" for n in NICHES)
        )

    # Carica citta'
    cities_list = load_cities(args.input, state_filter=args.state, lang=args.lang)
    if not cities_list:
        raise SystemExit("Nessuna citta' trovata nel CSV con i filtri specificati.")

    out_path = args.output
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    done_pairs = get_already_completed(out_path)

    total = len(cities_list)
    print(f"\n{'='*60}")
    print(f"BATCH SCRAPING")
    print(f"  Citta' da processare  : {total}")
    print(f"  Nicchie               : {args.nicchie}")
    print(f"  Keywords              : {keywords}")
    print(f"  Lingua/mercato        : {args.lang.upper()}")
    print(f"  Filtro stato/prov.    : {args.state or 'tutti'}")
    print(f"  Output CSV            : {out_path}")
    print(f"  Headless              : {args.headless}")
    print(f"  Pausa tra citta'      : {args.pause_min}-{args.pause_max}s")
    print(f"{'='*60}\n")

    total_leads = 0

    for idx, entry in enumerate(cities_list, 1):
        city = entry["city"]
        state = entry["state"]
        population = entry["population"]
        max_results = get_max_results(population, lang=args.lang)

        # Resume: salta se tutte le keyword sono gia' nel CSV
        keywords_da_fare = [
            kw for kw in keywords
            if (city.lower(), kw.lower()) not in done_pairs
        ]
        if not keywords_da_fare:
            logger.info(f"[{idx}/{total}] {city} — gia' completato, saltato.")
            continue

        print(f"[{idx}/{total}] {city}, {state} (pop. {population:,} | max_results={max_results})")

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
            )
            n = len(results)
            total_leads += n
            print(f"  -> {n} lead trovati (totale cumulativo: {total_leads})")

            for kw in keywords:
                done_pairs.add((city.lower(), kw.lower()))

        except Exception as e:
            logger.error(f"[{idx}/{total}] Errore su {city}: {e}")
            print(f"  -> ERRORE: {e} — continuo con la prossima citta'")

        if idx < total:
            pause = random.uniform(args.pause_min, args.pause_max)
            logger.info(f"Pausa {pause:.1f}s prima della prossima citta'...")
            time.sleep(pause)

    print(f"\n{'='*60}")
    print(f"COMPLETATO — {total_leads} lead totali salvati in: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
