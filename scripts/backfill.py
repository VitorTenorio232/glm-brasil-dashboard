#!/usr/bin/env python3
"""Backfill histórico diário: download -> Parquet por hora -> remove NetCDF opcionalmente."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.glm_aws import download_period

p=argparse.ArgumentParser()
p.add_argument("--start",required=True,help="YYYY-MM-DD")
p.add_argument("--end",required=True,help="YYYY-MM-DD inclusivo")
p.add_argument("--raw-dir",default="data/raw")
p.add_argument("--flashes-dir",default="data/flashes")
p.add_argument("--manifests-dir",default="data/manifests")
p.add_argument("--municipalities",default="data/municipalities/municipios_brasil.gpkg")
p.add_argument("--quality",choices=["all","zero_only"],default="all")
p.add_argument("--keep-raw",action="store_true")
a=p.parse_args()
start=datetime.strptime(a.start,"%Y-%m-%d").replace(tzinfo=timezone.utc)
end=datetime.strptime(a.end,"%Y-%m-%d").replace(tzinfo=timezone.utc)
Path(a.manifests_dir).mkdir(parents=True,exist_ok=True)
cur=start
while cur<=end:
    day_end=cur+timedelta(days=1)-timedelta(microseconds=1)
    print(f"=== {cur:%Y-%m-%d} ===")
    res=download_period(cur,day_end,a.raw_dir)
    manifest=Path(a.manifests_dir)/f"glm_{cur:%Y%m%d}.csv"
    pd.DataFrame(res.manifest).to_csv(manifest,index=False)
    print(f"arquivos encontrados: {res.files_found} | manifesto: {manifest}")
    cmd=[sys.executable,"scripts/ingest_partitioned.py","--raw-dir",a.raw_dir,
         "--municipalities",a.municipalities,"--output",a.flashes_dir,"--quality",a.quality]
    if not a.keep_raw: cmd.append("--delete-raw")
    subprocess.check_call(cmd)
    cur+=timedelta(days=1)
print("Backfill concluído. Gere as agregações com scripts/build_products_duckdb.py")
