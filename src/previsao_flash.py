"""Flash View — Tendência OBSERVADA dos flashes GLM (não é previsão).

Oferece mapa clicável com flashes por idade, raio variável, coordenadas
editáveis, seleção por UF/município e visualização temporal observacional.
"""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import folium
from folium.plugins import FastMarkerCluster, Fullscreen
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.alertas_flash import analyze_glm_activity, render_observational_alert, add_collapsible_glm_legend
from src.realtime_glm import AGE_GROUPS

BR_TZ = ZoneInfo("America/Sao_Paulo")
UTC_TZ = ZoneInfo("UTC")
DEFAULT_POINT = (-15.0, -60.0)
ADMIN_DIR = Path(__file__).resolve().parents[1] / "data" / "admin"

# Lista de UFs em ordem alfabética, com código IBGE.
STATE_CODES = {
    "AC": 12, "AL": 27, "AP": 16, "AM": 13, "BA": 29, "CE": 23,
    "DF": 53, "ES": 32, "GO": 52, "MA": 21, "MT": 51, "MS": 50,
    "MG": 31, "PA": 15, "PB": 25, "PR": 41, "PE": 26, "PI": 22,
    "RJ": 33, "RN": 24, "RS": 43, "RO": 11, "RR": 14, "SC": 42,
    "SP": 35, "SE": 28, "TO": 17,
}


@st.cache_data(ttl=24*3600, show_spinner=False, max_entries=2)
def city_catalog() -> pd.DataFrame:
    """Lê CSV local; senão geometria local; senão CSV público cacheado.

    O CSV é um catálogo de coordenadas aproximadas da sede municipal (não polígono).
    A consulta remota não utiliza API do GitHub; somente o arquivo raw estático.
    """
    local_csv = ADMIN_DIR / "municipios_centros.csv"
    if local_csv.is_file():
        df = pd.read_csv(local_csv, dtype={"code_muni": str})
        required = {"code_muni", "name_muni", "abbrev_state", "lat", "lon"}
        if required.issubset(df.columns):
            return df.dropna(subset=["lat", "lon"]).copy()

    local_geo = ADMIN_DIR / "municipalities_2022.parquet"
    if local_geo.is_file():
        import geopandas as gpd
        gdf = gpd.read_parquet(local_geo).to_crs(4326)
        centroids = gdf.to_crs("EPSG:5880").representative_point().to_crs(4326)
        return pd.DataFrame({
            "code_muni": gdf["code_muni"].astype(str).to_numpy(),
            "name_muni": gdf["name_muni"].astype(str).to_numpy(),
            "abbrev_state": gdf["abbrev_state"].astype(str).to_numpy(),
            "lat": centroids.y.to_numpy(),
            "lon": centroids.x.to_numpy(),
        })

    import requests
    url = "https://raw.githubusercontent.com/kelvins/Municipios-Brasileiros/main/csv/municipios.csv"
    try:
        response = requests.get(url, timeout=(5, 20))
        response.raise_for_status()
        from io import StringIO
        raw = pd.read_csv(StringIO(response.text), dtype={"codigo_ibge": str})
        df = raw.rename(columns={
            "codigo_ibge": "code_muni", "nome": "name_muni",
            "latitude": "lat", "longitude": "lon", "codigo_uf": "state_code",
        })
        by_code = {v: k for k, v in STATE_CODES.items()}
        df["abbrev_state"] = df["state_code"].map(by_code)
        df = df[["code_muni", "name_muni", "abbrev_state", "lat", "lon"]]
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df = df.dropna(subset=["lat", "lon", "abbrev_state"])
        return df
    except Exception as exc:
        raise RuntimeError(
            "Catálogo de cidades indisponível. Instale data/admin/municipios_centros.csv "
            "ou data/admin/municipalities_2022.parquet no projeto."
        ) from exc


def flashes_near_point(flashes: pd.DataFrame, lat: float, lon: float,
                       radius_km: float) -> pd.DataFrame:
    """Filtra flashes por distância Haversine aproximada (km)."""
    if flashes is None or flashes.empty:
        return flashes.copy() if flashes is not None else pd.DataFrame()
    if not {"lat", "lon"}.issubset(flashes.columns):
        raise KeyError("Dados GLM sem lat/lon")
    phi1 = np.radians(float(lat))
    phi2 = np.radians(pd.to_numeric(flashes["lat"], errors="coerce").to_numpy(dtype=float))
    dphi = phi2 - phi1
    dlambda = np.radians(pd.to_numeric(flashes["lon"], errors="coerce").to_numpy(dtype=float) - float(lon))
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2)**2
    dist = 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return flashes.loc[np.isfinite(dist) & (dist <= float(radius_km))].copy()


