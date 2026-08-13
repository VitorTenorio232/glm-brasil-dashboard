from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd
import geopandas as gpd
import streamlit as st

from .storage import load_table
from .config import PROCESSED_DIR, MUNICIPALITIES_DIR

METRIC_LABELS = {
    "flash_count": "Número de flashes",
    "flash_density_km2": "Densidade de flashes (flashes/km²)",
    "lightning_days": "Dias com relâmpagos",
    "max_daily_flashes": "Máximo diário de flashes",
    "max_hourly_flashes": "Máximo horário de flashes",
    "mean_energy_j": "Energia média do flash (J)",
    "mean_area_km2": "Área média do flash (km²)",
    "mean_duration_ms": "Duração média do flash (ms)",
    "flash_count_anom_pct": "Anomalia de flashes (%)",
    "flash_count_z": "Anomalia padronizada (z-score)",
}


def get_data_dir() -> Path:
    custom = os.getenv("GLM_PROCESSED_DIR")
    if custom:
        return Path(custom)
    if (PROCESSED_DIR / "monthly.parquet").exists() or (PROCESSED_DIR / "monthly.csv").exists():
        return PROCESSED_DIR
    return Path(__file__).resolve().parents[1] / "data" / "demo" / "processed"


def load(name: str) -> pd.DataFrame:
    return load_table(get_data_dir() / name)


def geometry_path() -> Path:
    # Arquivo leve dedicado à visualização, quando existir.
    custom_web = os.getenv("GLM_MUNICIPALITIES_WEB_FILE")
    if custom_web:
        return Path(custom_web)

    custom = os.getenv("GLM_MUNICIPALITIES_FILE")
    if custom:
        p = Path(custom)
        # Se existir uma versão web ao lado do arquivo indicado, prefira-a.
        web_candidate = p.with_name("municipios_brasil_web.geojson")
        if web_candidate.exists():
            return web_candidate
        return p

    # Prefira SEMPRE a malha simplificada para renderização no navegador.
    for name in [
        "municipios_brasil_web.geojson",
        "municipios_brasil_web.gpkg",
        "municipios_brasil.gpkg",
        "municipios_brasil.geojson",
    ]:
        p = MUNICIPALITIES_DIR / name
        if p.exists():
            return p

    return Path(__file__).resolve().parents[1] / "data" / "demo" / "municipalities.geojson"


@st.cache_data(show_spinner=False)
def _read_geometry_cached(path_str: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path_str).to_crs(4326)
    # Levar ao browser apenas atributos necessários.
    keep = [c for c in ["code_muni", "name_muni", "abbrev_state", "geometry"] if c in gdf.columns]
    return gdf[keep].copy()


def load_geometry() -> gpd.GeoDataFrame:
    return _read_geometry_cached(str(geometry_path())).copy()


