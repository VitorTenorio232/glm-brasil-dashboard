from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
import json
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from shapely.geometry import shape

from src.v4_repository import FlashesRepository
from src.v4_analysis import calculate_analysis, area_km2, filter_by_geometry, MONTH_NAMES
from src.v4_maps import build_draw_map, build_analysis_map
from src.v4_ui import load_municipalities_web, format_int, format_float, geometry_path

st.set_page_config(page_title="GLM Brasil V4", page_icon="⚡", layout="wide")

st.title("⚡ GLM Brasil — Análise espacial de relâmpagos")
st.caption(
    "Selecione Município, Estado ou uma Região personalizada; escolha o período; "
    "e o sistema calcula os produtos GLM para exatamente essa área."
)

# -----------------------------------------------------------------------------
# HISTÓRICO: aguardando a base processada
# -----------------------------------------------------------------------------
HISTORICAL_ANALYSIS_AVAILABLE = False

if not HISTORICAL_ANALYSIS_AVAILABLE:
    st.info(
        "🚧 **Análises históricas — Em breve.** A base GLM processada está sendo preparada "
        "e este módulo será habilitado assim que os arquivos estiverem disponíveis."
    )
    st.success(
        "📡 O **Monitoramento GLM em tempo real** já está disponível com os últimos 30 minutos."
    )
    st.page_link(
        "pages/02_Monitoramento.py",
        label="Abrir monitoramento em tempo real",
        icon="📡",
        use_container_width=True,
    )
    st.stop()

repo = FlashesRepository()
if not repo.exists():
    st.error("A base de flashes individuais ainda não está disponível.")
    st.code(
        "python scripts/process_glm.py --raw-dir data/raw "
        "--municipalities data/municipalities/municipios_brasil.gpkg "
        "--output data/processed --save-flashes"
    )
    st.stop()

try:
    tmin, tmax = repo.available_range()
except Exception as exc:
    st.error("Não foi possível identificar o período disponível na base de flashes.")
    st.exception(exc)
    st.stop()

muni = load_municipalities_web()

# -----------------------------------------------------------------------------
# 1) SELEÇÃO DA ÁREA
# -----------------------------------------------------------------------------
st.sidebar.header("1. Área de análise")
selection_type = st.sidebar.radio(
    "Tipo de área",
    ["Município", "Estado", "Região personalizada"],
    index=0,
)

selected_geometry = None
selection_label = None
selected_code = None
selected_state = None

states = sorted(muni["abbrev_state"].dropna().astype(str).unique())

if selection_type == "Município":
    state_choice = st.sidebar.selectbox(
        "Estado", ["— Selecione —"] + states, index=0
    )
    if state_choice == "— Selecione —":
        st.info("Selecione um estado e um município para iniciar a análise.")
        st.stop()
    selected_state = state_choice
    mstate = muni[muni["abbrev_state"].astype(str) == selected_state].copy()
    city_names = sorted(mstate["name_muni"].astype(str).unique())
    city_choice = st.sidebar.selectbox(
        "Município", ["— Selecione —"] + city_names, index=0
    )
    if city_choice == "— Selecione —":
        st.info("Agora selecione o município que deseja analisar.")
        st.stop()
    selected_city = city_choice
    row = mstate[mstate["name_muni"].astype(str) == selected_city].iloc[0]
    selected_code = str(row["code_muni"]).replace(".0", "")
    selected_geometry = row.geometry
    selection_label = f"{selected_city} - {selected_state}"
    selection_area = float(row.get("area_muni_km2", np.nan))
    if not np.isfinite(selection_area):
        selection_area = area_km2(selected_geometry)

elif selection_type == "Estado":
    state_choice = st.sidebar.selectbox(
        "Estado", ["— Selecione —"] + states, index=0
    )
    if state_choice == "— Selecione —":
        st.info("Selecione o estado que deseja analisar.")
        st.stop()
    selected_state = state_choice
    mstate = muni[muni["abbrev_state"].astype(str) == selected_state].copy()
    try:
        selected_geometry = mstate.geometry.union_all()
    except Exception:
        selected_geometry = mstate.geometry.unary_union
    selection_label = selected_state
    if "area_muni_km2" in mstate.columns:
        selection_area = float(pd.to_numeric(mstate["area_muni_km2"], errors="coerce").sum())
    else:
        selection_area = area_km2(selected_geometry)

