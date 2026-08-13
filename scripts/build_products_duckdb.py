#!/usr/bin/env python3
from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.duckdb_products import build_duckdb_products
p=argparse.ArgumentParser(); p.add_argument("--glob",default="data/flashes/**/*.parquet"); p.add_argument("--output",default="data/processed"); a=p.parse_args()
build_duckdb_products(a.glob,a.output); print("Produtos DuckDB concluídos em",a.output)
