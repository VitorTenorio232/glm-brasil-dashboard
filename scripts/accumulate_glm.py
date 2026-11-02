#!/usr/bin/env python3
"""Acumula grades GLM do Flash View: diário -> mensal e mensal -> anual.

Reproduz o accumulate_glm_d-m-y.py usado na base original (descrito nos próprios arquivos):
  - flash_count: soma;
  - flash_energy, flash_area, flash_duration: média ponderada pelo flash_count
    (células sem flash ficam NaN).

Estrutura esperada (a mesma do Hugging Face):
  OUTPUT/02_DAILY/AAAA/MM/Gxx_GLM_FLASH_DAILY_AAAAMMDD.nc
  OUTPUT/03_MONTHLY/AAAA/Gxx_GLM_FLASH_MONTHLY_AAAAMM.nc
  OUTPUT/04_YEARLY/Gxx_GLM_FLASH_YEARLY_AAAA.nc

Exemplos:
  python scripts/accumulate_glm.py --data-root ../GLM_Process/OUTPUT --monthly 2025-04
  python scripts/accumulate_glm.py --data-root ../GLM_Process/OUTPUT --yearly 2025
  # validação: recria num diretório à parte e compara com o arquivo existente
  python scripts/accumulate_glm.py --data-root ../GLM_Process/OUTPUT --yearly 2024 --output-root /tmp/teste --compare
"""
from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import datetime
from pathlib import Path
import re

import numpy as np
import xarray as xr

MEAN_VARS = ("flash_energy", "flash_area", "flash_duration")
VAR_ATTRS = {
    "flash_count": ("{T} GLM Flash Centroid Density", "lightning_flash_count", "count/{u}/64km2",
                    "Total accumulated number of lightning flashes per {l}.", "time: sum (weighted by count)"),
    "flash_energy": ("{T} Mean Flash Radiant Energy", "lightning_radiant_energy", "J",
                     "{T} mean radiant energy of lightning flashes (weighted by count).", "time: mean (weighted by count)"),
    "flash_area": ("{T} Mean Flash Area", "lightning_flash_area", "m2",
                   "{T} mean coverage area of lightning flashes (weighted by count).", "time: mean (weighted by count)"),
    "flash_duration": ("{T} Mean Flash Duration", "lightning_flash_duration", "s",
                       "{T} mean duration of lightning flashes (weighted by count).", "time: mean (weighted by count)"),
}
SCALES = {"monthly": ("Monthly", "month", "monthly"), "yearly": ("Yearly", "year", "yearly")}
_SAT = re.compile(r"^(G\d+)_")


def accumulate(files: list[Path]) -> tuple[dict[str, np.ndarray], xr.Dataset]:
    """Soma das contagens e média ponderada das demais variáveis (em float64)."""
    total = None
    weighted = {}
    template = None
    for path in files:
        with xr.open_dataset(path) as ds:
            ds = ds.load()
        count = np.nan_to_num(ds["flash_count"].values[0].astype("float64"), nan=0.0)
        if total is None:
            template, total = ds, np.zeros_like(count)
            weighted = {v: np.zeros_like(count) for v in MEAN_VARS}
        elif ds.sizes["lat"] != template.sizes["lat"] or ds.sizes["lon"] != template.sizes["lon"]:
            raise ValueError(f"Grade diferente em {path.name}")
        total += count
        for var in MEAN_VARS:
            values = np.nan_to_num(ds[var].values[0].astype("float64"), nan=0.0)
            weighted[var] += values * count
    out = {"flash_count": total}
    with np.errstate(invalid="ignore", divide="ignore"):
        for var in MEAN_VARS:
            out[var] = np.where(total > 0, weighted[var] / np.where(total > 0, total, 1), np.nan)
    return out, template


def satellite_prefix(files: list[Path]) -> str:
    """Satélite com mais arquivos de entrada (ex.: abril/2025 = 6 dias G16 + 24 dias G19 -> G19)."""
    sats = Counter(_SAT.match(p.name).group(1) for p in files if _SAT.match(p.name))
    return sats.most_common(1)[0][0] if sats else "G16"


