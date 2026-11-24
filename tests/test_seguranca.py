"""Regressões de segurança: rótulos do usuário nos mapas, mensagens de erro, XML e dependências."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.erros import public_message  # noqa: E402
from src.spatial_tools import map_text  # noqa: E402

EVIL = "Arquivo <img src=x onerror=alert(document.domain)>`;alert(2);`${alert(3)}.geojson"


def test_map_text_escapa_html_crase_e_cifrao():
    out = map_text(EVIL)
    assert "<" not in out and "`" not in out and "${" not in out
    assert "&lt;img" in out


def test_tooltip_da_tendencia_nao_executa_nome_do_arquivo():
    from src.previsao_flash import build_observed_map

    m = build_observed_map(-21.5, -44.5, 20, pd.DataFrame(columns=["lat", "lon", "age_minutes", "time_start"]),
                           center=[-21.5, -44.5], geometry=box(-45, -22, -44, -21), geometry_label=EVIL)
    page = m.get_root().render()
    assert "<img src=x" not in page
    assert "`;alert(2);`" not in page and "${alert(3)}" not in page


def test_camadas_do_mapa_historico_escapam_o_rotulo():
    import numpy as np

    from src.historical_glm import build_historical_map

    lat = np.arange(-22.5, -20.5, 0.08)
    lon = np.arange(-45.5, -43.5, 0.08)
    m = build_historical_map(lat, lon, np.ones((lat.size, lon.size)), "flash_count",
                             layer_name=f"Flashes — {EVIL}", clip_geometry=box(-45, -22, -44, -21),
                             boundary_name=f"Limite — {EVIL}", display_range=(0, 1))
    page = m.get_root().render()
    assert "<img src=x" not in page and "\\u003cimg src=x" not in page


@pytest.mark.parametrize("raw, hidden", [
    (r"[Errno -101] NetCDF: HDF error: 'C:\Users\fulano\AppData\Local\Temp\glm_brasil_live\OR_GLM.nc'", "fulano"),
    ("No such file: '/mount/src/glm-brasil-dashboard/GLM_Process/OUTPUT/03_MONTHLY/x.nc'", "/mount/src"),
    ("401 Client Error for token hf_TOKENFALSOparaTESTE000", "TOKENFALSO"),
])
def test_mensagem_publica_esconde_caminhos_e_tokens(raw, hidden):
    out = public_message(RuntimeError(raw))
    assert hidden not in out
    assert "OR_GLM.nc" in out or "x.nc" in out or "hf_***" in out


def test_mensagem_publica_mantem_url_da_fonte():
    out = public_message(RuntimeError('Connect timeout on endpoint URL: "https://noaa-goes19.s3.amazonaws.com/a/b"'))
    assert "https://noaa-goes19.s3.amazonaws.com/a/b" in out


def test_app_nao_usa_st_exception_direto():
    """st.exception() ignora client.showErrorDetails e mostra o traceback ao público."""
    offenders = [f"{p.name}:{i}" for p in [ROOT / "app.py", *sorted((ROOT / "src").glob("*.py"))]
                 if p.name not in {"erros.py", "earth_engine.py"} and not p.name.startswith("v4_")
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if "st.exception(" in line]
    assert offenders == []


def test_kml_com_billion_laughs_e_recusado_rapido():
    from src.map_uploads import load_user_overlay

    entities = '<!ENTITY a0 "lol">' + "".join(f'<!ENTITY a{i} "{"&a%d;" % (i - 1) * 10}">' for i in range(1, 10))
    bomb = (f'<?xml version="1.0"?><!DOCTYPE kml [{entities}]>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>&a9;</name></Document></kml>').encode()
    t0 = time.perf_counter()
    with pytest.raises(Exception):
        load_user_overlay("bomba.kml", bomb)
    assert time.perf_counter() - t0 < 5


def test_zip_com_caminho_para_fora_e_recusado():
    import io
    import zipfile

    from src.map_uploads import load_user_overlay

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../fora.shp", b"x")
    with pytest.raises(ValueError, match="inseguro"):
        load_user_overlay("area.zip", buf.getvalue())


def test_requirements_pedem_pillow_corrigido():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    spec = re.search(r"^Pillow([^\n#]*)", text, re.M | re.I).group(1)
    low = re.search(r">=\s*([\d.]+)", spec)
    assert low and tuple(int(x) for x in low.group(1).split(".")[:2]) >= (13, 0), spec
