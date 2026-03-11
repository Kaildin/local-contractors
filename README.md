# 🔧 Local Contractors Finder

Trova piccole realtà artigianali locali (imbianchini, idraulici, elettricisti, toelettatori, ecc.) che:
- **NON hanno un sito web**
- Hanno **pochissime recensioni su Google (1-15)**

## Output per ogni attività trovata
- Nome attività
- Numero di telefono
- Orario di apertura
- Link alla pagina Google Maps

## Setup

```bash
pip install -r requirements.txt
```

Crea un file `.env` con la tua Google Places API Key:

```
GOOGLE_PLACES_API_KEY=la_tua_key_qui
```

## Uso

```bash
streamlit run app.py
```

1. Inserisci i **comuni** da cercare
2. Seleziona le **nicchie** (categorie artigiani)
3. Clicca **Avvia ricerca**
4. Scarica il CSV con i risultati

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
