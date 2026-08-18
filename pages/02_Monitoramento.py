from __future__ import annotations

import streamlit as st
from streamlit_folium import st_folium

from src.realtime_glm import AGE_GROUPS, build_live_map, fetch_live_snapshot, group_counts

st.set_page_config(page_title="Tempo real GLM", page_icon="📡", layout="wide")
st.title("📡 Monitoramento GLM — últimos 30 minutos")
st.caption(
    "Dados GLM-L2-LCFA do GOES-19 obtidos diretamente do NOAA Open Data Dissemination / AWS. "
    "A página atualiza automaticamente a cada 60 segundos."
)


@st.cache_data(ttl=50, show_spinner=False)
def _load_snapshot():
    return fetch_live_snapshot(window_minutes=30, quality="zero_only")


@st.fragment(run_every="60s")
def live_panel():
    top_a, top_b = st.columns([0.82, 0.18])
    with top_b:
        if st.button("🔄 Atualizar agora", use_container_width=True):
            _load_snapshot.clear()

    try:
        with st.spinner("Buscando os arquivos GLM mais recentes no NOAA/AWS..."):
            snapshot = _load_snapshot()
    except Exception as exc:
        st.error("Não foi possível obter os dados GLM em tempo real.")
        st.exception(exc)
        st.info(
            "O módulo histórico permanece independente. Se a NOAA/AWS estiver temporariamente indisponível, "
            "esta página voltará a funcionar quando novos arquivos GLM forem publicados."
        )
        return

    counts = group_counts(snapshot.flashes)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Flashes em 30 min", f"{len(snapshot.flashes):,}".replace(",", "."))
    c2.metric("Arquivos LCFA", f"{snapshot.source_files:,}".replace(",", "."))
    c3.metric("Satélite", "GOES-19")
    c4.metric("Último dado UTC", snapshot.observation_end_utc.strftime("%H:%M:%S"))
    c5.metric("Latência", f"{snapshot.latency_minutes:.1f} min")

    if snapshot.latency_minutes > 10:
        st.warning(
            "⚠️ O arquivo GLM mais recente disponível está atrasado em relação ao relógio atual. "
            "O mapa continua mostrando os últimos 30 minutos **disponíveis**, mas a fonte não está atualizada em tempo real."
        )
    elif snapshot.latency_minutes > 5:
        st.info("ℹ️ Há alguns minutos de latência na publicação dos arquivos GLM.")

    st.caption(
        "Janela disponível: "
        f"{snapshot.window_start_utc.strftime('%d/%m/%Y %H:%M:%S')} → "
        f"{snapshot.observation_end_utc.strftime('%d/%m/%Y %H:%M:%S')} UTC"
    )

    st.markdown("#### Atividade por faixa temporal")
    cols = st.columns(4)
    for col, (label, _, _, color) in zip(cols, AGE_GROUPS):
        with col:
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:2px'>"
                f"<span style='width:11px;height:11px;border-radius:50%;background:{color};display:inline-block'></span>"
                f"<b>{label}</b></div>",
                unsafe_allow_html=True,
            )
            st.metric("Flashes", f"{counts[label]:,}".replace(",", "."), label_visibility="collapsed")

    st.markdown("#### Mapa interativo")
    if snapshot.flashes.empty:
        st.warning("Nenhum flash com quality_flag=0 foi encontrado no recorte do Brasil nessa janela de 30 minutos.")
    mapa = build_live_map(snapshot.flashes)
    st_folium(
        mapa,
        use_container_width=True,
        height=730,
        returned_objects=[],
        key=f"glm_live_{snapshot.observation_end_utc:%Y%m%d%H%M}",
    )

    st.caption(
        "🔴 0–5 min • 🔵 5–10 min • 🟢 10–20 min • 🟡 20–30 min. "
        "As faixas são calculadas em relação ao horário do arquivo GLM mais recente disponível. "
        "Os pontos representam centroides de flashes do produto GLM-L2-LCFA."
    )


live_panel()
