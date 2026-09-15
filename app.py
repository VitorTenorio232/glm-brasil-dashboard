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
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.realtime_glm import AGE_GROUPS, build_live_map, fetch_live_snapshot, group_counts
from src.historical_glm import (
    MONTH_NAMES_PT,
    VARIABLES,
    HISTORICAL_MAX_DATE,
    HistoricalGLMRepository,
    SourceConfig,
    build_historical_map,
    format_value,
    get_municipality_geometry,
    get_state_geometry,
    load_country,
    load_municipalities,
    load_states,
    make_source_config,
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

    .fv-header { padding: 0.15rem 0 0.9rem 0; }
    .fv-title {
        margin: 0;
        font-size: 2.55rem;
        line-height: 1.05;
        font-weight: 820;
        letter-spacing: -0.045rem;
        color: #0f172a;
    }
    .fv-subtitle {
        margin-top: 0.45rem;
        color: #64748b;
        font-size: 1.02rem;
    }

    .metric-card {
        background: #ffffff;
        border: 1px solid #e6eaf0;
        border-radius: 14px;
        padding: 18px 20px 17px 20px;
        min-height: 118px;
        box-shadow: 0 4px 15px rgba(15, 23, 42, 0.07);
    }
    .metric-card-label {
        color: #64748b;
        font-size: 0.88rem;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .metric-card-value {
        color: #0f172a;
        font-size: 1.82rem;
        line-height: 1.08;
        font-weight: 730;
        white-space: normal;
    }
    .metric-card-small {
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
    hf_repo = _secret("FLASH_VIEW_HF_REPO") or os.getenv("FLASH_VIEW_HF_REPO")
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


@st.cache_data(ttl=3600, show_spinner=False)
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


@st.cache_data(ttl=3600, show_spinner=False)
def _climatology_field(config: SourceConfig, scale: str, month: int | None, years: tuple[int, ...], variable: str):
    repo = HistoricalGLMRepository(config)
    if scale == "monthly":
        items = [repo.get_monthly(y, int(month)) for y in years]
    else:
        items = [repo.get_yearly(y) for y in years]
    lat, lon, data, n = repo.climatology(items, variable)
    return lat, lon, data, n


@st.cache_data(ttl=3600, show_spinner=False)
def _states_geojson() -> dict | None:
    try:
        states = load_states(2022).copy()
        states["geometry"] = states.geometry.simplify(0.025, preserve_topology=True)
        return json.loads(states.to_json())
    except Exception:
        return None




@st.cache_resource(show_spinner=False)
def _country_geometry_safe():
    # Sem geometria administrativa, o raster do Brasil não deve ser mostrado
    # como um retângulo. Primeiro tenta read_country; depois, a união das UFs.
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
                "Verifique se geobr, geopandas e shapely estão instalados."
            ) from exc

@st.cache_data(ttl=3600, show_spinner=False)
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


# =============================================================================
# CABEÇALHO
# =============================================================================
st.markdown(
    """
    <div class="fv-header">
        <h1 class="fv-title">⚡ Flash View</h1>
        <div class="fv-subtitle">
            Monitoramento e análise de relâmpagos com dados do Geostationary Lightning Mapper (GLM) sobre o Brasil
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# 3 ABAS PRINCIPAIS
# =============================================================================
tab_live, tab_clim, tab_series = st.tabs(
    [
        "⚡ Relâmpagos em tempo real",
        "🌦️ Climatologia",
        "📈 Séries temporais",
    ]
)


# =============================================================================
# ABA 1 — RELÂMPAGOS EM TEMPO REAL
# =============================================================================
@st.cache_data(ttl=50, show_spinner=False)
def _load_snapshot():
    return fetch_live_snapshot(window_minutes=30, quality="zero_only")


@st.fragment(run_every="60s")
def _live_panel():
    action_left, action_right = st.columns([0.84, 0.16])
    with action_left:
        st.caption(
            "Últimos 30 minutos disponíveis do produto GLM-L2-LCFA do GOES-19. "
            "Atualização automática a cada 60 segundos."
        )
    with action_right:
        if st.button("🔄 Atualizar agora", width="stretch", key="refresh_live"):
            _load_snapshot.clear()

    try:
        with st.spinner("Buscando os dados GLM mais recentes..."):
            snapshot = _load_snapshot()
    except Exception as exc:
        st.error("Não foi possível obter os dados GLM mais recentes.")
        with st.expander("Detalhes técnicos"):
            st.exception(exc)
        return

    counts = group_counts(snapshot.flashes)

    window_start_local = _local_time(snapshot.window_start_utc)
    observation_end_local = _local_time(snapshot.observation_end_utc)

    c1, c2, c3 = st.columns(3)
    with c1:
        _card("Flashes", _fmt_int(len(snapshot.flashes)), "Intervalo de 30 minutos")
    with c2:
        _card("Satélite", "GOES-19", "Geostationary Lightning Mapper")
    with c3:
        _card(
            "Última atualização",
            observation_end_local.strftime("%d/%m/%Y %H:%M:%S"),
            "Horário local de Brasília",
        )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.caption(
        "Intervalo disponível (horário local): "
        f"{window_start_local.strftime('%d/%m/%Y %H:%M:%S')} → "
        f"{observation_end_local.strftime('%d/%m/%Y %H:%M:%S')}"
    )

    if snapshot.latency_minutes > 10:
        st.warning(
            "⚠️ O último arquivo disponível está desatualizado em relação ao horário atual. "
            "Confira o horário exibido em **Última atualização**."
        )

    st.markdown('<div class="section-heading">Mapa interativo</div>', unsafe_allow_html=True)
    if snapshot.flashes.empty:
        st.warning(
            "Nenhum flash com quality_flag=0 foi encontrado no recorte do Brasil "
            "durante o intervalor disponível."
        )

    mapa = build_live_map(snapshot.flashes)
    st_folium(
        mapa,
        width=None,
        height=730,
        returned_objects=[],
        key=f"flash_view_live_{snapshot.observation_end_utc:%Y%m%d%H%M}",
    )

    st.markdown('<div class="section-heading">Atividade por faixa temporal</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, (label, _, _, color) in zip(cols, AGE_GROUPS):
        with col:
            _time_card(label, counts[label], color)

    st.caption(
        "As faixas de tempo são calculadas a partir do horário do dado GLM mais recente disponível. "
        "Os pontos representam centroides dos flashes identificados no produto GLM-L2-LCFA."
    )


with tab_live:
    _live_panel()


# =============================================================================
# FONTE HISTÓRICA
# =============================================================================
historical_config = _historical_config()
historical_repo = None
historical_error = None
if historical_config.mode != "none":
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
if historical_repo is not None and historical_config.mode == "huggingface":
    st.caption(f"Base histórica: Hugging Face Dataset · {historical_config.hf_repo}")


# =============================================================================
# ABA 2 — CLIMATOLOGIA / MAPAS HISTÓRICOS
# =============================================================================
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

        area_col, mode_col, scale_col, var_col = st.columns([1.0, 1.05, 0.9, 1.25])
        with area_col:
            spatial_level = st.selectbox(
                "Recorte espacial",
                ["Brasil", "Estado", "Município"],
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

        # O recorte padrão é Brasil. Estado e município só carregam suas geometrias
        # quando o usuário escolhe explicitamente essas opções.
        spatial_payload = {"spatial_level": spatial_level, "uf": None, "code_muni": None, "location_label": "Brasil"}
        if spatial_level == "Estado":
            states = load_states(2022)
            state_lookup = {
                f"{row.abbrev_state} — {row.name_state}": row.abbrev_state
                for row in states.itertuples()
            }
            chosen_state = st.selectbox("Estado", list(state_lookup), key="clim_state")
            spatial_payload["uf"] = state_lookup[chosen_state]
            spatial_payload["location_label"] = chosen_state
        elif spatial_level == "Município":
            states = load_states(2022)
            state_lookup = {
                f"{row.abbrev_state} — {row.name_state}": row.abbrev_state
                for row in states.itertuples()
            }
            c_uf, c_muni = st.columns([0.8, 1.2])
            with c_uf:
                chosen_state = st.selectbox("Estado", list(state_lookup), key="clim_muni_state")
            uf = state_lookup[chosen_state]
            with st.spinner("Carregando municípios..."):
                municipalities = load_municipalities(uf, 2022)
            muni_lookup = {
                f"{row.name_muni} ({uf})": str(row.code_muni)
                for row in municipalities.itertuples()
            }
            with c_muni:
                chosen_muni = st.selectbox("Município", list(muni_lookup), key="clim_muni")
            spatial_payload["uf"] = uf
            spatial_payload["code_muni"] = muni_lookup[chosen_muni]
            spatial_payload["location_label"] = chosen_muni
            st.caption(
                "O recorte municipal respeita a grade de aproximadamente 0,08°. Em municípios muito pequenos, "
                "poucas células podem representar a área selecionada."
            )

        request_spec = None
        request_payload = None
        selection_valid = True

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
                    if spatial_level_now == "Estado":
                        clip_geometry = get_state_geometry(request_payload["uf"], 2022)
                        boundary_name = f"Limite — {location_label}"
                        context_geojson = None
                    elif spatial_level_now == "Município":
                        clip_geometry = get_municipality_geometry(
                            request_payload["code_muni"], request_payload["uf"], 2022
                        )
                        boundary_name = f"Limite — {location_label}"
                        context_geojson = None
                    else:
                        clip_geometry = _country_geometry_safe()
                        boundary_name = "Limite do Brasil"
                        context_geojson = _states_geojson()

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
            controls1, controls2, controls3 = st.columns([1.0, 1.0, 1.25])
            with controls1:
                spatial_level = st.selectbox("Área", ["Brasil", "Estado", "Município"], key="series_area")
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

            location_label = "Brasil"
            location_key = ("Brasil",)

            if spatial_level == "Estado":
                states = load_states(2022)
                state_lookup = {
                    f"{row.abbrev_state} — {row.name_state}": row.abbrev_state
                    for row in states.itertuples()
                }
                chosen = st.selectbox("Estado", list(state_lookup), key="series_state")
                uf = state_lookup[chosen]
                location_label = chosen
                location_key = ("Estado", uf)

            elif spatial_level == "Município":
                states = load_states(2022)
                state_lookup = {
                    f"{row.abbrev_state} — {row.name_state}": row.abbrev_state
                    for row in states.itertuples()
                }
                chosen_state = st.selectbox("Estado", list(state_lookup), key="series_muni_state")
                uf = state_lookup[chosen_state]
                with st.spinner("Carregando municípios..."):
                    municipalities = load_municipalities(uf, 2022)
                muni_lookup = {
                    f"{row.name_muni} ({uf})": str(row.code_muni)
                    for row in municipalities.itertuples()
                }
                chosen_muni = st.selectbox("Município", list(muni_lookup), key="series_muni")
                code_muni = muni_lookup[chosen_muni]
                location_label = chosen_muni
                location_key = ("Município", uf, code_muni)
                st.info(
                    "ℹ️ A base histórica está em grade de aproximadamente 0,08°. Para municípios, o valor é "
                    "calculado pelas células cujo centro está dentro do limite municipal; municípios muito pequenos "
                    "podem ter representação limitada pela resolução da grade."
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

                period_ok = start_ts <= end_ts
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
                        if spatial_level == "Brasil":
                            geometry = load_country(2022)
                        elif spatial_level == "Estado":
                            geometry = get_state_geometry(location_key[1], 2022)
                        else:
                            geometry = get_municipality_geometry(location_key[2], location_key[1], 2022)

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
                        if series_variable == "flash_count":
                            fig.update_yaxes(rangemode="tozero")
                        st.plotly_chart(fig, width="stretch", config={"displaylogo": False})

                        st.markdown("---")
                        st.markdown("**Download da figura**")
                        png_bytes = _series_figure_png(
                            valid,
                            scale=series_scale,
                            variable=series_variable,
                            location_label=location_label,
                        )
                        download_col, download_space = st.columns([1.55, 4.45])
                        with download_col:
                            st.download_button(
                                "⬇️ Baixar figura (PNG)",
                                data=png_bytes,
                                file_name=(
                                    f"flash_view_{_safe_filename(location_label)}_"
                                    f"{series_scale}_{series_variable}.png"
                                ),
                                mime="image/png",
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
# RODAPÉ
# =============================================================================
st.markdown("---")
st.caption(
    "Flash View • Dados de relâmpagos do Geostationary Lightning Mapper (GLM) / NOAA. "
    "Monitoramento quase em tempo real e análise histórica em uma única interface."
)
