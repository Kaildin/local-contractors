import argparse
import logging
import pandas as pd
from pathlib import Path

from src.scraper import search_contractors
from src.niches import NICHES


def build_keywords(selected_labels):
    niche_map = {label: keywords for label, keywords in NICHES}
    keywords = []
    for label in selected_labels:
        keywords.extend(niche_map.get(label, []))
    return keywords


def main():
    parser = argparse.ArgumentParser(description="Local Contractors CLI debug runner")
    parser.add_argument("--comune", required=True)
    parser.add_argument("--nicchie", nargs="+", required=True)
    parser.add_argument("--min-reviews", type=int, default=1)
    parser.add_argument("--max-reviews", type=int, default=15)
    parser.add_argument("--scroll-times", type=int, default=5)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-http-check", action="store_true")
    parser.add_argument("--output", default="output/debug_run.csv")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
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

    print(f"\nComune: {args.comune}")
    print(f"Keywords: {keywords}")
    print(f"Recensioni: {args.min_reviews}-{args.max_reviews}")
    print(f"Headless: {args.headless} | HTTP check: {not args.no_http_check} | Scroll: {args.scroll_times}\n")

    results = search_contractors(
        comune=args.comune,
        keywords=keywords,
        min_reviews=args.min_reviews,
        max_reviews=args.max_reviews,
        check_website_alive=not args.no_http_check,
        headless=args.headless,
        scroll_times=args.scroll_times,
    )

    print(f"\n{'='*60}")
    print(f"RISULTATI: {len(results)}")
    print(f"{'='*60}\n")

    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.get('nome', '')}")
        print(f"    comune:      {r.get('comune', '')}")
        print(f"    keyword:     {r.get('keyword', '')}")
        print(f"    telefono:    {r.get('telefono', '')}")
        orario = r.get('orario', '')
        print(f"    orario:      {orario[:80]}..." if len(orario) > 80 else f"    orario:      {orario}")
        print(f"    recensioni:  {r.get('num_recensioni', '')}")
        print(f"    sito_google: {r.get('sito_google', '')}")
        print(f"    maps:        {r.get('google_maps', '')}")
        print()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(out, index=False)
    print(f"CSV salvato in: {out}")


if __name__ == "__main__":
    main()