def write_product(arrays, template, files, scale: str, when: datetime, target: Path) -> None:
    title, unit, label = SCALES[scale]
    sats = sorted({_SAT.match(p.name).group(1) for p in files if _SAT.match(p.name)})
    coords = {"time": [np.datetime64(when, "ns")], "lat": template["lat"].values, "lon": template["lon"].values}
    data_vars = {}
    for var, (long_name, std, units, desc, cell) in VAR_ATTRS.items():
        data_vars[var] = (("time", "lat", "lon"), arrays[var].astype("float32")[None, ...], {
            "long_name": long_name.format(T=title), "standard_name": std,
            "units": units.format(u=unit), "description": desc.format(T=title, l=label), "cell_methods": cell,
        })
    ds = xr.Dataset(data_vars, coords=coords, attrs={
        "history": f"Created by scripts/accumulate_glm.py (Flash View) on {datetime.now()}",
        "source": f"Aggregated from {len(files)} input files",
        "aggregation_method": "Weighted mean by flash_count for energy, area, duration; sum for count",
        "satellites": ", ".join(sats),
    })
    for name in ("lat", "lon"):
        ds[name].attrs = dict(template[name].attrs)
    encoding = {var: {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "float32",
                      "_FillValue": np.float32(np.nan), "chunksizes": (1, ds.sizes["lat"], ds.sizes["lon"])}
                for var in VAR_ATTRS}
    encoding["time"] = {"units": "days since 1970-01-01", "calendar": "proleptic_gregorian", "dtype": "int32"}
    target.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(target, encoding=encoding)


def compare(new: Path, old: Path) -> str:
    with xr.open_dataset(new) as a, xr.open_dataset(old) as b:
        parts = []
        for var in VAR_ATTRS:
            x, y = a[var].values.astype("float64"), b[var].values.astype("float64")
            same_nan = bool(np.array_equal(np.isnan(x), np.isnan(y)))
            ok = ~np.isnan(x) & ~np.isnan(y)
            rel = np.abs(x[ok] - y[ok]) / np.maximum(np.abs(y[ok]), 1e-30)
            parts.append(f"{var}: NaN iguais={same_nan} dif. relativa máx={rel.max() if rel.size else 0:.2e}")
        return "; ".join(parts)


def find_existing(folder: Path, pattern: str) -> Path | None:
    hits = sorted(folder.glob(pattern)) if folder.exists() else []
    return hits[0] if hits else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-root", required=True, help="Pasta OUTPUT com 02_DAILY, 03_MONTHLY e 04_YEARLY")
    p.add_argument("--output-root", help="Onde gravar (padrão: a própria data-root)")
    p.add_argument("--monthly", action="append", default=[], metavar="AAAA-MM")
    p.add_argument("--yearly", action="append", default=[], metavar="AAAA", type=int)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--compare", action="store_true", help="Compara com o arquivo já existente na data-root")
    a = p.parse_args()
    root = Path(a.data_root).expanduser().resolve()
    out_root = Path(a.output_root).expanduser().resolve() if a.output_root else root

    for text in a.monthly:
        year, month = map(int, text.split("-"))
        files = sorted((root / "02_DAILY" / f"{year}" / f"{month:02d}").glob(f"G*_GLM_FLASH_DAILY_{year}{month:02d}*.nc"))
        expected = calendar.monthrange(year, month)[1]
        if len(files) != expected:
            raise SystemExit(f"{year}-{month:02d}: {len(files)} diários de {expected}; mês incompleto.")
        target = out_root / "03_MONTHLY" / f"{year}" / f"{satellite_prefix(files)}_GLM_FLASH_MONTHLY_{year}{month:02d}.nc"
        existing = find_existing(root / "03_MONTHLY" / f"{year}", f"G*_GLM_FLASH_MONTHLY_{year}{month:02d}.nc")
        if existing and not a.compare and not a.overwrite and out_root == root:
            print(f"Já existe: {existing.name} (use --overwrite)"); continue
        arrays, template = accumulate(files)
        write_product(arrays, template, files, "monthly", datetime(year, month, 1), target)
        print(f"Mensal {year}-{month:02d}: {len(files)} diários -> {target}")
        if a.compare and existing:
            print("  comparação com", existing.name, "->", compare(target, existing))

    for year in a.yearly:
        files = sorted((root / "03_MONTHLY" / f"{year}").glob(f"G*_GLM_FLASH_MONTHLY_{year}*.nc"))
        months = sorted({p.stem[-2:] for p in files})
        if len(months) != 12:
            missing = sorted(set(f"{m:02d}" for m in range(1, 13)) - set(months))
            raise SystemExit(f"{year}: faltam os meses {', '.join(missing)}; gere-os com --monthly antes.")
        target = out_root / "04_YEARLY" / f"{satellite_prefix(files)}_GLM_FLASH_YEARLY_{year}.nc"
        existing = find_existing(root / "04_YEARLY", f"G*_GLM_FLASH_YEARLY_{year}.nc")
        if existing and not a.compare and not a.overwrite and out_root == root:
            print(f"Já existe: {existing.name} (use --overwrite)"); continue
        arrays, template = accumulate(files)
        write_product(arrays, template, files, "yearly", datetime(year, 1, 1), target)
        print(f"Anual {year}: {len(files)} mensais -> {target}")
        if a.compare and existing:
            print("  comparação com", existing.name, "->", compare(target, existing))


if __name__ == "__main__":
    main()
