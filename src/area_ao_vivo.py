"""Área da aba ao vivo: Pontual, Retângulo, Estados, Municípios ou Arquivo (os mesmos tipos da Tendência).

A área escolhida filtra os números e o mapa ao vivo e é a área vigiada pelo botão "Ativar alarme".
O mapa (src/maplibre_realtime.js) devolve um ponto clicado ou um retângulo arrastado; os valores entram nos
campos pelo padrão "pendente" (gravados antes de criar os widgets no rerun seguinte), como na Tendência.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import streamlit as st

LIVE_AREA_MODES = ["Pontual", "Retângulo", "Estados", "Municípios", "Arquivo"]
_MODE_LABELS = {"Pontual": "📍 Pontual", "Retângulo": "▭ Retângulo", "Estados": "🗺️ Estados",
                "Municípios": "🏙️ Municípios", "Arquivo": "📁 Arquivo"}
_RECT_KEYS = ("fv_live_rect_s", "fv_live_rect_n", "fv_live_rect_w", "fv_live_rect_e")


@dataclass(frozen=True)
class LiveArea:
    mode: str | None
    geometry: object | None = None
    label: str | None = None          # usado nas mensagens, ex.: "raio de 20 km em Itajubá (MG)"
    map_mode: str | None = None       # o que um clique no mapa faz: "point", "rectangle" ou nada
    point: tuple[float, float] | None = None   # (lat, lon) do modo Pontual
    reference: str = "do centro da área"        # de onde o alarme mede a distância


def clear_live_area() -> None:
    """Callback do botão Limpar: volta para o mapa inteiro."""
    st.session_state["fv_live_area_mode"] = None


def queue_map_point(lat: float, lon: float, name: str | None = None) -> None:
    """Ponto clicado no mapa (ou município escolhido): entra nos campos no próximo rerun."""
    lat, lon = round(float(lat), 4), round(float(lon), 4)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Ponto fora do intervalo de latitude/longitude.")
    st.session_state["fv_live_pending_point"] = (lat, lon, name)


def queue_map_rectangle(rect: dict) -> None:
    """Retângulo arrastado no mapa ({west, south, east, north}): entra nos campos no próximo rerun."""
    west, south, east, north = (round(float(rect[k]), 4) for k in ("west", "south", "east", "north"))
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise ValueError("Retângulo fora do intervalo de latitude/longitude.")
    st.session_state["fv_live_pending_rect"] = (south, north, west, east)


def _apply_pending() -> None:
    """Executar ANTES de criar os campos (o Streamlit não deixa mudar um widget já criado)."""
    pending = st.session_state.pop("fv_live_pending_point", None)
    if pending is not None:
        lat, lon, name = pending
        st.session_state["fv_live_lat"], st.session_state["fv_live_lon"] = lat, lon
        st.session_state["fv_live_point_name"] = (lat, lon, name) if name else None
        st.session_state["fv_live_area_mode"] = "Pontual"
    pending = st.session_state.pop("fv_live_pending_rect", None)
    if pending is not None:
        for key, value in zip(_RECT_KEYS, pending):
            st.session_state[key] = value
        st.session_state["fv_live_rect_redraw"] = False
        st.session_state["fv_live_area_mode"] = "Retângulo"


@st.cache_data(ttl=24 * 3600, max_entries=32, show_spinner=False)
def _states_wkb(ufs: tuple[str, ...]) -> str | None:
    from src.previsao_flash import _simplified_states, _union
    states = _simplified_states()
    geom = _union(states.loc[states["abbrev_state"].isin(ufs)].geometry.tolist())
    return geom.wkb.hex() if geom is not None else None


@st.cache_data(ttl=24 * 3600, max_entries=32, show_spinner=False)
def _municipalities_wkb(selected: tuple[tuple[str, str], ...]) -> str | None:
    from src.previsao_flash import _municipality_geometries, _union
    geom = _union(_municipality_geometries(list(selected)))
    return geom.wkb.hex() if geom is not None else None


def _from_wkb(hexed: str | None):
    if not hexed:
        return None
    from shapely import from_wkb
    return from_wkb(bytes.fromhex(hexed))


def _point_panel() -> LiveArea:
    from src.previsao_flash import city_catalog
    from src.spatial_tools import circular_buffer_geometry

    c1, c2, c3 = st.columns([1, 1, 1.3])
    lat = c1.number_input("Latitude (°)", -90.0, 90.0, value=None, step=0.0001, format="%.4f",
                          placeholder="clique no mapa", key="fv_live_lat")
    lon = c2.number_input("Longitude (°)", -180.0, 180.0, value=None, step=0.0001, format="%.4f",
                          placeholder="ou digite", key="fv_live_lon")
    radius = c3.slider("Raio (km)", 5, 100, 20, 5, key="fv_live_radius")
    try:
        cities = city_catalog()
        u1, u2, u3 = st.columns([0.7, 1.6, 0.9], vertical_alignment="bottom")
        ufs = sorted(cities["abbrev_state"].dropna().unique().tolist())
        uf = u1.selectbox("UF", ["—"] + ufs, key="fv_live_uf")
        sub = cities[cities["abbrev_state"] == uf].sort_values("name_muni")
        city = u2.selectbox("Ou um município (sede)", ["—"] + sub["name_muni"].astype(str).tolist(),
                            key="fv_live_city", disabled=uf == "—")
        if u3.button("📌 Usar município", key="fv_live_go_city", width="stretch",
                     disabled=uf == "—" or city == "—"):
            rec = sub[sub["name_muni"].eq(city)].iloc[0]
            queue_map_point(rec["lat"], rec["lon"], f"{city} ({uf})")
            st.rerun(scope="fragment")
    except Exception:
        st.caption("Lista de municípios indisponível nesta sessão; use o mapa ou as coordenadas.")
    if lat is None or lon is None:
        st.caption("Clique no mapa para marcar o ponto, digite as coordenadas ou escolha um município.")
        return LiveArea("Pontual", map_mode="point")
    named = st.session_state.get("fv_live_point_name")
    name = named[2] if named and (named[0], named[1]) == (round(lat, 4), round(lon, 4)) else f"{lat:.3f}, {lon:.3f}"
    st.caption(f"Raio de {radius} km em {name}. Clique no mapa para mudar o ponto.")
    return LiveArea("Pontual", circular_buffer_geometry(lat, lon, radius), f"raio de {radius} km em {name}",
                    map_mode="point", point=(lat, lon), reference="do ponto")


def _rectangle_panel() -> LiveArea:
    from src.spatial_tools import rectangle_geometry

    r = st.columns(4)
    labels = ("Lat. sul", "Lat. norte", "Lon. oeste", "Lon. leste")
    limits = ((-90.0, 90.0), (-90.0, 90.0), (-180.0, 180.0), (-180.0, 180.0))
    hints = ("ex.: -23,0", "ex.: -21,0", "ex.: -46,5", "ex.: -44,0")
    values = [col.number_input(lab, lo, hi, value=None, step=0.1, format="%.4f", placeholder=hint, key=key)
              for col, lab, (lo, hi), hint, key in zip(r, labels, limits, hints, _RECT_KEYS)]
    complete = None not in values
    drawing = not complete or bool(st.session_state.get("fv_live_rect_redraw"))
    cap, btn = st.columns([0.72, 0.28], vertical_alignment="center")
    if drawing:
        cap.caption("**Arraste no mapa** para desenhar o retângulo (ou clique em dois cantos opostos), "
                    "ou digite os limites em graus decimais.")
    else:
        cap.caption("Retângulo aplicado. Para trocar, desenhe de novo ou edite os limites.")
        if btn.button("▭ Desenhar de novo", key="fv_live_rect_redraw_btn", width="stretch"):
            st.session_state["fv_live_rect_redraw"] = True
            st.rerun(scope="fragment")
    geometry = None
    if complete:
        south, north, west, east = values
        try:
            geometry = rectangle_geometry(south, west, north, east)
        except ValueError as exc:
            st.warning(str(exc))
    return LiveArea("Retângulo", geometry, "retângulo selecionado" if geometry is not None else None,
                    map_mode="rectangle" if drawing else None)


def _states_panel() -> LiveArea:
    from src.previsao_flash import _simplified_states, area_label
    try:
        states = _simplified_states()
    except Exception:
        st.warning("Limites dos estados indisponíveis nesta sessão.")
        return LiveArea("Estados")
    lookup = {f"{r.abbrev_state} — {r.name_state}": r.abbrev_state for r in states.itertuples()}
    chosen = st.multiselect("Estados", list(lookup), key="fv_live_states", placeholder="Escolha um ou mais estados")
    if not chosen:
        return LiveArea("Estados")
    ufs = tuple(sorted(lookup[c] for c in chosen))
    label = chosen[0] if len(chosen) == 1 else area_label(list(ufs), "estados")
    return LiveArea("Estados", _from_wkb(_states_wkb(ufs)), label)


def _municipalities_panel() -> LiveArea:
    from src.previsao_flash import _norm_code, area_label, city_catalog
    try:
        cities = city_catalog().sort_values(["name_muni", "abbrev_state"])
    except Exception:
        st.warning("Lista de municípios indisponível nesta sessão.")
        return LiveArea("Municípios")
    options = {f"{r.name_muni} ({r.abbrev_state})": (_norm_code(r.code_muni), r.abbrev_state)
               for r in cities.itertuples()}
    chosen = st.multiselect("Municípios", list(options), key="fv_live_munis", max_selections=30,
                            placeholder="Digite o nome e escolha um ou mais")
    if not chosen:
        return LiveArea("Municípios")
    try:
        with st.spinner("Carregando limites municipais (IBGE)…"):
            geometry = _from_wkb(_municipalities_wkb(tuple(sorted(options[c] for c in chosen))))
    except Exception:
        geometry = None
    if geometry is None:
        st.warning("Limites desses municípios indisponíveis nesta sessão.")
        return LiveArea("Municípios")
    return LiveArea("Municípios", geometry, area_label(chosen, "municípios"))


def _file_panel() -> LiveArea:
    from src.map_uploads import load_user_overlay

    st.caption("Shapefile (ZIP com .shp, .shx, .dbf e .prj), KML, KMZ ou GeoJSON, até 20 MB. "
               "O arquivo fica só na sua sessão; não é enviado ao GitHub/HF.")
    uploaded = st.file_uploader("Arquivo da área", type=["zip", "kmz", "kml", "geojson", "json"],
                                key=f"fv_geo_upload_{st.session_state.get('fv_upload_version', 0)}")
    if uploaded is not None:
        blob = uploaded.getvalue()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != st.session_state.get("fv_uploaded_digest"):
            try:
                geojson, polygon, nfeat = load_user_overlay(uploaded.name, blob)
                st.session_state["fv_user_geojson"] = geojson
                st.session_state["fv_user_polygon_wkb"] = polygon.wkb.hex() if polygon is not None else None
                st.session_state["fv_uploaded_digest"] = digest
                st.session_state["fv_uploaded_name"] = uploaded.name
                st.toast(f"Camada carregada: {nfeat} feição(ões).")
            except Exception as exc:
                st.error(f"Não foi possível ler a geometria: {exc}")
    if not st.session_state.get("fv_user_geojson"):
        return LiveArea("Arquivo")
    name = st.session_state.get("fv_uploaded_name") or "arquivo importado"
    nfeat = len(st.session_state["fv_user_geojson"]["features"])
    info, rm = st.columns([0.72, 0.28], vertical_alignment="center")
    info.caption(f"Camada ativa: {name} ({nfeat} feição(ões)).")
    if rm.button("✖ Remover arquivo", key="fv_overlay_reset", width="stretch"):
        for key in ("fv_user_geojson", "fv_user_polygon_wkb", "fv_uploaded_digest", "fv_uploaded_name"):
            st.session_state.pop(key, None)
        st.session_state["fv_upload_version"] = int(st.session_state.get("fv_upload_version", 0)) + 1
        st.rerun(scope="fragment")
    geometry = _from_wkb(st.session_state.get("fv_user_polygon_wkb"))
    if geometry is None:
        st.warning("O arquivo não tem polígonos (só linhas ou pontos): ele aparece no mapa, mas não filtra.")
        return LiveArea("Arquivo")
    return LiveArea("Arquivo", geometry, f"arquivo {name}")


def live_area_mode_control() -> str | None:
    """Barra "Área no mapa" (como na Tendência). None: mapa inteiro, sem filtro."""
    _apply_pending()
    return st.segmented_control("Área no mapa", LIVE_AREA_MODES, format_func=_MODE_LABELS.get,
                                key="fv_live_area_mode")


def render_live_area_panel(mode: str | None) -> LiveArea:
    """Campos do tipo de área escolhido, numa caixa logo abaixo da barra."""
    if mode is None:
        st.caption("Sem área: o mapa e os números mostram toda a cobertura do GLM. Escolha um tipo de área "
                   "para filtrar e para usar o alarme.")
        return LiveArea(None)
    with st.container(border=True):
        panel = {"Pontual": _point_panel, "Retângulo": _rectangle_panel, "Estados": _states_panel,
                 "Municípios": _municipalities_panel, "Arquivo": _file_panel}[mode]
        return panel()
