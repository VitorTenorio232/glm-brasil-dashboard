"""Mapa persistente do GLM com MapLibre GL JS + Streamlit Components v2.

Somente o GeoJSON da fonte é trocado; a câmera fica no navegador.
O componente NÃO envia zoom/centro ao Python para evitar reruns cíclicos.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st

_ASSETS = Path(__file__).resolve().parent
MAX_VISUAL_FLASHES = 60_000


def flash_payload(df: pd.DataFrame, *, limit: int = MAX_VISUAL_FLASHES) -> list[list[float | int]]:
    """Converte lat/lon/tempo UTC em registros compactos [lon,lat,ms].

    A amostra visual é distribuída por faixas de 5 minutos (não apenas pelos
    dados mais recentes), para a barra histórica não perder seus quadros.
    Os totais estatísticos usam sempre o DataFrame completo.
    """
    if df is None or df.empty:
        return []
    required = {"lon", "lat", "time_start"}
    if not required.issubset(df.columns):
        raise ValueError(f"Faltam colunas para MapLibre: {sorted(required - set(df.columns))}")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    lat = pd.to_numeric(df["lat"], errors="coerce")
    dates = pd.to_datetime(df["time_start"], errors="coerce", utc=True)
    valid = lon.between(-180, 180) & lat.between(-85, 85) & dates.notna()
    if not valid.any():
        return []
    packed = pd.DataFrame({"lon": lon[valid], "lat": lat[valid], "date": dates[valid]})
    # Amostragem temporal estratificada: um .head(limit) retém somente flashes
    # recentes e deixa vazios os quadros antigos da animação de uma hora.
    packed["bucket"] = packed["date"].dt.floor("5min")
    nlimit = max(1, int(limit))
    if len(packed) > nlimit:
        total = len(packed)
        groups = [(key, sub) for key, sub in packed.groupby("bucket", sort=True)]
        # Cotas proporcionais + pelo menos uma amostra de cada fatia temporal.
        quotas = {key: min(len(sub), max(1, int(nlimit * len(sub) / total))) for key, sub in groups}
        chosen = [sub.sample(n=quotas[key], random_state=17) if len(sub)>quotas[key] else sub
                  for key, sub in groups]
        packed = pd.concat(chosen, ignore_index=True)
        if len(packed) > nlimit:
            packed = packed.sample(n=nlimit, random_state=17)
        # Não é necessário preencher cada cota restante: a distribuição
        # temporal tem prioridade sobre alcançar exatamente o limite.
    packed = packed.sort_values("date", ascending=False)
    ms = packed["date"].astype("int64") // 1_000_000
    return [
        [round(float(lon), 5), round(float(lat), 5), int(ts)]
        for lon, lat, ts in zip(packed["lon"], packed["lat"], ms)
    ]


def _maplibre_component():
    """Registro de componente v2, com recursos JS/CSS estáticos e confiáveis."""
    return st.components.v2.component(
        name="flash_view_live_maplibre_v83",
        html='<div class="fv-map-shell"><div class="fv-map-canvas"></div><div class="fv-map-loading">Carregando mapa de satélite…</div><div class="fv-map-hud">GLM · NOAA</div><div class="fv-map-timeline"><div class="fv-map-controls"><button type="button" data-act="play">▶ Reproduzir</button><button type="button" data-act="prev" title="Quadro anterior">◀</button><button type="button" data-act="next" title="Próximo quadro">▶</button><button type="button" data-act="live">● Ao vivo</button><label>Velocidade <select data-role="speed"><option value="1000">1 s</option><option value="2000" selected>2 s</option><option value="4000">4 s</option></select></label><span class="fv-map-frame-label"></span></div><div class="fv-map-progress"><span>−60 min</span><input type="range" min="0" max="12" value="12" step="1" data-role="frame" aria-label="Quadro da última hora"/><span>mais recente</span></div></div><div class="fv-map-legend"><b>Intervalo dos Flashes</b><span><i style="background:#ff2d20"></i> 0–5 min</span><span><i style="background:#f4b942"></i> 5–10 min</span><span><i style="background:#24c96b"></i> 10–20 min</span><span><i style="background:#1787ff"></i> 20–30 min</span></div></div>',
        css=(_ASSETS / "maplibre_realtime.css").read_text(encoding="utf-8"),
        js=(_ASSETS / "maplibre_realtime.js").read_text(encoding="utf-8"),
        isolate_styles=False,
    )


# Registrado uma única vez por sessão de script; dados variam sem reinicialização de JS.
_MAP = _maplibre_component()


def show_realtime_map(
    points: list[list[float | int]],
    observation_end_utc: datetime,
    *,
    selected_geojson: dict | None = None,
    uploaded_geojson: dict | None = None,
    selecting: bool = False,
):
    """Renderiza o mapa e recebe, se houver, retângulo selecionado pelo usuário."""
    if observation_end_utc.tzinfo is None:
        observation_end_utc = observation_end_utc.replace(tzinfo=timezone.utc)
    end_ms = int(observation_end_utc.astimezone(timezone.utc).timestamp() * 1000)
    return _MAP(
        key="fv_maplibre_live_v83",
        height=805,
        width="stretch",
        data={
            "points": points,
            "observation_end_ms": end_ms,
            "selection": selected_geojson,
            "overlay": uploaded_geojson,
            "selecting": bool(selecting),
        },
        on_rectangle_change=lambda: None,
    )
