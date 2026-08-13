#!/usr/bin/env python3
"""Diagnóstico rápido de acesso externo a NOAA/AWS e Google Earth Engine."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_aws import list_hour_keys, satellite_for_datetime


def parse_dt(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


p = argparse.ArgumentParser()
p.add_argument("--time", default="2025-11-13T03:00:00Z", help="Horário UTC para testar o bucket GLM.")
p.add_argument("--ee-project", default=os.getenv("EE_PROJECT"))
a = p.parse_args()
dt = parse_dt(a.time)

print("=== NOAA/AWS GLM ===")
try:
    sat = satellite_for_datetime(dt)
    from src.glm_aws import unsigned_s3_client
    client = unsigned_s3_client()
    keys = list_hour_keys(client, dt)
    print(f"OK: GOES-{sat}; {len(keys)} objetos GLM-L2-LCFA encontrados na hora {dt:%Y-%m-%d %H} UTC.")
    if keys:
        print("Exemplo:", keys[0])
except Exception as exc:
    print(f"FALHOU: {type(exc).__name__}: {exc}")

print("\n=== Google Earth Engine ===")
if not a.ee_project:
    print("NÃO TESTADO: informe --ee-project ou defina EE_PROJECT.")
else:
    try:
        from src.earth_engine import initialize_ee
        ee = initialize_ee(project=a.ee_project)
        print("OK: ee.Number(1) =", ee.Number(1).getInfo())
    except Exception as exc:
        print(f"FALHOU: {type(exc).__name__}: {exc}")
