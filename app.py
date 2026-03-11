import os
import sys
import time
import io
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.niches import NICHES
from src.scraper import search_contractors

load_dotenv()

APP_TITLE = "🔧 Local Contractors Finder"

st.set_page_config(page_title=APP_TITLE, page_icon="🔧", layout="wide")
st.title(APP_TITLE)
st.caption("Trova artigiani locali senza sito web e con pochissime recensioni Google (1–15)")

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Impostazioni")

google_api = st.sidebar.text_input(
    "Google Places API Key",
    value=os.getenv("GOOGLE_PLACES_API_KEY", ""),
    type="password",
    help="Richiesta per Nearby Search + Details.",
)

st.sidebar.markdown("---")
min_reviews = st.sidebar.number_input("Recensioni minime", min_value=0, value=1, step=1)
max_reviews = st.sidebar.number_input("Recensioni massime", min_value=1, value=15, step=1)
radius_km   = st.sidebar.slider("Raggio ricerca (km)", min_value=1, max_value=30, value=5)

output_dir = Path(st.sidebar.text_input("Cartella output", value=str(Path.cwd() / "output")))
output_dir.mkdir(parents=True, exist_ok=True)

# ── Main ───────────────────────────────────────────────────────────────────────
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
niche_labels  = [n[0] for n in NICHES]
selected      = st.multiselect(
    "Seleziona le categorie da cercare",
    options=niche_labels,
    default=niche_labels[:3],
)

run = st.button("🚀 Avvia ricerca", type="primary")

if run:
    # Validazioni
    if not google_api:
        st.error("Inserisci la Google Places API Key nella sidebar.")
        st.stop()

    # Costruisce lista comuni
    if comuni_file is not None:
        if comuni_file.name.lower().endswith(".csv"):
            df_comuni = pd.read_csv(comuni_file)
        else:
            df_comuni = pd.read_excel(comuni_file)
        comuni_list = df_comuni["comune"].dropna().tolist() if "comune" in df_comuni.columns else []
    else:
        comuni_list = [c.strip() for c in comuni_text.splitlines() if c.strip()]

    if not comuni_list:
        st.error("Nessun comune valido trovato.")
        st.stop()

    # Costruisce keywords per le nicchie selezionate
    keywords_per_niche = {n[0]: n[1] for n in NICHES}
    all_keywords = []
    for label in selected:
        all_keywords.extend(keywords_per_niche.get(label, []))

    if not all_keywords:
        st.error("Seleziona almeno una nicchia.")
        st.stop()

    st.info(f"Cercando in {len(comuni_list)} comuni, {len(selected)} nicchie selezionate...")
    progress = st.progress(0)
    status_box = st.empty()
    all_results = []

    total_steps = len(comuni_list)
    for i, comune in enumerate(comuni_list):
        status_box.markdown(f"⏳ Scansionando **{comune}**...")
        results = search_contractors(
            comune=comune,
            keywords=all_keywords,
            api_key=google_api,
            min_reviews=int(min_reviews),
            max_reviews=int(max_reviews),
            radius_km=float(radius_km),
        )
        all_results.extend(results)
        progress.progress((i + 1) / total_steps)

    status_box.empty()
    progress.empty()

    if not all_results:
        st.warning("Nessun risultato trovato con i filtri impostati. Prova ad allargare il raggio o le nicchie.")
    else:
        df = pd.DataFrame(all_results)
        # Riordina colonne
        cols = ["nome", "telefono", "orario", "google_maps", "comune", "keyword", "num_recensioni"]
        df = df[[c for c in cols if c in df.columns]]

        st.success(f"✅ Trovati **{len(df)}** artigiani senza sito web con {min_reviews}–{max_reviews} recensioni!")

        # Preview
        st.dataframe(
            df,
            column_config={
                "google_maps": st.column_config.LinkColumn("Link Google Maps"),
            },
            use_container_width=True,
        )

        # Download CSV
        ts_name = f"local_contractors_{int(time.time())}.csv"
        final_path = output_dir / ts_name
        df.to_csv(final_path, index=False)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Scarica CSV",
            data=csv_bytes,
            file_name=ts_name,
            mime="text/csv",
        )
        st.caption(f"Salvato anche in: `{final_path}`")
