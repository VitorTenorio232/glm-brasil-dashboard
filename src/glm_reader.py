from __future__ import annotations

from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import xarray as xr

FLASH_VARS = [
    "flash_id",
    "flash_lat",
    "flash_lon",
    "flash_time_offset_of_first_event",
    "flash_time_offset_of_last_event",
    "flash_area",
    "flash_energy",
    "flash_quality_flag",
]


def _as_datetime(values) -> pd.Series:
    return pd.Series(pd.to_datetime(values, utc=True, errors="coerce"))


def _normalize_area(values: np.ndarray, units: str | None) -> np.ndarray:
    units = (units or "").lower().replace("²", "2")
    arr = np.asarray(values, dtype="float64")
    if units in {"m2", "m^2", "square meter", "square meters"} or "m2" in units:
        return arr / 1_000_000.0
    # Se o arquivo já declarar km² (ou unidade desconhecida), preserva os valores.
    return arr


def _attr_text(value) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.size == 1:
        return _attr_text(value.reshape(-1)[0])
    return str(value)


def _attr_scalar(attrs, name):
    if name not in attrs:
        return None
    return np.asarray(attrs[name]).reshape(-1)[0]


def _h5_decode(dset) -> np.ndarray:
    """Aplica _Unsigned, _FillValue, scale_factor e add_offset (convenção CF), como o xarray."""
    raw = dset[()]
    attrs = dset.attrs
    unsigned = _attr_text(attrs["_Unsigned"]).lower() == "true" if "_Unsigned" in attrs else False
    fill = _attr_scalar(attrs, "_FillValue")
    if unsigned and raw.dtype.kind == "i":
        utype = np.dtype(f"u{raw.dtype.itemsize}")
        raw = raw.view(utype)
        if fill is not None:
            fill = np.asarray(fill, dtype=raw.dtype.str.replace("u", "i")).view(utype)
    scale = _attr_scalar(attrs, "scale_factor")
    offset = _attr_scalar(attrs, "add_offset")
    if fill is None and scale is None and offset is None:
        return raw
    out = raw.astype("float64")
    if fill is not None:
        out[raw == fill] = np.nan
    if scale is not None:
        out *= float(scale)
    if offset is not None:
        out += float(offset)
    return out


def _h5_times(dset) -> pd.Series:
    units = _attr_text(dset.attrs.get("units", ""))
    if not units.startswith("seconds since "):
        raise ValueError(f"Unidade de tempo não suportada: {units!r}")
    base = pd.Timestamp(units[len("seconds since "):], tz="UTC")
    seconds = _h5_decode(dset)
    return pd.Series(base + pd.to_timedelta(seconds, unit="s"))


def _read_glm_arrays_h5py(path: Path):
    """Leitura direta via h5py.

    No Windows, abrir um LCFA com netCDF4/xarray leva ~2 s por arquivo; com h5py, ~1 ms.
    A janela ao vivo usa ~270 arquivos, então isso define o tempo da primeira carga.
    """
    import h5py

    with h5py.File(path, "r") as h:
        missing = [v for v in ["flash_lat", "flash_lon", "flash_time_offset_of_first_event"] if v not in h]
        if missing:
            raise KeyError(f"{path.name}: variáveis obrigatórias ausentes: {missing}")
        n = int(h["flash_lat"].size)
        if n == 0:
            return None
        lat = np.asarray(_h5_decode(h["flash_lat"]), dtype="float64")
        lon = np.asarray(_h5_decode(h["flash_lon"]), dtype="float64")
        start_time = _h5_times(h["flash_time_offset_of_first_event"])
        end_time = (_h5_times(h["flash_time_offset_of_last_event"])
                    if "flash_time_offset_of_last_event" in h else start_time.copy())
        flash_id = _h5_decode(h["flash_id"]) if "flash_id" in h else np.arange(n)
        area = (_normalize_area(_h5_decode(h["flash_area"]), _attr_text(h["flash_area"].attrs.get("units", "")))
                if "flash_area" in h else np.full(n, np.nan))
        energy = (np.asarray(_h5_decode(h["flash_energy"]), dtype="float64")
                  if "flash_energy" in h else np.full(n, np.nan))
        qflag = _h5_decode(h["flash_quality_flag"]) if "flash_quality_flag" in h else np.full(n, np.nan)
    return lat, lon, start_time, end_time, flash_id, area, energy, qflag


