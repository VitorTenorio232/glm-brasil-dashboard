from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import h5py
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.alertas_flash import analyze_glm_activity
from src.glm_reader import read_glm_file
from src.historical_glm import anomaly_range


def _write_fake_lcfa(path: Path) -> None:
    """Arquivo no formato do GLM-L2-LCFA: int16 '_Unsigned', _FillValue e scale/offset."""
    raw_time = np.array([13107, 26214, -1], dtype=np.int16)  # -1 = 65535 sem sinal
    time_attrs = {
        "scale_factor": np.array([0.00038147560553625226], dtype=np.float32),
        "add_offset": np.array([-5.0], dtype=np.float32),
        "_Unsigned": b"true",
        "units": b"seconds since 2026-10-26 20:57:00.000",
    }
    with h5py.File(path, "w") as h:
        h["flash_lat"] = np.array([-15.0, -20.5, -3.25], dtype=np.float32)
        h["flash_lon"] = np.array([-47.9, -43.2, -60.0], dtype=np.float32)
        h["flash_id"] = np.array([1, 2, -1], dtype=np.int16)
        h["flash_id"].attrs["_Unsigned"] = b"true"
        for name in ("flash_time_offset_of_first_event", "flash_time_offset_of_last_event"):
            h[name] = raw_time
            h[name].attrs.update(time_attrs)
        h["flash_area"] = np.array([10, -1, 20], dtype=np.int16)
        h["flash_area"].attrs.update({"_FillValue": np.array([-1], dtype=np.int16),
                                      "scale_factor": np.array([152601.859375], dtype=np.float32),
                                      "_Unsigned": b"true", "units": b"m2"})
        h["flash_quality_flag"] = np.array([0, 0, 1], dtype=np.int16)
        h["flash_quality_flag"].attrs.update({"_FillValue": np.array([-1], dtype=np.int16),
                                              "_Unsigned": b"true"})


def test_h5py_reader_decodes_cf_packing(tmp_path):
    path = tmp_path / "OR_GLM-L2-LCFA_fake.nc"
    _write_fake_lcfa(path)
    df = read_glm_file(path, quality="all")

    assert list(df["flash_id"]) == [1, 2, 65535]  # _Unsigned aplicado
    assert np.isnan(df.loc[1, "area_km2"])  # _FillValue vira NaN
    assert np.isclose(df.loc[0, "area_km2"], 152601.859375 * 10 / 1e6)
    base = pd.Timestamp("2026-10-26 20:57:00", tz="UTC")
    expected = base + pd.to_timedelta(13107 * np.float32(0.00038147560553625226) - 5.0, unit="s")
    assert abs(df.loc[0, "time_start"] - expected) < pd.Timedelta("1us")
    # 65535 sem sinal: offset positivo (~20 s), não negativo
    assert df.loc[2, "time_start"] > base + pd.Timedelta(seconds=19)

    assert len(read_glm_file(path, quality="zero_only")) == 2


def test_anomaly_range_is_symmetric():
    lo, hi = anomaly_range(np.array([-3.0, 1.0, 2.0, np.nan]))
    assert lo == -hi and hi > 0
    assert anomaly_range(np.zeros(4)) == (-1.0, 1.0)


def test_activity_trend_windows():
    end = datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc)
    times = ([end - timedelta(minutes=2)] * 12 + [end - timedelta(minutes=15)] * 4)
    summary = analyze_glm_activity(pd.DataFrame({"time_start": times}), end, latency_minutes=1)
    assert (summary.latest_10min, summary.previous_10min) == (12, 4)
    assert summary.trend.startswith("Intensificação")
    assert summary.delta_percent == 200


