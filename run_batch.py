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


def get_max_results(popolazione: int) -> int:
    """Adatta max_results alla dimensione del comune."""
    if popolazione < 5_000:
        return 10
    elif popolazione < 20_000:
        return 20
    elif popolazione < 100_000:
        return 30
    else:
        return 50


def load_comuni(csv_path: str, provincia_filter: str = None):
    """
    Legge il CSV dei comuni.
    Colonne attese: comune, provincia, popolazione
    """
    comuni = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comune = (row.get("comune") or "").strip()
            provincia = (row.get("provincia") or "").strip()
            try:
                popolazione = int((row.get("popolazione") or "0").replace(".", "").replace(",", ""))
            except ValueError:
                popolazione = 0

            if not comune:
                continue
            if provincia_filter and provincia.lower() != provincia_filter.lower():
                continue

            comuni.append({
                "comune": comune,
                "provincia": provincia,
                "popolazione": popolazione,
            })
    return comuni


def get_already_completed_comuni(output_csv: str) -> set:
    """
    Legge il CSV output esistente e restituisce il set di
    (comune.lower, keyword.lower) gia' completati.
    Usato per il resume: se un comune e' gia' stato scrapato
    per TUTTE le keyword della nicchia, viene saltato.
    """
    done = set()
    path = Path(output_csv)
    if not path.exists():
        return done
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                comune = (row.get("comune") or "").strip().lower()
                keyword = (row.get("keyword") or "").strip().lower()
                if comune and keyword:
                    done.add((comune, keyword))
        logger.info(f"[Resume] {len(done)} (comune, keyword) gia' presenti nel CSV.")
    except Exception as e:
        logger.warning(f"[Resume] Errore lettura CSV esistente: {e}")
    return done


def main():
    parser = argparse.ArgumentParser(
        description="Batch scraper: itera su tutti i comuni di un CSV input."
    )
    parser.add_argument(
        "--input", required=True,
        help="Path al CSV con colonne: comune, provincia, popolazione"
    )
    parser.add_argument(
        "--nicchie", nargs="+", required=True,
        help="Una o piu' nicchie (es. \"Imbianchino / Pittore edile\")"
    )
    parser.add_argument(
        "--provincia", default=None,
        help="Filtra per provincia (es. Roma). Se omesso, scrapa tutto il CSV."
    )
    parser.add_argument("--min-reviews", type=int, default=1)
    parser.add_argument("--max-reviews", type=int, default=15)
    parser.add_argument("--scroll-times", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-http-check", action="store_true")
    parser.add_argument(
        "--output", default="output/batch_results.csv",
        help="CSV output (salvataggio incrementale, supporta resume)"
    )
    parser.add_argument(
        "--pause-min", type=float, default=5.0,
        help="Pausa minima in secondi tra un comune e l'altro (anti-ban)"
    )
    parser.add_argument(
        "--pause-max", type=float, default=15.0,
        help="Pausa massima in secondi tra un comune e l'altro (anti-ban)"
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

    # Carica comuni
    comuni_list = load_comuni(args.input, provincia_filter=args.provincia)
    if not comuni_list:
        raise SystemExit("Nessun comune trovato nel CSV con i filtri specificati.")

    out_path = args.output
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # Resume: carica (comune, keyword) gia' presenti
    done_pairs = get_already_completed_comuni(out_path)

    total = len(comuni_list)
    print(f"\n{'='*60}")
    print(f"BATCH SCRAPING")
    print(f"  Comuni da processare : {total}")
    print(f"  Nicchie              : {args.nicchie}")
    print(f"  Keywords             : {keywords}")
    print(f"  Provincia filtro     : {args.provincia or 'tutte'}")
    print(f"  Output CSV           : {out_path}")
    print(f"  Headless             : {args.headless}")
    print(f"  Pausa tra comuni     : {args.pause_min}-{args.pause_max}s")
    print(f"{'='*60}\n")

    total_leads = 0

    for idx, entry in enumerate(comuni_list, 1):
        comune = entry["comune"]
        popolazione = entry["popolazione"]
        max_results = get_max_results(popolazione)

        # Resume: salta il comune se TUTTE le sue keyword sono gia' nel CSV
        keywords_da_fare = [
            kw for kw in keywords
            if (comune.lower(), kw.lower()) not in done_pairs
        ]
        if not keywords_da_fare:
            logger.info(f"[{idx}/{total}] {comune} — gia' completato, saltato.")
            continue

        print(f"[{idx}/{total}] {comune} (pop. {popolazione:,} | max_results={max_results})")

        try:
            results = search_contractors(
                comune=comune,
                keywords=keywords,  # passa tutte, la dedup interna gestisce
                min_reviews=args.min_reviews,
                max_reviews=args.max_reviews,
                check_website_alive=not args.no_http_check,
                headless=args.headless,
                scroll_times=args.scroll_times,
                max_results=max_results,
                output_csv=out_path,
            )
            n = len(results)
            total_leads += n
            print(f"  -> {n} lead trovati (totale cumulativo: {total_leads})")

            # Aggiorna done_pairs con le keyword appena processate
            for kw in keywords:
                done_pairs.add((comune.lower(), kw.lower()))

        except Exception as e:
            logger.error(f"[{idx}/{total}] Errore su {comune}: {e}")
            print(f"  -> ERRORE: {e} — continuo con il prossimo comune")

        # Pausa anti-ban tra un comune e l'altro
        if idx < total:
            pause = random.uniform(args.pause_min, args.pause_max)
            logger.info(f"Pausa {pause:.1f}s prima del prossimo comune...")
            time.sleep(pause)

    print(f"\n{'='*60}")
    print(f"COMPLETATO — {total_leads} lead totali salvati in: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