else:
    st.subheader("🛰️ Desenhe a região personalizada")
    st.info(
        "Use o botão de polígono ou retângulo no mapa. A região desenhada será a máscara "
        "dos cálculos e dos rankings."
    )
    previous = st.session_state.get("v4_custom_geometry")
    draw_map = build_draw_map(previous)
    from streamlit_folium import st_folium
    draw_result = st_folium(
        draw_map,
        use_container_width=True,
        height=520,
        returned_objects=["last_active_drawing"],
        key="v4_draw_map",
    )
    drawing = (draw_result or {}).get("last_active_drawing")
    if drawing and drawing.get("geometry"):
        try:
            selected_geometry = shape(drawing["geometry"])
            if not selected_geometry.is_valid:
                selected_geometry = selected_geometry.buffer(0)
            if not selected_geometry.is_empty:
                st.session_state["v4_custom_geometry"] = selected_geometry
        except Exception:
            selected_geometry = previous
    else:
        selected_geometry = previous

    if selected_geometry is None or selected_geometry.is_empty:
        st.warning("Desenhe uma região no mapa para continuar.")
        st.stop()
    selection_label = "Região personalizada"
    selection_area = area_km2(selected_geometry)
    st.success(f"Região selecionada: {format_float(selection_area, 1)} km²")

# -----------------------------------------------------------------------------
# 2) PERÍODO E BASE TEMPORAL
# -----------------------------------------------------------------------------
st.sidebar.header("2. Período")
time_basis = st.sidebar.selectbox(
    "Base de horário",
    ["Brasília (UTC-3)", "UTC"],
    index=0,
)
utc_offset = -3 if time_basis.startswith("Brasília") else 0

local_min = tmin + pd.Timedelta(hours=utc_offset)
local_max = tmax + pd.Timedelta(hours=utc_offset)
min_date = local_min.date()
max_date = local_max.date()

default_start = min_date
if (max_date - min_date).days > 365 * 5:
    default_start = date(max_date.year - 4, 1, 1)
    if default_start < min_date:
        default_start = min_date

start_date = st.sidebar.date_input("Data inicial", value=default_start, min_value=min_date, max_value=max_date)
end_date = st.sidebar.date_input("Data final", value=max_date, min_value=min_date, max_value=max_date)
if end_date < start_date:
    st.sidebar.error("A data final deve ser igual ou posterior à data inicial.")
    st.stop()

# Datas escolhidas são datas locais na base selecionada; converte para UTC.
start_local_naive = pd.Timestamp(datetime.combine(start_date, time.min))
end_local_naive = pd.Timestamp(datetime.combine(end_date, time.max))
start_utc = (start_local_naive - pd.Timedelta(hours=utc_offset)).tz_localize("UTC")
end_utc = (end_local_naive - pd.Timedelta(hours=utc_offset)).tz_localize("UTC")
start_utc = max(start_utc, tmin)
end_utc = min(end_utc, tmax)

st.sidebar.caption(
    f"Base disponível: {local_min.strftime('%d/%m/%Y %H:%M')} → "
    f"{local_max.strftime('%d/%m/%Y %H:%M')} ({time_basis})"
)

st.sidebar.header("3. Executar")
if st.sidebar.button("⚡ ANALISAR", type="primary", use_container_width=True):
    st.session_state["v4_analysis_active"] = True
if st.sidebar.button("Limpar análise", use_container_width=True):
    st.session_state["v4_analysis_active"] = False

if not st.session_state.get("v4_analysis_active", False):
    st.markdown("### Área escolhida")
    c1, c2, c3 = st.columns(3)
    c1.metric("Seleção", selection_label)
    c2.metric("Área", f"{format_float(selection_area, 1)} km²")
    c3.metric("Fonte", "GLM-L2-LCFA")
    st.info("Defina o período na barra lateral e clique em **ANALISAR**.")
    st.stop()

