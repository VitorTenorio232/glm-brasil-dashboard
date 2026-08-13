#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.municipalities import download_municipalities, save_municipalities

p = argparse.ArgumentParser(description="Baixa malha municipal do geobr/IBGE e prepara arquivos para o dashboard.")
p.add_argument("--year", type=int, default=2025)
p.add_argument("--output", default="data/municipalities")
p.add_argument("--full", action="store_true", help="Usa geometria não simplificada.")
a = p.parse_args()
gdf = download_municipalities(a.year, simplified=not a.full)
paths = save_municipalities(gdf, a.output)
print(f"Municípios: {len(gdf)}")
for k, v in paths.items(): print(f"{k}: {v}")
