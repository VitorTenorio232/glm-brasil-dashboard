#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_glm_admin_rankings.py

Gera produtos administrativos de ranking de flashes GLM a partir dos NetCDF
gridded do projeto Flash View.

Entrada esperada
----------------
Arquivos NetCDF com:
    flash_count(time, lat, lon)
    lat(lat)
    lon(lon)

Exemplos de nomes já usados no projeto:
    G16_GLM_FLASH_DAILY_20220131.nc
    G16_GLM_FLASH_MONTHLY_202212.nc
    G16_GLM_FLASH_YEARLY_2022.nc

Saídas
------
Para cada escala solicitada, cria:
    GLM_RANKING_MUNICIPAL_<ESCALA>_<INICIO>_<FIM>.nc
    GLM_RANKING_STATE_<ESCALA>_<INICIO>_<FIM>.nc

Também cria Parquet equivalentes, úteis para o dashboard.

Metodologia espacial
--------------------
Cada célula da grade GLM é atribuída ao município que contém o CENTRO da célula.
A associação espacial é calculada uma única vez e reutilizada para todos os
arquivos da mesma grade. Isso torna o processamento muito rápido.

Atenção:
    Para municípios muito pequenos ou fronteiriços, essa abordagem é uma
    aproximação da grade (~0,08° no banco atual). Para uma versão futura mais
    rigorosa, pode-se usar ponderação pela fração de área de cada célula dentro
    de cada município.

Uso
---
python build_glm_admin_rankings.py \
    --input-root "/caminho/GLM_Process/OUTPUT" \
    --municipalities "/caminho/municipios_brasil.gpkg" \
    --output-dir "/caminho/GLM_Process/OUTPUT/05_RANKINGS" \
    --scales daily monthly yearly \
    --start 2020-01-01 \
    --end 2022-12-31
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from tqdm import tqdm


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

SCALE_DIRS = {
    "daily": "02_DAILY",
    "monthly": "03_MONTHLY",
    "yearly": "04_YEARLY",
}

