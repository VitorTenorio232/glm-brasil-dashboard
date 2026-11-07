from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from shapely.geometry import box

from src.alarme import (AlarmMonitor, ObservationArea, alarm_message, bearing_deg, direction_label,
                        distance_km)

T0 = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
ITAJUBA = ObservationArea("Itajubá", -22.4136, -45.4497, radius_km=20)


def _flashes(points, start=T0):
    """points: lista de (minutos depois de T0, lat, lon)."""
    return pd.DataFrame({
        "flash_uid": [f"f{i}-{m}" for i, (m, _, _) in enumerate(points)],
        "time_start": [start + timedelta(minutes=m) for m, _, _ in points],
        "lat": [p[1] for p in points],
        "lon": [p[2] for p in points],
    })


def test_distancia_e_direcao():
    # 1° de latitude ~ 111,2 km; ao norte do ponto.
    assert distance_km(0, 0, [1.0], [0.0])[0] == pytest.approx(111.2, abs=0.2)
    assert bearing_deg(0, 0, [0.0], [1.0])[0] == pytest.approx(90.0)
    assert [direction_label(d) for d in (0, 44, 46, 90, 180, 225, 270, 315, 359)] == [
        "N", "NE", "NE", "L", "S", "SO", "O", "NO", "N"]


def test_area_por_raio_seleciona_so_os_de_dentro():
    df = _flashes([(0, -22.40, -45.45), (0, -22.80, -45.45), (0, float("nan"), -45.4)])
    sel = ITAJUBA.select(df)
    assert len(sel) == 1
    assert sel["dist_km"].iloc[0] < 2
    assert ITAJUBA.select(df.iloc[0:0]).empty


def test_area_por_poligono():
    area = ObservationArea("Caixa", -22.4, -45.4, polygon=box(-45.5, -22.5, -45.3, -22.3))
    sel = area.select(_flashes([(0, -22.45, -45.35), (0, -22.6, -45.35)]))
    assert list(sel["lat"]) == [-22.45]


def test_area_invalida():
    with pytest.raises(ValueError):
        ObservationArea("Sem raio", -22.4, -45.4)
    with pytest.raises(ValueError):
        ObservationArea("Fora", -122.4, -45.4, radius_km=10)


def test_monitor_toca_uma_vez_e_rearma_depois_da_calma():
    mon = AlarmMonitor(ITAJUBA, min_flashes=1, window_minutes=10, rearm_minutes=30)
    assert mon.update(ITAJUBA.select(_flashes([])), T0) == []

    ev = mon.update(ITAJUBA.select(_flashes([(1, -22.30, -45.40)])), T0 + timedelta(minutes=2))
    assert [e.kind for e in ev] == ["alarme"]
    assert ev[0].count == 1 and ev[0].nearest_direction == "N"

    # Mesma tempestade: mais flashes não tocam de novo.
    assert mon.update(ITAJUBA.select(_flashes([(5, -22.35, -45.40)])), T0 + timedelta(minutes=6)) == []

    # 20 min calmo ainda não rearma; 30 min rearma, e um flash novo toca de novo.
    assert mon.update(None, T0 + timedelta(minutes=25)) == []
    assert [e.kind for e in mon.update(None, T0 + timedelta(minutes=36))] == ["rearmado"]
    ev = mon.update(ITAJUBA.select(_flashes([(40, -22.41, -45.30)])), T0 + timedelta(minutes=41))
    assert [e.kind for e in ev] == ["alarme"]
    assert ev[0].nearest_direction == "L"


def test_monitor_rearma_e_toca_no_mesmo_lote():
    """Se a tempestade volta depois da calma, o mesmo lote rearma e toca."""
    mon = AlarmMonitor(ITAJUBA, rearm_minutes=30)
    mon.update(ITAJUBA.select(_flashes([(0, -22.41, -45.45)])), T0 + timedelta(minutes=1))
    ev = mon.update(ITAJUBA.select(_flashes([(45, -22.41, -45.45)])), T0 + timedelta(minutes=46))
    assert [e.kind for e in ev] == ["rearmado", "alarme"]


def test_monitor_min_flashes_e_janela():
    mon = AlarmMonitor(ITAJUBA, min_flashes=3, window_minutes=10)
    assert mon.update(ITAJUBA.select(_flashes([(0, -22.41, -45.45), (1, -22.42, -45.45)])),
                      T0 + timedelta(minutes=2)) == []
    # O terceiro chega 15 min depois: os dois primeiros já saíram da janela de 10 min.
    assert mon.update(ITAJUBA.select(_flashes([(15, -22.41, -45.45)])), T0 + timedelta(minutes=16)) == []
    ev = mon.update(ITAJUBA.select(_flashes([(16, -22.41, -45.44), (17, -22.40, -45.45)])),
                    T0 + timedelta(minutes=18))
    assert [e.kind for e in ev] == ["alarme"] and ev[0].count == 3


