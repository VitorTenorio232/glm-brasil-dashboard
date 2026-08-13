from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry.base import BaseGeometry

ESRI_IMAGERY = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
ESRI_LABELS = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
)
ESRI_ATTR = "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"


def _base_map(location=(-14.2, -51.9), zoom=4):
    import folium
    m = folium.Map(location=list(location), zoom_start=zoom, tiles=None, control_scale=True, prefer_canvas=True)
    folium.TileLayer(
        tiles=ESRI_IMAGERY, attr=ESRI_ATTR, name="Satélite", overlay=False,
        control=False, max_zoom=19,
    ).add_to(m)
    folium.TileLayer(
        tiles=ESRI_LABELS, attr="Esri", name="Nomes e limites", overlay=True,
        control=True, show=True, max_zoom=19, opacity=.9,
    ).add_to(m)
    return m


def build_draw_map(initial_geometry: BaseGeometry | None = None):
    import folium
    from folium.plugins import Draw

    m = _base_map()
    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": False,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "polygon": {"allowIntersection": False, "showArea": True},
            "rectangle": {"showArea": True},
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    if initial_geometry is not None:
        folium.GeoJson(
            gpd.GeoSeries([initial_geometry], crs=4326).to_json(),
            style_function=lambda _: {"color": "#00ffff", "weight": 3, "fillOpacity": .08},
            name="Região selecionada",
        ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def _add_boundary(m, geometry: BaseGeometry, label: str):
    import folium
    gdf = gpd.GeoDataFrame({"label": [label]}, geometry=[geometry], crs=4326)
    folium.GeoJson(
        gdf.to_json(drop_id=True),
        name=label,
        style_function=lambda _: {
            "color": "#ffffff", "weight": 2.5, "opacity": .95,
            "fillColor": "#000000", "fillOpacity": 0.0,
        },
        tooltip=label,
    ).add_to(m)


def _fit(m, geometry: BaseGeometry):
    minx, miny, maxx, maxy = geometry.bounds
    m.fit_bounds([[float(miny), float(minx)], [float(maxy), float(maxx)]], padding=(25, 25))


def _popup(row: pd.Series) -> str:
    t = pd.to_datetime(row.get("time_start"), utc=True, errors="coerce")
    parts = [f"<b>UTC:</b> {t.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(t) else '-'}"]
    if pd.notna(row.get("energy_j", np.nan)):
        parts.append(f"<b>Energia:</b> {float(row['energy_j']):.4g} J")
    if pd.notna(row.get("area_km2", np.nan)):
        parts.append(f"<b>Área:</b> {float(row['area_km2']):.2f} km²")
    if pd.notna(row.get("duration_ms", np.nan)):
        parts.append(f"<b>Duração:</b> {float(row['duration_ms']):.0f} ms")
    return "<br>".join(parts)


def build_analysis_map(
    flashes: pd.DataFrame,
    geometry: BaseGeometry,
    *,
    label: str,
    mode: str = "Flashes individuais",
    max_points: int = 20000,
):
    import folium
    from folium.plugins import HeatMap, FastMarkerCluster

    minx, miny, maxx, maxy = geometry.bounds
    m = _base_map(location=((miny + maxy) / 2, (minx + maxx) / 2), zoom=8)
    _add_boundary(m, geometry, label)

    data = flashes.copy()
    sampled = False
    if len(data) > max_points:
        data = data.sample(max_points, random_state=42).sort_values("time_start")
        sampled = True

    if mode == "Mapa de calor":
        points = data[["lat", "lon"]].dropna().values.tolist()
        if points:
            HeatMap(points, radius=10, blur=14, min_opacity=.25, name="Densidade visual").add_to(m)
    elif mode == "Últimos 15 min (🔴🔵🟢)":
        if not data.empty:
            times = pd.to_datetime(data["time_start"], utc=True, errors="coerce")
            latest = times.max()
            age = (latest - times).dt.total_seconds() / 60
            groups = [
                ("10–15 min", (age > 10) & (age <= 15), "green"),
                ("5–10 min", (age > 5) & (age <= 10), "blue"),
                ("0–5 min", (age >= 0) & (age <= 5), "red"),
            ]
            for name, mask, color in groups:
                sub = data.loc[mask]
                fg = folium.FeatureGroup(name=f"{name}: {len(sub):,}".replace(",", "."), show=True)
                for _, row in sub.iterrows():
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])], radius=3.2,
                        color=color, weight=.8, fill=True, fill_color=color, fill_opacity=.9,
                        popup=folium.Popup(_popup(row), max_width=320),
                    ).add_to(fg)
                fg.add_to(m)
    else:
        # Para muitos pontos, FastMarkerCluster é muito mais leve que milhares de CircleMarker.
        points = data[["lat", "lon"]].dropna().values.tolist()
        if len(points) > 4000:
            FastMarkerCluster(points, name="Flashes").add_to(m)
        else:
            fg = folium.FeatureGroup(name="Flashes", show=True)
            for _, row in data.iterrows():
                folium.CircleMarker(
                    [float(row["lat"]), float(row["lon"])], radius=3,
                    color="#ff2d20", weight=.7, fill=True, fill_color="#ff2d20", fill_opacity=.85,
                    popup=folium.Popup(_popup(row), max_width=320),
                ).add_to(fg)
            fg.add_to(m)

    _fit(m, geometry)
    folium.LayerControl(collapsed=False).add_to(m)
    m._glm_sampled = sampled
    m._glm_plotted = len(data)
    return m
