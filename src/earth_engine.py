from __future__ import annotations

import math
import os
from typing import Mapping

DEFAULT_PALETTE = ["0d0887", "5b02a3", "9a179b", "cb4679", "ed7953", "fb9f3a", "fdca26", "f0f921"]


def initialize_ee(project: str | None = None, service_account: str | None = None, private_key_json: str | None = None):
    import ee
    project = project or os.getenv("EE_PROJECT")
    if not project:
        raise RuntimeError("Defina EE_PROJECT com o projeto Google Cloud registrado no Earth Engine.")
    service_account = service_account or os.getenv("EE_SERVICE_ACCOUNT")
    private_key_json = private_key_json or os.getenv("EE_PRIVATE_KEY_JSON")
    if service_account and private_key_json:
        credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key_json)
        ee.Initialize(credentials, project=project)
    else:
        ee.Initialize(project=project)
    return ee


def metric_image(asset_id: str, mapping: Mapping[str, float], *, code_property: str = "code_muni", missing_value: float = -9999.0):
    import ee
    clean = {
        str(k): float(v) for k, v in mapping.items()
        if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
    }
    values = ee.Dictionary(clean)
    fc = ee.FeatureCollection(asset_id)

    def attach(feature):
        key = ee.String(feature.get(code_property))
        val = ee.Number(values.get(key, missing_value))
        return feature.set("metric", val)

    fc_metric = fc.map(attach)
    image = ee.Image().float().paint(fc_metric, "metric")
    image = image.updateMask(image.neq(missing_value))
    borders = ee.Image().byte().paint(fc, 1, 1)
    return image, borders, fc_metric


def folium_ee_map(
    asset_id: str,
    mapping: Mapping[str, float],
    *,
    vmin: float,
    vmax: float,
    palette=None,
    center=(-14.2, -51.9),
    zoom=4,
    code_property="code_muni",
):
    import folium
    palette = palette or DEFAULT_PALETTE
    image, borders, _ = metric_image(asset_id, mapping, code_property=code_property)
    vis = {"min": float(vmin), "max": float(vmax), "palette": palette}
    map_id = image.getMapId(vis)
    border_id = borders.getMapId({"palette": ["333333"]})
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron", control_scale=True)
    folium.TileLayer(
        tiles=map_id["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name="GLM municipal",
        overlay=True,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles=border_id["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name="Limites municipais",
        overlay=True,
        control=True,
    ).add_to(m)
    folium.LayerControl().add_to(m)
    return m
