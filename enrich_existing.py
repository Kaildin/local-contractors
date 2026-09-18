"""
Script di arricchimento per CSV esistenti.

Aggiunge email, pertinenza, categoria, confidenza e contatto (admin)
a un CSV già processato con il vecchio local-contractors.

Utilizzo:
    python enrich_existing.py \
        --input output/aziende_esistenti.csv \
        --output output/aziende_arricchite.csv \
        --industry fotovoltaico

Opzioni:
    --input      Percorso del CSV di input (obbligatorio)
    --output     Percorso del CSV di output (default: output/aziende_arricchite.csv)
    --industry   Settore per l'analisi di pertinenza (default: fotovoltaico)
    --skip-admin Salta la ricerca admin via DeepSeek (più veloce, senza API)
    --max-workers Numero massimo di thread per il parallelismo (default: 5)
"""

import argparse
import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

# Importa le funzioni di arricchimento
from src.scraper import (
    _extract_emails_from_website,
    _filter_valid_emails,
    _is_big_company,
)

try:
    from outreach_saas.analysis.relevance_analyzer import WebsiteRelevanceAnalyzer
    from outreach_saas.scraping.ddg_search_improved import ddg_search_improved
    from outreach_saas.scraping.deepseek_extractor import extract_admin_with_deepseek
    OUTREACH_AVAILABLE = True
except ImportError as e:
    OUTREACH_AVAILABLE = False
    logging.warning(f"Outreach SaaS modules not available: {e}. Admin search disabled.")

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("enrich_existing.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Campi aggiuntivi per il CSV arricchito
NEW_FIELDS = ["email", "linkedin", "pertinenza", "categoria", "confidenza_analisi", "contatto"]


def load_existing_csv(input_path: str) -> List[Dict]:
    """Carica il CSV esistente"""
    rows = []
    path = Path(input_path)
    
    if not path.exists():
        logger.error(f"File non trovato: {input_path}")
        return rows
    
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        logger.info(f"Caricate {len(rows)} righe da {input_path}")
    except Exception as e:
        logger.error(f"Errore lettura CSV: {e}")
    
    return rows


def enrich_row(row: Dict, industry: str, skip_admin: bool = False) -> Dict:
    """Arricchisce una singola riga con email, pertinenza e admin"""
    nome = row.get("nome", row.get("name", "")).strip()
    website = (row.get("sito_web") or row.get("website") or "").strip()
    
    # Salta se non c'è il sito web
    if not website:
        logger.debug(f"Nessun sito web per {nome}, salto arricchimento")
        for field in NEW_FIELDS:
            if field not in row:
                row[field] = ""
        return row
    
    # Salta grandi aziende
    if _is_big_company(nome):
        logger.info(f"Saltata grande impresa: {nome}")
        for field in NEW_FIELDS:
            if field not in row:
                row[field] = ""
        return row
    
    # --- 1. Estrazione email ---
    try:
        emails = _extract_emails_from_website(website)
        filtered_emails = _filter_valid_emails(emails)
        if filtered_emails:
            row["email"] = ", ".join(filtered_emails)
            logger.info(f"Email trovate per {nome}: {len(filtered_emails)}")
        else:
            row["email"] = ""
    except Exception as e:
        logger.error(f"Errore estrazione email per {nome}: {e}")
        row["email"] = ""
    
    # --- 2. Analisi pertinenza ---
    try:
        if OUTREACH_AVAILABLE:
            analyzer = WebsiteRelevanceAnalyzer(industry=industry)
            analysis = analyzer.analyze_website_relevance(website)
            row["pertinenza"] = analysis.get("is_relevant", False)
            row["categoria"] = analysis.get("category", "Sconosciuto")
            row["confidenza_analisi"] = analysis.get("confidence", 0.0)
            logger.info(f"Pertinenza per {nome}: {row['pertinenza']} (categoria: {row['categoria']})")
        else:
            row["pertinenza"] = False
            row["categoria"] = "Sconosciuto"
            row["confidenza_analisi"] = 0.0
    except Exception as e:
        logger.error(f"Errore analisi pertinenza per {nome}: {e}")
        row["pertinenza"] = False
        row["categoria"] = "Sconosciuto"
        row["confidenza_analisi"] = 0.0
    
    # --- 3. Ricerca admin (opzionale) ---
    if not skip_admin and OUTREACH_AVAILABLE:
        try:
            query = f"{nome} amministratore"
            ddg_results = ddg_search_improved(query, max_results=5)
            if ddg_results:
                payload = f"AZIENDA: {nome}\nQUERY: {query}\n\nRISULTATI (DuckDuckGo):\n"
                for i, item in enumerate(ddg_results[:5], 1):
                    payload += (
                        f"\n[{i}] TITOLO: {item.get('title', '')}\n"
                        f"[{i}] SNIPPET: {item.get('snippet', '')}\n"
                        f"[{i}] URL: {item.get('url', '')}"
                    )
                
                admin_name = extract_admin_with_deepseek(payload)
                if admin_name:
                    row["contatto"] = admin_name
                    logger.info(f"Admin trovato per {nome}: {admin_name}")
                else:
                    row["contatto"] = ""
            else:
                row["contatto"] = ""
        except Exception as e:
            logger.error(f"Errore ricerca admin per {nome}: {e}")
            row["contatto"] = ""
    else:
        row["contatto"] = ""
    
    # Inizializza campi linkedin vuoti
    if "linkedin" not in row:
        row["linkedin"] = ""
    
    # Inizializza industry se non presente
    if "industry" not in row:
        row["industry"] = industry
    
    return row


def process_batch(rows: List[Dict], industry: str, skip_admin: bool = False, 
                 max_workers: int = 5) -> List[Dict]:
    """Processa un batch di righe in parallelo"""
    enriched_rows = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(enrich_row, row, industry, skip_admin): idx 
            for idx, row in enumerate(rows)
        }
        
        for future in as_completed(futures):
            try:
                enriched_row = future.result()
                enriched_rows.append(enriched_row)
            except Exception as e:
                logger.error(f"Errore nel processing parallelo: {e}")
    
    return enriched_rows


