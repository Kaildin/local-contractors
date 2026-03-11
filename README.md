# 🔧 Local Contractors Finder

Trova piccole realtà artigianali locali (imbianchini, idraulici, elettricisti, toelettatori, ecc.) che:
- **NON hanno un sito web reale** (i profili Facebook/Instagram non contano)
- Hanno **pochissime recensioni su Google (1–15)**

**Motore: puro Selenium** — nessuna API key necessaria.

## Output per ogni attività trovata
- Nome attività
- Numero di telefono
- Orario di apertura
- Link diretto alla pagina Google Maps
- Numero recensioni

## Setup

```bash
git clone https://github.com/Kaildin/local-contractors.git
cd local-contractors
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Su Ubuntu assicurati di avere Chrome installato:
> ```bash
> wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
> sudo apt install ./google-chrome-stable_current_amd64.deb
> ```

## Uso

```bash
streamlit run app.py
```

1. Inserisci i **comuni** da cercare
2. Seleziona le **nicchie** (categorie artigiani)
3. Configura i filtri nella sidebar
4. Clicca **Avvia ricerca**
5. Scarica il CSV

## Nicchie disponibili
- Imbianchino / Pittore edile
- Idraulico / Termoidraulico
- Elettricista
- Toelettatore
- Giardiniere
- Falegname
- Piastrellista
- Muratore / Ristrutturazioni
- Fabbro
- Carrozziere

## Filtro sito web
Vengono scartati automaticamente:
- Profili **Facebook, Instagram, TikTok, LinkedIn**
- Directory come **PagineGialle, TripAdvisor, Yelp**
- Siti morti / non raggiungibili (se il toggle HTTP check è attivo)