# -----------------------------------------------------------------------------
# 3) CONSULTA DA BASE PRIMÁRIA
# -----------------------------------------------------------------------------
with st.spinner("Consultando flashes GLM e calculando produtos..."):
    if selection_type == "Município":
        flashes = repo.load(start=start_utc, end=end_utc, code_muni=selected_code)
    elif selection_type == "Estado":
        flashes = repo.load(start=start_utc, end=end_utc, state=selected_state)
    else:
        bbox = selected_geometry.bounds
        flashes = repo.load(start=start_utc, end=end_utc, bbox=bbox)
        flashes = filter_by_geometry(flashes, selected_geometry)

    products = calculate_analysis(
        flashes,
        start=start_utc,
        end=end_utc,
        selection_area_km2=selection_area,
        utc_offset_hours=utc_offset,
    )

# -----------------------------------------------------------------------------
# CABEÇALHO DA ANÁLISE
# -----------------------------------------------------------------------------
st.markdown(f"## {selection_label}")
st.caption(
    f"Período analisado: **{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}** • "
    f"{time_basis} • fonte individual: `{repo.source_description()}`"
)

s = products.summary
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Flashes", format_int(s["flash_count"]))
c2.metric("Densidade", f"{format_float(s['flash_density_km2'], 3)} /km²")
c3.metric("Dias com relâmpagos", format_int(s["lightning_days"]))
c4.metric("Flashes/dia", format_float(s["flashes_per_day"], 2))
c5.metric("Flashes/dia ativo", format_float(s["flashes_per_active_day"], 2))

if products.monthly["year"].nunique() < 2:
    st.warning(
        "O período selecionado possui menos de 2 anos. Climatologia, anomalias e z-score são mostrados "
        "para testar a estrutura, mas ainda não devem ser interpretados como climatologia robusta."
    )

# -----------------------------------------------------------------------------
# ABAS DE RESULTADOS
# -----------------------------------------------------------------------------
tabs = st.tabs([
    "🗺️ Mapa", "📊 Resumo", "📅 Temporal", "🌦️ Climatologia",
    "⚡ Características", "🏆 Ranking / Município", "💾 Dados",
])

with tabs[0]:
    st.subheader("Mapa de satélite")
    map_mode = st.radio(
        "Visualização dos flashes",
        ["Flashes individuais", "Últimos 15 min (🔴🔵🟢)", "Mapa de calor"],
        horizontal=True,
    )
    max_points = st.slider("Máximo de pontos enviados ao navegador", 1000, 30000, 12000, step=1000)
    m = build_analysis_map(
        products.flashes,
        selected_geometry,
        label=selection_label,
        mode=map_mode,
        max_points=max_points,
    )
    from streamlit_folium import st_folium
    st_folium(m, use_container_width=True, height=690, returned_objects=[])
    if getattr(m, "_glm_sampled", False):
        st.warning(
            f"A análise usa todos os {format_int(len(products.flashes))} flashes, mas o mapa desenha "
            f"somente uma amostra de {format_int(getattr(m, '_glm_plotted', max_points))} para proteger o navegador."
        )
    elif map_mode == "Últimos 15 min (🔴🔵🟢)":
        st.caption("🔴 0–5 min • 🔵 5–10 min • 🟢 10–15 min em relação ao flash mais recente do período carregado.")