def metric_range(df: pd.DataFrame, metric: str, diverging: bool = False) -> tuple[float, float]:
    vals = pd.to_numeric(df[metric], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if vals.empty:
        return 0.0, 1.0
    if diverging:
        lim = float(np.nanpercentile(np.abs(vals), 95)) or 1.0
        return -lim, lim
    lo, hi = np.nanpercentile(vals, [2, 98])
    if lo == hi:
        hi = lo + 1
    return float(lo), float(hi)


def _simplify_for_browser(gdf: gpd.GeoDataFrame, tolerance_m: float = 1000.0) -> gpd.GeoDataFrame:
    """Fallback de segurança caso apenas a geometria completa esteja disponível."""
    if gdf.empty:
        return gdf
    projected = gdf.to_crs(5880)
    projected = projected.copy()
    projected["geometry"] = projected.geometry.simplify(tolerance_m, preserve_topology=True)
    projected = projected[
        projected.geometry.notna()
        & (~projected.geometry.is_empty)
    ].copy()
    return projected.to_crs(4326)


def local_folium_map(stats: pd.DataFrame, metric: str, *, tooltip_cols=None, diverging=False):
    import folium
    import branca.colormap as cm

    gdf = load_geometry()
    gdf["code_muni"] = gdf["code_muni"].astype(str)

    data = stats.copy()
    data["code_muni"] = data["code_muni"].astype(str)

    # Só envia ao browser municípios realmente presentes no produto selecionado.
    # Isso evita serializar a malha nacional completa em mapas de períodos curtos.
    active_codes = set(data["code_muni"].dropna().astype(str))
    if active_codes:
        gdf = gdf[gdf["code_muni"].isin(active_codes)].copy()

    # Se o arquivo carregado não for a versão "_web", simplifica em memória.
    if "_web." not in geometry_path().name.lower():
        gdf = _simplify_for_browser(gdf, tolerance_m=1000.0)

    geom_keep = [c for c in ["code_muni", "name_muni", "abbrev_state", "geometry"] if c in gdf.columns]
    gdf = gdf[geom_keep].copy()

    keep = ["code_muni", metric] + [c for c in ["name_muni", "abbrev_state"] if c in data.columns]
    keep = list(dict.fromkeys(keep))
    data_small = data[keep].drop_duplicates("code_muni")

    merged = gdf.merge(data_small, on="code_muni", how="left", suffixes=("", "_stat"))

    # Se os nomes vierem tanto da malha quanto da estatística, mantenha uma coluna canônica.
    for base in ["name_muni", "abbrev_state"]:
        stat_col = f"{base}_stat"
        if stat_col in merged.columns:
            if base in merged.columns:
                merged[base] = merged[stat_col].fillna(merged[base])
            else:
                merged[base] = merged[stat_col]
            merged = merged.drop(columns=[stat_col])

    vmin, vmax = metric_range(data, metric, diverging=diverging)
    if diverging:
        cmap = cm.LinearColormap(["#3b4cc0", "#f7f7f7", "#b40426"], vmin=vmin, vmax=vmax)
    else:
        cmap = cm.LinearColormap(["#0d0887", "#9c179e", "#ed7953", "#f0f921"], vmin=vmin, vmax=vmax)

    cmap.caption = METRIC_LABELS.get(metric, metric)

    m = folium.Map(
        location=[-14.2, -51.9],
        zoom_start=4,
        tiles="CartoDB positron",
        control_scale=True,
    )

    def style(feature):
        value = feature["properties"].get(metric)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            fill = "#d9d9d9"
        else:
            fill = cmap(value)
        return {
            "fillColor": fill,
            "color": "#555555",
            "weight": 0.4,
            "fillOpacity": 0.75,
        }

    fields = tooltip_cols or [c for c in ["name_muni", "abbrev_state", metric] if c in merged.columns]
    aliases = [METRIC_LABELS.get(c, c) for c in fields]

    geojson_text = merged.to_json(drop_id=True)
    payload_mb = len(geojson_text.encode("utf-8")) / (1024 ** 2)

    # Proteção adicional: não deixe um payload gigantesco chegar ao Streamlit.
    if payload_mb > 120:
        merged = _simplify_for_browser(merged, tolerance_m=2500.0)
        geojson_text = merged.to_json(drop_id=True)
        payload_mb = len(geojson_text.encode("utf-8")) / (1024 ** 2)

    folium.GeoJson(
        geojson_text,
        style_function=style,
        tooltip=folium.GeoJsonTooltip(
            fields=fields,
            aliases=aliases,
            localize=True,
        ),
        name="Municípios",
    ).add_to(m)

    cmap.add_to(m)

    # Informação técnica útil sem mandar a geometria completa para uma tabela.
    m.get_root().html.add_child(
        folium.Element(f"<!-- GLM municipal GeoJSON payload: {payload_mb:.2f} MB -->")
    )
    return m


def render_map(stats: pd.DataFrame, metric: str, *, diverging=False, height=650):
    from streamlit_folium import st_folium

    use_ee = False
    ee_error = None

    try:
        project = st.secrets.get("EE_PROJECT", None) if hasattr(st, "secrets") else None
        asset = st.secrets.get("EE_MUNICIPALITIES_ASSET", None) if hasattr(st, "secrets") else None

        project = project or os.getenv("EE_PROJECT")
        asset = asset or os.getenv("EE_MUNICIPALITIES_ASSET")

        if project and asset:
            from .earth_engine import initialize_ee, folium_ee_map

            service_account = st.secrets.get("EE_SERVICE_ACCOUNT", None) if hasattr(st, "secrets") else None
            private_key_json = st.secrets.get("EE_PRIVATE_KEY_JSON", None) if hasattr(st, "secrets") else None

            service_account = service_account or os.getenv("EE_SERVICE_ACCOUNT")
            private_key_json = private_key_json or os.getenv("EE_PRIVATE_KEY_JSON")

            initialize_ee(
                project=project,
                service_account=service_account,
                private_key_json=private_key_json,
            )

            vmin, vmax = metric_range(stats, metric, diverging=diverging)
            mapping = dict(
                zip(
                    stats["code_muni"].astype(str),
                    pd.to_numeric(stats[metric], errors="coerce"),
                )
            )
            palette = (
                ["3b4cc0", "92b4e6", "f7f7f7", "e69479", "b40426"]
                if diverging
                else None
            )
            m = folium_ee_map(
                asset,
                mapping,
                vmin=vmin,
                vmax=vmax,
                palette=palette,
            )
            use_ee = True
        else:
            m = local_folium_map(stats, metric, diverging=diverging)

    except Exception as exc:
        ee_error = str(exc)
        m = local_folium_map(stats, metric, diverging=diverging)

    st_folium(
        m,
        use_container_width=True,
        height=height,
        returned_objects=[],
    )

    if use_ee:
        st.caption("Mapa temático renderizado pelo Google Earth Engine.")
    elif ee_error:
        st.caption(
            f"Fallback cartográfico local "
            f"(Earth Engine indisponível: {ee_error})."
        )
    else:
        st.caption(
            "Fallback cartográfico local com geometria otimizada para web. "
            "Configure EE_PROJECT e EE_MUNICIPALITIES_ASSET para renderização pelo Earth Engine."
        )