def test_tendencia_quatro_tipos_de_area():
    import pandas as pd
    from shapely.geometry import box
    from src.previsao_flash import AREA_MODES, _norm_code, _union, area_label, rect_from_drawing
    from src.spatial_tools import filter_points_by_geometry

    assert AREA_MODES == ["Pontual", "Retângulo", "Estados", "Municípios", "Arquivo"]
    # GeoJSON do Leaflet.Draw (lon, lat) -> (sul, norte, oeste, leste)
    drawing = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[
        [-48.0, -23.0], [-48.0, -18.0], [-42.0, -18.0], [-42.0, -23.0], [-48.0, -23.0]]]}}
    assert rect_from_drawing(drawing) == (-23.0, -18.0, -48.0, -42.0)
    assert rect_from_drawing(None) is None

    assert area_label(["MG", "SP"], "estados") == "MG, SP"
    assert area_label(["A", "B", "C", "D"], "municípios") == "4 municípios: A, B e outros"
    assert _norm_code(3132404.0) == "3132404" and _norm_code("3132404") == "3132404"

    # Duas áreas separadas: os flashes de ambas entram, o de fora não.
    union = _union([box(0, 0, 1, 1), box(5, 5, 6, 6)])
    flashes = pd.DataFrame({"lat": [0.5, 5.5, 3.0], "lon": [0.5, 5.5, 3.0]})
    assert len(filter_points_by_geometry(flashes, union)) == 2
    assert _union([]) is None


def test_tendencia_area_de_arquivo(tmp_path):
    import io
    import json
    import zipfile

    import geopandas as gpd
    import pytest
    from shapely.geometry import box
    from src.previsao_flash import area_from_upload

    area = box(-60.0, -5.0, -58.0, -3.0)

    # Shapefile em ZIP (.shp, .shx, .dbf, .prj), como sai do QGIS.
    gpd.GeoDataFrame({"nome": ["teste"]}, geometry=[area], crs=4326).to_file(tmp_path / "area.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in ("shp", "shx", "dbf", "prj"):
            zf.write(tmp_path / f"area.{ext}", f"area.{ext}")
    geom, label = area_from_upload("minha_area.zip", buf.getvalue())
    assert geom.equals_exact(area, 1e-6) or abs(geom.area - area.area) < 1e-9
    assert label == "Arquivo minha_area.zip"

    kml = ("<?xml version='1.0'?><kml xmlns='http://www.opengis.net/kml/2.2'><Placemark><Polygon>"
           "<outerBoundaryIs><LinearRing><coordinates>-60,-5 -58,-5 -58,-3 -60,-3 -60,-5</coordinates>"
           "</LinearRing></outerBoundaryIs></Polygon></Placemark></kml>").encode()
    geom, _ = area_from_upload("area.kml", kml)
    assert abs(geom.area - area.area) < 1e-9

    two = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": json.loads(json.dumps(box(-60, -5, -59, -4).__geo_interface__))},
        {"type": "Feature", "properties": {}, "geometry": json.loads(json.dumps(box(-50, -5, -49, -4).__geo_interface__))},
    ]}
    geom, label = area_from_upload("duas.geojson", json.dumps(two).encode())
    assert abs(geom.area - 2.0) < 1e-9 and label.endswith("(2 feições)")

    line = {"type": "LineString", "coordinates": [[-60, -5], [-58, -3]]}
    with pytest.raises(ValueError, match="polígonos"):
        area_from_upload("linha.geojson", json.dumps(line).encode())


def test_cartoes_da_tendencia_mostram_as_tres_janelas():
    from src.alertas_flash import LightningActivity, render_observational_alert

    shown = []

    class _Col:
        def metric(self, label, value, **kwargs):
            shown.append((label, value))

    class _Box:
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    class _St:
        def container(self, **kwargs): return _Box()
        def columns(self, n): return [_Col() for _ in range(n)]
        def markdown(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def info(self, *a, **k): pass
        def caption(self, *a, **k): pass

    summary = LightningActivity(1200, 900, 1500, "Intensificação ▲", 33.3, "ok", False)
    render_observational_alert(_St(), summary)
    assert shown == [("Flashes · 0–10 min", "1.200"), ("Flashes · 10–20 min", "900"),
                     ("Flashes · 20–30 min", "1.500"), ("Tendência observada", "Intensificação ▲")]
