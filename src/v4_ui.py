from __future__ import annotations

from pathlib import Path
import os
import geopandas as gpd
import pandas as pd
import streamlit as st

from .config import MUNICIPALITIES_DIR


@st.cache_data(show_spinner=False)
def _load_geometry_cached(path_str: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path_str).to_crs(4326)
    keep = [c for c in ["code_muni", "name_muni", "abbrev_state", "area_muni_km2", "geometry"] if c in gdf.columns]
    gdf = gdf[keep].copy()
    gdf["code_muni"] = gdf["code_muni"].astype(str).str.replace(r"\.0$", "", regex=True)
    return gdf


def geometry_path() -> Path:
    custom_web = os.getenv("GLM_MUNICIPALITIES_WEB_FILE")

    if custom_web:
        p = Path(custom_web)
        if p.exists():
            return p

    custom = os.getenv("GLM_MUNICIPALITIES_FILE")

    if custom:
        p = Path(custom)

        if p.exists():
            web = p.with_name("municipios_brasil_web.geojson")

            if web.exists():
                return web

            return p

    candidates = [
        MUNICIPALITIES_DIR / "municipios_brasil_web.geojson",
        MUNICIPALITIES_DIR / "municipios_brasil_web.gpkg",
        MUNICIPALITIES_DIR / "municipios_brasil.gpkg",
        MUNICIPALITIES_DIR / "municipios_brasil.geojson",
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Malha municipal não encontrada. "
        "Esperado: data/municipalities/municipios_brasil_web.geojson"
    )

def load_municipalities_web() -> gpd.GeoDataFrame:
    return _load_geometry_cached(str(geometry_path())).copy()


def format_int(value) -> str:
    try:
        return f"{int(round(value)):,}".replace(",", ".")
    except Exception:
        return "—"


def format_float(value, ndigits=2) -> str:
    try:
        if pd.isna(value): return "—"
        return f"{float(value):,.{ndigits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"
