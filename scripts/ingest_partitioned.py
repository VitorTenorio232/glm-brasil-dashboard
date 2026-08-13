#!/usr/bin/env python3
"""Ingestão escalável: lê GLM por hora e grava flashes enriquecidos em Parquet particionado."""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_aws import parse_key_start_time
from src.glm_reader import read_glm_files
from src.municipalities import load_municipalities
from src.spatial import assign_flashes_to_municipalities

p=argparse.ArgumentParser()
p.add_argument("--raw-dir",default="data/raw")
p.add_argument("--municipalities",default="data/municipalities/municipios_brasil.gpkg")
p.add_argument("--output",default="data/flashes")
p.add_argument("--quality",choices=["all","zero_only"],default="all")
p.add_argument("--delete-raw",action="store_true")
a=p.parse_args()
try:
    import pyarrow  # noqa
except Exception:
    raise SystemExit("Este modo exige pyarrow: pip install pyarrow")
muni=load_municipalities(a.municipalities)
groups=defaultdict(list)
for f in Path(a.raw_dir).glob("*.nc"):
    ts=parse_key_start_time(f.name)
    if ts: groups[ts.strftime("%Y/%m/%d/%H")].append(f)
if not groups: raise SystemExit("Nenhum arquivo GLM reconhecido.")
for key in sorted(groups):
    files=sorted(groups[key]); flashes=read_glm_files(files,quality=a.quality)
    enriched=assign_flashes_to_municipalities(flashes,muni)
    enriched=enriched[enriched.code_muni.notna()].copy()
    y,m,d,h=key.split("/")
    out=Path(a.output)/f"year={y}"/f"month={m}"/f"day={d}"/f"hour={h}"
    out.mkdir(parents=True,exist_ok=True)
    target=out/"flashes.parquet"
    enriched.to_parquet(target,index=False,compression="zstd")
    print(key, f"arquivos={len(files)} flashes={len(enriched):,} -> {target}")
    if a.delete_raw:
        for f in files: f.unlink(missing_ok=True)
