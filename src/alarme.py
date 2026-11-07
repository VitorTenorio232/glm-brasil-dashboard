"""Alarme local de relâmpagos (GLM) para uma área de observação.

Este módulo guarda só a lógica: a área (ponto com raio ou polígono), a distância e a direção de cada flash, e a
regra de quando tocar. Há duas versões do alarme:
- no computador: scripts/alarme_relampagos.py busca os arquivos no NOAA/AWS, toca o som e avisa o celular;
- no site: o botão "Ativar alarme" do mapa ao vivo (src/alarme_navegador.js), que recebe os flashes da área por
  browser_alarm_payload e aplica a mesma regra no navegador.

Aviso observacional: o GLM chega com cerca de 1 a 3 min de atraso, não detecta todos os relâmpagos e não separa
intranuvem de nuvem-solo. Não substitui os alertas oficiais (Defesa Civil, INMET).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib

import numpy as np
import pandas as pd
import shapely

EARTH_RADIUS_KM = 6371.0088
DIRECTIONS = ("N", "NE", "L", "SE", "S", "SO", "O", "NO")


def distance_km(lat0: float, lon0: float, lat, lon) -> np.ndarray:
    """Distância de grande círculo (haversine) do ponto (lat0, lon0) até cada (lat, lon)."""
    p0, l0 = np.radians(lat0), np.radians(lon0)
    p, lam = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    a = np.sin((p - p0) / 2) ** 2 + np.cos(p0) * np.cos(p) * np.sin((lam - l0) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing_deg(lat0: float, lon0: float, lat, lon) -> np.ndarray:
    """Rumo (0° = norte, 90° = leste) do ponto (lat0, lon0) até cada (lat, lon)."""
    p0, l0 = np.radians(lat0), np.radians(lon0)
    p, lam = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    y = np.sin(lam - l0) * np.cos(p)
    x = np.cos(p0) * np.sin(p) - np.sin(p0) * np.cos(p) * np.cos(lam - l0)
    return np.degrees(np.arctan2(y, x)) % 360.0


def direction_label(deg: float) -> str:
    """Rumo em graus para um dos 8 pontos da rosa dos ventos (N, NE, L, SE, S, SO, O, NO)."""
    return DIRECTIONS[int(((float(deg) % 360.0) + 22.5) // 45.0) % 8]


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


@dataclass(frozen=True)
class ObservationArea:
    """Área de observação: ponto (lat, lon) com raio em km, ou um polígono.

    No modo polígono, (lat, lon) é só o ponto de referência para a distância e a direção nas mensagens.
    """

    name: str
    lat: float
    lon: float
    radius_km: float | None = None
    polygon: object | None = None

    def __post_init__(self):
        if not (-90.0 <= self.lat <= 90.0 and -180.0 <= self.lon <= 180.0):
            raise ValueError("Latitude deve ficar entre -90 e 90 e longitude entre -180 e 180.")
        if self.polygon is None and not (self.radius_km and self.radius_km > 0):
            raise ValueError("Informe um raio maior que zero ou um arquivo com o polígono da área.")

    @property
    def description(self) -> str:
        if self.polygon is not None:
            return f"{self.name} (polígono do arquivo)"
        return f"{self.name} (raio de {self.radius_km:g} km)"

    def select(self, flashes: pd.DataFrame | None) -> pd.DataFrame:
        """Flashes dentro da área, com as colunas dist_km e bearing_deg (a partir do ponto de referência)."""
        if flashes is None or flashes.empty:
            base = flashes if flashes is not None else pd.DataFrame(columns=["time_start", "lat", "lon"])
            return base.iloc[0:0].assign(dist_km=pd.Series(dtype=float), bearing_deg=pd.Series(dtype=float))
        lat = pd.to_numeric(flashes["lat"], errors="coerce").to_numpy(dtype=float)
        lon = pd.to_numeric(flashes["lon"], errors="coerce").to_numpy(dtype=float)
        dist = distance_km(self.lat, self.lon, lat, lon)
        if self.polygon is not None:
            inside = np.asarray(shapely.contains_xy(self.polygon, lon, lat), dtype=bool)
        else:
            inside = dist <= float(self.radius_km)
        inside &= np.isfinite(dist)
        out = flashes.loc[inside].copy()
        out["dist_km"] = dist[inside]
        out["bearing_deg"] = bearing_deg(self.lat, self.lon, lat[inside], lon[inside])
        return out


@dataclass(frozen=True)
class AlarmEvent:
    """O que o monitor decidiu: 'alarme' (tocar) ou 'rearmado' (área ficou calma, pode tocar de novo)."""

    kind: str
    observation_end: pd.Timestamp
    count: int = 0
    nearest_km: float | None = None
    nearest_direction: str | None = None
    last_flash: pd.Timestamp | None = None


class AlarmMonitor:
    """Decide quando tocar.

    Toca quando há pelo menos ``min_flashes`` flashes na área nos últimos ``window_minutes`` (tempo da
    observação, não do relógio do PC). Depois de tocar, só toca de novo quando a área fica ``rearm_minutes``
    sem nenhum flash, para não disparar a cada minuto durante a mesma tempestade.
    """

    def __init__(self, area: ObservationArea, *, min_flashes: int = 1, window_minutes: float = 10.0,
                 rearm_minutes: float = 30.0):
        if min_flashes < 1:
            raise ValueError("min_flashes deve ser 1 ou mais.")
        self.area = area
        self.min_flashes = int(min_flashes)
        self.window = timedelta(minutes=float(window_minutes))
        self.rearm = timedelta(minutes=float(rearm_minutes))
        self.armed = True
        self.last_hit: pd.Timestamp | None = None
        self._recent: deque[tuple[pd.Timestamp, float, float, str]] = deque()
        self._seen: set[str] = set()

    def update(self, in_area: pd.DataFrame | None, observation_end: datetime) -> list[AlarmEvent]:
        """Recebe os flashes novos já filtrados pela área (``ObservationArea.select``)."""
        obs = _utc(observation_end)
        rows = []
        if in_area is not None and not in_area.empty:
            times = pd.to_datetime(in_area["time_start"], utc=True, errors="coerce")
            uids = in_area["flash_uid"].astype(str) if "flash_uid" in in_area else times.astype(str)
            for t, d, b, uid in zip(times, in_area["dist_km"], in_area["bearing_deg"], uids):
                if pd.isna(t) or uid in self._seen:
                    continue
                rows.append((t, float(d), float(b), uid))
        rows.sort(key=lambda r: r[0])

        events: list[AlarmEvent] = []
        # Rearma antes de somar os flashes novos: conta o tempo calmo até o primeiro deles.
        quiet_until = rows[0][0] if rows else obs
        if not self.armed and self.last_hit is not None and quiet_until - self.last_hit >= self.rearm:
            self.armed = True
            events.append(AlarmEvent("rearmado", obs, last_flash=self.last_hit))

        for row in rows:
            self._recent.append(row)
            self._seen.add(row[3])
            self.last_hit = row[0] if self.last_hit is None else max(self.last_hit, row[0])
        while self._recent and self._recent[0][0] < obs - self.window:
            self._seen.discard(self._recent.popleft()[3])

        if self.armed and len(self._recent) >= self.min_flashes:
            nearest = min(self._recent, key=lambda r: r[1])
            self.armed = False
            events.append(AlarmEvent(
                "alarme", obs, count=len(self._recent), nearest_km=nearest[1],
                nearest_direction=direction_label(nearest[2]), last_flash=max(r[0] for r in self._recent)))
        return events


def browser_alarm_payload(in_area: pd.DataFrame | None, geometry, *, label: str, limit: int = 3000,
                          reference: str = "do centro da área") -> dict | None:
    """Dados do botão "Ativar alarme" do mapa ao vivo (src/alarme_navegador.js).

    ``in_area``: flashes já filtrados pela área (os últimos 30 min do mapa). Vai para o navegador só o
    necessário para a regra e a mensagem: [ms UTC, distância em km, rumo em graus] a partir do centro da área,
    os ``limit`` mais recentes. ``signature`` muda quando a área muda, e o navegador recomeça a contagem.
    ``reference`` diz na mensagem de onde se mede a distância ("do ponto" no modo Pontual).
    """
    if geometry is None or geometry.is_empty:
        return None
    ref = geometry.centroid
    if not geometry.contains(ref):
        ref = geometry.representative_point()
    rows: list[list[float]] = []
    if in_area is not None and not in_area.empty:
        times = pd.to_datetime(in_area["time_start"], utc=True, errors="coerce")
        ok = times.notna().to_numpy()
        times = times[ok]
        ms = ((times - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
        lat = pd.to_numeric(in_area["lat"], errors="coerce").to_numpy(dtype=float)[ok]
        lon = pd.to_numeric(in_area["lon"], errors="coerce").to_numpy(dtype=float)[ok]
        order = np.argsort(-ms, kind="stable")[: max(0, int(limit))]
        dist = distance_km(ref.y, ref.x, lat[order], lon[order])
        rumo = bearing_deg(ref.y, ref.x, lat[order], lon[order])
        rows = [[int(t), round(float(d), 1), int(round(float(b))) % 360]
                for t, d, b in zip(ms[order], dist, rumo) if np.isfinite(d)]
    total = 0 if in_area is None else len(in_area)
    return {
        "label": label,
        "signature": hashlib.blake2s(geometry.wkb, digest_size=6).hexdigest(),
        "center": [round(ref.x, 4), round(ref.y, 4)],
        "reference": reference,
        "flashes": rows,
        # A lista foi cortada nos mais recentes: o navegador mostra "mais de N".
        "truncated": bool(total > len(rows)),
    }


def alarm_message(area: ObservationArea, event: AlarmEvent, window_minutes: float, *, tz=None) -> tuple[str, str]:
    """Título e texto do aviso, com o horário local do PC (ou ``tz``)."""
    last = event.last_flash.floor("s")
    last = last.tz_convert(tz) if tz is not None else last.to_pydatetime().astimezone()
    title = f"Relâmpago a {event.nearest_km:.0f} km ({event.nearest_direction}) — {area.name}"
    plural = "relâmpago" if event.count == 1 else "relâmpagos"
    text = (f"{event.count} {plural} na área nos últimos {window_minutes:g} min. "
            f"Mais perto: {event.nearest_km:.0f} km a {event.nearest_direction} do ponto de referência. "
            f"Último às {last:%H:%M} (horário local). "
            "Fonte: GLM/GOES (NOAA), dado observacional com ~1–3 min de atraso; não é alerta oficial.")
    return title, text
