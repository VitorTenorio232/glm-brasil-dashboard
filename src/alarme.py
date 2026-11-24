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
from functools import cached_property, lru_cache
import hashlib

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import mapping

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = np.pi * EARTH_RADIUS_KM / 180.0
DIRECTIONS = ("N", "NE", "L", "SE", "S", "SO", "O", "NO")
# Anéis em volta da área (como na Sala do Céu Nowcasting): distância até a BORDA da área, em km.
# 20 km toca a sirene, 50 km mostra um aviso com bipe e 100 km só um aviso discreto.
RING_KM = (20, 50, 100)


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


def reference_point(geometry):
    """Ponto de referência das mensagens: o centroide da área, ou um ponto garantido dentro dela."""
    ref = geometry.centroid
    if not geometry.contains(ref):
        ref = geometry.representative_point()
    return ref


class LocalPlane:
    """Plano em km centrado num ponto (projeção azimutal equidistante na esfera).

    Serve para medir a distância até a borda da área e traçar os anéis em volta dela. A distância a partir do
    centro é exata; nas outras direções o erro fica abaixo de 0,5% até 1.000 km do centro.
    """

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = float(lat0), float(lon0)

    def forward(self, lon, lat) -> tuple[np.ndarray, np.ndarray]:
        d = distance_km(self.lat0, self.lon0, lat, lon)
        b = np.radians(bearing_deg(self.lat0, self.lon0, lat, lon))
        return d * np.sin(b), d * np.cos(b)

    def inverse(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        delta = np.hypot(x, y) / EARTH_RADIUS_KM
        b = np.arctan2(x, y)
        p0, l0 = np.radians(self.lat0), np.radians(self.lon0)
        p = np.arcsin(np.clip(np.sin(p0) * np.cos(delta) + np.cos(p0) * np.sin(delta) * np.cos(b), -1.0, 1.0))
        lam = l0 + np.arctan2(np.sin(b) * np.sin(delta) * np.cos(p0), np.cos(delta) - np.sin(p0) * np.sin(p))
        return (np.degrees(lam) + 540.0) % 360.0 - 180.0, np.degrees(p)

    def to_plane(self, geometry):
        return shapely.transform(geometry, lambda xy: np.column_stack(self.forward(xy[:, 0], xy[:, 1])))

    def to_lonlat(self, geometry):
        return shapely.transform(geometry, lambda xy: np.column_stack(self.inverse(xy[:, 0], xy[:, 1])))


@dataclass(frozen=True)
class _AreaIndex:
    area: object      # a área em lon/lat, preparada para o teste ponto-dentro
    plane: LocalPlane
    shape: object     # a área no plano em km (simplificada a ~100 m)
    edges: object     # STRtree dos segmentos da borda no plano: distância de milhares de pontos em ms


@lru_cache(maxsize=8)
def _area_index(wkb: bytes) -> _AreaIndex:
    """Índices da área, guardados entre as atualizações do mapa (~60 s). Estados do IBGE têm ~80 mil vértices."""
    area = shapely.from_wkb(wkb)
    shapely.prepare(area)
    ref = reference_point(area)
    plane = LocalPlane(ref.y, ref.x)
    shape = plane.to_plane(area).simplify(0.1, preserve_topology=True)
    segments = []
    for part in shapely.get_parts(shape.boundary):
        xy = shapely.get_coordinates(part)
        if len(xy) >= 2:
            segments.append(np.stack([xy[:-1], xy[1:]], axis=1))
    edges = shapely.STRtree(shapely.linestrings(np.concatenate(segments))) if segments else None
    return _AreaIndex(area, plane, shape, edges)


def edge_distance_km(geometry, lat, lon, *, max_km: float = max(RING_KM)) -> np.ndarray:
    """Distância (km) de cada ponto até a borda da área: 0 dentro dela e NaN além de ``max_km`` ou sem posição."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    out = np.full(lat.shape, np.nan)
    valid = np.isfinite(lat) & np.isfinite(lon)
    if geometry is None or geometry.is_empty or not valid.any():
        return out
    # Pré-filtro pela caixa da área aumentada em max_km (graus de longitude encolhem com a latitude).
    west, south, east, north = geometry.bounds
    dy = max(0.0, float(max_km)) / KM_PER_DEGREE
    widest = np.cos(np.radians(min(89.0, max(abs(south), abs(north)) + dy)))
    dx = max(0.0, float(max_km)) / (KM_PER_DEGREE * max(widest, 0.05))
    near = valid & (lon >= west - dx) & (lon <= east + dx) & (lat >= south - dy) & (lat <= north + dy)
    idx = np.flatnonzero(near)
    if not idx.size:
        return out
    index = _area_index(geometry.wkb)
    inside = np.asarray(shapely.contains_xy(index.area, lon[idx], lat[idx]), dtype=bool)
    out[idx[inside]] = 0.0
    rest = idx[~inside]
    if rest.size and max_km > 0 and index.edges is not None:
        x, y = index.plane.forward(lon[rest], lat[rest])
        (which, _seg), d = index.edges.query_nearest(shapely.points(x, y), max_distance=float(max_km),
                                                     return_distance=True, all_matches=False)
        out[rest[which]] = d
    return out


@lru_cache(maxsize=8)
def _rings_geojson(wkb: bytes, rings: tuple[int, ...]) -> dict:
    index = _area_index(wkb)
    plane = index.plane
    base = index.shape.simplify(0.5, preserve_topology=True)  # 500 m: só para desenhar
    features = []
    for km in rings:
        line = plane.to_lonlat(base.buffer(float(km), quad_segs=12).boundary.simplify(0.3))
        line = shapely.transform(line, lambda xy: np.round(xy, 4))
        features.append({"type": "Feature", "properties": {"km": int(km)}, "geometry": mapping(line)})
    return {"type": "FeatureCollection", "features": features}


def ring_geojson(geometry, rings=RING_KM) -> dict | None:
    """Contornos dos anéis (linhas a ``rings`` km da borda da área), em GeoJSON lon/lat, com a propriedade km."""
    if geometry is None or geometry.is_empty:
        return None
    return _rings_geojson(geometry.wkb, tuple(sorted({int(r) for r in rings if r > 0})))


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

    @cached_property
    def geometry(self):
        """A área como polígono lon/lat: o do arquivo, ou o círculo do raio (para os anéis em volta)."""
        if self.polygon is not None:
            return self.polygon
        plane = LocalPlane(self.lat, self.lon)
        return plane.to_lonlat(shapely.Point(0.0, 0.0).buffer(float(self.radius_km), quad_segs=32))

    def select_near(self, flashes: pd.DataFrame | None, max_km: float) -> pd.DataFrame:
        """Flashes dentro da área ou a até ``max_km`` da borda, com edge_km (0 = dentro), dist_km e bearing_deg."""
        cols = {c: pd.Series(dtype=float) for c in ("edge_km", "dist_km", "bearing_deg")}
        if flashes is None or flashes.empty:
            base = flashes if flashes is not None else pd.DataFrame(columns=["time_start", "lat", "lon"])
            return base.iloc[0:0].assign(**cols)
        lat = pd.to_numeric(flashes["lat"], errors="coerce").to_numpy(dtype=float)
        lon = pd.to_numeric(flashes["lon"], errors="coerce").to_numpy(dtype=float)
        edge = edge_distance_km(self.geometry, lat, lon, max_km=max_km)
        keep = np.isfinite(edge)
        out = flashes.loc[keep].copy()
        out["edge_km"] = edge[keep]
        out["dist_km"] = distance_km(self.lat, self.lon, lat[keep], lon[keep])
        out["bearing_deg"] = bearing_deg(self.lat, self.lon, lat[keep], lon[keep])
        return out

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

    @property
    def recent_count(self) -> int:
        """Flashes contados na janela, depois do último ``update``."""
        return len(self._recent)

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


class RingMonitor:
    """Anéis em volta da área: um AlarmMonitor por anel, com a distância até a borda (mesma regra do site,
    ``ringStep`` em src/alarme_navegador.js).

    Os flashes de dentro da área também contam para os anéis: assim um anel não rearma enquanto a tempestade está
    sobre a área e não toca de novo quando ela sai. Por atualização sai no máximo um aviso, o do anel mais perto, e
    nenhum quando já há flash dentro da área (``inside_now``): aí quem avisa é o alarme da área.
    """

    def __init__(self, area: ObservationArea, rings=RING_KM, **monitor_kwargs):
        self.area = area
        self.rings = tuple(sorted({int(r) for r in rings if r > 0}))
        self.monitors = {r: AlarmMonitor(area, **monitor_kwargs) for r in self.rings}

    @property
    def max_km(self) -> int:
        return max(self.rings, default=0)

    def update(self, near: pd.DataFrame | None, observation_end: datetime, *,
               inside_now: bool) -> list[tuple[int, AlarmEvent]]:
        """``near``: flashes novos de ``ObservationArea.select_near``. Devolve [(anel em km, evento 'alarme')]."""
        out: list[tuple[int, AlarmEvent]] = []
        for r in self.rings:
            sub = None
            if near is not None and not near.empty:
                sub = near.loc[near["edge_km"] <= r]
                sub = sub.assign(dist_km=sub["edge_km"])
            for event in self.monitors[r].update(sub, observation_end):
                if event.kind == "alarme" and not inside_now and not out:
                    out.append((r, event))
        return out


def browser_alarm_payload(flashes: pd.DataFrame | None, geometry, *, label: str, limit: int = 3000,
                          reference: str = "do centro da área", rings=RING_KM) -> dict | None:
    """Dados do botão "Ativar alarme" do mapa ao vivo (src/alarme_navegador.js).

    ``flashes``: os flashes da janela do mapa (últimos 30 min), de qualquer lugar. Vão para o navegador só os de
    dentro da área e os de até ``max(rings)`` km da borda dela, cada um como
    [ms UTC, distância do centro (km), rumo do centro (graus), distância da borda (km; 0 = dentro)].
    Ficam os ``limit`` mais recentes de dentro e os ``limit`` mais recentes de fora. ``signature`` muda quando a
    área muda, e o navegador recomeça a contagem. ``reference`` diz na mensagem de onde se mede a distância
    ("do ponto" no modo Pontual). ``rings`` traz os contornos dos anéis para o mapa.
    """
    if geometry is None or geometry.is_empty:
        return None
    ref = reference_point(geometry)
    ring_km = tuple(sorted({int(r) for r in rings if r > 0}))
    limit = max(0, int(limit))
    rows: list[list[float]] = []
    total_inside = total_near = 0
    if flashes is not None and not flashes.empty:
        times = pd.to_datetime(flashes["time_start"], utc=True, errors="coerce")
        lat = pd.to_numeric(flashes["lat"], errors="coerce").to_numpy(dtype=float)
        lon = pd.to_numeric(flashes["lon"], errors="coerce").to_numpy(dtype=float)
        edge = edge_distance_km(geometry, lat, lon, max_km=max(ring_km, default=0))
        idx = np.flatnonzero(times.notna().to_numpy() & np.isfinite(edge))
        ms = ((times.iloc[idx] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
        newest_first = np.argsort(-ms, kind="stable")
        idx, ms = idx[newest_first], ms[newest_first]
        inside = edge[idx] == 0
        total_inside, total_near = int(inside.sum()), int((~inside).sum())
        keep = np.flatnonzero(inside)[:limit].tolist() + np.flatnonzero(~inside)[:limit].tolist()
        keep.sort()  # continua do mais recente para o mais antigo
        sel = idx[keep]
        dist = distance_km(ref.y, ref.x, lat[sel], lon[sel])
        rumo = bearing_deg(ref.y, ref.x, lat[sel], lon[sel])
        # Fora da área a borda fica em pelo menos 0,1 km: 0 quer dizer "dentro" no navegador.
        rows = [[int(t), round(float(d), 1), int(round(float(b))) % 360, 0.0 if e == 0 else max(0.1, round(float(e), 1))]
                for t, d, b, e in zip(ms[keep], dist, rumo, edge[sel])]
    n_inside = sum(1 for r in rows if r[3] == 0)
    return {
        "label": label,
        "signature": hashlib.blake2s(geometry.wkb, digest_size=6).hexdigest(),
        "center": [round(ref.x, 4), round(ref.y, 4)],
        "reference": reference,
        "flashes": rows,
        # A lista foi cortada nos mais recentes: o navegador mostra "mais de N".
        "truncated": bool(total_inside > n_inside),
        "nearTruncated": bool(total_near > len(rows) - n_inside),
        "ringKm": list(ring_km),
        "rings": ring_geojson(geometry, ring_km) if ring_km else None,
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


def ring_message(area: ObservationArea, ring_km: float, event: AlarmEvent, window_minutes: float, *,
                 tz=None) -> tuple[str, str]:
    """Título e texto do aviso de um anel (distância até a borda da área)."""
    last = event.last_flash.floor("s")
    last = last.tz_convert(tz) if tz is not None else last.to_pydatetime().astimezone()
    km = "menos de 1" if event.nearest_km < 1 else f"{event.nearest_km:.0f}"
    title = f"Relâmpago a {km} km da área ({event.nearest_direction}) — {area.name}"
    plural = "relâmpago" if event.count == 1 else "relâmpagos"
    text = (f"{event.count} {plural} a até {ring_km:g} km da área nos últimos {window_minutes:g} min. "
            f"Mais perto: {km} km da borda da área, a {event.nearest_direction} do ponto de referência. "
            f"Último às {last:%H:%M} (horário local). "
            "Fonte: GLM/GOES (NOAA), dado observacional com ~1–3 min de atraso; não é alerta oficial.")
    return title, text
