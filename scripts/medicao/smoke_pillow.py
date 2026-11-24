"""Exportações que usam Pillow (prancha raster, prancha de imagem, GIF, JPEG) com fundo offline.

Uso: python smoke_pillow.py <repo>  -> imprime versão do Pillow, tamanho e hash de cada saída.
"""
import hashlib
import io
import sys
import warnings
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore")
sys.path.insert(0, sys.argv[1])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import PIL  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import box  # noqa: E402

from src.cartographic_export import (BoardMeta, jpeg_from_png, render_glm_board_gif,  # noqa: E402
                                     render_image_board, render_raster_board)
from src.view_exports import to_jpeg  # noqa: E402


def loader(ax, *a, **k):
    rgb = np.full((64, 64, 3), 90, dtype=np.uint8)
    return rgb, (-6.0e6, -4.0e6, -3.5e6, -1.5e6)


def show(name, data):
    im = Image.open(io.BytesIO(data))
    frames = getattr(im, "n_frames", 1)
    print(f"{name:<14} {im.format:<4} {im.size} quadros={frames} sha={hashlib.sha256(data).hexdigest()[:12]}")


print("Pillow", PIL.__version__)
meta = BoardMeta(product="Teste", region="MG", period="jan/2025", source="sintético", resolution="0,08°",
                 basemap="satellite")
lat = np.arange(-23.0, -14.0, 0.08)
lon = np.arange(-51.0, -39.0, 0.08)
field = np.random.default_rng(0).random((lat.size, lon.size)) * 10
png = render_raster_board(lat, lon, field, meta=meta, variable="flash_count", fixed_range=(0, 10),
                          geometry=box(-50, -22, -40, -15), width=1600, unit="flashes",
                          background_loader=loader)
show("raster PNG", png)
show("raster JPEG", jpeg_from_png(png))
show("imagem PNG", render_image_board(png, meta=meta, chart_kind="Teste"))
show("to_jpeg", to_jpeg(png))
end = datetime(2026, 11, 23, 22, 0, tzinfo=timezone.utc)
rng = np.random.default_rng(1)
flashes = pd.DataFrame({
    "lat": rng.uniform(-22, -15, 400), "lon": rng.uniform(-50, -40, 400),
    "time_start": [end - timedelta(minutes=float(m)) for m in rng.uniform(0, 89, 400)],
})
gif = render_glm_board_gif(flashes, end, meta=meta, geometry=box(-50, -22, -40, -15), width=1600,
                           output_width=600, background_loader=loader)
show("GIF", gif)
