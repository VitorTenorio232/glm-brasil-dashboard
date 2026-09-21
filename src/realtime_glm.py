from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from .glm_aws import iter_hours, list_hour_keys, unsigned_s3_client
from .glm_reader import read_glm_files

# Recorte operacional do mapa. Mantém o Brasil inteiro e uma pequena margem.
# Ordem: lon_min, lat_min, lon_max, lat_max.
BRAZIL_VIEW_BBOX = (-75.5, -35.5, -32.0, 6.5)
LIVE_CACHE_DIR = Path(tempfile.gettempdir()) / "glm_brasil_live"

AGE_GROUPS = [
    ("0–5 min", 0.0, 5.0, "#ff2d20"),
    ("5–10 min", 5.0, 10.0, "#f4b942"),
    ("10–20 min", 10.0, 20.0, "#24c96b"),
    ("20–30 min", 20.0, 30.000001, "#1787ff"),
]


@dataclass
class LiveSnapshot:
    flashes: pd.DataFrame
    now_utc: datetime
    observation_end_utc: datetime
    window_start_utc: datetime
    source_files: int
    newest_file_start_utc: datetime
    latency_seconds: float

    @property
    def latency_minutes(self) -> float:
        return self.latency_seconds / 60.0


def _ensure_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _list_recent_keys(client, now_utc: datetime, search_back_minutes: int = 120):
    """Lista arquivos GLM recentes sem fazer uma chamada S3 por arquivo de 20 s."""
    search_start = now_utc - timedelta(minutes=search_back_minutes)
    rows = []
    for hour in iter_hours(search_start, now_utc):
        rows.extend(list_hour_keys(client, hour))
    rows = [r for r in rows if search_start <= r[2] <= now_utc + timedelta(minutes=1)]
    rows.sort(key=lambda x: x[2])
    return rows


def _download_key(client, bucket: str, key: str) -> Path:
    LIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = LIVE_CACHE_DIR / Path(key).name
    if not target.exists() or target.stat().st_size == 0:
        tmp = target.with_suffix(target.suffix + ".part")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        client.download_file(bucket, key, str(tmp))
        tmp.replace(target)
    return target


def _download_selected(client, selected, max_workers: int = 8) -> list[Path]:
    paths: list[Path] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {
            pool.submit(_download_key, client, bucket, key): (bucket, key)
            for bucket, key, _ in selected
        }
        for fut in as_completed(futs):
            paths.append(fut.result())
    return sorted(paths)


def _prune_cache(keep: set[str]) -> None:
    if not LIVE_CACHE_DIR.exists():
        return
    for p in LIVE_CACHE_DIR.glob("*.nc"):
        if p.name not in keep:
            try:
                # Mantém algum cache recente, mas remove arquivos antigos para não crescer indefinidamente.
                if datetime.now().timestamp() - p.stat().st_mtime > 3 * 3600:
                    p.unlink(missing_ok=True)
            except OSError:
                pass


