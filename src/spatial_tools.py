from __future__ import annotations

from typing import Any

import numpy as np


def rectangle_geometry(south: float, west: float, north: float, east: float):
    from shapely.geometry import box

    south, north = sorted((float(south), float(north)))
    west, east = sorted((float(west), float(east)))
    if not (-90 <= south < north <= 90):
        raise ValueError("Latitudes inválidas para o retângulo.")
    if not (-180 <= west < east <= 180):
        raise ValueError("Longitudes inválidas para o retângulo.")
    return box(west, south, east, north)


def circular_buffer_geometry(lat: float, lon: float, radius_km: float):
    """Cria buffer geodésico aproximado em km usando AEQD local."""
    from pyproj import CRS, Transformer
    from shapely.geometry import Point
    from shapely.ops import transform

    lat = float(lat)
    lon = float(lon)
    radius_km = float(radius_km)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude/longitude inválidas.")
    if radius_km <= 0:
        raise ValueError("O raio do buffer deve ser positivo.")

    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs"
    )
    wgs84 = CRS.from_epsg(4326)
    to_local = Transformer.from_crs(wgs84, local, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(local, wgs84, always_xy=True).transform
    point_local = transform(to_local, Point(lon, lat))
    return transform(to_wgs84, point_local.buffer(radius_km * 1000.0, resolution=64))


def geometry_from_geojson(obj: dict[str, Any] | None):
    if not obj:
        return None
    from shapely.geometry import shape

    geometry = obj.get("geometry", obj)
    if not geometry:
        return None
    geom = shape(geometry)
    if geom.is_empty:
        return None
    return geom


def representative_latlon(geometry) -> tuple[float, float]:
    point = geometry.representative_point()
    return float(point.y), float(point.x)


def filter_points_by_geometry(df, geometry, *, lat_col: str = "lat", lon_col: str = "lon"):
    """Filtra DataFrame de pontos sem GeoDataFrame, usando Shapely vetorizado."""
    if geometry is None or df is None or len(df) == 0:
        return df
    from shapely import contains_xy, intersects_xy

    lat = np.asarray(df[lat_col], dtype=float)
    lon = np.asarray(df[lon_col], dtype=float)
    valid = np.isfinite(lat) & np.isfinite(lon)
    inside = np.zeros(len(df), dtype=bool)
    if np.any(valid):
        mask = contains_xy(geometry, lon[valid], lat[valid])
        try:
            mask |= intersects_xy(geometry.boundary, lon[valid], lat[valid])
        except Exception:
            pass
        inside[np.where(valid)[0]] = mask
    return df.loc[inside].copy()


def padded_bounds(geometry, *, frac: float = 0.06, min_pad: float = 0.08):
    minx, miny, maxx, maxy = geometry.bounds
    dx = max(float(maxx - minx) * frac, min_pad)
    dy = max(float(maxy - miny) * frac, min_pad)
    return [[miny - dy, minx - dx], [maxy + dy, maxx + dx]]


def build_rectangle_selector_map(initial_geometry=None):
    import folium
    from folium.plugins import Draw, Fullscreen

    m = folium.Map(
        location=[-14.2, -51.9],
        zoom_start=4,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri",
        name="Satélite",
        overlay=False,
        control=True,
        show=True,
        max_zoom=19,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Mapa", show=False).add_to(m)

    if initial_geometry is not None:
        from shapely.geometry import mapping
        folium.GeoJson(
            mapping(initial_geometry),
            name="Área selecionada",
            style_function=lambda _: {
                "color": "#f97316", "weight": 2.5, "fillColor": "#f97316", "fillOpacity": 0.08
            },
        ).add_to(m)
        m.fit_bounds(padded_bounds(initial_geometry))
    else:
        m.fit_bounds([[-35.5, -75.5], [6.5, -32.0]], padding=(10, 10))

    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": False,
            "polygon": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
            "rectangle": {
                "shapeOptions": {
                    "color": "#f97316",
                    "weight": 2.5,
                    "fillOpacity": 0.08,
                }
            },
        },
        edit_options={"edit": False, "remove": True},
    ).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def build_geometry_preview_map(geometry, *, label: str = "Área selecionada"):
    import folium
    from folium.plugins import Fullscreen
    from shapely.geometry import mapping

    m = folium.Map(
        location=[-14.2, -51.9], zoom_start=4, tiles=None,
        control_scale=True, prefer_canvas=True,
    )
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri", name="Satélite", show=True, max_zoom=19,
    ).add_to(m)
    folium.GeoJson(
        mapping(geometry), name=label,
        style_function=lambda _: {
            "color": "#f97316", "weight": 2.5,
            "fillColor": "#f97316", "fillOpacity": 0.08,
        },
    ).add_to(m)
    m.fit_bounds(padded_bounds(geometry), padding=(10, 10))
    Fullscreen(position="topleft").add_to(m)
    return m