def _read_glm_arrays_xarray(path: Path):
    with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as ds:
        missing = [v for v in ["flash_lat", "flash_lon", "flash_time_offset_of_first_event"] if v not in ds]
        if missing:
            raise KeyError(f"{path.name}: variáveis obrigatórias ausentes: {missing}")

        n = int(ds["flash_lat"].size)
        if n == 0:
            return None

        lat = np.asarray(ds["flash_lat"].values, dtype="float64").copy()
        lon = np.asarray(ds["flash_lon"].values, dtype="float64").copy()
        start_time = _as_datetime(ds["flash_time_offset_of_first_event"].values)
        if "flash_time_offset_of_last_event" in ds:
            end_time = _as_datetime(ds["flash_time_offset_of_last_event"].values)
        else:
            end_time = start_time.copy()
        flash_id = np.asarray(ds["flash_id"].values).copy() if "flash_id" in ds else np.arange(n)
        area = (
            _normalize_area(ds["flash_area"].values, ds["flash_area"].attrs.get("units"))
            if "flash_area" in ds else np.full(n, np.nan)
        )
        energy = np.asarray(ds["flash_energy"].values, dtype="float64").copy() if "flash_energy" in ds else np.full(n, np.nan)
        qflag = np.asarray(ds["flash_quality_flag"].values).copy() if "flash_quality_flag" in ds else np.full(n, np.nan)
    return lat, lon, start_time, end_time, flash_id, area, energy, qflag


def read_glm_file(path: str | Path, *, quality: str = "all") -> pd.DataFrame:
    """Lê flashes de um arquivo LCFA. quality: 'all' ou 'zero_only'."""
    path = Path(path)
    try:
        arrays = _read_glm_arrays_h5py(path)
    except KeyError:
        raise
    except Exception:
        arrays = _read_glm_arrays_xarray(path)
    if arrays is None:
        return pd.DataFrame(columns=[
            "flash_uid", "flash_id", "time_start", "time_end", "lat", "lon",
            "area_km2", "energy_j", "quality_flag", "duration_ms", "source_file"
        ])
    lat, lon, start_time, end_time, flash_id, area, energy, qflag = arrays

    # flash_id é único apenas dentro do arquivo/produto.
    file_hash = hashlib.blake2s(path.name.encode(), digest_size=5).hexdigest()
    uid = [f"{file_hash}-{int(x)}" for x in flash_id.astype("int64", copy=False)]
    out = pd.DataFrame({
        "flash_uid": uid,
        "flash_id": flash_id,
        "time_start": start_time,
        "time_end": end_time,
        "lat": lat,
        "lon": lon,
        "area_km2": area,
        "energy_j": energy,
        "quality_flag": qflag,
        "source_file": path.name,
    })
    out["duration_ms"] = (out["time_end"] - out["time_start"]).dt.total_seconds() * 1000.0

    if quality == "zero_only":
        out = out[out["quality_flag"].fillna(0) == 0].copy()
    elif quality != "all":
        raise ValueError("quality deve ser 'all' ou 'zero_only'")
    return out.reset_index(drop=True)

def read_glm_files(paths, *, quality: str = "all") -> pd.DataFrame:
    frames = []
    for p in sorted(map(Path, paths)):
        df = read_glm_file(p, quality=quality)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["flash_uid"]).sort_values("time_start").reset_index(drop=True)
    return out
