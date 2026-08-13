#!/usr/bin/env python3
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import box
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_reader import read_glm_files
from src.spatial import assign_flashes_to_municipalities
from src.statistics import build_products
from src.storage import save_products, save_table
from src.qc import quality_summary


def glm_name(dt: datetime, goes: str) -> str:
    start = dt.strftime("%Y%j%H%M%S") + "0"
    end = (dt + timedelta(seconds=20)).strftime("%Y%j%H%M%S") + "0"
    created = (dt + timedelta(seconds=25)).strftime("%Y%j%H%M%S") + "0"
    return f"OR_GLM-L2-LCFA_G{goes}_s{start}_e{end}_c{created}.nc"


def write_glm_file(path: Path, dt: datetime, rng: np.random.Generator, month: int, year: int):
    centers = [(-45.5, -19.5), (-44.5, -19.5), (-45.5, -18.5)]
    base = [35, 55, 25]
    lons=[]; lats=[]; starts=[]; ends=[]; area=[]; energy=[]; qflag=[]; ids=[]
    idx=0
    for j, (cx, cy) in enumerate(centers):
        seasonal = 1.0 + 0.65*np.cos((month-1)/12*2*np.pi)
        trend = 1.15 if year == 2025 else 1.0
        n = max(8, int(base[j] * seasonal * trend))
        for _ in range(n):
            lons.append(cx + rng.normal(0, .20)); lats.append(cy + rng.normal(0, .20))
            offset_ms = int(rng.integers(0, 19_000)); dur = int(rng.integers(50, 1200))
            starts.append(offset_ms); ends.append(offset_ms+dur)
            area.append(float(rng.lognormal(mean=3.0, sigma=.55)))
            energy.append(float(rng.lognormal(mean=-2.8, sigma=.7)))
            qflag.append(0 if rng.random() > .08 else 1)
            ids.append(idx); idx += 1
    # alguns flashes fora dos 3 municípios para testar descarte espacial
    for _ in range(5):
        lons.append(-43.0+rng.normal(0,.05)); lats.append(-17.0+rng.normal(0,.05))
        starts.append(int(rng.integers(0,19000))); ends.append(starts[-1]+200)
        area.append(20.0); energy.append(.05); qflag.append(0); ids.append(idx); idx+=1

    ds = xr.Dataset(
        data_vars={
            "flash_id": ("number_of_flashes", np.array(ids, dtype=np.int32)),
            "flash_lat": ("number_of_flashes", np.array(lats, dtype=np.float32)),
            "flash_lon": ("number_of_flashes", np.array(lons, dtype=np.float32)),
            "flash_time_offset_of_first_event": ("number_of_flashes", np.array(starts, dtype=np.float64)),
            "flash_time_offset_of_last_event": ("number_of_flashes", np.array(ends, dtype=np.float64)),
            "flash_area": ("number_of_flashes", np.array(area, dtype=np.float32) * 1_000_000.0),
            "flash_energy": ("number_of_flashes", np.array(energy, dtype=np.float32)),
            "flash_quality_flag": ("number_of_flashes", np.array(qflag, dtype=np.int16)),
        }
    )
    units = f"milliseconds since {dt:%Y-%m-%d %H:%M:%S}"
    ds["flash_time_offset_of_first_event"].attrs["units"] = units
    ds["flash_time_offset_of_last_event"].attrs["units"] = units
    ds["flash_area"].attrs["units"] = "square meters"
    ds["flash_energy"].attrs["units"] = "J"
    ds.to_netcdf(path, engine="scipy")


def main(root: Path):
    rng = np.random.default_rng(20260811)
    if root.exists(): shutil.rmtree(root)
    raw = root / "raw"; processed = root / "processed"
    raw.mkdir(parents=True); processed.mkdir(parents=True)
    muni = gpd.GeoDataFrame({
        "code_muni": ["9990001", "9990002", "9990003"],
        "name_muni": ["Município Alpha", "Município Beta", "Município Gamma"],
        "abbrev_state": ["XX", "XX", "YY"],
        "area_muni_km2": [1100.0, 900.0, 1300.0],
        "geometry": [box(-46,-20,-45,-19), box(-45,-20,-44,-19), box(-46,-19,-45,-18)],
    }, crs=4326)
    muni.to_file(root / "municipalities.geojson", driver="GeoJSON")

    for year in [2024, 2025]:
        for month in range(1,13):
            for day, hour in [(10,18),(20,21)]:
                dt = datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
                goes = "16" if dt < datetime(2025,4,7,15,10,tzinfo=timezone.utc) else "19"
                write_glm_file(raw / glm_name(dt, goes), dt, rng, month, year)

    files = sorted(raw.glob("*.nc"))
    all_flashes = read_glm_files(files, quality="all")
    qsum = quality_summary(all_flashes)
    good_flashes = read_glm_files(files, quality="zero_only")
    enriched = assign_flashes_to_municipalities(good_flashes, muni)
    products = build_products(enriched)
    paths = save_products(products, processed)
    save_table(qsum, processed / "quality_summary")

    monthly = products["monthly"]
    annual = products["annual"]
    clim = products["monthly_climatology"]
    anom = products["monthly_anomalies"]
    assertions = {
        "48 NetCDF sintéticos criados": len(files) == 48,
        "flashes lidos": len(all_flashes) > 0,
        "filtro QC remove alguns flashes": len(good_flashes) < len(all_flashes),
        "3 municípios presentes": monthly["code_muni"].nunique() == 3,
        "24 meses por município": len(monthly) == 3*24,
        "2 anos por município": len(annual) == 3*2,
        "climatologia 12 meses x 3": len(clim) == 36,
        "anomalias geradas": {"flash_count_anom_pct","flash_count_z"}.issubset(anom.columns),
        "densidade positiva": (monthly["flash_density_km2"] > 0).all(),
        "dias com relâmpagos": (monthly["lightning_days"] == 2).all(),
    }
    failed = [k for k,v in assertions.items() if not v]
    report = ["# RELATÓRIO DA SIMULAÇÃO V3", "", f"Arquivos GLM sintéticos: {len(files)}",
              f"Flashes brutos: {len(all_flashes)}", f"Flashes após QC flag=0: {len(good_flashes)}",
              f"Flashes dentro de municípios: {enriched['code_muni'].notna().sum()}", "", "## Testes"]
    report += [f"- {'APROVADO' if v else 'FALHOU'} — {k}" for k,v in assertions.items()]
    report += ["", "## Produtos", *[f"- {k}: {v}" for k,v in paths.items()]]
    (root / "SIMULATION_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    if failed:
        raise SystemExit("Falhas: " + ", ".join(failed))

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--root", default="data/demo"); a=p.parse_args()
    main(Path(a.root))