with tabs[1]:
    st.subheader("Resumo do período")
    a, b, c, d = st.columns(4)
    a.metric("Máximo diário", format_int(s["max_daily_flashes"]), str(s["max_daily_date"])[:10] if s["max_daily_date"] is not None else None)
    b.metric("Máximo horário", format_int(s["max_hourly_flashes"]))
    c.metric("Área analisada", f"{format_float(s['area_km2'], 1)} km²")
    c2 = 100 * s["lightning_days"] / s["total_days"] if s["total_days"] else np.nan
    d.metric("Dias ativos", f"{format_float(c2, 1)}%")

    if s["max_hourly_date"] is not None:
        st.write(
            f"**Recorde horário:** {format_int(s['max_hourly_flashes'])} flashes em "
            f"{pd.Timestamp(s['max_hourly_date']).strftime('%d/%m/%Y')}, hora local {s['max_hourly_hour']:02d}:00–{(s['max_hourly_hour']+1)%24:02d}:00."
        )
    st.markdown("#### Frequência diária")
    st.write(
        f"Média considerando **todos os dias**: **{format_float(s['flashes_per_day'], 2)} flashes/dia**.  \n"
        f"Média considerando somente **dias com relâmpagos**: **{format_float(s['flashes_per_active_day'], 2)} flashes/dia ativo**."
    )

