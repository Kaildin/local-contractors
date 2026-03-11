import os
import time
import logging
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.niches import NICHES
from src.scraper import search_contractors

load_dotenv()
logging.basicConfig(level=logging.INFO)

APP_TITLE = "🔧 Local Contractors Finder"

st.set_page_config(page_title=APP_TITLE, page_icon="🔧", layout="wide")
st.title(APP_TITLE)
st.caption("Trova artigiani locali senza sito web reale e con poche recensioni Google (1–15) — motore: Selenium")

# ── Sidebar ───────────────────────────────────────────────────
st.sidebar.header("⚙️ Impostazioni")

st.sidebar.markdown("### 🔍 Filtri")
min_reviews = st.sidebar.number_input("Recensioni minime", min_value=0, value=1, step=1)
max_reviews = st.sidebar.number_input("Recensioni massime", min_value=1, value=15, step=1)

st.sidebar.markdown("### 🌐 Filtro sito web")
check_alive = st.sidebar.toggle(
    "Verifica che il sito sia attivo (HTTP check)",
    value=True,
    help="Se attivo controlla che il sito non risponda. I social vengono sempre bloccati.",
)
st.sidebar.caption(
    "⚠️ Facebook, Instagram, TikTok, PagineGialle, TripAdvisor ecc. "
    "vengono sempre scartati."
)

st.sidebar.markdown("### 🦠 Selenium")
headless = st.sidebar.toggle("Headless (Chrome invisibile)", value=True)
scroll_times = st.sidebar.slider(
    "Scroll risultati Maps",
    min_value=2, max_value=15, value=5,
    help="Quante volte scrolla la lista risultati: più scroll = più attività trovate, ma più lento."
)

output_dir = Path(st.sidebar.text_input("Cartella output", value=str(Path.cwd() / "output")))
output_dir.mkdir(parents=True, exist_ok=True)

# ── Main ───────────────────────────────────────────────────
st.subheader("1️⃣ Comuni")
col1, col2 = st.columns([2, 1])
with col1:
    comuni_text = st.text_area(
        "Inserisci i comuni (uno per riga)",
        height=140,
        placeholder="Roma\nMilano\nNapoli",
    )
with col2:
    comuni_file = st.file_uploader(
        "Oppure carica CSV con colonna 'comune'",
        type=["csv", "xlsx"],
    )

st.subheader("2️⃣ Nicchie artigianali")
niche_labels = [n[0] for n in NICHES]
selected = st.multiselect(
    "Seleziona le categorie da cercare",
    options=niche_labels,
    default=niche_labels[:3],
)

run = st.button("🚀 Avvia ricerca", type="primary")

if run:
    # Costruisce lista comuni
    if comuni_file is not None:
        if comuni_file.name.lower().endswith(".csv"):
            df_comuni = pd.read_csv(comuni_file)
        else:
            df_comuni = pd.read_excel(comuni_file)
        comuni_list = (
            df_comuni["comune"].dropna().tolist()
            if "comune" in df_comuni.columns else []
        )
    else:
        comuni_list = [c.strip() for c in comuni_text.splitlines() if c.strip()]

    if not comuni_list:
        st.error("Nessun comune valido trovato.")
        st.stop()

    keywords_per_niche = {n[0]: n[1] for n in NICHES}
    all_keywords = []
    for label in selected:
        all_keywords.extend(keywords_per_niche.get(label, []))

    if not all_keywords:
        st.error("Seleziona almeno una nicchia.")
        st.stop()

    st.info(
        f"Cercando in **{len(comuni_list)}** comuni · **{len(selected)}** nicchie · "
        f"Selenium headless: **{'sì' if headless else 'no'}** · "
        f"Scroll x{scroll_times}"
    )

    progress   = st.progress(0)
    status_box = st.empty()
    all_results = []

    for i, comune in enumerate(comuni_list):
        status_box.markdown(f"⏳ Scansionando **{comune}** ({i+1}/{len(comuni_list)})…")
        results = search_contractors(
            comune=comune,
            keywords=all_keywords,
            min_reviews=int(min_reviews),
            max_reviews=int(max_reviews),
            check_website_alive=bool(check_alive),
            headless=bool(headless),
            scroll_times=int(scroll_times),
        )
        all_results.extend(results)
        progress.progress((i + 1) / len(comuni_list))

    status_box.empty()
    progress.empty()

    if not all_results:
        st.warning(
            "Nessun risultato trovato. Prova ad aumentare gli scroll o allargare le nicchie."
        )
    else:
        df = pd.DataFrame(all_results)
        cols = ["nome", "telefono", "orario", "google_maps",
                "comune", "keyword", "num_recensioni", "sito_google"]
        df = df[[c for c in cols if c in df.columns]]

        st.success(
            f"✅ Trovati **{len(df)}** artigiani senza sito reale "
            f"con {min_reviews}–{max_reviews} recensioni!"
        )
        st.dataframe(
            df,
            column_config={
                "google_maps": st.column_config.LinkColumn("📍 Google Maps"),
            },
            use_container_width=True,
        )

        ts_name    = f"local_contractors_{int(time.time())}.csv"
        final_path = output_dir / ts_name
        df.to_csv(final_path, index=False)

        st.download_button(
            label="⬇️ Scarica CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=ts_name,
            mime="text/csv",
        )
        st.caption(f"Salvato anche in: `{final_path}`")