SCALE_LABELS = {
    "daily": "DAILY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}

DATE_REGEX = {
    "daily": re.compile(r"_(\d{8})\.nc$", re.IGNORECASE),
    "monthly": re.compile(r"_(\d{6})\.nc$", re.IGNORECASE),
    "yearly": re.compile(r"_(\d{4})\.nc$", re.IGNORECASE),
}


@dataclass
class GridLookup:
    lat: np.ndarray
    lon: np.ndarray
    municipality_index: np.ndarray
    state_index: np.ndarray


# =============================================================================
# UTILIDADES
# =============================================================================

def _normalize_column(gdf: gpd.GeoDataFrame, preferred: str, aliases: list[str]) -> str:
    cols = {c.lower(): c for c in gdf.columns}
    if preferred.lower() in cols:
        return cols[preferred.lower()]
    for alias in aliases:
        if alias.lower() in cols:
            return cols[alias.lower()]
    raise KeyError(
        f"Não encontrei a coluna '{preferred}'. "
        f"Colunas disponíveis: {list(gdf.columns)}"
    )


def _load_municipalities(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)

    if gdf.crs is None:
        raise ValueError("A malha municipal não possui CRS.")

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    code_col = _normalize_column(
        gdf, "code_muni",
        ["cod_mun", "codigo_municipio", "cd_mun", "geocode", "ibge_code"]
    )
    name_col = _normalize_column(
        gdf, "name_muni",
        ["nome_muni", "municipio", "nm_mun", "name"]
    )
    uf_col = _normalize_column(
        gdf, "abbrev_state",
        ["sigla_uf", "uf", "state_abbrev", "abbrev_uf"]
    )

    # name_state é opcional; se não existir, usamos a própria sigla.
    try:
        state_name_col = _normalize_column(
            gdf, "name_state",
            ["nome_uf", "estado", "state_name", "nm_uf"]
        )
    except KeyError:
        state_name_col = None

    out = gdf[[code_col, name_col, uf_col, "geometry"]].copy()
    out = out.rename(columns={
        code_col: "code_muni",
        name_col: "name_muni",
        uf_col: "abbrev_state",
    })

    if state_name_col is not None:
        out["name_state"] = gdf[state_name_col].astype(str).values
    else:
        out["name_state"] = out["abbrev_state"].astype(str)

    out["code_muni"] = pd.to_numeric(out["code_muni"], errors="coerce")
    out = out[out["code_muni"].notna() & out.geometry.notna()].copy()
    out["code_muni"] = out["code_muni"].astype("int64")
    out["name_muni"] = out["name_muni"].astype(str)
    out["abbrev_state"] = out["abbrev_state"].astype(str)
    out["name_state"] = out["name_state"].astype(str)

    out = out.drop_duplicates("code_muni").sort_values("code_muni").reset_index(drop=True)
    out["municipality_index"] = np.arange(len(out), dtype=np.int32)

    # Área em km² usando projeção equivalente de Albers para América do Sul.
    area_crs = "ESRI:102033"
    area_gdf = out.to_crs(area_crs)
    out["area_km2"] = area_gdf.geometry.area.to_numpy() / 1e6

    # Ponto de referência garantidamente dentro do polígono.
    ref = out.geometry.representative_point()
    out["longitude"] = ref.x.to_numpy()
    out["latitude"] = ref.y.to_numpy()

    return out


def _build_states(muni: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    states = (
        muni[["abbrev_state", "name_state", "geometry"]]
        .dissolve(by=["abbrev_state", "name_state"], as_index=False)
        .sort_values("abbrev_state")
        .reset_index(drop=True)
    )
    states["state_index"] = np.arange(len(states), dtype=np.int16)

    area_crs = "ESRI:102033"
    area_gdf = states.to_crs(area_crs)
    states["area_km2"] = area_gdf.geometry.area.to_numpy() / 1e6

    ref = states.geometry.representative_point()
    states["longitude"] = ref.x.to_numpy()
    states["latitude"] = ref.y.to_numpy()
    return states


def _parse_file_date(path: Path, scale: str) -> pd.Timestamp | None:
    m = DATE_REGEX[scale].search(path.name)
    if not m:
        return None

    token = m.group(1)
    if scale == "daily":
        return pd.to_datetime(token, format="%Y%m%d")
    if scale == "monthly":
        return pd.to_datetime(token, format="%Y%m")
    if scale == "yearly":
        return pd.to_datetime(token, format="%Y")
    return None


def _discover_files(root: Path, scale: str, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, Path]]:
    folder = root / SCALE_DIRS[scale]
    if not folder.exists():
        raise FileNotFoundError(f"Diretório não encontrado: {folder}")

    rows: list[tuple[pd.Timestamp, Path]] = []
    for path in folder.rglob("*.nc"):
        dt = _parse_file_date(path, scale)
        if dt is None:
            continue

        if scale == "monthly":
            dt_end = dt + pd.offsets.MonthEnd(0)
            if dt_end < start or dt > end:
                continue
        elif scale == "yearly":
            year_start = pd.Timestamp(dt.year, 1, 1)
            year_end = pd.Timestamp(dt.year, 12, 31)
            if year_end < start or year_start > end:
                continue
        else:
            if dt < start or dt > end:
                continue

        rows.append((dt, path))

    rows.sort(key=lambda x: x[0])
    return rows


def _read_grid(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with xr.open_dataset(path) as ds:
        if "lat" not in ds.coords and "lat" not in ds:
            raise KeyError(f"'lat' não encontrada em {path.name}")
        if "lon" not in ds.coords and "lon" not in ds:
            raise KeyError(f"'lon' não encontrada em {path.name}")
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
    return lat, lon


def _cache_filename(lat: np.ndarray, lon: np.ndarray, cache_dir: Path) -> Path:
    key = (
        f"{len(lat)}x{len(lon)}_"
        f"{lat[0]:.5f}_{lat[-1]:.5f}_"
        f"{lon[0]:.5f}_{lon[-1]:.5f}"
    ).replace("-", "m").replace(".", "p")
    return cache_dir / f"glm_admin_lookup_{key}.npz"


def _make_grid_lookup(
    lat: np.ndarray,
    lon: np.ndarray,
    muni: gpd.GeoDataFrame,
    states: gpd.GeoDataFrame,
    cache_dir: Path,
    force: bool = False,
) -> GridLookup:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = _cache_filename(lat, lon, cache_dir)

    if cache.exists() and not force:
        data = np.load(cache)
        return GridLookup(
            lat=data["lat"],
            lon=data["lon"],
            municipality_index=data["municipality_index"],
            state_index=data["state_index"],
        )

    print("Criando associação espacial grade GLM -> municípios...")
    print("Esta etapa é feita apenas uma vez para esta grade.")

    # Vetores achatados da grade inteira.
    nlat, nlon = len(lat), len(lon)
    total_cells = nlat * nlon
    muni_index_full = np.full(total_cells, -1, dtype=np.int32)
    state_index_full = np.full(total_cells, -1, dtype=np.int16)

    # Reduz a criação de pontos ao bbox do Brasil + pequena margem.
    minx, miny, maxx, maxy = muni.total_bounds
    lat_idx = np.where((lat >= miny - 0.2) & (lat <= maxy + 0.2))[0]
    lon_idx = np.where((lon >= minx - 0.2) & (lon <= maxx + 0.2))[0]

    yy, xx = np.meshgrid(lat_idx, lon_idx, indexing="ij")
    flat_indices = (yy * nlon + xx).ravel()

    point_lat = lat[yy.ravel()]
    point_lon = lon[xx.ravel()]

    points = gpd.GeoDataFrame(
        {"flat_index": flat_indices},
        geometry=gpd.points_from_xy(point_lon, point_lat),
        crs="EPSG:4326",
    )

    join_cols = ["municipality_index", "abbrev_state", "geometry"]
    joined = gpd.sjoin(
        points,
        muni[join_cols],
        how="left",
        predicate="within",
    )

    # Em fronteiras exatas um ponto pode ficar sem município. Tenta intersects
    # apenas nesses poucos casos.
    missing = joined["municipality_index"].isna()
    if missing.any():
        retry = gpd.sjoin(
            joined.loc[missing, ["flat_index", "geometry"]],
            muni[join_cols],
            how="left",
            predicate="intersects",
        )
        retry = retry[retry["municipality_index"].notna()]
        retry = retry[~retry.index.duplicated(keep="first")]
        joined.loc[retry.index, "municipality_index"] = retry["municipality_index"]
        joined.loc[retry.index, "abbrev_state"] = retry["abbrev_state"]

    joined = joined[joined["municipality_index"].notna()].copy()
    joined = joined[~joined["flat_index"].duplicated(keep="first")]

    flat = joined["flat_index"].to_numpy(dtype=np.int64)
    muni_idx = joined["municipality_index"].to_numpy(dtype=np.int32)
    muni_index_full[flat] = muni_idx

    state_map = dict(zip(states["abbrev_state"], states["state_index"]))
    st_idx = joined["abbrev_state"].map(state_map).to_numpy()
    valid_state = pd.notna(st_idx)
    state_index_full[flat[valid_state]] = st_idx[valid_state].astype(np.int16)

    municipality_index = muni_index_full.reshape(nlat, nlon)
    state_index = state_index_full.reshape(nlat, nlon)

    np.savez_compressed(
        cache,
        lat=lat.astype(np.float32),
        lon=lon.astype(np.float32),
        municipality_index=municipality_index,
        state_index=state_index,
    )

    print(f"Lookup salvo em: {cache}")

    return GridLookup(
        lat=lat,
        lon=lon,
        municipality_index=municipality_index,
        state_index=state_index,
    )


def _aggregate_one_file(
    path: Path,
    lookup: GridLookup,
    n_muni: int,
    n_states: int,
) -> tuple[np.ndarray, np.ndarray]:
    with xr.open_dataset(path) as ds:
        if "flash_count" not in ds:
            raise KeyError(f"'flash_count' não encontrada em {path.name}")

        da = ds["flash_count"]

        # Os arquivos atuais têm time=1 para daily/monthly/yearly.
        if "time" in da.dims:
            da = da.isel(time=0)

        arr = np.asarray(da.values, dtype=np.float64)

    if arr.shape != lookup.municipality_index.shape:
        raise ValueError(
            f"Grade incompatível em {path.name}: "
            f"{arr.shape} != {lookup.municipality_index.shape}"
        )

    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    flat_values = arr.ravel()

    muni_idx = lookup.municipality_index.ravel()
    valid_muni = muni_idx >= 0
    muni_sum = np.bincount(
        muni_idx[valid_muni],
        weights=flat_values[valid_muni],
        minlength=n_muni,
    )

    state_idx = lookup.state_index.ravel()
    valid_state = state_idx >= 0
    state_sum = np.bincount(
        state_idx[valid_state],
        weights=flat_values[valid_state],
        minlength=n_states,
    )

    return muni_sum, state_sum


def _time_bounds_label(scale: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[str, str]:
    if scale == "daily":
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if scale == "monthly":
        return start.strftime("%Y%m"), end.strftime("%Y%m")
    return start.strftime("%Y"), end.strftime("%Y")


def _write_municipality_dataset(
    output: Path,
    times: list[pd.Timestamp],
    counts: np.ndarray,
    muni: gpd.GeoDataFrame,
    scale: str,
) -> xr.Dataset:
    counts_int = np.rint(counts).astype(np.int64)
    density = counts / muni["area_km2"].to_numpy()[None, :]

    ds = xr.Dataset(
        data_vars={
            "flash_count": (
                ("time", "municipality"),
                counts_int,
                {
                    "long_name": "GLM flash count assigned to municipality",
                    "units": "count",
                    "aggregation": "sum of gridded flash_count cells assigned by cell center",
                },
            ),
            "flash_density": (
                ("time", "municipality"),
                density.astype(np.float32),
                {
                    "long_name": "GLM flash count per municipality area",
                    "units": "count km-2",
                    "description": "flash_count divided by official polygon area used in this processing",
                },
            ),
            "municipality_code": (
                ("municipality",),
                muni["code_muni"].to_numpy(dtype=np.int64),
                {"long_name": "IBGE municipality code"},
            ),
            "municipality_name": (
                ("municipality",),
                muni["name_muni"].astype(str).to_numpy(),
                {"long_name": "Municipality name"},
            ),
            "state_abbrev": (
                ("municipality",),
                muni["abbrev_state"].astype(str).to_numpy(),
                {"long_name": "State abbreviation"},
            ),
            "state_name": (
                ("municipality",),
                muni["name_state"].astype(str).to_numpy(),
                {"long_name": "State name"},
            ),
            "latitude": (
                ("municipality",),
                muni["latitude"].to_numpy(dtype=np.float32),
                {"units": "degrees_north", "description": "Representative point inside municipality"},
            ),
            "longitude": (
                ("municipality",),
                muni["longitude"].to_numpy(dtype=np.float32),
                {"units": "degrees_east", "description": "Representative point inside municipality"},
            ),
            "area_km2": (
                ("municipality",),
                muni["area_km2"].to_numpy(dtype=np.float32),
                {"units": "km2", "long_name": "Municipality area"},
            ),
        },
        coords={
            "time": pd.DatetimeIndex(times),
            "municipality": np.arange(len(muni), dtype=np.int32),
        },
        attrs={
            "title": f"Flash View - GLM municipal ranking ({scale})",
            "spatial_assignment": "GLM grid-cell center assigned to municipality polygon",
            "source_variable": "flash_count",
            "note": (
                "Boundary uncertainty follows the spatial resolution of the gridded GLM product. "
                "Small municipalities can be sensitive to cell-center assignment."
            ),
        },
    )

    encoding = {
        "flash_count": {"zlib": True, "complevel": 4},
        "flash_density": {"zlib": True, "complevel": 4},
    }
    ds.to_netcdf(output, engine="netcdf4", format="NETCDF4", encoding=encoding)
    return ds


def _write_state_dataset(
    output: Path,
    times: list[pd.Timestamp],
    counts: np.ndarray,
    states: gpd.GeoDataFrame,
    scale: str,
) -> xr.Dataset:
    counts_int = np.rint(counts).astype(np.int64)
    density = counts / states["area_km2"].to_numpy()[None, :]

    ds = xr.Dataset(
        data_vars={
            "flash_count": (
                ("time", "state"),
                counts_int,
                {"long_name": "GLM flash count assigned to state", "units": "count"},
            ),
            "flash_density": (
                ("time", "state"),
                density.astype(np.float32),
                {"long_name": "GLM flash count per state area", "units": "count km-2"},
            ),
            "state_abbrev": (
                ("state",),
                states["abbrev_state"].astype(str).to_numpy(),
                {"long_name": "State abbreviation"},
            ),
            "state_name": (
                ("state",),
                states["name_state"].astype(str).to_numpy(),
                {"long_name": "State name"},
            ),
            "latitude": (
                ("state",),
                states["latitude"].to_numpy(dtype=np.float32),
                {"units": "degrees_north", "description": "Representative point inside state"},
            ),
            "longitude": (
                ("state",),
                states["longitude"].to_numpy(dtype=np.float32),
                {"units": "degrees_east", "description": "Representative point inside state"},
            ),
            "area_km2": (
                ("state",),
                states["area_km2"].to_numpy(dtype=np.float32),
                {"units": "km2", "long_name": "State area"},
            ),
        },
        coords={
            "time": pd.DatetimeIndex(times),
            "state": np.arange(len(states), dtype=np.int16),
        },
        attrs={
            "title": f"Flash View - GLM state ranking ({scale})",
            "spatial_assignment": "GLM grid-cell center assigned to municipality/state polygon",
            "source_variable": "flash_count",
        },
    )

    encoding = {
        "flash_count": {"zlib": True, "complevel": 4},
        "flash_density": {"zlib": True, "complevel": 4},
    }
    ds.to_netcdf(output, engine="netcdf4", format="NETCDF4", encoding=encoding)
    return ds


def _write_parquet_municipality(
    output: Path,
    times: list[pd.Timestamp],
    counts: np.ndarray,
    muni: gpd.GeoDataFrame,
    scale: str,
) -> None:
    frames = []
    for i, dt in enumerate(times):
        df = pd.DataFrame({
            "time": dt,
            "municipality_code": muni["code_muni"].to_numpy(dtype=np.int64),
            "municipality_name": muni["name_muni"].astype(str).to_numpy(),
            "state_abbrev": muni["abbrev_state"].astype(str).to_numpy(),
            "state_name": muni["name_state"].astype(str).to_numpy(),
            "latitude": muni["latitude"].to_numpy(dtype=np.float32),
            "longitude": muni["longitude"].to_numpy(dtype=np.float32),
            "area_km2": muni["area_km2"].to_numpy(dtype=np.float32),
            "flash_count": np.rint(counts[i]).astype(np.int64),
        })
        df["flash_density"] = df["flash_count"] / df["area_km2"]
        df["scale"] = scale
        frames.append(df)

    pd.concat(frames, ignore_index=True).to_parquet(output, index=False)


def _write_parquet_state(
    output: Path,
    times: list[pd.Timestamp],
    counts: np.ndarray,
    states: gpd.GeoDataFrame,
    scale: str,
) -> None:
    frames = []
    for i, dt in enumerate(times):
        df = pd.DataFrame({
            "time": dt,
            "state_abbrev": states["abbrev_state"].astype(str).to_numpy(),
            "state_name": states["name_state"].astype(str).to_numpy(),
            "latitude": states["latitude"].to_numpy(dtype=np.float32),
            "longitude": states["longitude"].to_numpy(dtype=np.float32),
            "area_km2": states["area_km2"].to_numpy(dtype=np.float32),
            "flash_count": np.rint(counts[i]).astype(np.int64),
        })
        df["flash_density"] = df["flash_count"] / df["area_km2"]
        df["scale"] = scale
        frames.append(df)

    pd.concat(frames, ignore_index=True).to_parquet(output, index=False)


# =============================================================================
# PROCESSAMENTO PRINCIPAL
# =============================================================================

def process_scale(
    root: Path,
    municipalities_path: Path,
    output_dir: Path,
    scale: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: Path,
    force_lookup: bool,
) -> None:
    files = _discover_files(root, scale, start, end)
    if not files:
        print(f"[{scale}] Nenhum arquivo encontrado no período.")
        return

    print(f"\n[{scale}] Arquivos encontrados: {len(files)}")
    print(f"[{scale}] Primeiro: {files[0][1].name}")
    print(f"[{scale}] Último : {files[-1][1].name}")

    muni = _load_municipalities(municipalities_path)
    states = _build_states(muni)

    lat, lon = _read_grid(files[0][1])
    lookup = _make_grid_lookup(
        lat=lat,
        lon=lon,
        muni=muni,
        states=states,
        cache_dir=cache_dir,
        force=force_lookup,
    )

    muni_counts = np.zeros((len(files), len(muni)), dtype=np.float64)
    state_counts = np.zeros((len(files), len(states)), dtype=np.float64)
    times: list[pd.Timestamp] = []

    for i, (dt, path) in enumerate(tqdm(files, desc=f"Agregando {scale}", unit="arquivo")):
        msum, ssum = _aggregate_one_file(
            path,
            lookup,
            n_muni=len(muni),
            n_states=len(states),
        )
        muni_counts[i, :] = msum
        state_counts[i, :] = ssum
        times.append(dt)

    output_dir.mkdir(parents=True, exist_ok=True)
    ini, fim = _time_bounds_label(scale, times[0], times[-1])
    label = SCALE_LABELS[scale]

    muni_nc = output_dir / f"GLM_RANKING_MUNICIPAL_{label}_{ini}_{fim}.nc"
    state_nc = output_dir / f"GLM_RANKING_STATE_{label}_{ini}_{fim}.nc"

    muni_pq = output_dir / f"GLM_RANKING_MUNICIPAL_{label}_{ini}_{fim}.parquet"
    state_pq = output_dir / f"GLM_RANKING_STATE_{label}_{ini}_{fim}.parquet"

    ds_muni = _write_municipality_dataset(muni_nc, times, muni_counts, muni, scale)
    ds_state = _write_state_dataset(state_nc, times, state_counts, states, scale)

    _write_parquet_municipality(muni_pq, times, muni_counts, muni, scale)
    _write_parquet_state(state_pq, times, state_counts, states, scale)

    ds_muni.close()
    ds_state.close()

    print(f"[{scale}] Criado: {muni_nc}")
    print(f"[{scale}] Criado: {state_nc}")
    print(f"[{scale}] Criado: {muni_pq}")
    print(f"[{scale}] Criado: {state_pq}")

    # Mostra Top 10 do último período como checagem.
    last = pd.DataFrame({
        "municipio": muni["name_muni"],
        "UF": muni["abbrev_state"],
        "flash_count": np.rint(muni_counts[-1]).astype(np.int64),
        "flash_density": muni_counts[-1] / muni["area_km2"].to_numpy(),
    }).sort_values("flash_count", ascending=False)

    print(f"\n[{scale}] Top 10 municipal por número de flashes - {times[-1].date()}")
    print(last.head(10).to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cria NetCDF/Parquet de ranking municipal e estadual de flashes GLM."
    )
    parser.add_argument(
        "--input-root",
        required=True,
        type=Path,
        help="Pasta OUTPUT contendo 02_DAILY, 03_MONTHLY e 04_YEARLY.",
    )
    parser.add_argument(
        "--municipalities",
        required=True,
        type=Path,
        help="GeoPackage/Shapefile dos municípios do Brasil.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Pasta de saída dos rankings.",
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        choices=["daily", "monthly", "yearly"],
        default=["monthly", "yearly"],
        help="Escalas a processar.",
    )
    parser.add_argument(
        "--start",
        default="2020-01-01",
        help="Data inicial, padrão 2020-01-01.",
    )
    parser.add_argument(
        "--end",
        default="2022-12-31",
        help="Data final, padrão 2022-12-31.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Pasta para cache da associação grade->município.",
    )
    parser.add_argument(
        "--force-lookup",
        action="store_true",
        help="Recria a associação espacial mesmo que exista cache.",
    )

    args = parser.parse_args()

    root = args.input_root.expanduser().resolve()
    municipalities = args.municipalities.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    cache_dir = (
        args.cache_dir.expanduser().resolve()
        if args.cache_dir is not None
        else output_dir / "_cache"
    )

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    if not root.exists():
        raise FileNotFoundError(root)
    if not municipalities.exists():
        raise FileNotFoundError(municipalities)
    if end < start:
        raise ValueError("--end deve ser posterior a --start.")

    print("=" * 78)
    print("FLASH VIEW - RANKING ADMINISTRATIVO GLM")
    print("=" * 78)
    print(f"Entrada       : {root}")
    print(f"Municípios    : {municipalities}")
    print(f"Saída         : {output_dir}")
    print(f"Escalas       : {', '.join(args.scales)}")
    print(f"Período       : {start.date()} até {end.date()}")
    print("=" * 78)

    for scale in args.scales:
        process_scale(
            root=root,
            municipalities_path=municipalities,
            output_dir=output_dir,
            scale=scale,
            start=start,
            end=end,
            cache_dir=cache_dir,
            force_lookup=args.force_lookup,
        )

    print("\nProcessamento concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