def _filter_view_bbox(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    lon_min, lat_min, lon_max, lat_max = BRAZIL_VIEW_BBOX
    mask = (
        pd.to_numeric(df["lon"], errors="coerce").between(lon_min, lon_max)
        & pd.to_numeric(df["lat"], errors="coerce").between(lat_min, lat_max)
    )
    return df.loc[mask].copy()


def classify_age_groups(df: pd.DataFrame, observation_end_utc: datetime) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["age_minutes"] = pd.Series(dtype="float64")
        out["age_group"] = pd.Series(dtype="object")
        out["age_color"] = pd.Series(dtype="object")
        return out

    times = pd.to_datetime(out["time_start"], utc=True, errors="coerce")
    anchor = pd.Timestamp(observation_end_utc)
    age = (anchor - times).dt.total_seconds() / 60.0
    out["age_minutes"] = age
    out["age_group"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out["age_color"] = pd.Series(pd.NA, index=out.index, dtype="object")

    for label, lower, upper, color in AGE_GROUPS:
        mask = (out["age_minutes"] >= lower) & (out["age_minutes"] < upper)
        out.loc[mask, "age_group"] = label
        out.loc[mask, "age_color"] = color

    out = out[out["age_group"].notna()].copy()
    return out.sort_values("time_start").reset_index(drop=True)


def fetch_live_snapshot(
    *,
    window_minutes: int = 30,
    quality: str = "zero_only",
    now_utc: datetime | None = None,
    search_back_minutes: int = 120,
    max_workers: int = 8,
) -> LiveSnapshot:
    """Obtém os 30 minutos mais recentes disponíveis do GLM GOES-East via NOAA/NODD AWS.

    A janela é ancorada no arquivo LCFA mais recente disponível, e não no relógio local.
    Assim o usuário também recebe uma métrica explícita de latência da fonte.
    """
    now_utc = _ensure_utc(now_utc)
    client = unsigned_s3_client()
    keys = _list_recent_keys(client, now_utc, search_back_minutes=search_back_minutes)
    if not keys:
        raise RuntimeError(
            "Nenhum arquivo GLM-L2-LCFA foi encontrado no NOAA/AWS nas últimas "
            f"{search_back_minutes} min. A fonte pode estar temporariamente indisponível."
        )

    newest_file_start = max(item[2] for item in keys)
    # Cada LCFA representa ~20 s. Usar +20 s evita classificar flashes do arquivo mais novo como futuros.
    observation_end = newest_file_start + timedelta(seconds=20)
    window_start = observation_end - timedelta(minutes=window_minutes)

    selected = [
        item for item in keys
        if (window_start - timedelta(seconds=20)) <= item[2] <= newest_file_start
    ]
    if not selected:
        raise RuntimeError("Não foi possível montar a janela de 30 min a partir dos arquivos disponíveis.")

    paths = _download_selected(client, selected, max_workers=max_workers)
    _prune_cache({p.name for p in paths})

    flashes = read_glm_files(paths, quality=quality)
    if not flashes.empty:
        flashes["time_start"] = pd.to_datetime(flashes["time_start"], utc=True, errors="coerce")
        flashes = flashes[
            flashes["time_start"].between(
                pd.Timestamp(window_start), pd.Timestamp(observation_end), inclusive="both"
            )
        ].copy()
        flashes = _filter_view_bbox(flashes)
        flashes = classify_age_groups(flashes, observation_end)

    latency = max(0.0, (now_utc - observation_end).total_seconds())
    return LiveSnapshot(
        flashes=flashes,
        now_utc=now_utc,
        observation_end_utc=observation_end,
        window_start_utc=window_start,
        source_files=len(selected),
        newest_file_start_utc=newest_file_start,
        latency_seconds=latency,
    )


def group_counts(df: pd.DataFrame) -> dict[str, int]:
    counts = {label: 0 for label, *_ in AGE_GROUPS}
    if df.empty or "age_group" not in df:
        return counts
    vc = df["age_group"].value_counts()
    for label in counts:
        counts[label] = int(vc.get(label, 0))
    return counts


def _safe_popup(row: pd.Series) -> str:
    t = pd.to_datetime(row.get("time_start"), utc=True, errors="coerce")
    age = row.get("age_minutes", np.nan)
    parts = [
        f"<b>UTC:</b> {t.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(t) else '-'}",
        f"<b>Idade:</b> {float(age):.1f} min" if pd.notna(age) else "",
    ]
    if pd.notna(row.get("energy_j", np.nan)):
        parts.append(f"<b>Energia:</b> {float(row['energy_j']):.4g} J")
    if pd.notna(row.get("area_km2", np.nan)):
        parts.append(f"<b>Área:</b> {float(row['area_km2']):.2f} km²")
    if pd.notna(row.get("duration_ms", np.nan)):
        parts.append(f"<b>Duração:</b> {float(row['duration_ms']):.0f} ms")
    return "<br>".join(x for x in parts if x)


def build_live_map(df: pd.DataFrame, *, view_geometry=None, enable_area_draw: bool = False):
    """Mapa satélite leve, com seleção opcional de área por retângulo."""
    import folium
    from folium.plugins import Draw, FastMarkerCluster, Fullscreen

    m = folium.Map(
        location=[-14.2, -51.9],
        zoom_start=4,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri",
        name="Satélite",
        overlay=False,
        control=False,
        max_zoom=19,
    ).add_to(m)
    folium.TileLayer(
        tiles=(
            "https://services.arcgisonline.com/ArcGIS/rest/services/"
            "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri",
        name="Nomes e limites",
        overlay=True,
        control=True,
        show=True,
        opacity=0.9,
        max_zoom=19,
    ).add_to(m)

    # Ordem visual solicitada no controle: 0–5, 5–10, 10–20, 20–30 min.
    for label, _, _, color in AGE_GROUPS:
        sub = df[df.get("age_group", pd.Series(index=df.index, dtype="object")) == label]
        data = []
        for _, row in sub.iterrows():
            if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
                continue
            data.append([float(row["lat"]), float(row["lon"]), _safe_popup(row)])

        callback = f"""
        function (row) {{
            var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {{
                radius: 4.2,
                color: '{color}',
                weight: 0.8,
                fill: true,
                fillColor: '{color}',
                fillOpacity: 0.92
            }});
            if (row[2]) {{ marker.bindPopup(row[2], {{maxWidth: 320}}); }}
            return marker;
        }};
        """
        FastMarkerCluster(
            data=data,
            callback=callback,
            name=f"{label} ({len(data):,})".replace(",", "."),
            show=True,
            options={"disableClusteringAtZoom": 7, "maxClusterRadius": 45},
        ).add_to(m)

    if view_geometry is not None:
        try:
            from shapely.geometry import mapping
            minx, miny, maxx, maxy = view_geometry.bounds
            dx = max(0.05, (maxx - minx) * 0.06)
            dy = max(0.05, (maxy - miny) * 0.06)
            folium.GeoJson(
                mapping(view_geometry),
                name="Área selecionada",
                style_function=lambda _: {
                    "color": "#ff7a18", "weight": 2.5,
                    "fillColor": "#ff7a18", "fillOpacity": 0.06,
                },
                show=True,
            ).add_to(m)
            m.fit_bounds([[miny-dy, minx-dx], [maxy+dy, maxx+dx]], padding=(12, 12))
        except Exception:
            lon_min, lat_min, lon_max, lat_max = BRAZIL_VIEW_BBOX
            m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(12, 12))
    else:
        lon_min, lat_min, lon_max, lat_max = BRAZIL_VIEW_BBOX
        m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(12, 12))

    if enable_area_draw:
        Draw(
            export=False,
            position="topleft",
            draw_options={
                "polyline": False, "polygon": False, "circle": False,
                "marker": False, "circlemarker": False,
                "rectangle": {
                    "shapeOptions": {
                        "color": "#ff7a18", "weight": 2.5, "fillOpacity": 0.08
                    }
                },
            },
            edit_options={"edit": False, "remove": True},
        ).add_to(m)

    Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    legend_items = "".join(
        f"<div style='margin:3px 0'><span style='display:inline-block;width:11px;height:11px;"
        f"border-radius:50%;background:{color};margin-right:7px'></span>{label}</div>"
        for label, _, _, color in AGE_GROUPS
    )
    legend = f"""
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:rgba(20,20,20,.88);
                color:white;padding:10px 12px;border-radius:8px;font-size:13px;
                box-shadow:0 1px 6px rgba(0,0,0,.35)">
      <b>Idade do flash</b>{legend_items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))
    return m
