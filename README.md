# local-contractors

Scraper Google Maps per la raccolta automatica di contatti locali (nome, indirizzo, telefono, sito web, recensioni) per qualsiasi nicchia e area geografica. Supporta mercato italiano e mercato US/English.

## Funzionalità

- Scraping via Selenium + undetected-chromedriver con bypass della "limited view" di Google Maps
- Supporto multilingua tramite flag `--lang` (`it` / `en`): controlla lingua browser, parametri `hl`/`gl` URL e token sanitizer
- Auto-scroll intelligente della lista risultati: si ferma al segnale di fine lista GMaps o per stallo conteggio risultati
- Flag `--max-results` per limitare il numero di risultati processati per query (stop scroll anticipato se raggiunti)
- Extraction multi-strategia delle recensioni (JSON embedded, aria-label, selettori CSS 2025/2026, body text)
- Deduplicazione per-run ed esportazione CSV / Excel
- Interfaccia Streamlit (`app.py`) e execution batch da CLI (`run_batch.py`)

## Struttura progetto

```
local-contractors/
│
├── app.py                  # Interfaccia Streamlit
├── run.py                  # Entry point CLI uso singolo
├── run_batch.py            # Execution batch multi-città
├── cities_us_sample.csv    # Campione città US per test
├── requirements.txt
└── src/
    ├── __init__.py
    ├── driver_utils.py     # Init Chrome + fingerprint anti-bot
    ├── niches.py           # Lista nicchie per mercato it/en
    ├── scraper.py          # Scraper leggero (test/fallback)
    ├── selenium_scraper.py # Core Selenium scraper
    ├── text_utils.py       # Pulizia testi
    └── website_checker.py  # Verifica siti web
```

## Installazione

```bash
git clone https://github.com/Kaildin/local-contractors.git
cd local-contractors
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Requisito: Google Chrome installato sul sistema. `webdriver-manager` gestisce automaticamente il ChromeDriver.

## Uso

### Interfaccia Streamlit

```bash
streamlit run app.py
```

### CLI - uso singolo

```bash
python run.py --lang it --keyword "idraulico" --comune "Milano"
python run.py --lang en --keyword "plumber" --comune "Austin TX"
```

### CLI - batch multi-città

```bash
python run_batch.py \
  --lang en \
  --keywords "plumber" "electrician" \
  --cities-file cities_us_sample.csv \
  --max-results 20 \
  --output results.xlsx
```

### Opzioni principali

| Flag | Default | Descrizione |
|------|---------|-------------|
| `--lang` | `it` | Lingua scraping: `it` o `en` |
| `--max-results` | `20` | Max risultati per query |
| `--scroll-times` | `30` | Limite massimo scroll (safety cap) |
| `--headless` | `True` | Chrome headless mode |
| `--output` | `results.xlsx` | File output (.xlsx o .csv) |

## Output

Ogni riga del file di output contiene:

| Colonna | Descrizione |
|---------|-------------|
| `comune` | Città della ricerca |
| `keyword` | Nicchia ricercata |
| `nome` | Nome attività |
| `indirizzo` | Indirizzo fisico |
| `telefono` | Telefono |
| `sito_web` | URL sito web |
| `num_recensioni` | Numero recensioni Google Maps |
| `maps_url` | Link scheda Google Maps |

## Dipendenze

- `selenium` >= 4.0
- `undetected-chromedriver` >= 3.5
- `webdriver-manager`
- `streamlit` >= 1.28
- `pandas`
- `requests`

***

## Esempi e tutorial

### Esempio 1 — Raccogliere idraulici a Milano

```bash
python run.py --lang it --keyword "idraulico" --comune "Milano" --max-results 15
```

Output atteso (`results.xlsx`):

| nome | indirizzo | telefono | sito_web | num_recensioni |
|------|-----------|----------|----------|----------------|
| Idraulico Rossi | Via Roma 12, Milano | +39 02 1234567 | www.rossi-idraulica.it | 48 |
| Pronto Intervento Idraulico | Corso Buenos Aires 5, Milano | +39 02 9876543 | — | 12 |

***

### Esempio 2 — Batch elettricisti in 3 città italiane

Crea un file `cities_it.csv`:
```csv
comune
Roma
Milano
Napoli
```

Poi lancia:
```bash
python run_batch.py \
  --lang it \
  --keywords "elettricista" \
  --cities-file cities_it.csv \
  --max-results 20 \
  --output elettricisti_italia.xlsx
```

Il file `elettricisti_italia.xlsx` conterrà fino a 60 righe (20 per città).

***

### Esempio 3 — Batch mercato US, più nicchie

```bash
python run_batch.py \
  --lang en \
  --keywords "plumber" "electrician" "roofer" \
  --cities-file cities_us_sample.csv \
  --max-results 10 \
  --output us_contractors.xlsx
```

Con `cities_us_sample.csv` da 5 città e 3 keyword → fino a 150 righe totali.

***

### Esempio 4 — Modalità visibile (debug)

Se lo scraper non trova risultati o Chrome si comporta in modo strano, lancia senza headless per vedere cosa sta succedendo:

```bash
python run.py --lang it --keyword "pizzeria" --comune "Roma" --headless False
```

***

### Esempio 5 — Interfaccia Streamlit

```bash
streamlit run app.py
```

Si apre nel browser su `http://localhost:8501`. Da lì puoi:
1. Selezionare lingua (`it` / `en`)
2. Inserire keyword e città
3. Avviare lo scraping con un click
4. Scaricare il risultato in Excel direttamente dall'interfaccia