with tabs[2]:
    st.subheader("Séries diária, mensal e anual")
    gran = st.radio("Escala", ["Diária", "Mensal", "Anual"], horizontal=True)
    if gran == "Diária":
        table = products.daily.copy(); x = "date"; title = "Flashes por dia"
    elif gran == "Mensal":
        table = products.monthly.copy(); x = "period_label"; title = "Flashes por mês"
    else:
        table = products.annual.copy(); x = "year"; title = "Flashes por ano"
    fig = px.bar(table, x=x, y="flash_count", title=title, labels={"flash_count": "Flashes"})
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(table, use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Média mensal climatológica")
    clim = products.monthly_climatology.copy()
    fig = px.bar(
        clim, x="month_name", y="flash_count_mean",
        category_orders={"month_name": list(MONTH_NAMES.values())},
        labels={"month_name": "Mês", "flash_count_mean": "Média mensal de flashes"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(clim, use_container_width=True, hide_index=True)

    st.subheader("Anomalias mensais")
    anom_mode = st.radio("Métrica de anomalia", ["Absoluta", "Percentual", "Z-score"], horizontal=True)
    col = {"Absoluta": "flash_count_anom", "Percentual": "flash_count_anom_pct", "Z-score": "flash_count_z"}[anom_mode]
    if col in products.monthly_anomalies:
        fig = px.bar(products.monthly_anomalies, x="period_label", y=col, labels={col: anom_mode, "period_label": "Mês/Ano"})
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Dias com relâmpagos e sazonalidade")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(products.seasonality_month, x="month_name", y="mean_lightning_days",
                     category_orders={"month_name": list(MONTH_NAMES.values())},
                     labels={"month_name": "Mês", "mean_lightning_days": "Média de dias com relâmpagos"})
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(products.seasonality_season, x="season", y="fraction_pct",
                     labels={"season": "Estação", "fraction_pct": "% dos flashes"})
        st.plotly_chart(fig, use_container_width=True)

with tabs[4]:
    st.subheader("Duração, energia e área dos flashes")
    metric_options = {
        "Duração (ms)": "duration_ms",
        "Energia (J)": "energy_j",
        "Área do flash (km²)": "area_km2",
    }
    label_metric = st.selectbox("Característica", list(metric_options))
    metric = metric_options[label_metric]
    fs = products.feature_summary[metric]
    cols = st.columns(7)
    for box, key in zip(cols, ["mean", "median", "std", "p90", "p95", "p99", "max"]):
        box.metric(key.upper(), format_float(fs.get(key), 3))
    values = pd.to_numeric(products.flashes.get(metric, pd.Series(dtype=float)), errors="coerce").dropna()
    if not values.empty:
        fig = px.histogram(values.to_frame(metric), x=metric, nbins=50, labels={metric: label_metric})
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Ciclo diurno/noturno")
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.bar(products.diurnal, x="hour", y="flash_count", labels={"hour": f"Hora ({time_basis})", "flash_count": "Flashes"})
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.pie(products.day_night, names="period", values="flash_count", hole=.45)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("V4: diurno = 06:00–17:59; noturno = 18:00–05:59 na base de horário selecionada.")

with tabs[5]:
    if selection_type == "Município":
        st.subheader("Perfil mensal do município")
        mp = products.municipality_months.copy()
        valid = mp[mp["flash_count_mean"].notna()]
        if not valid.empty:
            imax = valid["flash_count_mean"].idxmax(); imin = valid["flash_count_mean"].idxmin()
            rmax = valid.loc[imax]; rmin = valid.loc[imin]
            c1, c2 = st.columns(2)
            c1.metric("Mês climatologicamente mais ativo", rmax["month_name"], f"média {format_float(rmax['flash_count_mean'], 1)} flashes")
            c2.metric("Mês climatologicamente menos ativo", rmin["month_name"], f"média {format_float(rmin['flash_count_mean'], 1)} flashes")
        show = mp[[
            "month", "month_name", "total_flashes", "flash_count_mean", "flash_count_median",
            "flash_count_min", "flash_count_max", "climatological_fraction_pct", "n_years",
        ]].copy()
        show = show.rename(columns={
            "month": "mês_nº", "month_name": "mês", "total_flashes": "flashes_total",
            "flash_count_mean": "média_mensal", "flash_count_median": "mediana_mensal",
            "flash_count_min": "mínimo_mensal", "flash_count_max": "máximo_mensal",
            "climatological_fraction_pct": "%_climatológico", "n_years": "anos",
        })
        st.dataframe(show, use_container_width=True, hide_index=True)
    elif selection_type == "Estado":
        st.subheader(f"Ranking municipal — {selected_state}")
        st.dataframe(products.ranking_municipalities, use_container_width=True, hide_index=True)
        if not products.ranking_municipalities.empty:
            fig = px.bar(products.ranking_municipalities.head(20), x="name_muni", y="flash_count", hover_data=["abbrev_state", "lightning_days"])
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.subheader("Ranking estadual dentro da região desenhada")
        st.dataframe(products.ranking_states, use_container_width=True, hide_index=True)
        st.subheader("Ranking municipal dentro da região desenhada")
        st.caption("São contados apenas os flashes que caíram dentro do polígono desenhado, e não o total inteiro dos municípios interceptados.")
        st.dataframe(products.ranking_municipalities, use_container_width=True, hide_index=True)

with tabs[6]:
    st.subheader("Downloads da análise")
    exports = {
        "diario.csv": products.daily,
        "mensal.csv": products.monthly,
        "anual.csv": products.annual,
        "climatologia_mensal.csv": products.monthly_climatology,
        "anomalias_mensais.csv": products.monthly_anomalies,
        "ciclo_diurno.csv": products.diurnal,
        "sazonalidade_mensal.csv": products.seasonality_month,
        "ranking_estadual.csv": products.ranking_states,
        "ranking_municipal.csv": products.ranking_municipalities,
    }
    for filename, df in exports.items():
        if df is None or df.empty:
            continue
        st.download_button(
            f"Baixar {filename}",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=filename,
            mime="text/csv",
            key=f"download_{filename}",
        )
    if len(products.flashes) <= 200_000:
        st.download_button(
            "Baixar flashes individuais da seleção",
            data=products.flashes.to_csv(index=False).encode("utf-8"),
            file_name="flashes_selecao.csv",
            mime="text/csv",
        )
    else:
        st.warning("A seleção possui mais de 200 mil flashes; o download individual pelo navegador foi desabilitado para proteger o Streamlit.")

with st.expander("Metodologia resumida desta análise"):
    st.markdown(
        """
- **Unidade:** flash GLM.
- **Município:** centroide do flash associado ao polígono municipal.
- **Estado:** todos os flashes associados a municípios da UF selecionada.
- **Região personalizada:** somente flashes cujo ponto cai dentro do polígono/retângulo desenhado.
- **Dias com relâmpagos:** dias com pelo menos um flash.
- **Frequência diária:** calculada para todos os dias e, separadamente, somente para dias ativos.
- **Climatologia mensal:** média entre ocorrências de cada mês no intervalo escolhido, incluindo meses sem flashes como zero.
- **Anomalia:** valor mensal menos climatologia do mesmo mês; também percentual e z-score quando há variabilidade suficiente.
- **Diurno/noturno V4:** classificação horária fixa 06–18 / 18–06 na base de horário selecionada.
        """
    )
