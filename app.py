from __future__ import annotations

import html
import io
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.realtime_glm import AGE_GROUPS, fetch_live_snapshot, group_counts
from src.maplibre_realtime import flash_payload, show_realtime_map
from src.alertas_flash import analyze_glm_activity
from src.previsao_flash import render_trend_tab
from src.historical_glm import (
    MONTH_NAMES_PT,
    VARIABLES,
    HISTORICAL_MAX_DATE,
    HistoricalGLMRepository,
    SourceConfig,
    build_historical_map,
    clip_field_to_geometry,
    fixed_map_range,
    format_value,
    get_municipality_geometry,
    get_state_geometry,
    load_country,
    load_municipalities,
    load_states,
    make_source_config,
)
from src.spatial_tools import (
    build_rectangle_selector_map,
    build_geometry_preview_map,
    circular_buffer_geometry,
    filter_points_by_geometry,
    geometry_from_geojson,
    rectangle_geometry,
    representative_latlon,
)
from src.ranking_glm import RankingRepository, rank_dataframe
from src.map_uploads import load_user_overlay
from src.view_exports import (
    to_jpeg, time_window_frame, render_flash_png, render_glm_gif, render_ranking_png
)


APP_DIR = Path(__file__).resolve().parent
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Flash View",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# =============================================================================
# ESTILO VISUAL
# =============================================================================
st.markdown(
    """
    <style>
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    .block-container {
        max-width: 1550px;
        padding-top: 1.15rem;
        padding-bottom: 2.5rem;
    }

    .fv-header {
        padding: 1.15rem 1.4rem 1.2rem 1.4rem;
        margin-bottom: 0.9rem;
        text-align: center;
        border: 1px solid #e2e8f0;
        border-radius: 18px;
        background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(241,245,249,.94));
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.07);
    }
    .fv-title {
        margin: 0;
        font-size: 2.55rem;
        line-height: 1.05;
        font-weight: 820;
        letter-spacing: -0.045rem;
        color: #0f172a;
        text-align: center;
    }
    .fv-subtitle {
        margin-top: 0.45rem;
        color: #64748b;
        font-size: 1.02rem;
        text-align: center;
    }

    .metric-card {
        background: #ffffff;
        border: 1px solid #e6eaf0;
        border-radius: 14px;
        padding: 18px 20px 17px 20px;
        min-height: 118px;
        box-shadow: 0 4px 15px rgba(15, 23, 42, 0.07);
        text-align: center;
    }
    .metric-card-label {
        text-align: center;
        color: #64748b;
        font-size: 0.88rem;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .metric-card-value {
        text-align: center;
        color: #0f172a;
        font-size: 1.82rem;
        line-height: 1.08;
        font-weight: 730;
        white-space: normal;
    }
    .metric-card-small {
        text-align: center;
        color: #94a3b8;
        font-size: 0.76rem;
        margin-top: 8px;
    }

    .time-card {
        background: #ffffff;
        border: 1px solid #e6eaf0;
        border-radius: 13px;
        padding: 16px 18px 17px 18px;
        min-height: 106px;
        box-shadow: 0 3px 12px rgba(15, 23, 42, 0.06);
        border-top: 5px solid var(--accent);
    }
    .time-card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.92rem;
        font-weight: 650;
        color: #334155;
    }
    .time-dot {
        width: 11px;
        height: 11px;
        border-radius: 50%;
        background: var(--accent);
        flex: 0 0 11px;
    }
    .time-card-value {
        margin-top: 10px;
        color: #0f172a;
        font-size: 1.8rem;
        line-height: 1;
        font-weight: 750;
    }

    .section-heading {
        text-align: center;
        margin-top: 0.35rem;
        margin-bottom: 0.75rem;
        color: #0f172a;
        font-size: 1.35rem;
        font-weight: 750;
    }

    .info-panel {
        padding: 17px 19px;
        border: 1px solid #e2e8f0;
        background: #f8fafc;
        border-radius: 12px;
        color: #475569;
        margin: 0.4rem 0 1rem 0;
    }
    .info-panel strong { color: #0f172a; }

    button[data-baseweb="tab"] p {
        font-size: 1rem;
        font-weight: 650;
    }
    div[data-testid="stHorizontalBlock"] { gap: 0.85rem; }
    div[data-baseweb="tab-list"] { justify-content: center; gap: 0.45rem; }
    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button {
        border-radius: 10px;
        font-weight: 650;
        min-height: 2.65rem;
    }
    .fv-action-panel {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        background: #f8fafc;
        padding: 0.85rem 1rem;
        margin: 0.55rem 0 0.9rem 0;
    }
    
    /* Flash View | Sala de Operações — visual escuro inspirado em aplicações meteorológicas. */
    .stApp {background:#080e17;color:#e7edf6;}
    .block-container {max-width:1900px;padding:0.45rem 1.25rem 2rem;}
    .fv-header {background:linear-gradient(95deg,#0c1826,#15283a);color:white;
        border:1px solid #26384a;border-radius:12px;box-shadow:none;text-align:left;
        padding:0.65rem 1.2rem;margin:0 0 0.45rem;}
    .fv-title {font-size:1.6rem;color:white;text-align:left;letter-spacing:-0.02em;}
    .fv-subtitle {font-size:0.82rem;margin-top:0.2rem;color:#a9c1d6;text-align:left;}
    .metric-card,.time-card {background:#131f2e;border:1px solid #2c3b50;
        box-shadow:none;color:#ecf4ff;min-height:90px;padding:11px 14px;}
    .metric-card-label,.time-card-header {color:#b5c7dc;}
    .metric-card-value,.time-card-value {color:#f1f6ff;font-size:1.4rem;}
    .metric-card-small {color:#9eb1c6;}
    .section-heading {color:#ecf5ff;text-align:left;margin-top:.65rem;font-size:1.12rem;}
    .info-panel,.fv-action-panel {background:#132132;border-color:#2b4358;color:#d8e8f8;}
    button[data-baseweb="tab"] {border-radius:7px 7px 0 0;}
    div[data-baseweb="tab-list"] {justify-content:flex-start;gap:.20rem;}
    button[data-baseweb="tab"] p {font-size:.89rem;}
    [data-testid="stMetricValue"],[data-testid="stMetricLabel"] {color:#e8f2ff;}
    .fv-ops-strip {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:9px;
        background:#101c2b;border:1px solid #263b50;color:#d1e7f8;padding:10px 14px;
        border-radius:10px;margin-bottom:10px;font-size:12px;}
    .fv-ops-pill {display:inline-block;background:#173548;color:#7de5ef;border:1px solid #266579;
        padding:4px 8px;border-radius:8px;font-weight:750;letter-spacing:.02em;}
    .fv-ops-main {font-weight:800;font-size:13px;letter-spacing:.06em;color:#fff;}
    .fv-ops-muted {color:#9fb9cd;}
    .fv-timeline-title {background:#0e1a2b;border:1px solid #27415a;border-radius:10px;
        color:#e4f0fc;padding:9px 12px;margin-top:8px;}
    div[data-testid="stExpander"] {background:#0d1929;border-radius:9px;}
    
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# HELPERS VISUAIS
# =============================================================================
def _fmt_int(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".")


def _local_time(dt):
    """Converte um datetime UTC para o horário local de Brasília/São Paulo."""
    if dt is None:
        return None
    return dt.astimezone(LOCAL_TIMEZONE)


def _safe_filename(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-zÀ-ÿ_-]+", "_", str(text).strip())
    return re.sub(r"_+", "_", text).strip("_") or "flash_view"


def _series_figure_png(
    data: pd.DataFrame,
    *,
    scale: str,
    variable: str,
    location_label: str,
) -> bytes:
    """Gera uma versão PNG da série exibida no painel, sem depender de Kaleido."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)
    values = pd.to_numeric(data["value"], errors="coerce").to_numpy(dtype=float)

    if scale in {"daily", "monthly"}:
        x = pd.to_datetime(data["date"])
        ax.plot(x, values, marker="o", linewidth=1.6, markersize=3.8)
        fig.autofmt_xdate()
    else:
        x = data["year"].astype(int).to_numpy()
        ax.plot(x, values, marker="o", linewidth=1.8, markersize=5)
        ax.set_xticks(x)

    ax.set_title(f"{VARIABLES[variable]['label']} — {location_label}")
    ax.set_xlabel("Período")
    ax.set_ylabel(f"{VARIABLES[variable]['label']} ({VARIABLES[variable]['unit']})")
    ax.grid(True, alpha=0.25)
    if variable == "flash_count":
        ax.set_ylim(bottom=0)

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def _card(label: str, value: str, small: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-card-label">{html.escape(str(label))}</div>
            <div class="metric-card-value">{html.escape(str(value))}</div>
            {f'<div class="metric-card-small">{html.escape(str(small))}</div>' if small else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _time_card(label: str, value: int, color: str) -> None:
    st.markdown(
        f"""
        <div class="time-card" style="--accent:{color};">
            <div class="time-card-header">
                <span class="time-dot"></span>
                <span>{html.escape(label)}</span>
            </div>
            <div class="time-card-value">{_fmt_int(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def _historical_config() -> SourceConfig:
    # No Streamlit Community Cloud, os dados históricos ficam em um Dataset
    # privado do Hugging Face. O token NUNCA deve ser colocado no código.
    # Ele é lido de .streamlit/secrets.toml (local) ou dos Secrets do app (Cloud).
    hf_token = _secret("HF_TOKEN") or os.getenv("HF_TOKEN")
    if hf_token:
        # historical_glm.py usa o token pelo mecanismo oficial do huggingface_hub.
        os.environ["HF_TOKEN"] = str(hf_token)

    local_root = _secret("FLASH_VIEW_DATA_ROOT") or os.getenv("FLASH_VIEW_DATA_ROOT")
    hf_repo = _secret("FLASH_VIEW_HF_REPO") or os.getenv("FLASH_VIEW_HF_REPO") or "VitorLSR/flash-view-glm-data"
    hf_prefix = _secret("FLASH_VIEW_HF_PREFIX", "") or os.getenv("FLASH_VIEW_HF_PREFIX", "")
    return make_source_config(
        app_dir=APP_DIR,
        local_root=local_root,
        hf_repo=hf_repo,
        hf_prefix=hf_prefix,
    )


def _hf_token_available() -> bool:
    return bool(_secret("HF_TOKEN") or os.getenv("HF_TOKEN"))


@st.cache_resource(show_spinner=False)
def _get_repo(config: SourceConfig) -> HistoricalGLMRepository:
    repo = HistoricalGLMRepository(config)
    repo.scan()
    return repo


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False)
def _specific_field(
    config: SourceConfig,
    scale: str,
    year: int,
    month: int | None,
    day: int | None,
    variable: str,
):
    repo = HistoricalGLMRepository(config)
    if scale == "daily":
        item = repo.get_daily(year, int(month), int(day))
    elif scale == "monthly":
        item = repo.get_monthly(year, int(month))
    else:
        item = repo.get_yearly(year)
    lat, lon, data, _ = repo.read_grid(item, variable)
    return lat, lon, data, item.relpath


@st.cache_data(ttl=3600, max_entries=16, show_spinner=False)
def _climatology_field(config: SourceConfig, scale: str, month: int | None, years: tuple[int, ...], variable: str):
    repo = HistoricalGLMRepository(config)
    if scale == "monthly":
        items = [repo.get_monthly(y, int(month)) for y in years]
    else:
        items = [repo.get_yearly(y) for y in years]
    lat, lon, data, n = repo.climatology(items, variable)
    return lat, lon, data, n


@st.cache_data(ttl=86400, max_entries=2, show_spinner=False)
def _states_geojson() -> dict | None:
    try:
        states = load_states(2022).copy()
        states["geometry"] = states.geometry.simplify(0.025, preserve_topology=True)
        return json.loads(states.to_json())
    except Exception:
        return None




@st.cache_resource(show_spinner=False)
def _country_geometry_safe():
    """Carrega o Brasil; usa a união das UFs como fallback."""
    try:
        return load_country(2022)
    except Exception:
        try:
            states = load_states(2022)
            geom = (
                states.geometry.union_all()
                if hasattr(states.geometry, "union_all")
                else states.geometry.unary_union
            )
            if geom is None or geom.is_empty:
                raise RuntimeError("A geometria administrativa do Brasil ficou vazia.")
            return geom
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível carregar a geometria administrativa do Brasil. "
                "Verifique geobr/geopandas/shapely."
            ) from exc

@st.cache_data(ttl=3600, max_entries=16, show_spinner=False)
def _series_cached(
    config: SourceConfig,
    geometry_wkb: bytes,
    scale: str,
    variable: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    from shapely import from_wkb

    repo = HistoricalGLMRepository(config)
    geom = from_wkb(geometry_wkb)
    return repo.series_for_geometry(
        geom,
        variable=variable,
        scale=scale,
        start_date=start_date,
        end_date=end_date,
    )



@st.cache_resource(show_spinner=False)
def _get_ranking_repo(config: SourceConfig) -> RankingRepository:
    return RankingRepository(config)


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def _ranking_data(config: SourceConfig, level: str, scale: str) -> pd.DataFrame:
    repo = RankingRepository(config)
    return repo.load(level, scale)


def _geometry_from_payload(payload: dict):
    from shapely import from_wkb

    wkb_hex = payload.get("geometry_wkb_hex")
    if wkb_hex:
        return from_wkb(bytes.fromhex(wkb_hex))
    level = payload.get("spatial_level", "Brasil")
    if level == "Brasil":
        return _country_geometry_safe()
    if level == "Estado":
        return get_state_geometry(payload["uf"], 2022)
    if level == "Município":
        return get_municipality_geometry(payload["code_muni"], payload["uf"], 2022)
    raise ValueError(f"Recorte espacial não reconhecido: {level}")


def _spatial_details(spatial_level: str, prefix: str) -> tuple[dict, bool]:
    """Resolve controles administrativos/personalizados sem ler NetCDF."""
    payload = {
        "spatial_level": spatial_level,
        "uf": None,
        "code_muni": None,
        "location_label": "Brasil",
        "geometry_wkb_hex": None,
    }
    valid = True

    if spatial_level == "Brasil":
        return payload, valid

    if spatial_level == "Estado":
        states = load_states(2022)
        lookup = {f"{r.abbrev_state} — {r.name_state}": r.abbrev_state for r in states.itertuples()}
        chosen = st.selectbox("Estado", list(lookup), key=f"{prefix}_state")
        payload.update(uf=lookup[chosen], location_label=chosen)
        return payload, valid

    if spatial_level == "Município":
        states = load_states(2022)
        lookup = {f"{r.abbrev_state} — {r.name_state}": r.abbrev_state for r in states.itertuples()}
        c1, c2 = st.columns([0.8, 1.2])
        with c1:
            chosen_state = st.selectbox("Estado", list(lookup), key=f"{prefix}_muni_state")
        uf = lookup[chosen_state]
        municipalities = load_municipalities(uf, 2022)
        mlookup = {f"{r.name_muni} ({uf})": str(r.code_muni) for r in municipalities.itertuples()}
        with c2:
            chosen_muni = st.selectbox("Município", list(mlookup), key=f"{prefix}_muni")
        payload.update(uf=uf, code_muni=mlookup[chosen_muni], location_label=chosen_muni)
        st.caption("O recorte municipal usa os centros das células da grade (~0,08°).")
        return payload, valid

    if spatial_level == "Retângulo":
        method = st.radio(
            "Definição do retângulo",
            ["Desenhar no mapa", "Digitar coordenadas"],
            horizontal=True,
            key=f"{prefix}_rectangle_method",
        )
        if method == "Digitar coordenadas":
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                south = st.number_input("Lat. sul", -90.0, 90.0, -23.0, 0.1, key=f"{prefix}_south")
            with c2:
                north = st.number_input("Lat. norte", -90.0, 90.0, -18.0, 0.1, key=f"{prefix}_north")
            with c3:
                west = st.number_input("Lon. oeste", -180.0, 180.0, -48.0, 0.1, key=f"{prefix}_west")
            with c4:
                east = st.number_input("Lon. leste", -180.0, 180.0, -42.0, 0.1, key=f"{prefix}_east")
            try:
                geom = rectangle_geometry(south, west, north, east)
                payload.update(
                    location_label=f"Retângulo {south:.2f},{west:.2f} → {north:.2f},{east:.2f}",
                    geometry_wkb_hex=geom.wkb.hex(),
                )
                with st.expander("Pré-visualizar área", expanded=False):
                    st_folium(
                        build_geometry_preview_map(geom, label="Retângulo"),
                        width=None, height=330, returned_objects=[],
                        key=f"{prefix}_manual_rect_preview",
                    )
            except Exception as exc:
                st.error(str(exc)); valid = False
        else:
            stored = st.session_state.get(f"{prefix}_rectangle_wkb")
            existing = None
            if stored:
                from shapely import from_wkb
                existing = from_wkb(bytes.fromhex(stored))
            selector = build_rectangle_selector_map(existing)
            map_state = st_folium(
                selector, width=None, height=420,
                returned_objects=["all_drawings"],
                key=f"{prefix}_rectangle_selector",
            )
            drawings = (map_state or {}).get("all_drawings") or []
            if drawings:
                geom = geometry_from_geojson(drawings[-1])
                if geom is not None:
                    st.session_state[f"{prefix}_rectangle_wkb"] = geom.wkb.hex()
                    stored = geom.wkb.hex()
            if stored:
                payload.update(location_label="Retângulo selecionado", geometry_wkb_hex=stored)
                st.success("Área retangular selecionada.")
            else:
                st.info("Use a ferramenta retângulo no canto superior esquerdo do mapa.")
                valid = False
        return payload, valid

    if spatial_level == "Buffer circular":
        source = st.radio(
            "Centro do buffer",
            ["Município", "Latitude/Longitude"],
            horizontal=True,
            key=f"{prefix}_buffer_source",
        )
        radius = st.slider("Raio do buffer (km)", 20, 80, 40, 5, key=f"{prefix}_buffer_radius")
        if source == "Município":
            states = load_states(2022)
            lookup = {f"{r.abbrev_state} — {r.name_state}": r.abbrev_state for r in states.itertuples()}
            c1, c2 = st.columns([0.8, 1.2])
            with c1:
                chosen_state = st.selectbox("Estado", list(lookup), key=f"{prefix}_buffer_state")
            uf = lookup[chosen_state]
            municipalities = load_municipalities(uf, 2022)
            mlookup = {f"{r.name_muni} ({uf})": str(r.code_muni) for r in municipalities.itertuples()}
            with c2:
                chosen_muni = st.selectbox("Município", list(mlookup), key=f"{prefix}_buffer_muni")
            center_geom = get_municipality_geometry(mlookup[chosen_muni], uf, 2022)
            lat0, lon0 = representative_latlon(center_geom)
            label = chosen_muni
        else:
            c1, c2 = st.columns(2)
            with c1:
                lat0 = st.number_input("Latitude central", -90.0, 90.0, -15.8, 0.05, key=f"{prefix}_buffer_lat")
            with c2:
                lon0 = st.number_input("Longitude central", -180.0, 180.0, -47.9, 0.05, key=f"{prefix}_buffer_lon")
            label = f"{lat0:.2f}, {lon0:.2f}"
        geom = circular_buffer_geometry(lat0, lon0, radius)
        payload.update(
            location_label=f"Buffer {radius} km — {label}",
            geometry_wkb_hex=geom.wkb.hex(),
        )
        with st.expander("Pré-visualizar buffer", expanded=False):
            st_folium(
                build_geometry_preview_map(geom, label=f"Buffer {radius} km"),
                width=None, height=330, returned_objects=[],
                key=f"{prefix}_buffer_preview",
            )
        return payload, valid

    raise ValueError(spatial_level)


def _field_png(lat, lon, data, *, variable: str, title: str, geometry, display_range) -> bytes:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 8), dpi=160)
    mesh = ax.pcolormesh(
        lon, lat, data, shading="nearest", cmap="turbo",
        vmin=float(display_range[0]), vmax=float(display_range[1]),
    )
    if geometry is not None:
        try:
            import geopandas as gpd
            gpd.GeoSeries([geometry], crs="EPSG:4326").boundary.plot(
                ax=ax, color="black", linewidth=0.9
            )
        except Exception:
            pass
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal", adjustable="box")
    cb = fig.colorbar(mesh, ax=ax, shrink=0.82, pad=0.02)
    cb.set_label(f"{VARIABLES[variable]['label']} ({VARIABLES[variable]['map_unit']})")
    fig.tight_layout()
    bio = io.BytesIO()
    fig.savefig(bio, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return bio.getvalue()


def _field_netcdf_bytes(lat, lon, data, *, variable: str, title: str) -> bytes:
    ds = xr.Dataset(
        {variable: (("lat", "lon"), np.asarray(data, dtype=np.float32))},
        coords={"lat": np.asarray(lat, dtype=np.float32), "lon": np.asarray(lon, dtype=np.float32)},
        attrs={"title": title, "source": "Flash View / GLM"},
    )
    ds[variable].attrs.update(
        long_name=VARIABLES[variable]["label"], unit=VARIABLES[variable]["unit"]
    )
    raw = ds.to_netcdf(engine="scipy")
    return bytes(raw)


def _series_csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8-sig")

# =============================================================================
# CABEÇALHO
# =============================================================================
st.markdown(
    """
    <div class="fv-header">
        <h1 class="fv-title">⚡ Flash View <span style="font-size:0.65rem;color:#42bff5;font-weight:600;letter-spacing:.1em">SALA DE MONITORAMENTO</span></h1>
        <div class="fv-subtitle">
            Relâmpagos totais • GOES-19 / NOAA • Monitoramento, evolução horária e análise geográfica
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# 4 ABAS PRINCIPAIS
# =============================================================================
tab_live, tab_clim, tab_series, tab_rank, tab_forecast = st.tabs(
    [
        '⚡ Relâmpagos em tempo real',
        '🌦️ Climatologia',
        '📈 Séries temporais',
        '🏆 Ranking',
        '📊 Tendência',
    ],
    key='fv_active_tab', on_change='rerun',
)


# =============================================================================
# ABA 1 — RELÂMPAGOS EM TEMPO REAL
# =============================================================================
@st.cache_data(ttl=55, max_entries=1, show_spinner=False)
def _load_snapshot():
    # A hora inteira é necessária para a evolução temporal observada.
    return fetch_live_snapshot(window_minutes=90, quality="zero_only")


# A animação precisa de atualização frequente; o modo ao vivo NÃO.
# Uma nova agenda só é necessária quando o usuário inicia/pausa a reprodução.
@st.fragment(run_every="60s")
def _live_panel():
    # Este fragmento atualiza apenas os dados; a câmera e a animação vivem no navegador.
    st.markdown('''<div class="fv-ops-strip"><span class="fv-ops-main">◉ FLASH VIEW · OPERAÇÕES</span>
        <span class="fv-ops-pill">GLM-L2-LCFA</span><span>GOES-19 • NOAA/AWS</span>
        <span class="fv-ops-muted">● Online quando há arquivos recentes • Fuso UTC/BRT</span></div>''', unsafe_allow_html=True)
    action_text, action_refresh, action_select = st.columns([0.68, 0.16, 0.16])
    with action_text:
        st.caption(
            "GLM-L2-LCFA • visualização: 30 min por quadro • animação: última hora, passos de 5 min. "
            "Fonte consultada aproximadamente a cada 60 segundos."
        )
    with action_refresh:
        if st.button("🔄 Atualizar agora", width="stretch", key="refresh_live"):
            _load_snapshot.clear()
    with action_select:
        selecting = bool(st.session_state.get("live_area_select_mode", False))
        if st.button(
            "✚ Selecionar Área" if not selecting else "✓ Selecionando",
            width="stretch",
            key="select_live_area",
        ):
            st.session_state["live_area_select_mode"] = not selecting
            st.rerun(scope="fragment")

    try:
        with st.spinner("Buscando os dados GLM mais recentes..."):
            snapshot = _load_snapshot()
    except Exception as exc:
        st.error("Não foi possível obter os dados GLM mais recentes.")
        with st.expander("Detalhes técnicos"):
            st.exception(exc)
        return

    # ==================== Camadas SHP/KMZ/KML/GeoJSON ====================
    with st.expander("🗺️ Área personalizada · importar SHP/KMZ/KML/GeoJSON", expanded=False):
        st.caption("Shapefile: envie um ZIP com .shp, .shx, .dbf e .prj. "
                   "Aceita também KMZ, KML e GeoJSON (até 20 MB). "
                   "O arquivo fica somente na sua sessão; não é enviado ao GitHub/HF.")
        if st.button("✖ Remover camada importada", key="fv_overlay_reset"):
            st.session_state.pop("fv_user_geojson", None)
            st.session_state.pop("fv_user_polygon_wkb", None)
            st.session_state.pop("fv_uploaded_digest", None)
            st.session_state["fv_upload_version"] = int(st.session_state.get("fv_upload_version", 0))+1
            st.rerun(scope="fragment")
        uploaded = st.file_uploader(
            "Escolha a geometria", type=["zip", "kmz", "kml", "geojson", "json"],
            key=f"fv_geo_upload_{st.session_state.get('fv_upload_version',0)}"
        )
        if uploaded is not None:
            import hashlib
            blob = uploaded.getvalue()
            digest = hashlib.sha256(blob).hexdigest()
            if digest != st.session_state.get("fv_uploaded_digest"):
                try:
                    geojson, polygon, nfeat = load_user_overlay(uploaded.name, blob)
                    st.session_state["fv_user_geojson"] = geojson
                    st.session_state["fv_user_polygon_wkb"] = polygon.wkb.hex() if polygon is not None else None
                    st.session_state["fv_uploaded_digest"] = digest
                    st.success(f"Camada carregada: {nfeat} feição(ões).")
                except Exception as exc:
                    st.error(f"Não foi possível ler a geometria: {exc}")
        if st.session_state.get("fv_user_geojson"):
            st.success(f"Camada geográfica ativa ({len(st.session_state['fv_user_geojson']['features'])} feições).")
            st.checkbox("Filtrar as contagens pelo polígono importado", value=True,
                        key="fv_filter_uploaded_polygon")

    selected_geometry = None
    # Área desenhada tem preferência; em seguida, polígono importado.
    stored_wkb = st.session_state.get("live_area_wkb")
    if not stored_wkb and st.session_state.get("fv_filter_uploaded_polygon", True):
        stored_wkb = st.session_state.get("fv_user_polygon_wkb")
    if stored_wkb:
        try:
            from shapely import from_wkb
            selected_geometry = from_wkb(bytes.fromhex(stored_wkb))
        except Exception:
            st.warning("Não foi possível carregar o polígono para filtro.")

    # 60 min preservados para playback; painel atual usa 30 min.
    recent = snapshot.flashes.loc[
        pd.to_numeric(snapshot.flashes["age_minutes"],errors="coerce").between(0,30, inclusive="left")
    ].copy() if not snapshot.flashes.empty else snapshot.flashes.copy()
    display_flashes = (
        filter_points_by_geometry(recent, selected_geometry)
        if selected_geometry is not None else recent
    )
    hour_flashes = (
        filter_points_by_geometry(snapshot.flashes, selected_geometry)
        if selected_geometry is not None else snapshot.flashes
    )
    counts = group_counts(display_flashes)

    window_start_local = _local_time(snapshot.window_start_utc)
    observation_end_local = _local_time(snapshot.observation_end_utc)

    # Exibe data e hora separadamente, com fuso selecionável pelo usuário.
    c1, c2 = st.columns(2)
    with c1:
        small = ("Área selecionada · janela móvel de 30 minutos"
                 if selected_geometry is not None else "Janela móvel de 30 minutos")
        _card("Flashes", _fmt_int(len(display_flashes)), small)
    with c2:
        _card("Satélite", "GOES-19", "Geostationary Lightning Mapper")

    tz_mode = st.segmented_control(
        "Exibir horário da observação em", ["Brasília", "UTC"],
        default="Brasília", key="fv_live_time_zone"
    )
    chosen_tz = LOCAL_TIMEZONE if tz_mode == "Brasília" else ZoneInfo("UTC")
    observed = snapshot.observation_end_utc.astimezone(chosen_tz)
    window_start = snapshot.window_start_utc.astimezone(chosen_tz)
    date_col, time_col = st.columns(2)
    with date_col:
        _card(f"Data · {tz_mode}", observed.strftime("%d/%m/%Y"), "Último dado GLM")
    with time_col:
        _card(f"Hora · {tz_mode}", observed.strftime("%H:%M:%S"),
              "UTC±00:00" if tz_mode == "UTC" else "UTC−03:00")

    st.caption(f"Janela disponível ({tz_mode}): "
               f"{window_start:%d/%m/%Y %H:%M:%S} → "
               f"{observed:%d/%m/%Y %H:%M:%S}")

    if snapshot.latency_minutes > 10:
        st.warning(
            "⚠️ O último arquivo disponível está desatualizado em relação ao horário atual. "
            "Confira a data e a hora observadas acima."
        )

    if selected_geometry is not None:
        info_col, clear_col = st.columns([0.84, 0.16])
        with info_col:
            st.success(f"Área aplicada ao tempo real: {len(display_flashes):,} flashes na janela atual.".replace(",", "."))
        with clear_col:
            if st.button("✖ Limpar área", width="stretch", key="clear_live_area"):
                st.session_state.pop("live_area_wkb", None)
                st.session_state["live_area_select_mode"] = False
                st.rerun(scope="fragment")

    st.markdown('<div class="section-heading">Mapa interativo</div>', unsafe_allow_html=True)
    if display_flashes.empty:
        st.warning("Nenhum flash foi encontrado na área selecionada durante a janela disponível.")

    selecting = bool(st.session_state.get("live_area_select_mode", False))
    if selecting:
        st.info("Clique em dois cantos opostos do retângulo no mapa para delimitar a área.")

    # ==================== MapLibre persistente + reprodução JS ====================
    # O mapa e a animação nunca são recriados a cada quadro.
    # Camera (zoom/centro) gravada pelo navegador em sessionStorage, sem rerun Python.
    from shapely.geometry import mapping, box
    selection_json = mapping(selected_geometry) if selected_geometry is not None else None
    points_js = flash_payload(hour_flashes)
    if len(hour_flashes) > len(points_js):
        st.caption(f"Exibindo {len(points_js):,} dos {len(hour_flashes):,} flashes no mapa por desempenho; "
                   "as estatísticas continuam utilizando todos os registros.".replace(",", "."))
    map_result = show_realtime_map(
        points_js, snapshot.observation_end_utc,
        selected_geojson=selection_json,
        uploaded_geojson=st.session_state.get("fv_user_geojson"),
        selecting=selecting,
    )
    rectangle = getattr(map_result, "rectangle", None)
    if rectangle:
        try:
            west, south, east, north = (
                float(rectangle[k]) for k in ("west", "south", "east", "north")
            )
            if -180 <= west < east <= 180 and -85 <= south < north <= 85:
                st.session_state["live_area_wkb"] = box(west, south, east, north).wkb.hex()
                st.session_state["live_area_select_mode"] = False
                st.rerun(scope="fragment")
        except (TypeError, ValueError, KeyError):
            st.warning("Não foi possível interpretar o retângulo selecionado.")

    st.caption("Mapa MapLibre: centro e zoom são mantidos no navegador. "
               "Os controles da última hora operam sem executar novamente o Python.")

    # ==================== Exportar PNG/JPEG/GIF ====================
    ec1,ec2,ec3=st.columns([1.5,1.3,3])
    with ec1:
        if st.button("📷 Preparar PNG/JPEG", key="fv_live_prepare_images"):
            png=render_flash_png(display_flashes,title="Flash View | Monitoramento GLM",
                subtitle=(f"Observação até {snapshot.observation_end_utc:%d/%m/%Y %H:%M} UTC "
                          f"• {len(display_flashes)} flashes"),
                geometry=selected_geometry,
                observation_end=snapshot.observation_end_utc)
            st.session_state["fv_live_png_export"]=png
    with ec2:
        if st.button("🎞️ Preparar GIF (1 h)",key="fv_live_prepare_gif"):
            with st.spinner("Gerando 12 quadros da última hora..."):
                st.session_state["fv_live_gif_export"]=render_glm_gif(
                    hour_flashes,snapshot.observation_end_utc,geometry=selected_geometry)
    with ec3:
        st.caption("Exportação científica em fundo cartográfico simples, "
                   "sem copiar mosaicos de satélite de terceiros.")
    if st.session_state.get("fv_live_png_export"):
        im1,im2=st.columns(2)
        im1.download_button("⬇️ PNG",st.session_state["fv_live_png_export"],
                           file_name="flash_view_tempo_real.png",mime="image/png",key="fv_live_dl_png")
        im2.download_button("⬇️ JPEG",to_jpeg(st.session_state["fv_live_png_export"]),
                           file_name="flash_view_tempo_real.jpg",mime="image/jpeg",key="fv_live_dl_jpg")
    if st.session_state.get("fv_live_gif_export"):
        st.download_button("⬇️ GIF animado (última hora)",st.session_state["fv_live_gif_export"],
                           file_name="flash_view_glm_1h.gif",mime="image/gif",key="fv_live_dl_gif")

    st.markdown('<div class="section-heading">Atividade por faixa temporal</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, _, _, color) in zip(cols, AGE_GROUPS):
        with col:
            _time_card(label, counts[label], color)

    st.caption(
        "As faixas de tempo são calculadas a partir do horário do dado GLM mais recente disponível. "
        "Os pontos representam centroides dos flashes identificados no produto GLM-L2-LCFA."
    )


if tab_live.open:
    with tab_live:
        _live_panel()
else:
    # Sem fragmento em segundo plano quando a aba Tempo real não está ativa.
    pass


if tab_forecast.open:
    with tab_forecast:
        render_trend_tab(snapshot_loader=_load_snapshot)


# =============================================================================
# FONTE HISTÓRICA
# =============================================================================
historical_config = _historical_config()
historical_repo = None
historical_error = None
if (tab_clim.open or tab_series.open or tab_rank.open) and historical_config.mode != "none":
    try:
        if historical_config.mode == "huggingface" and not _hf_token_available():
            # Localmente, um login feito com `hf auth login` ainda pode funcionar pelo
            # cache do huggingface_hub. No Streamlit Cloud, porém, HF_TOKEN é obrigatório
            # para um Dataset privado. Tentamos a conexão e exibimos instrução clara se falhar.
            pass
        historical_repo = _get_repo(historical_config)
    except Exception as exc:
        historical_error = exc


def _historical_unavailable():
    st.error("A base histórica está temporariamente indisponível.")
    st.caption(
        "O monitoramento quase em tempo real continua disponível. "
        "Tente novamente em instantes; se o problema persistir, consulte os detalhes técnicos."
    )
    if historical_error is not None:
        with st.expander("Detalhes técnicos"):
            st.exception(historical_error)


# Indicador discreto da origem histórica (sem expor o token).
if (tab_clim.open or tab_series.open or tab_rank.open) and historical_repo is not None and historical_config.mode == "huggingface":
    st.caption(f"Base histórica: Hugging Face Dataset · {historical_config.hf_repo}")


# =============================================================================
# ABA 2 — CLIMATOLOGIA / MAPAS HISTÓRICOS
# =============================================================================
if tab_clim.open:
    with tab_clim:
        st.markdown('<div class="section-heading">Climatologia e mapas históricos</div>', unsafe_allow_html=True)
        st.caption(
            "Visualização dos produtos GLM processados em grade. Número de flashes é tratado como contagem; "
            "energia, área e duração são médias ponderadas pelo número de flashes."
        )
        with st.expander("ℹ️ Como os cálculos são feitos"):
            st.markdown(
                "**Agregação espacial:** o número de flashes é a **soma** das células incluídas no recorte. "
                "Energia, área e duração são calculadas por **média ponderada por `flash_count`**.\n\n"
                "**Climatologia:** para número de flashes, calcula-se a **média climatológica das contagens** "
                "dos períodos selecionados; para energia, área e duração, mantém-se a média ponderada pelos flashes."
            )
        st.info("📅 Base histórica processada disponível até **31/12/2022**.")

        if historical_repo is None:
            _historical_unavailable()
        else:
            daily_years = historical_repo.daily_years()
            monthly_years = historical_repo.monthly_years()
            yearly_years = historical_repo.yearly_years()

            area_col, mode_col, scale_col, var_col = st.columns([1.15, 1.05, 0.9, 1.25])
            with area_col:
                spatial_level = st.selectbox(
                    "Recorte espacial",
                    ["Brasil", "Estado", "Município", "Retângulo", "Buffer circular"],
                    index=0,
                    key="clim_area",
                )
            with mode_col:
                mode = st.selectbox(
                    "Produto",
                    ["Período específico", "Climatologia"],
                    key="clim_mode",
                )
            with scale_col:
                scale_options = ["Diária", "Mensal", "Anual"] if mode == "Período específico" else ["Mensal", "Anual"]
                scale_label = st.selectbox("Escala", scale_options, key="clim_scale")
            with var_col:
                variable = st.selectbox(
                    "Variável",
                    list(VARIABLES),
                    format_func=lambda x: VARIABLES[x]["label"],
                    key="clim_variable",
                )
            scale = {"Diária": "daily", "Mensal": "monthly", "Anual": "yearly"}[scale_label]

            spatial_payload, spatial_valid = _spatial_details(spatial_level, "clim")
            fixed_range = fixed_map_range(variable, scale)
            st.caption(
                f"Escala de cores fixa para comparação: {fixed_range[0]:.3g} → {fixed_range[1]:.3g} "
                f"{VARIABLES[variable]['map_unit']}. Valores acima do teto ficam saturados na cor máxima."
            )

            request_spec = None
            request_payload = None
            selection_valid = bool(spatial_valid)

            if scale == "daily" and not daily_years:
                st.info("Nenhum produto diário foi encontrado na base configurada.")
                selection_valid = False
            elif scale == "monthly" and not monthly_years:
                st.info("Nenhum produto mensal foi encontrado na base configurada.")
                selection_valid = False
            elif scale == "yearly" and not yearly_years:
                st.info("Nenhum produto anual foi encontrado na base configurada.")
                selection_valid = False

            if selection_valid:
                if mode == "Período específico":
                    if scale == "daily":
                        s1, s2, s3 = st.columns(3)
                        with s1:
                            year = st.selectbox(
                                "Ano", daily_years, index=len(daily_years) - 1, key="spec_daily_year"
                            )
                        available_months = historical_repo.daily_months_for_year(year)
                        with s2:
                            month = st.selectbox(
                                "Mês", available_months, format_func=lambda m: MONTH_NAMES_PT[m],
                                index=len(available_months) - 1, key="spec_daily_month"
                            )
                        available_days = historical_repo.daily_days_for_month(year, month)
                        with s3:
                            day = st.selectbox(
                                "Dia", available_days, index=len(available_days) - 1, key="spec_daily_day"
                            )
                        request_payload = {
                            "mode": mode, "scale": scale, "variable": variable,
                            "year": int(year), "month": int(month), "day": int(day),
                            **spatial_payload,
                        }

                    elif scale == "monthly":
                        s1, s2 = st.columns(2)
                        with s1:
                            year = st.selectbox(
                                "Ano", monthly_years, index=len(monthly_years) - 1, key="spec_month_year"
                            )
                        available_months = historical_repo.months_for_year(year)
                        with s2:
                            month = st.selectbox(
                                "Mês", available_months, format_func=lambda m: MONTH_NAMES_PT[m],
                                index=len(available_months) - 1, key="spec_month"
                            )
                        request_payload = {
                            "mode": mode, "scale": scale, "variable": variable,
                            "year": int(year), "month": int(month), "day": None,
                            **spatial_payload,
                        }

                    else:
                        year = st.selectbox(
                            "Ano", yearly_years, index=len(yearly_years) - 1, key="spec_year"
                        )
                        request_payload = {
                            "mode": mode, "scale": scale, "variable": variable,
                            "year": int(year), "month": None, "day": None,
                            **spatial_payload,
                        }

                else:
                    if scale == "monthly":
                        all_months = sorted({m for y in monthly_years for m in historical_repo.months_for_year(y)})
                        month = st.selectbox(
                            "Mês climatológico",
                            all_months,
                            format_func=lambda m: MONTH_NAMES_PT[m],
                            key="clim_month",
                        )
                        years_available = historical_repo.years_for_month(month)
                        complete_years = [y for y in years_available if y in historical_repo.complete_monthly_years()]
                        default_years = complete_years or years_available
                        selected_years = st.multiselect(
                            "Anos utilizados",
                            years_available,
                            default=default_years,
                            key="clim_month_years",
                        )
                        if not selected_years:
                            st.info("Selecione pelo menos um ano para gerar a climatologia.")
                            selection_valid = False
                        else:
                            request_payload = {
                                "mode": mode, "scale": scale, "variable": variable,
                                "month": int(month), "years": tuple(sorted(map(int, selected_years))),
                                **spatial_payload,
                            }
                    else:
                        selected_years = st.multiselect(
                            "Anos utilizados",
                            yearly_years,
                            default=yearly_years,
                            key="clim_years",
                        )
                        if not selected_years:
                            st.info("Selecione pelo menos um ano para gerar a climatologia.")
                            selection_valid = False
                        else:
                            request_payload = {
                                "mode": mode, "scale": scale, "variable": variable,
                                "month": None, "years": tuple(sorted(map(int, selected_years))),
                                **spatial_payload,
                            }

            if selection_valid and request_payload is not None:
                # Tupla estável para comparar a consulta atual com o último mapa efetivamente gerado.
                request_spec = tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in request_payload.items()))

                st.caption(
                    "O mapa não é calculado automaticamente. Ajuste os parâmetros acima e clique em "
                    "**Gerar mapa** somente quando quiser processar a consulta."
                )

                if mode == "Climatologia":
                    n_selected = len(request_payload.get("years", ()))
                    if n_selected > 1:
                        st.warning(
                            f"⏳ Esta climatologia utilizará **{n_selected} arquivos/períodos**. "
                            "O primeiro processamento pode demorar enquanto os NetCDF são baixados do Hugging Face; "
                            "arquivos já presentes no cache são reutilizados."
                        )

                b1, b2, b3 = st.columns([0.34, 0.32, 0.34])
                with b2:
                    generate_map = st.button(
                        "🗺️ Gerar mapa",
                        type="primary",
                        width="stretch",
                        key="generate_historical_map",
                    )

                if generate_map:
                    try:
                        period_text = ""
                        source_text = ""
                        n_periods = 1

                        if mode == "Período específico":
                            year = request_payload["year"]
                            month = request_payload.get("month")
                            day = request_payload.get("day")

                            if scale == "daily":
                                spinner_text = "Lendo o produto diário..."
                            elif scale == "monthly":
                                spinner_text = "Lendo o produto mensal..."
                            else:
                                spinner_text = "Lendo o produto anual..."

                            with st.spinner(spinner_text):
                                lat, lon, field, relpath = _specific_field(
                                    historical_config, scale, year, month, day, variable
                                )

                            if scale == "daily":
                                period_text = f"{day:02d}/{month:02d}/{year}"
                            elif scale == "monthly":
                                period_text = f"{MONTH_NAMES_PT[month]} de {year}"
                            else:
                                period_text = str(year)
                            source_text = Path(relpath).name

                        else:
                            selected_years = tuple(request_payload["years"])
                            month = request_payload.get("month")
                            spinner_text = (
                                "Calculando climatologia mensal..."
                                if scale == "monthly" else "Calculando climatologia anual..."
                            )
                            with st.spinner(spinner_text):
                                lat, lon, field, n_periods = _climatology_field(
                                    historical_config,
                                    scale,
                                    month,
                                    selected_years,
                                    variable,
                                )
                            if scale == "monthly":
                                period_text = f"Climatologia de {MONTH_NAMES_PT[month]}"
                            else:
                                period_text = "Climatologia anual"
                            source_text = ", ".join(map(str, selected_years))

                        # Resolve o recorte somente no clique em Gerar mapa.
                        spatial_level_now = request_payload.get("spatial_level", "Brasil")
                        location_label = request_payload.get("location_label", "Brasil")
                        clip_geometry = _geometry_from_payload(request_payload)
                        boundary_name = (
                            "Limite do Brasil" if spatial_level_now == "Brasil"
                            else f"Limite — {location_label}"
                        )
                        context_geojson = _states_geojson() if spatial_level_now in {"Brasil", "Retângulo", "Buffer circular"} else None
                        display_range = fixed_map_range(variable, scale)

                        with st.spinner(f"Montando o mapa — {location_label}..."):
                            hist_map = build_historical_map(
                                lat,
                                lon,
                                field,
                                variable,
                                layer_name=f"{VARIABLES[variable]['short']} — {period_text}",
                                states_geojson=context_geojson,
                                clip_geometry=clip_geometry,
                                boundary_name=boundary_name,
                                mask_to_geometry=True,
                                display_range=display_range,
                            )
                            dl_lat, dl_lon, dl_field = clip_field_to_geometry(
                                lat, lon, field, clip_geometry
                            )

                        render_id = int(st.session_state.get("historical_map_render_id", 0)) + 1
                        st.session_state["historical_map_render_id"] = render_id
                        st.session_state["historical_map_result"] = {
                            "request_spec": request_spec,
                            "map": hist_map,
                            "period_text": period_text,
                            "source_text": source_text,
                            "n_periods": int(n_periods),
                            "variable": variable,
                            "mode": mode,
                            "scale": scale,
                            "location_label": location_label,
                            "spatial_level": spatial_level_now,
                            "render_id": render_id,
                            "lat": np.asarray(dl_lat, dtype=np.float32),
                            "lon": np.asarray(dl_lon, dtype=np.float32),
                            "field": np.asarray(dl_field, dtype=np.float32),
                            "geometry_wkb_hex": clip_geometry.wkb.hex() if clip_geometry is not None else None,
                            "display_range": tuple(map(float, display_range)),
                        }
                    except Exception as exc:
                        st.error("Não foi possível gerar o produto histórico selecionado.")
                        with st.expander("Detalhes técnicos"):
                            st.exception(exc)

                result = st.session_state.get("historical_map_result")
                if result is not None:
                    if result.get("request_spec") != request_spec:
                        st.info(
                            "ℹ️ Os parâmetros foram alterados desde o último mapa gerado. "
                            "Clique em **Gerar mapa** para atualizar a visualização."
                        )
                    else:
                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            _card("Produto", result["period_text"], result["mode"])
                        with c2:
                            _card("Recorte", result.get("location_label", "Brasil"), result.get("spatial_level", "Brasil"))
                        with c3:
                            _card(
                                "Variável",
                                VARIABLES[result["variable"]]["label"],
                                VARIABLES[result["variable"]]["unit"],
                            )
                        with c4:
                            _card(
                                "Períodos utilizados",
                                str(result["n_periods"]),
                                result["source_text"],
                            )

                        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                        st_folium(
                            result["map"],
                            width=None,
                            height=730,
                            returned_objects=[],
                            key=f"historical_map_render_{result['render_id']}",
                        )

                        st.markdown("**Downloads do produto**")
                        from shapely import from_wkb
                        result_geometry = (
                            from_wkb(bytes.fromhex(result["geometry_wkb_hex"]))
                            if result.get("geometry_wkb_hex") else None
                        )
                        figure_title = (
                            f"{VARIABLES[result['variable']]['label']} — {result['period_text']} — "
                            f"{result.get('location_label', 'Brasil')}"
                        )
                        png_bytes = _field_png(
                            result["lat"], result["lon"], result["field"],
                            variable=result["variable"], title=figure_title,
                            geometry=result_geometry, display_range=result["display_range"],
                        )
                        nc_bytes = _field_netcdf_bytes(
                            result["lat"], result["lon"], result["field"],
                            variable=result["variable"], title=figure_title,
                        )
                        d1, d2, d3, dspace = st.columns([1.1, 1.1, 1.1, 2.7])
                        with d1:
                            st.download_button(
                                "⬇️ Figura PNG", png_bytes,
                                file_name=f"flash_view_{_safe_filename(result['location_label'])}_{result['scale']}_{result['variable']}.png",
                                mime="image/png", width="stretch", key=f"map_png_{result['render_id']}",
                            )
                        with d3:
                            st.download_button(
                                "⬇️ Figura JPEG", to_jpeg(png_bytes),
                                file_name=f"flash_view_{_safe_filename(result['location_label'])}_{result['scale']}_{result['variable']}.jpg",
                                mime="image/jpeg", width="stretch",key=f"map_jpg_{result['render_id']}",
                            )
                        with d2:
                            st.download_button(
                                "⬇️ Dados NetCDF", nc_bytes,
                                file_name=f"flash_view_{_safe_filename(result['location_label'])}_{result['scale']}_{result['variable']}.nc",
                                mime="application/x-netcdf", width="stretch", key=f"map_nc_{result['render_id']}",
                            )

                        if result["variable"] == "flash_count":
                            st.caption(
                                "Nos mapas específicos, `flash_count` representa a contagem acumulada de flashes por célula "
                                "na escala selecionada. Nas climatologias, é apresentada a média entre os períodos utilizados. "
                                "O raster é recortado pelo limite administrativo selecionado usando os centros das células da grade; "
                                "a borda pode manter aspecto pixelizado devido à resolução espacial de aproximadamente 0,08°."
                            )
                        else:
                            st.caption(
                                "Energia, área e duração representam médias dos flashes. A climatologia é calculada com "
                                "ponderação por `flash_count`, preservando o método usado na agregação dos NetCDF. "
                                "O recorte espacial utiliza o limite administrativo selecionado e preserva a resolução original da grade."
                            )


# =============================================================================
# ABA 3 — SÉRIES TEMPORAIS
# =============================================================================
if tab_series.open:
    with tab_series:
        st.markdown('<div class="section-heading">Séries temporais</div>', unsafe_allow_html=True)
        st.caption(
            "Séries diárias, mensais ou anuais calculadas somente após você definir o período e clicar em "
            "**Calcular série**. A base histórica processada termina em 31/12/2022."
        )

        if historical_repo is None:
            _historical_unavailable()
        else:
            try:
                controls1, controls2, controls3 = st.columns([1.15, 1.0, 1.25])
                with controls1:
                    spatial_level = st.selectbox(
                        "Área",
                        ["Brasil", "Estado", "Município", "Retângulo", "Buffer circular"],
                        key="series_area",
                    )
                with controls2:
                    series_scale_label = st.selectbox(
                        "Escala temporal", ["Diária", "Mensal", "Anual"], key="series_scale"
                    )
                with controls3:
                    series_variable = st.selectbox(
                        "Variável",
                        list(VARIABLES),
                        format_func=lambda x: VARIABLES[x]["label"],
                        key="series_variable",
                    )
                series_scale = {"Diária": "daily", "Mensal": "monthly", "Anual": "yearly"}[series_scale_label]

                spatial_payload, spatial_valid = _spatial_details(spatial_level, "series")
                location_label = spatial_payload.get("location_label", "Brasil")
                location_key = (
                    spatial_level,
                    spatial_payload.get("uf"),
                    spatial_payload.get("code_muni"),
                    spatial_payload.get("geometry_wkb_hex"),
                )

                # -----------------------------------------------------------------
                # Período: nenhum NetCDF é lido aqui. O cálculo só ocorre no botão.
                # -----------------------------------------------------------------
                catalog_items = historical_repo.items(series_scale)
                if not catalog_items:
                    st.info(f"Nenhum produto {series_scale_label.lower()} foi encontrado na base configurada.")
                else:
                    available_dates = sorted({pd.Timestamp(x.date).normalize() for x in catalog_items})
                    min_available = available_dates[0]
                    max_available = min(available_dates[-1], HISTORICAL_MAX_DATE)

                    if series_scale == "daily":
                        default_start = max(min_available, max_available - pd.Timedelta(days=30))
                        p1, p2 = st.columns(2)
                        with p1:
                            start_value = st.date_input(
                                "Data inicial",
                                value=default_start.date(),
                                min_value=min_available.date(),
                                max_value=max_available.date(),
                                key="series_daily_start",
                            )
                        with p2:
                            end_value = st.date_input(
                                "Data final",
                                value=max_available.date(),
                                min_value=min_available.date(),
                                max_value=max_available.date(),
                                key="series_daily_end",
                            )
                        start_ts = pd.Timestamp(start_value)
                        end_ts = pd.Timestamp(end_value)

                    elif series_scale == "monthly":
                        month_items = sorted(catalog_items, key=lambda x: x.date)
                        month_labels = [f"{MONTH_NAMES_PT[x.month]}/{x.year}" for x in month_items]
                        label_to_date = {label: pd.Timestamp(item.date) for label, item in zip(month_labels, month_items)}
                        p1, p2 = st.columns(2)
                        with p1:
                            start_label = st.selectbox(
                                "Mês inicial", month_labels, index=len(month_labels) - 1, key="series_month_start"
                            )
                        with p2:
                            end_label = st.selectbox(
                                "Mês final", month_labels, index=len(month_labels) - 1, key="series_month_end"
                            )
                        start_ts = label_to_date[start_label]
                        # Fim do mês para incluir o item mensal selecionado.
                        end_month_start = label_to_date[end_label]
                        end_ts = min(end_month_start + pd.offsets.MonthEnd(0), HISTORICAL_MAX_DATE)

                    else:
                        years = sorted({x.year for x in catalog_items})
                        p1, p2 = st.columns(2)
                        with p1:
                            start_year = st.selectbox(
                                "Ano inicial", years, index=len(years) - 1, key="series_year_start"
                            )
                        with p2:
                            end_year = st.selectbox(
                                "Ano final", years, index=len(years) - 1, key="series_year_end"
                            )
                        start_ts = pd.Timestamp(int(start_year), 1, 1)
                        end_ts = min(pd.Timestamp(int(end_year), 12, 31), HISTORICAL_MAX_DATE)

                    period_ok = (start_ts <= end_ts) and bool(spatial_valid)
                    if not period_ok:
                        st.error("A data/período inicial deve ser anterior ou igual ao período final.")

                    # Alerta solicitado para consultas históricas acima de um mês.
                    spans_more_than_month = end_ts > (start_ts + pd.DateOffset(months=1))
                    if spans_more_than_month:
                        if series_scale == "daily":
                            n_est = len([x for x in catalog_items if start_ts <= x.date <= end_ts])
                            st.warning(
                                f"⏳ **Consulta histórica extensa:** o período selecionado ultrapassa um mês e pode "
                                f"demorar. Na escala diária, até **{n_est} arquivos NetCDF** podem precisar ser baixados "
                                "do Hugging Face e processados. Arquivos já baixados são reutilizados pelo cache."
                            )
                        else:
                            st.warning(
                                "⏳ **Consulta histórica extensa:** o período selecionado ultrapassa um mês. "
                                "O cálculo só será iniciado quando você clicar em **Calcular série** e pode levar algum tempo."
                            )

                    if series_scale == "daily":
                        n_daily = len([x for x in catalog_items if start_ts <= x.date <= end_ts])
                        if n_daily > 366:
                            period_ok = False
                            st.error(
                                f"Para proteger o servidor, séries diárias no site público são limitadas a 366 arquivos/dias "
                                f"por consulta (seleção atual: {n_daily}). Para períodos maiores, use a escala mensal."
                            )

                    request_signature = (
                        spatial_level,
                        location_key,
                        series_scale,
                        series_variable,
                        start_ts.strftime("%Y-%m-%d"),
                        end_ts.strftime("%Y-%m-%d"),
                    )

                    st.markdown("---")
                    st.markdown("**Ação da série temporal**")
                    calc_col, calc_space = st.columns([1.35, 4.65])
                    with calc_col:
                        calculate_series = st.button(
                            "📈 Calcular série",
                            type="primary",
                            width="stretch",
                            disabled=not period_ok,
                            key="calculate_historical_series",
                        )

                    if calculate_series:
                        with st.spinner("Calculando somente o período solicitado..."):
                            geometry = _geometry_from_payload(spatial_payload)
                            series = _series_cached(
                                historical_config,
                                geometry.wkb,
                                series_scale,
                                series_variable,
                                start_ts.strftime("%Y-%m-%d"),
                                end_ts.strftime("%Y-%m-%d"),
                            )
                        st.session_state["historical_series_result"] = series
                        st.session_state["historical_series_signature"] = request_signature
                        st.session_state["historical_series_location"] = location_label
                        st.session_state["historical_series_level"] = spatial_level

                    # Resultado só aparece se corresponder exatamente à consulta atual.
                    if st.session_state.get("historical_series_signature") == request_signature:
                        series = st.session_state.get("historical_series_result", pd.DataFrame())
                        valid = series[np.isfinite(series["value"])].copy() if not series.empty else pd.DataFrame()

                        if valid.empty:
                            st.warning(
                                "Não há células válidas da grade para a combinação/período selecionado. "
                                "Isso pode ocorrer principalmente em municípios muito pequenos ou em períodos ausentes."
                            )
                        else:
                            mean_value = float(valid["value"].mean())
                            max_idx = valid["value"].idxmax()
                            max_row = valid.loc[max_idx]
                            max_date = pd.Timestamp(max_row["date"])
                            if series_scale == "daily":
                                max_period = max_date.strftime("%d/%m/%Y")
                            elif series_scale == "monthly":
                                max_period = f"{MONTH_NAMES_PT[max_date.month]}/{max_date.year}"
                            else:
                                max_period = str(max_date.year)

                            c1, c2, c3 = st.columns(3)
                            with c1:
                                _card("Local", location_label, spatial_level)
                            with c2:
                                _card(
                                    "Média da série",
                                    format_value(mean_value, series_variable),
                                    VARIABLES[series_variable]["label"],
                                )
                            with c3:
                                _card(
                                    "Máximo da série",
                                    format_value(float(max_row["value"]), series_variable),
                                    max_period,
                                )

                            plot = valid.copy()
                            if series_scale in {"daily", "monthly"}:
                                plot["x"] = pd.to_datetime(plot["date"])
                            else:
                                plot["x"] = plot["year"].astype(int)

                            if series_scale == "daily":
                                hover = "%{x|%d/%m/%Y}<br>Valor: %{y:,.3g}<extra></extra>"
                            elif series_scale == "monthly":
                                hover = "%{x|%m/%Y}<br>Valor: %{y:,.3g}<extra></extra>"
                            else:
                                hover = "Ano: %{x}<br>Valor: %{y:,.3g}<extra></extra>"

                            fig = go.Figure()
                            fig.add_trace(
                                go.Scatter(
                                    x=plot["x"],
                                    y=plot["value"],
                                    mode="lines+markers",
                                    name=VARIABLES[series_variable]["short"],
                                    hovertemplate=hover,
                                )
                            )
                            fig.update_layout(
                                title=f"{VARIABLES[series_variable]['label']} — {location_label}",
                                xaxis_title="Período",
                                yaxis_title=f"{VARIABLES[series_variable]['label']} ({VARIABLES[series_variable]['unit']})",
                                hovermode="x unified",
                                height=520,
                                margin=dict(l=20, r=20, t=70, b=20),
                            )
                            fig.update_layout(template="plotly_dark",paper_bgcolor="#101c2b",
                                              plot_bgcolor="#14253a",font_color="#e4eef9")
                            if series_variable == "flash_count":
                                fig.update_yaxes(rangemode="tozero")
                            st.plotly_chart(fig, width="stretch", config={"displaylogo": False})

                            st.markdown("---")
                            st.markdown("**Downloads da série**")
                            png_bytes = _series_figure_png(
                                valid,
                                scale=series_scale,
                                variable=series_variable,
                                location_label=location_label,
                            )
                            csv_bytes = _series_csv_bytes(valid)
                            d1, d2, d3, dspace = st.columns([1.35, 1.35, 1.35, 2.0])
                            with d1:
                                st.download_button(
                                    "⬇️ Figura PNG",
                                    data=png_bytes,
                                    file_name=(
                                        f"flash_view_{_safe_filename(location_label)}_"
                                        f"{series_scale}_{series_variable}.png"
                                    ),
                                    mime="image/png",
                                    width="stretch",
                                )
                            with d3:
                                st.download_button(
                                    "⬇️ Figura JPEG", data=to_jpeg(png_bytes),
                                    file_name=(f"flash_view_{_safe_filename(location_label)}_"
                                               f"{series_scale}_{series_variable}.jpg"),
                                    mime="image/jpeg",width="stretch",
                                )
                            with d2:
                                st.download_button(
                                    "⬇️ Dados CSV",
                                    data=csv_bytes,
                                    file_name=(
                                        f"flash_view_{_safe_filename(location_label)}_"
                                        f"{series_scale}_{series_variable}.csv"
                                    ),
                                    mime="text/csv",
                                    width="stretch",
                                )

                            if series_variable == "flash_count":
                                st.caption(
                                    "Para número de flashes, cada ponto da série é a **soma** de `flash_count` "
                                    "das células incluídas na área selecionada."
                                )
                            else:
                                st.caption(
                                    "Energia, área e duração são calculadas por **média ponderada por `flash_count`** "
                                    "nas células incluídas na área selecionada."
                                )
                    else:
                        st.caption("Defina os parâmetros acima e clique em **Calcular série** para iniciar o processamento.")

            except Exception as exc:
                st.error("Não foi possível configurar ou gerar a série temporal selecionada.")
                with st.expander("Detalhes técnicos"):
                    st.exception(exc)



# =============================================================================
# ABA 4 — RANKING ADMINISTRATIVO
# =============================================================================
if tab_rank.open:
    with tab_rank:
        st.markdown('<div class="section-heading">Ranking de incidência de relâmpagos</div>', unsafe_allow_html=True)
        st.caption(
            "Ranking calculado a partir de produtos administrativos pré-processados. "
            "Isso evita varrer milhares de NetCDF durante o acesso ao site."
        )
        st.info(
            "💡 Para comparar municípios ou estados de tamanhos diferentes, a métrica recomendada é "
            "**densidade de flashes (flashes/km²)**. O número total de flashes também está disponível."
        )

        if historical_repo is None:
            _historical_unavailable()
        else:
            r1, r2, r3, r4 = st.columns([1.0, 1.0, 1.25, 0.9])
            with r1:
                rank_level_label = st.selectbox("Ranking de", ["Municípios", "Estados"], key="rank_level")
            with r2:
                rank_scale_label = st.selectbox("Escala-base", ["Mensal", "Anual"], key="rank_scale")
            with r3:
                rank_metric_label = st.selectbox(
                    "Métrica",
                    ["Densidade de flashes", "Número total de flashes"],
                    key="rank_metric",
                )
            with r4:
                top_n = st.slider("Top", 5, 30, 10, 5, key="rank_top_n")

            rank_level = "municipality" if rank_level_label == "Municípios" else "state"
            rank_scale = "monthly" if rank_scale_label == "Mensal" else "yearly"
            rank_metric = "flash_density" if rank_metric_label == "Densidade de flashes" else "flash_count"
            rank_uf = None

            if rank_level == "municipality":
                region_mode = st.radio(
                    "Área do ranking",
                    ["Brasil", "Somente um estado"],
                    horizontal=True,
                    key="rank_region_mode",
                )
                if region_mode == "Somente um estado":
                    states = load_states(2022)
                    lookup = {f"{r.abbrev_state} — {r.name_state}": r.abbrev_state for r in states.itertuples()}
                    chosen_rank_state = st.selectbox("Estado", list(lookup), key="rank_state_filter")
                    rank_uf = lookup[chosen_rank_state]

            rank_items = historical_repo.items(rank_scale)
            if not rank_items:
                st.warning("Não há períodos disponíveis para a escala escolhida.")
            else:
                if rank_scale == "monthly":
                    rank_items = sorted(rank_items, key=lambda x: x.date)
                    labels = [f"{MONTH_NAMES_PT[x.month]}/{x.year}" for x in rank_items]
                    to_date = {label: pd.Timestamp(item.date) for label, item in zip(labels, rank_items)}
                    c1, c2 = st.columns(2)
                    with c1:
                        rank_start_label = st.selectbox("Mês inicial", labels, index=0, key="rank_start_month")
                    with c2:
                        rank_end_label = st.selectbox("Mês final", labels, index=len(labels)-1, key="rank_end_month")
                    rank_start = to_date[rank_start_label]
                    rank_end = to_date[rank_end_label]
                else:
                    years = sorted({x.year for x in rank_items})
                    c1, c2 = st.columns(2)
                    with c1:
                        rank_start_year = st.selectbox("Ano inicial", years, index=0, key="rank_start_year")
                    with c2:
                        rank_end_year = st.selectbox("Ano final", years, index=len(years)-1, key="rank_end_year")
                    rank_start = pd.Timestamp(int(rank_start_year), 1, 1)
                    rank_end = pd.Timestamp(int(rank_end_year), 12, 31)

                rank_signature = (
                    rank_level, rank_scale, rank_metric, rank_uf,
                    rank_start.strftime("%Y-%m-%d"), rank_end.strftime("%Y-%m-%d"), int(top_n),
                )

                bc1, bc2, bc3 = st.columns([0.34, 0.32, 0.34])
                with bc2:
                    run_rank = st.button("🏆 Gerar ranking", type="primary", width="stretch", key="run_rank")

                if run_rank:
                    if rank_start > rank_end:
                        st.error("O período inicial deve ser anterior ao período final.")
                    else:
                        try:
                            with st.spinner("Consultando produto administrativo pré-processado..."):
                                rank_source = _ranking_data(historical_config, rank_level, rank_scale)
                                rank_df = rank_dataframe(
                                    rank_source,
                                    level=rank_level,
                                    start=rank_start,
                                    end=rank_end,
                                    metric=rank_metric,
                                    uf=rank_uf,
                                    top_n=top_n,
                                )
                            st.session_state["ranking_result"] = rank_df
                            st.session_state["ranking_signature"] = rank_signature
                        except FileNotFoundError as exc:
                            st.error(
                                "O produto de ranking ainda não foi encontrado em **05_RANKINGS**. "
                                "Processe os arquivos administrativos com o script fornecido e envie os Parquet para o Dataset."
                            )
                            with st.expander("Detalhes técnicos"):
                                st.exception(exc)
                        except Exception as exc:
                            st.error("Não foi possível gerar o ranking selecionado.")
                            with st.expander("Detalhes técnicos"):
                                st.exception(exc)

                if st.session_state.get("ranking_signature") == rank_signature:
                    rank_df = st.session_state.get("ranking_result", pd.DataFrame())
                    if rank_df.empty:
                        st.warning("Nenhum registro foi encontrado para a combinação selecionada.")
                    else:
                        display = rank_df.copy()
                        if rank_level == "municipality":
                            display["Local"] = display["municipality_name"] + " (" + display["state_abbrev"] + ")"
                        else:
                            display["Local"] = display["state_name"] + " (" + display["state_abbrev"] + ")"

                        if rank_metric == "flash_density":
                            display["Valor"] = display["flash_density"]
                            y_title = "Flashes/km²"
                        else:
                            display["Valor"] = display["flash_count"]
                            y_title = "Flashes"

                        fig_rank = go.Figure(go.Bar(
                            x=display["Valor"],
                            y=display["Local"],
                            orientation="h",
                            text=[f"{v:,.2f}" if rank_metric == "flash_density" else f"{v:,.0f}" for v in display["Valor"]],
                            textposition="auto",
                        ))
                        fig_rank.update_layout(
                            title=f"Top {len(display)} — {rank_metric_label}",
                            xaxis_title=y_title,
                            yaxis_title="",
                            height=max(430, 34 * len(display) + 170),
                            margin=dict(l=20, r=20, t=70, b=30),
                            yaxis={"autorange": "reversed"},
                        )
                        fig_rank.update_layout(template="plotly_dark",
                            paper_bgcolor="#101c2b",plot_bgcolor="#14253a",font_color="#e4eef9")
                        st.plotly_chart(fig_rank, width="stretch", config={"displaylogo": False})

                        table_cols = ["rank", "Local", "flash_count", "flash_density", "area_km2"]
                        st.dataframe(
                            display[table_cols].rename(columns={
                                "rank": "Posição",
                                "flash_count": "Flashes",
                                "flash_density": "Flashes/km²",
                                "area_km2": "Área (km²)",
                            }),
                            width="stretch",
                            hide_index=True,
                        )
                        rank_png = render_ranking_png(display,
                            title=f"Flash View | Top {len(display)} — {rank_metric_label}")
                        rk1,rk2,rk3=st.columns(3)
                        rk1.download_button("⬇️ Ranking PNG",rank_png,
                            file_name="flash_view_ranking.png",mime="image/png",key="fv_rank_png")
                        rk2.download_button("⬇️ Ranking JPEG",to_jpeg(rank_png),
                            file_name="flash_view_ranking.jpg",mime="image/jpeg",key="fv_rank_jpg")
                        st.download_button(
                            "⬇️ Baixar ranking (CSV)",
                            display.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"flash_view_ranking_{rank_level}_{rank_scale}.csv",
                            mime="text/csv",
                            key="download_ranking_csv",
                        )

    # =============================================================================
    # RODAPÉ
    # =============================================================================
    st.markdown("---")
    st.caption(
        "Flash View • Dados de relâmpagos do Geostationary Lightning Mapper (GLM) / NOAA. "
        "Monitoramento quase em tempo real e análise histórica em uma única interface."
    )
