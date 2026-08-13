from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from src.v4_repository import FlashesRepository
from src.v4_ui import load_municipalities_web, format_int
from src.v4_maps import build_analysis_map
from src.v4_analysis import area_km2

st.set_page_config(page_title="Monitoramento GLM", page_icon="📡", layout="wide")
st.title("📡 Monitoramento GLM — últimos 15 minutos disponíveis")
st.caption("Visualização operacional do período mais recente existente na base local.")

repo = FlashesRepository()
if not repo.exists():
    st.error("Base individual de flashes não encontrada.")
    st.stop()
tmin, tmax = repo.available_range()
muni = load_municipalities_web()

mode = st.sidebar.radio("Área", ["Município", "Estado"])
states = sorted(muni["abbrev_state"].dropna().astype(str).unique())
uf = st.sidebar.selectbox("Estado", states)
ms = muni[muni["abbrev_state"].astype(str) == uf]
if mode == "Município":
    city = st.sidebar.selectbox("Município", sorted(ms["name_muni"].astype(str).unique()))
    row = ms[ms["name_muni"].astype(str) == city].iloc[0]
    code = str(row["code_muni"]).replace(".0", "")
    geom = row.geometry
    label = f"{city} - {uf}"
    flashes = repo.load(start=tmax - pd.Timedelta(minutes=15), end=tmax, code_muni=code)
else:
    try: geom = ms.geometry.union_all()
    except Exception: geom = ms.geometry.unary_union
    label = uf
    flashes = repo.load(start=tmax - pd.Timedelta(minutes=15), end=tmax, state=uf)

c1, c2, c3 = st.columns(3)
c1.metric("Último horário UTC", tmax.strftime("%d/%m/%Y %H:%M:%S"))
c2.metric("Flashes em 15 min", format_int(len(flashes)))
c3.metric("Área", f"{area_km2(geom):,.0f} km²".replace(",", "."))

m = build_analysis_map(flashes, geom, label=label, mode="Últimos 15 min (🔴🔵🟢)", max_points=30000)
from streamlit_folium import st_folium
st_folium(m, use_container_width=True, height=720, returned_objects=[])
st.caption("🔴 0–5 min • 🔵 5–10 min • 🟢 10–15 min.")
