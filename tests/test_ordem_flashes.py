"""Relâmpagos mais recentes sempre por cima dos mais antigos (mapa ao vivo, Tendência e pranchas)."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

END = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def _flashes(ages_min, lat=-22.4, lon=-45.45):
    """Flashes no mesmo lugar, com as idades dadas (minutos antes de END)."""
    return pd.DataFrame({
        "time_start": [END - timedelta(minutes=a) for a in ages_min],
        "lat": [lat + 0.001 * i for i in range(len(ages_min))],
        "lon": [lon] * len(ages_min),
    })


def test_prancha_desenha_do_mais_antigo_ao_mais_novo(monkeypatch):
    import numpy as np
    from matplotlib.axes import Axes
    from src.cartographic_export import BoardMeta, GLM_BANDS, render_flash_board

    calls = []
    original = Axes.scatter

    def spy(self, x, y, *args, **kwargs):
        calls.append(list(kwargs.get("c")))
        return original(self, x, y, *args, **kwargs)

    monkeypatch.setattr(Axes, "scatter", spy)
    blank = lambda ex, _src: (np.zeros((4, 4, 3)), (ex[0], ex[1], ex[2], ex[3]))  # noqa: E731
    meta = BoardMeta(product="Teste", region="Itajubá", period="30 min", reference_utc=END)
    render_flash_board(_flashes([2, 25, 12, 7, 0.5]), meta=meta, width=1600,
                       observation_end=END, background_loader=blank)
    color = {label: c for _lo, _hi, c, label in GLM_BANDS}
    # 25 (20–30), 12 (10–20), 7 (5–10), 2 e 0,5 (0–5): o mais novo fica por último, por cima.
    assert calls == [[color["20–30 min"], color["10–20 min"], color["5–10 min"], color["0–5 min"], color["0–5 min"]]]


def test_mapa_da_tendencia_poe_faixa_recente_por_cima():
    from src.previsao_flash import build_observed_map
    from src.realtime_glm import classify_age_groups

    flashes = classify_age_groups(_flashes([45, 25, 2, 12, 7]), END)
    html = build_observed_map(-22.4, -45.45, 20, flashes).get_root().render()
    # Um pane por faixa, com z-index maior para a faixa mais recente (0–5 min).
    import re
    z = {int(rank): int(zi) for rank, zi in
         re.findall(r'createPane\(\s*"fv-flash-age-(\d)"\);\s*\w+\.style\.zIndex = (\d+);', html)}
    assert sorted(z) == [0, 1, 2, 3, 4]
    assert z[0] > z[1] > z[2] > z[3] > z[4] > 400
    assert html.count('"pane": "fv-flash-age-') == 5


def test_mapa_ao_vivo_ordena_pelo_tempo(tmp_path):
    """symbol-sort-key = order (ms até o fim da janela): o flash mais novo tem a maior chave."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não instalado")
    src = Path(__file__).resolve().parents[1] / "src"
    js = (src / "maplibre_realtime.js").read_text(encoding="utf-8")
    assert "'symbol-sort-key':['get','order']" in js
    module = tmp_path / "mapa.mjs"
    module.write_text((src / "alarme_navegador.js").read_text(encoding="utf-8") + "\n" + js, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text("""
import {timelineFeatureCollection} from './mapa.mjs';
const end = Date.UTC(2026, 10, 23, 15, 0), M = 60000;
const fc = timelineFeatureCollection([[-45, -22, end - 25*M], [-45, -22, end - 2*M], [-45, -22, end - 12*M]], end, true, 12);
console.log(JSON.stringify(fc.features.map(f => [f.properties.age, f.properties.order])));
""", encoding="utf-8")
    res = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    rows = json.loads(res.stdout)
    assert rows == [[25, -1500000], [2, -120000], [12, -720000]]
    newest = max(rows, key=lambda r: r[1])
    assert newest[0] == 2
