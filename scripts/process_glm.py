#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.glm_reader import read_glm_files
from src.municipalities import load_municipalities
from src.spatial import assign_flashes_to_municipalities
from src.statistics import build_products
from src.storage import save_products, save_table
from src.qc import completeness_tables, quality_summary

p = argparse.ArgumentParser(description="Processa GLM bruto -> estatísticas municipais V1-V3.")
p.add_argument("--raw-dir", default="data/raw")
p.add_argument("--municipalities", default="data/municipalities/municipios_brasil.gpkg")
p.add_argument("--output", default="data/processed")
p.add_argument("--quality", choices=["all", "zero_only"], default="all",
               help="'all' preserva todos os flashes; zero_only é um filtro opcional por flag=0.")
p.add_argument("--save-flashes", action="store_true", help="Salva flashes individuais enriquecidos (pode ficar enorme).")
a = p.parse_args()
files = sorted(Path(a.raw_dir).glob("*.nc"))
if not files:
    raise SystemExit(f"Nenhum NetCDF em {a.raw_dir}")
muni = load_municipalities(a.municipalities)
flashes = read_glm_files(files, quality=a.quality)
print(f"Flashes lidos após filtro: {len(flashes):,}")
qsum = quality_summary(flashes)
enriched = assign_flashes_to_municipalities(flashes, muni)
inside = enriched["code_muni"].notna().sum()
print(f"Flashes atribuídos a município: {inside:,}/{len(enriched):,}")
products = build_products(enriched)
if not a.save_flashes:
    products.pop("flashes_enriched", None)
paths = save_products(products, a.output)
daily_c, monthly_c = completeness_tables(files)
if not daily_c.empty:
    paths["completeness_daily"] = save_table(daily_c, Path(a.output) / "completeness_daily")
    paths["completeness_monthly"] = save_table(monthly_c, Path(a.output) / "completeness_monthly")
if not qsum.empty:
    paths["quality_summary"] = save_table(qsum, Path(a.output) / "quality_summary")
for k, v in paths.items(): print(f"{k}: {v}")