def save_enriched_csv(rows: List[Dict], output_path: str):
    """Salva il CSV arricchito"""
    if not rows:
        logger.warning("Nessuna riga da salvare")
        return
    
    # Determina tutti i fieldnames
    fieldnames = set()
    for row in rows:
        fieldnames.update(row.keys())
    fieldnames = sorted(fieldnames)
    
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Salvato CSV arricchito: {output_path}")
    except Exception as e:
        logger.error(f"Errore salvataggio CSV: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Arricchisce un CSV esistente con email, pertinenza e admin"
    )
    parser.add_argument('--input', type=str, required=True, 
                       help='Percorso del CSV di input (obbligatorio)')
    parser.add_argument('--output', type=str, default='output/aziende_arricchite.csv',
                       help='Percorso del CSV di output')
    parser.add_argument('--industry', type=str, default='fotovoltaico',
                       help='Settore per l\'analisi di pertinenza (default: fotovoltaico)')
    parser.add_argument('--skip-admin', action='store_true',
                       help='Salta la ricerca admin via DeepSeek')
    parser.add_argument('--max-workers', type=int, default=5,
                       help='Numero massimo di thread (default: 5)')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("ARRICCHIMENTO CSV ESISTENTE")
    logger.info("=" * 60)
    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Industry: {args.industry}")
    logger.info(f"Skip admin: {args.skip_admin}")
    logger.info(f"Max workers: {args.max_workers}")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    # Carica dati esistenti
    existing_rows = load_existing_csv(args.input)
    
    if not existing_rows:
        logger.error("Nessuna riga caricata. Verifica il file di input.")
        return
    
    # Arricchisci in parallelo
    logger.info(f"Arricchimento di {len(existing_rows)} righe...")
    enriched_rows = process_batch(
        existing_rows, 
        industry=args.industry, 
        skip_admin=args.skip_admin,
        max_workers=args.max_workers
    )
    
    # Salva risultato
    save_enriched_csv(enriched_rows, args.output)
    
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("ARRICCHIMENTO COMPLETATO")
    logger.info("=" * 60)
    logger.info(f"Tempo impiegato: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info(f"Righe processate: {len(enriched_rows)}")
    logger.info(f"Output: {args.output}")


if __name__ == "__main__":
    main()
