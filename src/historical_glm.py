from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
import calendar
import math
import os
import re
from typing import Iterable

import h5py
import numpy as np
import pandas as pd


BRAZIL_VIEW_BBOX = (-75.5, -35.5, -32.0, 6.5)  # lon_min, lat_min, lon_max, lat_max
# Limite superior da base histórica atualmente processada.
HISTORICAL_MAX_DATE = pd.Timestamp(2023, 12, 31)

VARIABLES = {
    "flash_count": {
        "label": "Número de flashes",
        "short": "Flashes",
        "unit": "flashes",
        "map_unit": "flashes/célula de 64 km²",
    },
    "flash_energy": {
        "label": "Energia radiante média",
        "short": "Energia",
        "unit": "J",
        "map_unit": "J",
    },
    "flash_area": {
        "label": "Área média do flash",
        "short": "Área",
        "unit": "km²",
        "map_unit": "km²",
    },
    "flash_duration": {
        "label": "Duração média do flash",
        "short": "Duração",
        "unit": "s",
        "map_unit": "s",
    },
}

# Limites de visualização fixos para permitir comparação direta entre mapas.
# Valores extremos acima do limite superior ficam saturados na cor máxima, mas
# os dados originais continuam preservados nos downloads.
FIXED_MAP_RANGES = {
    "flash_count": {
        "daily": (0.0, 50.0),
        "monthly": (0.0, 400.0),
        "yearly": (0.0, 2500.0),
    },
    "flash_energy": {"default": (0.0, 1.2e-11)},
    "flash_area": {"default": (0.0, 4000.0)},
    "flash_duration": {"default": (0.0, 1.2)},
}


def fixed_map_range(variable: str, scale: str) -> tuple[float, float]:
    cfg = FIXED_MAP_RANGES.get(variable, {})
    if scale in cfg:
        return tuple(cfg[scale])
    if "default" in cfg:
        return tuple(cfg["default"])
    raise KeyError(f"Escala fixa não configurada para {variable}/{scale}.")


MONTH_NAMES_PT = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}

_RE_HOURLY = re.compile(r"(?:^|/)01_HOURLY/(\d{4})/(\d{2})/G\d+_GLM_FLASH_HOURLY_(\d{8})\.nc$")
_RE_DAILY = re.compile(r"(?:^|/)02_DAILY/(\d{4})/(\d{2})/G\d+_GLM_FLASH_DAILY_(\d{8})\.nc$")
_RE_MONTHLY = re.compile(r"(?:^|/)03_MONTHLY/(\d{4})/G\d+_GLM_FLASH_MONTHLY_(\d{6})\.nc$")
_RE_YEARLY = re.compile(r"(?:^|/)04_YEARLY/G\d+_GLM_FLASH_YEARLY_(\d{4})\.nc$")


@dataclass(frozen=True)
class CatalogItem:
    scale: str
    relpath: str
    year: int
    month: int | None = None
    day: int | None = None

    @property
    def date(self) -> pd.Timestamp:
        return pd.Timestamp(self.year, self.month or 1, self.day or 1)


@dataclass(frozen=True)
class SourceConfig:
    local_root: str | None = None
    hf_repo: str | None = None
    hf_prefix: str = ""
    hf_token_env: str = "HF_TOKEN"

    @property
    def mode(self) -> str:
        if self.local_root:
            return "local"
        if self.hf_repo:
            return "huggingface"
        return "none"

    @property
    def label(self) -> str:
        if self.local_root:
            return str(self.local_root)
        if self.hf_repo:
            prefix = f"/{self.hf_prefix.strip('/')}" if self.hf_prefix else ""
            return f"hf://datasets/{self.hf_repo}{prefix}"
        return "não configurada"