def test_monitor_ignora_flash_repetido():
    mon = AlarmMonitor(ITAJUBA, min_flashes=2)
    lote = ITAJUBA.select(_flashes([(0, -22.41, -45.45)]))
    mon.update(lote, T0 + timedelta(minutes=1))
    assert mon.update(lote, T0 + timedelta(minutes=2)) == []


def test_mensagem():
    mon = AlarmMonitor(ITAJUBA)
    ev = mon.update(ITAJUBA.select(_flashes([(1, -22.30, -45.40), (2, -22.35, -45.40)])),
                    T0 + timedelta(minutes=3))[0]
    title, text = alarm_message(ITAJUBA, ev, 10, tz="America/Sao_Paulo")
    # Mais perto: (-22.35, -45.40), ~7 km ao norte e ~5 km a leste.
    assert title == "Relâmpago a 9 km (NE) — Itajubá"
    assert text.startswith("2 relâmpagos na área nos últimos 10 min.")
    assert "Último às 00:02 (horário local)" in text


def test_dados_do_alarme_do_site():
    from src.alarme import browser_alarm_payload

    area = box(-45.6, -22.6, -45.3, -22.2)
    df = _flashes([(1, -22.30, -45.45), (5, -22.41, -45.45), (3, -22.50, -45.40)])
    payload = browser_alarm_payload(df, area, label="o retângulo selecionado")
    assert payload["label"] == "o retângulo selecionado"
    assert payload["center"] == [-45.45, -22.4]
    # Mais recente primeiro: [ms UTC, km, rumo].
    t5 = int((T0 + timedelta(minutes=5)).timestamp() * 1000)
    assert payload["flashes"][0] == [t5, 1.1, 180]
    assert [row[0] for row in payload["flashes"]] == sorted((row[0] for row in payload["flashes"]), reverse=True)
    assert browser_alarm_payload(df, area, label="x", limit=2)["flashes"][0][0] == t5
    assert len(browser_alarm_payload(df, area, label="x", limit=2)["flashes"]) == 2
    assert browser_alarm_payload(df, area, label="x", limit=2)["truncated"] is True
    assert payload["truncated"] is False
    assert browser_alarm_payload(df.iloc[0:0], area, label="x")["flashes"] == []
    assert browser_alarm_payload(df, None, label="x") is None
    # A assinatura muda com a área (o navegador recomeça a contagem).
    other = browser_alarm_payload(df, box(-45.6, -22.6, -45.3, -22.1), label="x")
    assert other["signature"] != payload["signature"]


def test_regra_do_alarme_no_navegador(tmp_path):
    """Roda src/alarme_navegador.js no Node: mesma regra do AlarmMonitor."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não instalado")
    src = Path(__file__).resolve().parents[1] / "src" / "alarme_navegador.js"
    module = tmp_path / "alarme.mjs"
    module.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text("""
import {alarmStep, newAlarmState, directionLabel, sirenSamples} from './alarme.mjs';
const M = 60000, out = {};
let st = newAlarmState(), r;
r = alarmStep(st, [], 0); out.vazio = r.events.map(e => e.kind); st = r.state;
r = alarmStep(st, [[1*M, 12.3, 10], [2*M, 8.4, 50]], 3*M); out.primeiro = r.events; st = r.state;
r = alarmStep(st, [[1*M, 12.3, 10], [2*M, 8.4, 50], [5*M, 4, 90]], 6*M);
out.mesma = r.events.map(e => e.kind); out.recentes = r.recentCount; st = r.state;
r = alarmStep(st, [], 30*M); out.calma20 = r.events.map(e => e.kind); st = r.state;
r = alarmStep(st, [[40*M, 3, 180]], 41*M); out.volta = r.events.map(e => e.kind); st = r.state;
let s3 = newAlarmState();
r = alarmStep(s3, [[0, 1, 0], [1*M, 1, 0]], 2*M, {minFlashes: 3, windowMs: 10*M, rearmMs: 30*M});
out.min3 = r.events.length;
out.rumos = [0, 44, 46, 90, 180, 225, 270, 315, 359, -45].map(directionLabel);
const y = sirenSamples(22050); let peak = 0; for (const v of y) peak = Math.max(peak, Math.abs(v));
out.siren = [y.length, Math.round(peak * 100) / 100];
console.log(JSON.stringify(out));
""", encoding="utf-8")
    res = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["vazio"] == []
    assert out["primeiro"] == [{"kind": "alarme", "count": 2, "nearestKm": 8.4, "nearestDir": "NE", "lastMs": 120000}]
    assert out["mesma"] == [] and out["recentes"] == 3
    assert out["calma20"] == []
    assert out["volta"] == ["rearmado", "alarme"]
    assert out["min3"] == 0
    assert out["rumos"] == ["N", "NE", "NE", "L", "S", "SO", "O", "NO", "N", "NO"]
    assert out["siren"] == [33077, 0.95]  # ~1,5 s a 22050 Hz
