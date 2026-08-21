from __future__ import annotations

import html

import streamlit as st
from streamlit_folium import st_folium

from src.realtime_glm import AGE_GROUPS, build_live_map, fetch_live_snapshot, group_counts


# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="LUME-GLM",
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
    /* Remove a navegação lateral antiga: o LUME-GLM usa somente as três abas. */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    .block-container {
        max-width: 1550px;
        padding-top: 1.25rem;
        padding-bottom: 2.5rem;
    }

    .lume-header {
        padding: 0.2rem 0 0.85rem 0;
    }

    .lume-title {
        margin: 0;
        font-size: 2.55rem;
        line-height: 1.05;
        font-weight: 800;
        letter-spacing: -0.04rem;
        color: #0f172a;
    }

    .lume-subtitle {
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
        font-size: 1.95rem;
        line-height: 1.05;
        font-weight: 700;
        white-space: nowrap;
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
        margin-top: 0.25rem;
        margin-bottom: 0.75rem;
        color: #0f172a;
        font-size: 1.35rem;
        font-weight: 750;
    }

    .coming-soon {
        margin-top: 1rem;
        padding: 24px;
        background: linear-gradient(135deg, #f8fafc, #f1f5f9);
        border: 1px solid #e2e8f0;
        border-radius: 14px;
    }

    .coming-soon h3 {
        margin-top: 0;
        color: #0f172a;
    }

    .coming-soon p {
        color: #64748b;
        margin-bottom: 0;
    }

    /* Aba com visual mais compacto e semelhante a painel. */
    button[data-baseweb="tab"] p {
        font-size: 1rem;
        font-weight: 650;
    }

    div[data-testid="stHorizontalBlock"] {
        gap: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# HELPERS VISUAIS
# =============================================================================
def _fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _card(label: str, value: str, small: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-card-label">{html.escape(label)}</div>
            <div class="metric-card-value">{html.escape(value)}</div>
            {f'<div class="metric-card-small">{html.escape(small)}</div>' if small else ''}
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


# =============================================================================
# CABEÇALHO
# =============================================================================
st.markdown(
    """
    <div class="lume-header">
        <h1 class="lume-title">⚡ LUME-GLM</h1>
        <div class="lume-subtitle">
            Monitoramento e análise de relâmpagos com dados do Geostationary Lightning Mapper (GLM) sobre o Brasil
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# APENAS 3 ABAS PRINCIPAIS
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
        if st.button("🔄 Atualizar agora", use_container_width=True, key="refresh_live"):
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

    # -------------------------------------------------------------------------
    # CARDS PRINCIPAIS — estilo Power BI
    # -------------------------------------------------------------------------
    c1, c2, c3 = st.columns(3)
    with c1:
        _card(
            "Flashes Totais",
            _fmt_int(len(snapshot.flashes)),
            "Janela móvel de 30 minutos",
        )
    with c2:
        _card(
            "Satélite",
            "GOES-19",
            "Geostationary Lightning Mapper",
        )
    with c3:
        _card(
            "Último dado UTC",
            snapshot.observation_end_utc.strftime("%d/%m/%Y %H:%M:%S UTC"),
            "Horário do arquivo GLM mais recente disponível",
        )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.caption(
        "Janela disponível: "
        f"{snapshot.window_start_utc.strftime('%d/%m/%Y %H:%M:%S')} → "
        f"{snapshot.observation_end_utc.strftime('%d/%m/%Y %H:%M:%S')} UTC"
    )

    # Transparência sobre eventual interrupção da fonte sem exibir a métrica de latência.
    if snapshot.latency_minutes > 10:
        st.warning(
            "⚠️ O último arquivo disponível está desatualizado em relação ao horário atual. "
            "Confira o horário exibido em **Último dado UTC**."
        )

    # -------------------------------------------------------------------------
    # MAPA PRIMEIRO
    # -------------------------------------------------------------------------
    st.markdown('<div class="section-heading">Mapa interativo</div>', unsafe_allow_html=True)

    if snapshot.flashes.empty:
        st.warning(
            "Nenhum flash com quality_flag=0 foi encontrado no recorte do Brasil "
            "durante a janela disponível."
        )

    mapa = build_live_map(snapshot.flashes)
    st_folium(
        mapa,
        use_container_width=True,
        height=730,
        returned_objects=[],
        key=f"lume_glm_live_{snapshot.observation_end_utc:%Y%m%d%H%M}",
    )

    # -------------------------------------------------------------------------
    # RESULTADOS POR FAIXA ABAIXO DO MAPA
    # -------------------------------------------------------------------------
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
# ABA 2 — CLIMATOLOGIA
# =============================================================================
with tab_clim:
    st.markdown(
        """
        <div class="coming-soon">
            <h3>🌦️ Climatologia — Em breve</h3>
            <p>
                Esta área será habilitada quando a base histórica processada do GLM estiver disponível.
                O módulo será preparado para climatologias mensais e anuais, com mapas interativos e
                produtos estáticos para município, estado e Brasil.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Produtos planejados")
    p1, p2, p3 = st.columns(3)
    with p1:
        _card("Climatologia mensal", "Em breve", "Médias por mês")
    with p2:
        _card("Climatologia anual", "Em breve", "Síntese por ano")
    with p3:
        _card("Mapas", "Em breve", "Interativos e estáticos")


# =============================================================================
# ABA 3 — SÉRIES TEMPORAIS
# =============================================================================
with tab_series:
    st.markdown(
        """
        <div class="coming-soon">
            <h3>📈 Séries temporais — Em breve</h3>
            <p>
                O módulo utilizará a base histórica processada para gerar séries mensais e anuais
                de flashes, com seleção espacial por estado, município ou Brasil e visualização
                em gráficos interativos.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Estrutura planejada")
    p1, p2, p3 = st.columns(3)
    with p1:
        _card("Estado", "Em breve", "Séries mensais e anuais")
    with p2:
        _card("Município", "Em breve", "Séries mensais e anuais")
    with p3:
        _card("Brasil", "Em breve", "Séries mensais e anuais")