def build_observed_map(lat: float, lon: float, radius_km: int,
                       flashes: pd.DataFrame, *, center=None, zoom=4):
    """Mapa interativo com TODOS os flashes presentes no círculo selecionado."""
    center = center or [lat, lon]
    m = folium.Map(location=center, zoom_start=int(zoom), tiles=None,
                   control_scale=True, prefer_canvas=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Satélite", overlay=False, control=True,
        show=True, max_zoom=19,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Ruas", show=False).add_to(m)

    # Sem ponto selecionado, não desenha marcador ou círculo inicial.
    if lat is not None and lon is not None:
        folium.Circle([lat, lon], radius=int(radius_km)*1000,
                      color="#f43f5e", weight=2.5, fill=True,
                      fill_opacity=0.08, tooltip=f"Área GLM: raio {radius_km} km").add_to(m)
        folium.Marker([lat, lon], tooltip="Centro selecionado",
                      icon=folium.Icon(color="red", icon="flash", prefix="glyphicon")).add_to(m)

    if flashes is not None and not flashes.empty:
        # Máximo de 4 mil pontos para manter o mapa interativo responsivo.
        # O filtro estatístico usa todos os flashes; o limite é só visual.
        current = flashes.copy()
        if "time_start" in current.columns:
            current = current.sort_values("time_start", ascending=False)
        current = current.head(4000)
        groups = list(AGE_GROUPS) + [("30–60 min", 30, 60.01, "#a8b3c7")]
        for label, _lo, _hi, color in groups:
            if "age_group" not in current.columns:
                break
            points = current.loc[current["age_group"].eq(label)]
            if points.empty:
                continue
            layer = folium.FeatureGroup(name=f"Flashes {label} ({len(points)})", show=True)
            for item in points.itertuples(index=False):
                try:
                    p_lat, p_lon = float(item.lat), float(item.lon)
                    if not (np.isfinite(p_lat) and np.isfinite(p_lon)):
                        continue
                    when = pd.Timestamp(item.time_start)
                    tooltip = f"Flash {label} | {when:%d/%m/%Y %H:%M:%S} UTC"
                except (TypeError, ValueError, AttributeError):
                    continue
                folium.CircleMarker(
                    [p_lat, p_lon], radius=4.3,
                    color=color, fill_color=color,
                    fill=True, fill_opacity=0.95,
                    weight=0.8, opacity=0.95,
                    tooltip=tooltip,
                ).add_to(layer)
            layer.add_to(m)
    add_collapsible_glm_legend(m, list(AGE_GROUPS) + [("30–60 min", 30, 60.01, "#a8b3c7")])
    Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def _validated_point(lat: float, lon: float) -> tuple[float, float]:
    lat = round(float(lat), 5)
    lon = round(float(lon), 5)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude e longitude fora do intervalo permitido")
    return lat, lon


def _update_point(lat: float, lon: float, *, recenter=True):
    """Executar SOMENTE antes de criar st.number_input na execução corrente."""
    lat, lon = _validated_point(lat, lon)
    st.session_state["fv_trend_lat"] = lat
    st.session_state["fv_trend_lon"] = lon
    st.session_state["fv_trend_selected_point"] = (lat, lon)
    if recenter:
        st.session_state["fv_trend_map_center"] = [lat, lon]
        st.session_state["fv_trend_map_zoom"] = 7


def _queue_point(lat: float, lon: float, *, recenter: bool = True):
    """Agenda mudança para o próximo rerun, evitando StreamlitAPIException."""
    lat, lon = _validated_point(lat, lon)
    st.session_state["fv_trend_pending_point"] = (lat, lon, recenter)


def render_trend_tab(*, snapshot_loader=None):
    st.markdown('<div class="section-heading">📊 Tendência observada de atividade elétrica</div>',
                unsafe_allow_html=True)
    st.caption("Observações GLM-L2-LCFA. Clique no mapa, digite latitude/longitude ou "
               "selecione UF e município. Os flashes são mostrados na última hora "
               "disponível (30–60 min em cinza); a tendência compara os "
               "três intervalos mais recentes de 10 minutos.")

    # Migração da V4: evita reutilizar o antigo ponto inicial (-15, -60)
    # quando o aplicativo é atualizado em uma sessão ainda aberta.
    if "fv_trend_v5_initialized" not in st.session_state:
        if "fv_trend_selected_point" not in st.session_state:
            st.session_state["fv_trend_lat"] = None
            st.session_state["fv_trend_lon"] = None
            st.session_state["fv_trend_map_center"] = list(DEFAULT_POINT)
            st.session_state["fv_trend_map_zoom"] = 3
            st.session_state.pop("fv_trend_last_click", None)
        st.session_state["fv_trend_v5_initialized"] = True

    for name, default in {
        "fv_trend_lat": None, "fv_trend_lon": None,
        "fv_trend_selected_point": None,
        "fv_trend_map_center": list(DEFAULT_POINT), "fv_trend_map_zoom": 3,
    }.items():
        if name not in st.session_state:
            st.session_state[name] = default

    # IMPORTANTE: aplicar o ponto vindo do mapa/cidade ANTES dos number_input.
    pending = st.session_state.pop("fv_trend_pending_point", None)
    if pending is not None:
        _update_point(pending[0], pending[1], recenter=pending[2])

    snapshot = None
    load_error = None
    if snapshot_loader is not None:
        try:
            snapshot = snapshot_loader()
        except Exception as exc:
            load_error = exc

    col_map, col_side = st.columns([1.7, 1], gap="large")
    with col_side:
        st.markdown("**Área de interesse**")
        radius = st.slider("Raio da análise (km)", 10, 100, 40, 5,
                           key="fv_trend_obs_radius")
        lat = st.number_input("Latitude (°)", min_value=-90.0, max_value=90.0,
                              value=None, step=0.0001, format="%.5f",
                              placeholder="Digite a latitude", key="fv_trend_lat")
        lon = st.number_input("Longitude (°)", min_value=-180.0, max_value=180.0,
                              value=None, step=0.0001, format="%.5f",
                              placeholder="Digite a longitude", key="fv_trend_lon")
        if st.button("📍 Aplicar coordenadas", key="fv_trend_apply_coords", width="stretch"):
            if lat is None or lon is None:
                st.warning("Informe latitude e longitude antes de aplicar.")
            else:
                # Atualiza estado de SELEÇÃO, não altera as chaves dos inputs.
                point = _validated_point(lat, lon)
                st.session_state["fv_trend_selected_point"] = point
                st.session_state["fv_trend_map_center"] = list(point)
                st.session_state["fv_trend_map_zoom"] = 7
                st.rerun()

        st.markdown("**Ou escolha um município brasileiro**")
        try:
            df_cities = city_catalog()
            ufs = sorted(df_cities["abbrev_state"].dropna().unique().tolist())
            uf = st.selectbox("Estado (UF)", ["— Selecione —"] + ufs,
                              key="fv_trend_uf")
            if uf != "— Selecione —":
                sub = df_cities[df_cities["abbrev_state"] == uf].sort_values("name_muni")
                names = sub["name_muni"].astype(str).tolist()
                city = st.selectbox("Município", ["— Selecione —"] + names,
                                    key="fv_trend_city")
                if city != "— Selecione —" and st.button("📌 Ir para município",
                         key="fv_trend_go_city", width="stretch"):
                    rec = sub[sub["name_muni"].eq(city)].iloc[0]
                    _queue_point(rec["lat"], rec["lon"])
                    st.rerun()
        except Exception as exc:
            st.warning("Lista de municípios indisponível nesta sessão.")
            with st.expander("Detalhes da lista de cidades"):
                st.exception(exc)

        tz_mode = st.segmented_control("Fuso do horário observado", ["Brasília", "UTC"],
                                       default="Brasília", key="fv_trend_time_zone")

    point = st.session_state.get("fv_trend_selected_point")
    if point is None:
        lat, lon = None, None
    else:
        lat, lon = point
    inside = (flashes_near_point(snapshot.flashes, lat, lon, radius)
              if snapshot is not None and point is not None else pd.DataFrame())

    with col_map:
        map_state = st_folium(
            build_observed_map(lat, lon, radius, inside,
                               center=st.session_state["fv_trend_map_center"],
                               zoom=st.session_state["fv_trend_map_zoom"]),
            width=None, height=510, key="fv_trend_click_map_v5",
            returned_objects=["last_clicked", "center", "zoom"],
        )
        if point is None:
            st.info("Clique no mapa para marcar um ponto de análise, ou selecione "
                    "um município/insira coordenadas ao lado.")
        else:
            st.caption(f"⚡ {len(inside)} flashes nos últimos 60 minutos dentro do círculo de {radius} km. "
                       "Se não houver flashes na janela disponível, o círculo ficará sem pontos.")

    if map_state:
        view_center = map_state.get("center")
        view_zoom = map_state.get("zoom")
        if isinstance(view_center, dict) and {"lat", "lng"}.issubset(view_center):
            st.session_state["fv_trend_map_center"] = [float(view_center["lat"]), float(view_center["lng"])]
        if view_zoom is not None:
            st.session_state["fv_trend_map_zoom"] = int(view_zoom)
        clicked = map_state.get("last_clicked")
        if clicked and {"lat", "lng"}.issubset(clicked):
            newpoint = (round(float(clicked["lat"]), 5), round(float(clicked["lng"]), 5))
            if newpoint != point and newpoint != st.session_state.get("fv_trend_last_click"):
                st.session_state["fv_trend_last_click"] = newpoint
                _queue_point(*newpoint, recenter=False)
                st.rerun()

    # Downloads científicos da área selecionada; sem imagens de terceiros.
    if snapshot is not None and point is not None:
        from src.view_exports import render_flash_png,to_jpeg
        from src.spatial_tools import circular_buffer_geometry
        # Buffer equidistante azimutal centrado no ponto, com raio em quilômetros.
        circle = circular_buffer_geometry(lat,lon,radius)
        if st.button("📷 Preparar imagem da Tendência",key="fv_trend_prepare_export"):
            st.session_state["fv_trend_png_export"] = render_flash_png(inside,
                title="Flash View | Tendência observada",
                subtitle=f"Centro {lat:.4f}, {lon:.4f} • raio {radius} km • {len(inside)} flashes",
                geometry=circle,observation_end=snapshot.observation_end_utc)
        if st.session_state.get("fv_trend_png_export"):
            di1,di2=st.columns(2)
            di1.download_button("⬇️ Tendência PNG",st.session_state["fv_trend_png_export"],
                file_name="flash_view_tendencia.png",mime="image/png",key="fv_trend_dl_png")
            di2.download_button("⬇️ Tendência JPEG",to_jpeg(st.session_state["fv_trend_png_export"]),
                file_name="flash_view_tendencia.jpg",mime="image/jpeg",key="fv_trend_dl_jpg")

    st.markdown("### Atividade elétrica observada — GLM")
    if load_error is not None:
        st.warning("Não foi possível obter os flashes GLM neste momento.")
        with st.expander("Detalhes técnicos"):
            st.exception(load_error)
    elif snapshot is None:
        st.info("A leitura dos flashes GLM não está configurada.")
    elif point is None:
        st.info("Selecione um ponto para calcular a tendência observada e exibir os flashes na área.")
    else:
        summary = analyze_glm_activity(inside, snapshot.observation_end_utc,
                                       snapshot.latency_minutes)
        render_observational_alert(st, summary)
        obs = snapshot.observation_end_utc.astimezone(
            UTC_TZ if tz_mode == "UTC" else BR_TZ
        )
        d_col, h_col = st.columns(2)
        d_col.metric(f"Data da observação · {tz_mode}", obs.strftime("%d/%m/%Y"))
        h_col.metric(f"Hora da observação · {tz_mode}", obs.strftime("%H:%M:%S"))
        st.caption(f"Raio de {radius} km · {lat:.5f}°, {lon:.5f}° · "
                   "GLM mede relâmpagos totais (intranuvem e nuvem-solo). "
                   "Tendência observacional, não previsão nem alerta oficial.")
        if not inside.empty:
            export_cols = [c for c in ("time_start", "lat", "lon", "age_minutes",
                                       "age_group", "energy_j", "area_km2") if c in inside]
            st.download_button("⬇️ Baixar flashes da área (CSV)",
                inside[export_cols].to_csv(index=False).encode("utf-8-sig"),
                file_name="flash_view_tendencia_observada.csv", mime="text/csv",
                key="fv_download_obs")