class HistoricalGLMRepository:
    """Acesso aos produtos históricos processados do Flash View.

    A árvore esperada, a partir da raiz configurada, é:

        01_HOURLY/YYYY/MM/G16_GLM_FLASH_HOURLY_YYYYMMDD.nc
        02_DAILY/YYYY/MM/G16_GLM_FLASH_DAILY_YYYYMMDD.nc
        03_MONTHLY/YYYY/G16_GLM_FLASH_MONTHLY_YYYYMM.nc
        04_YEARLY/G16_GLM_FLASH_YEARLY_YYYY.nc

    A raiz pode ser uma pasta local ou um dataset público/privado no Hugging Face Hub.
    """

    def __init__(self, config: SourceConfig):
        if config.mode == "none":
            raise ValueError("Fonte histórica não configurada.")
        self.config = config
        self._catalog: list[CatalogItem] | None = None
        self._remote_files: list[str] | None = None

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def _list_relative_files(self) -> list[str]:
        if self.config.mode == "local":
            root = Path(self.config.local_root).expanduser().resolve()
            if not root.exists():
                raise FileNotFoundError(f"Diretório histórico não encontrado: {root}")
            return [p.relative_to(root).as_posix() for p in root.rglob("*.nc")]

        if self._remote_files is None:
            from huggingface_hub import HfApi

            token = os.getenv(self.config.hf_token_env) or None
            api = HfApi(token=token)
            files = api.list_repo_files(repo_id=self.config.hf_repo, repo_type="dataset")
            prefix = self.config.hf_prefix.strip("/")
            if prefix:
                prefix_slash = prefix + "/"
                files = [f[len(prefix_slash):] for f in files if f.startswith(prefix_slash)]
            self._remote_files = list(files)
        return list(self._remote_files)

    def scan(self, force: bool = False) -> list[CatalogItem]:
        if self._catalog is not None and not force:
            return list(self._catalog)

        items: list[CatalogItem] = []
        for rel in self._list_relative_files():
            rel = PurePosixPath(rel).as_posix()
            m = _RE_HOURLY.search(rel)
            if m:
                dt = datetime.strptime(m.group(3), "%Y%m%d")
                items.append(CatalogItem("hourly", rel, dt.year, dt.month, dt.day))
                continue
            m = _RE_DAILY.search(rel)
            if m:
                dt = datetime.strptime(m.group(3), "%Y%m%d")
                items.append(CatalogItem("daily", rel, dt.year, dt.month, dt.day))
                continue
            m = _RE_MONTHLY.search(rel)
            if m:
                dt = datetime.strptime(m.group(2), "%Y%m")
                items.append(CatalogItem("monthly", rel, dt.year, dt.month, 1))
                continue
            m = _RE_YEARLY.search(rel)
            if m:
                items.append(CatalogItem("yearly", rel, int(m.group(1)), 1, 1))
                continue

        # Ignora silenciosamente produtos posteriores ao fim oficial da base processada.
        # Isso evita que arquivos parciais/adicionados por engano apareçam nos seletores.
        items = [x for x in items if x.date <= HISTORICAL_MAX_DATE]
        items.sort(key=lambda x: (x.scale, x.year, x.month or 0, x.day or 0, x.relpath))
        self._catalog = items
        return list(items)

    def items(self, scale: str) -> list[CatalogItem]:
        return [x for x in self.scan() if x.scale == scale]

    def daily_years(self) -> list[int]:
        return sorted({x.year for x in self.items("daily")})

    def daily_months_for_year(self, year: int) -> list[int]:
        return sorted({x.month for x in self.items("daily") if x.year == int(year) and x.month is not None})

    def daily_days_for_month(self, year: int, month: int) -> list[int]:
        return sorted({
            x.day for x in self.items("daily")
            if x.year == int(year) and x.month == int(month) and x.day is not None
        })

    def daily_dates(self) -> list[pd.Timestamp]:
        return sorted({x.date for x in self.items("daily")})

    def monthly_years(self) -> list[int]:
        return sorted({x.year for x in self.items("monthly")})

    def yearly_years(self) -> list[int]:
        return sorted({x.year for x in self.items("yearly")})

    def months_for_year(self, year: int) -> list[int]:
        return sorted({x.month for x in self.items("monthly") if x.year == int(year) and x.month is not None})

    def years_for_month(self, month: int) -> list[int]:
        return sorted({x.year for x in self.items("monthly") if x.month == int(month)})

    def complete_monthly_years(self) -> list[int]:
        out = []
        for y in self.monthly_years():
            if set(self.months_for_year(y)) == set(range(1, 13)):
                out.append(y)
        return out

    def get_daily(self, year: int, month: int, day: int) -> CatalogItem:
        found = [
            x for x in self.items("daily")
            if x.year == int(year) and x.month == int(month) and x.day == int(day)
        ]
        if not found:
            raise FileNotFoundError(f"Produto diário não encontrado para {year}-{month:02d}-{day:02d}.")
        return found[0]

    def get_monthly(self, year: int, month: int) -> CatalogItem:
        found = [x for x in self.items("monthly") if x.year == int(year) and x.month == int(month)]
        if not found:
            raise FileNotFoundError(f"Produto mensal não encontrado para {year}-{month:02d}.")
        return found[0]

    def get_yearly(self, year: int) -> CatalogItem:
        found = [x for x in self.items("yearly") if x.year == int(year)]
        if not found:
            raise FileNotFoundError(f"Produto anual não encontrado para {year}.")
        return found[0]

    # ------------------------------------------------------------------
    # Materialização / leitura
    # ------------------------------------------------------------------
    def materialize(self, relpath: str) -> Path:
        if self.config.mode == "local":
            path = Path(self.config.local_root).expanduser().resolve() / relpath
            if not path.exists():
                raise FileNotFoundError(path)
            return path

        from huggingface_hub import hf_hub_download

        prefix = self.config.hf_prefix.strip("/")
        remote_name = f"{prefix}/{relpath}" if prefix else relpath
        token = os.getenv(self.config.hf_token_env) or None
        local = hf_hub_download(
            repo_id=self.config.hf_repo,
            repo_type="dataset",
            filename=remote_name,
            token=token,
        )
        return Path(local)

    @staticmethod
    def _decode_attr(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, np.bytes_):
            return value.tobytes().decode("utf-8", errors="replace")
        if isinstance(value, np.ndarray) and value.size == 1:
            return HistoricalGLMRepository._decode_attr(value.reshape(-1)[0])
        return value

    def file_metadata(self, item: CatalogItem) -> dict[str, object]:
        path = self.materialize(item.relpath)
        with h5py.File(path, "r") as h:
            attrs = {k: self._decode_attr(v) for k, v in h.attrs.items()}
            attrs["relpath"] = item.relpath
            attrs["file_size_bytes"] = path.stat().st_size
            return attrs

    def read_grid(self, item: CatalogItem, variable: str, time_index: int = 0):
        if variable not in VARIABLES:
            raise KeyError(variable)
        path = self.materialize(item.relpath)
        with h5py.File(path, "r") as h:
            lat = np.asarray(h["lat"][:], dtype=np.float64)
            lon = np.asarray(h["lon"][:], dtype=np.float64)
            data = np.asarray(h[variable][time_index, :, :], dtype=np.float64)
            count = np.asarray(h["flash_count"][time_index, :, :], dtype=np.float64)

        if variable == "flash_area":
            data = data / 1_000_000.0  # m² -> km² para visualização
        return lat, lon, data, count

    def read_hourly_grid(self, item: CatalogItem, variable: str, hour: int):
        if item.scale != "hourly":
            raise ValueError("O item informado não é horário.")
        if not 0 <= int(hour) <= 23:
            raise ValueError("hour deve estar entre 0 e 23.")
        return self.read_grid(item, variable, time_index=int(hour))

    # ------------------------------------------------------------------
    # Climatologia
    # ------------------------------------------------------------------
    def climatology(self, items: Iterable[CatalogItem], variable: str):
        items = list(items)
        if not items:
            raise ValueError("Nenhum arquivo disponível para a climatologia selecionada.")

        lat_ref = lon_ref = None
        sum_count = None
        sum_weighted = None
        sum_value = None
        valid_periods = None

        for item in items:
            lat, lon, data, count = self.read_grid(item, variable)
            if lat_ref is None:
                lat_ref, lon_ref = lat, lon
                shape = data.shape
                sum_count = np.zeros(shape, dtype=np.float64)
                sum_weighted = np.zeros(shape, dtype=np.float64)
                sum_value = np.zeros(shape, dtype=np.float64)
                valid_periods = np.zeros(shape, dtype=np.int32)
            elif not (np.array_equal(lat_ref, lat) and np.array_equal(lon_ref, lon)):
                raise ValueError("As grades dos arquivos históricos não são idênticas.")

            finite_count = np.isfinite(count)
            count_safe = np.where(finite_count, count, 0.0)

            if variable == "flash_count":
                finite = np.isfinite(data)
                sum_value[finite] += data[finite]
                valid_periods[finite] += 1
            else:
                finite = np.isfinite(data) & finite_count & (count > 0)
                sum_weighted[finite] += data[finite] * count[finite]
                sum_count[finite] += count[finite]

        if variable == "flash_count":
            out = np.full(sum_value.shape, np.nan, dtype=np.float64)
            ok = valid_periods > 0
            out[ok] = sum_value[ok] / valid_periods[ok]
        else:
            out = np.full(sum_weighted.shape, np.nan, dtype=np.float64)
            ok = sum_count > 0
            out[ok] = sum_weighted[ok] / sum_count[ok]

        return lat_ref, lon_ref, out, len(items)

    # ------------------------------------------------------------------
    # Séries temporais espaciais
    # ------------------------------------------------------------------
    @staticmethod
    def _grid_subset_for_geometry(lat: np.ndarray, lon: np.ndarray, geometry):
        minx, miny, maxx, maxy = geometry.bounds
        lat_idx = np.where((lat >= miny) & (lat <= maxy))[0]
        lon_idx = np.where((lon >= minx) & (lon <= maxx))[0]
        if lat_idx.size == 0 or lon_idx.size == 0:
            return None
        return lat_idx, lon_idx

    @staticmethod
    def _geometry_mask(lat: np.ndarray, lon: np.ndarray, geometry) -> np.ndarray:
        from shapely import contains_xy, intersects_xy

        xx, yy = np.meshgrid(lon, lat)
        mask = contains_xy(geometry, xx, yy)
        # inclui centros exatamente sobre o contorno, caso existam
        try:
            mask = mask | intersects_xy(geometry.boundary, xx, yy)
        except Exception:
            pass
        return np.asarray(mask, dtype=bool)

    @staticmethod
    def _aggregate_region(data: np.ndarray, count: np.ndarray, mask: np.ndarray, variable: str) -> float:
        if not np.any(mask):
            return float("nan")
        if variable == "flash_count":
            vals = data[mask]
            return float(np.nansum(vals)) if np.isfinite(vals).any() else float("nan")

        vals = data[mask]
        weights = count[mask]
        good = np.isfinite(vals) & np.isfinite(weights) & (weights > 0)
        if not np.any(good):
            return float("nan")
        return float(np.sum(vals[good] * weights[good]) / np.sum(weights[good]))

    def series_for_geometry(
        self,
        geometry,
        variable: str,
        scale: str = "monthly",
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Calcula somente os períodos explicitamente solicitados.

        Isso é especialmente importante para a fonte remota: uma série diária longa
        pode envolver dezenas ou centenas de NetCDF e não deve ser materializada
        automaticamente ao apenas mudar um seletor da interface.
        """
        if scale not in {"daily", "monthly", "yearly"}:
            raise ValueError("scale deve ser 'daily', 'monthly' ou 'yearly'.")

        items = self.items(scale)
        start_ts = pd.Timestamp(start_date).normalize() if start_date is not None else None
        end_ts = pd.Timestamp(end_date).normalize() if end_date is not None else HISTORICAL_MAX_DATE
        end_ts = min(end_ts, HISTORICAL_MAX_DATE)

        if start_ts is not None and start_ts > end_ts:
            raise ValueError("A data inicial não pode ser posterior à data final.")

        def selected(item: CatalogItem) -> bool:
            d = item.date.normalize()
            if start_ts is not None and d < start_ts:
                return False
            if d > end_ts:
                return False
            return True

        items = [item for item in items if selected(item)]
        if not items:
            return pd.DataFrame(columns=["date", "year", "month", "day", "value", "relpath"])

        rows = []
        cached_mask = None
        cached_signature = None

        for item in items:
            lat, lon, data, count = self.read_grid(item, variable)
            subset = self._grid_subset_for_geometry(lat, lon, geometry)
            if subset is None:
                value = float("nan")
            else:
                lat_idx, lon_idx = subset
                lat_sub = lat[lat_idx]
                lon_sub = lon[lon_idx]
                signature = (
                    float(lat_sub[0]), float(lat_sub[-1]), len(lat_sub),
                    float(lon_sub[0]), float(lon_sub[-1]), len(lon_sub),
                )
                if cached_mask is None or signature != cached_signature:
                    cached_mask = self._geometry_mask(lat_sub, lon_sub, geometry)
                    cached_signature = signature
                data_sub = data[np.ix_(lat_idx, lon_idx)]
                count_sub = count[np.ix_(lat_idx, lon_idx)]
                value = self._aggregate_region(data_sub, count_sub, cached_mask, variable)

            rows.append({
                "date": item.date,
                "year": item.year,
                "month": item.month,
                "day": item.day,
                "value": value,
                "relpath": item.relpath,
            })

        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Diagnóstico de completude
    # ------------------------------------------------------------------
    def completeness_summary(self) -> pd.DataFrame:
        rows = []
        years = sorted(set(self.daily_years()) | set(self.monthly_years()) | set(self.yearly_years()))
        for year in years:
            months = self.months_for_year(year)
            daily_files = len([x for x in self.items("daily") if x.year == year])
            rows.append({
                "year": year,
                "daily_files": daily_files,
                "monthly_files": len(months),
                "months": ", ".join(f"{m:02d}" for m in months),
                "monthly_complete": len(months) == 12,
                "yearly_available": year in self.yearly_years(),
            })
        return pd.DataFrame(rows)


# =============================================================================
# Configuração da fonte histórica
# =============================================================================
def autodetect_local_root(app_dir: str | Path | None = None) -> Path | None:
    base = Path(app_dir or Path.cwd()).expanduser().resolve()
    candidates = [
        base / "GLM_Process" / "OUTPUT",
        base.parent / "GLM_Process" / "OUTPUT",
        Path.home() / "Dashboard GLM" / "GLM_Process" / "OUTPUT",
        Path.home() / "Projeto-GLM-Dashboard" / "GLM_Process" / "OUTPUT",
    ]
    env = os.getenv("FLASH_VIEW_DATA_ROOT")
    if env:
        candidates.insert(0, Path(env).expanduser())

    seen: set[str] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except Exception:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "03_MONTHLY").exists() or (candidate / "04_YEARLY").exists():
            return candidate
    return None


def make_source_config(
    *,
    app_dir: str | Path | None = None,
    local_root: str | None = None,
    hf_repo: str | None = None,
    hf_prefix: str = "",
) -> SourceConfig:
    local = Path(local_root).expanduser().resolve() if local_root else autodetect_local_root(app_dir)
    if local and local.exists():
        return SourceConfig(local_root=str(local))
    hf_repo = hf_repo or os.getenv("FLASH_VIEW_HF_REPO") or None
    hf_prefix = hf_prefix or os.getenv("FLASH_VIEW_HF_PREFIX", "")
    if hf_repo:
        return SourceConfig(hf_repo=hf_repo, hf_prefix=hf_prefix)
    return SourceConfig()


# =============================================================================
# Geometrias administrativas (geobr)
# =============================================================================
def _find_col(columns, *candidates):
    lower = {str(c).lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    raise KeyError(f"Nenhuma das colunas {candidates} foi encontrada. Disponíveis: {list(columns)}")


def _to_wgs84(gdf):
    if gdf.crs is None:
        return gdf.set_crs(4674, allow_override=True).to_crs(4326)
    return gdf.to_crs(4326)


@lru_cache(maxsize=4)
def load_states(year: int = 2022):
    local_file = Path(__file__).resolve().parents[1] / "data" / "admin" / f"states_{year}.parquet"
    if local_file.is_file():
        import geopandas as gpd
        gdf = _to_wgs84(gpd.read_parquet(local_file))
    else:
        from geobr import read_state
        gdf = _to_wgs84(read_state(year=year))
    code_col = _find_col(gdf.columns, "code_state", "code_uf")
    uf_col = _find_col(gdf.columns, "abbrev_state", "sigla_uf")
    name_col = _find_col(gdf.columns, "name_state", "nome_uf")
    out = gdf[[code_col, uf_col, name_col, "geometry"]].copy()
    out.columns = ["code_state", "abbrev_state", "name_state", "geometry"]
    out["code_state"] = out["code_state"].astype(str)
    return out.sort_values("name_state").reset_index(drop=True)


@lru_cache(maxsize=32)
def load_municipalities(uf: str, year: int = 2022):
    local_file = Path(__file__).resolve().parents[1] / "data" / "admin" / f"municipalities_{year}.parquet"
    if local_file.is_file():
        import geopandas as gpd
        gdf = _to_wgs84(gpd.read_parquet(local_file))
        uf_col_local = _find_col(gdf.columns, "abbrev_state", "sigla_uf")
        gdf = gdf[gdf[uf_col_local].astype(str).str.upper() == str(uf).upper()].copy()
    else:
        from geobr import read_municipality
        gdf = _to_wgs84(read_municipality(code_muni=uf, year=year))
    code_col = _find_col(gdf.columns, "code_muni", "code_municipality", "codigo_ibge")
    name_col = _find_col(gdf.columns, "name_muni", "name_municipality", "nome_muni")
    uf_col = None
    for cand in ("abbrev_state", "sigla_uf"):
        if cand in gdf.columns:
            uf_col = cand
            break
    keep = [code_col, name_col, "geometry"] + ([uf_col] if uf_col else [])
    out = gdf[keep].copy()
    rename = {code_col: "code_muni", name_col: "name_muni"}
    if uf_col:
        rename[uf_col] = "abbrev_state"
    out = out.rename(columns=rename)
    out["code_muni"] = out["code_muni"].astype(str)
    if "abbrev_state" not in out:
        out["abbrev_state"] = uf
    return out.sort_values("name_muni").reset_index(drop=True)


@lru_cache(maxsize=2)
def load_country(year: int = 2022):
    local_file = Path(__file__).resolve().parents[1] / "data" / "admin" / f"country_{year}.parquet"
    if local_file.is_file():
        import geopandas as gpd
        gdf = _to_wgs84(gpd.read_parquet(local_file))
    else:
        from geobr import read_country
        gdf = _to_wgs84(read_country(year=year))
    # O Brasil pode vir com uma ou mais feições; a união garante uma geometria única.
    return gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union


def get_state_geometry(uf: str, year: int = 2022):
    states = load_states(year)
    row = states.loc[states["abbrev_state"].astype(str).str.upper() == uf.upper()]
    if row.empty:
        raise KeyError(f"UF não encontrada: {uf}")
    return row.iloc[0].geometry


def get_municipality_geometry(code_muni: str, uf: str, year: int = 2022):
    mun = load_municipalities(uf, year)
    row = mun.loc[mun["code_muni"].astype(str) == str(code_muni)]
    if row.empty:
        raise KeyError(f"Município não encontrado: {code_muni}")
    return row.iloc[0].geometry


# =============================================================================
# Mapas históricos
# =============================================================================
def _crop_to_bbox(lat, lon, data, bbox=BRAZIL_VIEW_BBOX):
    lon_min, lat_min, lon_max, lat_max = bbox
    iy = np.where((lat >= lat_min) & (lat <= lat_max))[0]
    ix = np.where((lon >= lon_min) & (lon <= lon_max))[0]
    if iy.size == 0 or ix.size == 0:
        raise ValueError("A grade não intercepta o recorte do Brasil configurado.")
    return lat[iy], lon[ix], data[np.ix_(iy, ix)]


def _axis_cell_edges(values: np.ndarray) -> tuple[float, float]:
    """Retorna os limites externos das células, não apenas os centros da grade.

    Os NetCDF armazenam latitude/longitude nos centros das células. Um ImageOverlay
    do Leaflet/Folium, porém, precisa receber as bordas externas da imagem. Usar os
    centros diretamente desloca visualmente o raster em aproximadamente meia célula.
    """
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        raise ValueError("Eixo espacial vazio.")
    if values.size == 1:
        half = 0.04
    else:
        step = float(np.nanmedian(np.diff(values)))
        half = abs(step) / 2.0
    return float(np.nanmin(values) - half), float(np.nanmax(values) + half)


def _robust_range(data: np.ndarray, variable: str):
    valid = data[np.isfinite(data)]
    if variable == "flash_count":
        valid = valid[valid > 0]
        vmin = 0.0
    else:
        vmin = float(np.nanpercentile(valid, 2)) if valid.size else 0.0
    if valid.size == 0:
        return 0.0, 1.0
    vmax = float(np.nanpercentile(valid, 99))
    if not np.isfinite(vmax) or vmax <= vmin:
        vmax = float(np.nanmax(valid)) if valid.size else vmin + 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax


def _rgba_clipped_to_country(
    data: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    variable: str,
    vmin: float,
    vmax: float,
    cmap,
    clip_geometry=None,
    oversample: int = 1,
) -> np.ndarray:
    """Converte o campo em RGBA e, opcionalmente, mascara fora da geometria.

    O recorte usa ``shapely.contains_xy`` de forma vetorizada nos centros das
    células. Como a grade é primeiro reduzida ao *bounding box* da área escolhida,
    o custo é pequeno para estados e municípios e continua aceitável para o Brasil.
    Nenhuma reamostragem/oversampling é aplicada.
    """
    normalized = (data - vmin) / (vmax - vmin)
    normalized = np.clip(normalized, 0.0, 1.0)
    rgba = (cmap(np.nan_to_num(normalized, nan=0.0)) * 255).astype(np.uint8)

    visible = np.isfinite(data)
    if variable == "flash_count":
        visible &= data > 0

    if clip_geometry is not None:
        try:
            from shapely import contains_xy, intersects_xy

            xx, yy = np.meshgrid(lon, lat)
            spatial_mask = contains_xy(clip_geometry, xx, yy)
            # Inclui pontos exatamente sobre a borda, quando existirem.
            try:
                spatial_mask |= intersects_xy(clip_geometry.boundary, xx, yy)
            except Exception:
                pass
            visible &= np.asarray(spatial_mask, dtype=bool)
        except Exception:
            # Se a máscara vetorizada não estiver disponível, preserva o raster e
            # mantém o limite vetorial desenhado por cima em vez de falhar o mapa.
            pass

    rgba[..., 3] = np.where(visible, 200, 0).astype(np.uint8)
    return rgba


def _crop_to_geometry_bbox(lat, lon, data, geometry):
    """Recorta a grade ao retângulo mínimo da geometria com uma célula de margem."""
    if geometry is None:
        return _crop_to_bbox(lat, lon, data)

    minx, miny, maxx, maxy = geometry.bounds
    dx = abs(float(np.nanmedian(np.diff(lon)))) if len(lon) > 1 else 0.08
    dy = abs(float(np.nanmedian(np.diff(lat)))) if len(lat) > 1 else 0.08

    # Uma célula de margem evita cortar pixels de fronteira antes da máscara.
    bbox = (minx - dx, miny - dy, maxx + dx, maxy + dy)
    try:
        return _crop_to_bbox(lat, lon, data, bbox=bbox)
    except ValueError:
        # Municípios menores que uma célula podem não conter nenhum centro de grade
        # no bbox estrito. Nesse caso usa a célula mais próxima do centróide.
        cx, cy = geometry.centroid.x, geometry.centroid.y
        iy = int(np.nanargmin(np.abs(np.asarray(lat) - cy)))
        ix = int(np.nanargmin(np.abs(np.asarray(lon) - cx)))
        return np.asarray(lat)[iy:iy+1], np.asarray(lon)[ix:ix+1], np.asarray(data)[iy:iy+1, ix:ix+1]

def clip_field_to_geometry(
    lat: np.ndarray,
    lon: np.ndarray,
    data: np.ndarray,
    geometry=None,
):
    """Recorta ao bbox e mascara centros de células fora da geometria.

    Retorna somente o produto necessário para visualização/download, reduzindo
    memória em recortes estaduais, municipais e personalizados.
    """
    lat2, lon2, data2 = _crop_to_geometry_bbox(lat, lon, data, geometry)
    data2 = np.asarray(data2, dtype=np.float64).copy()
    if geometry is not None:
        try:
            from shapely import contains_xy, intersects_xy
            xx, yy = np.meshgrid(lon2, lat2)
            mask = contains_xy(geometry, xx, yy)
            try:
                mask |= intersects_xy(geometry.boundary, xx, yy)
            except Exception:
                pass
            data2[~np.asarray(mask, dtype=bool)] = np.nan
        except Exception:
            pass
    return np.asarray(lat2), np.asarray(lon2), data2


def build_historical_map(
    lat: np.ndarray,
    lon: np.ndarray,
    data: np.ndarray,
    variable: str,
    *,
    layer_name: str,
    states_geojson=None,
    clip_geometry=None,
    boundary_name: str = "Limite selecionado",
    mask_to_geometry: bool = True,
    display_range: tuple[float, float] | None = None,
):
    import folium
    from branca.colormap import LinearColormap
    from folium.plugins import Fullscreen
    import matplotlib

    # Primeiro reduz a matriz ao retângulo mínimo da área escolhida. Isso evita
    # processar a grade brasileira inteira quando o usuário seleciona estado ou município.
    lat, lon, data = _crop_to_geometry_bbox(lat, lon, data, clip_geometry)

    # Por padrão ainda existe fallback automático, mas o Flash View público passa
    # display_range fixo por variável/escala para permitir comparação entre mapas.
    vmin, vmax = display_range if display_range is not None else _robust_range(data, variable)

    cmap = matplotlib.colormaps["turbo"]
    rgba = _rgba_clipped_to_country(
        data,
        lat,
        lon,
        variable=variable,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        clip_geometry=clip_geometry if mask_to_geometry else None,
        oversample=1,
    )

    # IMPORTANTe: lat/lon do NetCDF são centros de células. Para o ImageOverlay,
    # usamos as bordas externas das células. Isso corrige o deslocamento visual de
    # meia célula que fazia o raster não coincidir perfeitamente com os limites.
    south, north = _axis_cell_edges(lat)
    west, east = _axis_cell_edges(lon)

    # Leaflet desenha tiles em Web Mercator (EPSG:3857), enquanto a grade GLM
    # é regular em latitude/longitude (EPSG:4326). Reprojetamos a imagem antes
    # do ImageOverlay e endurecemos novamente o canal alfa para evitar que a
    # interpolação da reprojeção crie uma faixa semitransparente fora do shape.
    from folium.raster_layers import mercator_transform
    rgba_mercator = mercator_transform(rgba, (south, north), origin="lower")
    if rgba_mercator.shape[-1] == 4:
        rgba_mercator[..., 3] = np.where(rgba_mercator[..., 3] >= 100, 200, 0)
    rgba_mercator = np.clip(rgba_mercator, 0, 255).astype(np.uint8)

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
        control=True,
        show=True,
        max_zoom=19,
    ).add_to(m)
    folium.TileLayer(
        "OpenStreetMap",
        name="Mapa",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    folium.raster_layers.ImageOverlay(
        image=rgba_mercator,
        bounds=[[south, west], [north, east]],
        origin="lower",
        pixelated=True,
        name=layer_name,
        opacity=1.0,
        interactive=False,
        cross_origin=False,
        zindex=2,
        show=True,
    ).add_to(m)

    # Desenha o limite administrativo selecionado sobre o raster recortado.
    if clip_geometry is not None:
        try:
            from shapely.geometry import mapping
            folium.GeoJson(
                data=mapping(clip_geometry),
                name=boundary_name,
                style_function=lambda _: {
                    "color": "#ffffff",
                    "weight": 2.0,
                    "opacity": 1.0,
                    "fillOpacity": 0.0,
                },
                show=True,
            ).add_to(m)
        except Exception:
            pass

    if states_geojson is not None:
        try:
            folium.GeoJson(
                states_geojson,
                name="Limites estaduais",
                style_function=lambda _: {
                    "color": "#ffffff",
                    "weight": 1.0,
                    "opacity": 0.92,
                    "fillOpacity": 0.0,
                },
                show=True,
            ).add_to(m)
        except Exception:
            pass

    colors = [
        matplotlib.colors.to_hex(cmap(x), keep_alpha=False)
        for x in np.linspace(0.0, 1.0, 8)
    ]
    unit = VARIABLES[variable]["map_unit"]
    colorbar = LinearColormap(colors=colors, vmin=vmin, vmax=vmax)
    colorbar.caption = f"{VARIABLES[variable]['label']} ({unit})"
    colorbar.add_to(m)

    if clip_geometry is not None:
        try:
            minx, miny, maxx, maxy = clip_geometry.bounds
            pad_x = max(0.05, (maxx - minx) * 0.06)
            pad_y = max(0.05, (maxy - miny) * 0.06)
            m.fit_bounds(
                [[miny - pad_y, minx - pad_x], [maxy + pad_y, maxx + pad_x]],
                padding=(10, 10),
            )
        except Exception:
            lon_min, lat_min, lon_max, lat_max = BRAZIL_VIEW_BBOX
            m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(10, 10))
    else:
        lon_min, lat_min, lon_max, lat_max = BRAZIL_VIEW_BBOX
        m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(10, 10))

    Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m

def format_value(value: float, variable: str) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    if variable == "flash_count":
        return f"{value:,.0f}".replace(",", ".")
    if variable == "flash_energy":
        return f"{value:.3e} J"
    if variable == "flash_area":
        return f"{value:,.1f} km²".replace(",", "X").replace(".", ",").replace("X", ".")
    if variable == "flash_duration":
        return f"{value:.3f} s".replace(".", ",")
    return f"{value:.3g}"


def expected_days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(int(year), int(month))[1]
