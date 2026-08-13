#!/usr/bin/env python3
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_aws import download_period


def parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

p = argparse.ArgumentParser(description="Baixa GLM-L2-LCFA GOES-East da NOAA/AWS.")
p.add_argument("--start", required=True, help="ISO UTC. Ex.: 2026-01-01T00:00:00Z")
p.add_argument("--end", required=True, help="ISO UTC")
p.add_argument("--output", default="data/raw")
p.add_argument("--overwrite", action="store_true")
a = p.parse_args()
res = download_period(parse_dt(a.start), parse_dt(a.end), a.output, overwrite=a.overwrite)
manifest = Path(a.output) / f"manifest_{res.requested_start:%Y%m%dT%H%M%S}_{res.requested_end:%Y%m%dT%H%M%S}.csv"
pd.DataFrame(res.manifest).to_csv(manifest, index=False)
print(f"Encontrados: {res.files_found} | baixados: {res.files_downloaded} | existentes: {res.files_existing}")
print(f"Manifesto: {manifest}")
