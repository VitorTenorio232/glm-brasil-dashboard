"""Fluxo das Séries com base sintética (AppTest, sem rede): 0 ≠ ausente, catálogo lido uma vez e
downloads sem refazer a prancha a cada rerun. Também a máscara rápida de células."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dados_sinteticos import AUSENTE, ZERO, build_base  # noqa: E402

SERIES = "📈 Séries temporais"


def test_cells_in_geometry_igual_ao_metodo_antigo_inclusive_na_borda():
    from shapely import contains_xy, intersects_xy
    from shapely.geometry import Polygon, box

    from src.historical_glm import cells_in_geometry

    lat = np.round(np.arange(-22.5, -20.5, 0.02), 2)
    lon = np.round(np.arange(-45.5, -43.5, 0.02), 2)
    xx, yy = np.meshgrid(lon, lat)
    for geom in (box(-45.0, -22.0, -44.0, -21.0),  # lados exatamente sobre centros de células
                 Polygon([(-45.3, -22.3), (-43.7, -21.9), (-44.2, -20.6)])):
        old = contains_xy(geom, xx, yy) | intersects_xy(geom.boundary, xx, yy)
        assert np.array_equal(cells_in_geometry(geom, xx, yy), old)


def test_complete_series_distingue_zero_de_ausente():
    from src.historical_glm import SERIES_NO_FILE, SERIES_OBSERVED, complete_series

    s = pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-03-01"]), "year": [2024, 2024],
                      "month": [1, 3], "day": [1, 1], "value": [5.0, 0.0], "relpath": ["a", "b"]})
    full = complete_series(s, "monthly", "2024-01-01", "2024-04-30")
    assert list(full["month"]) == [1, 2, 3, 4]
    assert list(full["situacao"]) == [SERIES_OBSERVED, SERIES_NO_FILE, SERIES_OBSERVED, SERIES_NO_FILE]
    assert full.loc[2, "value"] == 0.0 and np.isnan(full.loc[1, "value"])


_MEDIA: dict[str, bytes] = {}


def _download(at, label: str) -> bytes:
    """Conteúdo servido pelo botão de download (o que o navegador receberia)."""
    button = next(b for b in at.get("download_button") if label in b.proto.label)
    file_id = button.proto.url.rsplit("/", 1)[-1].split(".")[0]
    return _MEDIA[file_id]


@pytest.fixture()
def app_series(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import src.cartographic_export as ce

    root = build_base(tmp_path / "OUTPUT")
    monkeypatch.setenv("FLASH_VIEW_DATA_ROOT", str(root))
    calls = {"rglob": 0, "board": 0}
    orig_rglob, orig_board = Path.rglob, ce.render_image_board

    def rglob(self, pattern, *a, **k):
        if str(self).startswith(str(root)):
            calls["rglob"] += 1
        return orig_rglob(self, pattern, *a, **k)

    def board(*a, **k):
        calls["board"] += 1
        return orig_board(*a, **k)

    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

    orig_load = MemoryMediaFileStorage.load_and_get_id

    def load(self, path_or_data, *a, **k):
        file_id = orig_load(self, path_or_data, *a, **k)
        if isinstance(path_or_data, bytes):
            _MEDIA[file_id] = path_or_data
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", load)
    monkeypatch.setattr(Path, "rglob", rglob)
    monkeypatch.setattr(ce, "render_image_board", board)
    import streamlit as st
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.session_state["fv_active_tab"] = SERIES  # sem abrir o ao vivo (rede)
    at.run()
    at.selectbox(key="series_area").set_value("Retângulo").run()
    at.radio(key="series_rectangle_method").set_value("Digitar coordenadas").run()
    at.selectbox(key="series_scale").set_value("Mensal").run()
    months = at.selectbox(key="series_month_start").options
    at.selectbox(key="series_month_start").set_value(months[0]).run()
    at.selectbox(key="series_month_end").set_value(months[-1]).run()
    return at, calls


def test_series_zero_observado_e_mes_sem_arquivo(app_series):
    import json

    at, calls = app_series
    at.button(key="calculate_historical_series").click().run()
    assert not at.exception
    info = " ".join(i.value for i in at.info)
    assert "1 período(s) sem dado" in info and "Abril/2024" in info

    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    trace = spec["data"][0]
    x = [str(v)[:7] for v in trace["x"]]
    assert x == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    assert trace.get("connectgaps") is False

    csv = pd.read_csv(io.BytesIO(_download(at, "Dados CSV")))  # o arquivo do botão, como baixado
    by_month = csv.set_index(pd.to_datetime(csv["date"]).dt.month)
    assert by_month.loc[ZERO, "value"] == 0 and by_month.loc[ZERO, "situacao"] == "observado"
    assert pd.isna(by_month.loc[AUSENTE, "value"]) and by_month.loc[AUSENTE, "situacao"] == "sem arquivo na base"


def test_catalogo_lido_uma_vez_e_prancha_nao_refeita_no_rerun(app_series):
    at, calls = app_series
    scans_before = calls["rglob"]
    at.button(key="calculate_historical_series").click().run()
    assert calls["board"] == 1
    at.run()  # rerun com a série na tela (ex.: outra interação na aba)
    at.run()
    assert calls["board"] == 1  # antes: uma prancha nova a cada rerun
    # Outra área (outro cálculo) não relê o catálogo: antes, cada consulta nova fazia um rglob
    # (no Hugging Face, um list_repo_files).
    at.number_input(key="series_north").set_value(-19.0).run()
    at.button(key="calculate_historical_series").click().run()
    assert not at.exception
    assert calls["rglob"] == scans_before
